"""{name} —— 从 onlinesession.py 拆分（2026-09-06，保持 API 兼容）。"""

import logging

from tea_agent.session.context import SessionComponent
from tea_agent.session.params import get_cheap_params
from tea_agent.session.prompts import (
    HISTORY_SUMMARIZE_SYSTEM,
    HISTORY_SUMMARIZE_USER,
)

logger = logging.getLogger("session")

class SummarizerComponent(SessionComponent):
    """历史摘要组件 — 负责旧对话压缩、三级历史管理、语义摘要生成。"""

    @property
    def name(self) -> str:
        return "summarizer"

    def initialize(self) -> None:
        pass

    def summarize_old_history(
        self, api_component, get_summarize_client_fn, force: bool = False
    ) -> None:
        """将旧对话历史压缩为摘要。

        Args:
            api_component: API 组件
            get_summarize_client_fn: 获取摘要客户端的回调
            force: S5 强制压缩标志 — token 预算已用尽时忽略 keep_turns
                轮次阈值，无条件执行摘要（即使未摘要对话较少也压缩）。
        """
        # 检查是否禁用摘要（disable_l3 或向后兼容的 disable_summary）
        if self.ctx.disable_summary or getattr(self.ctx, "disable_l3", False):
            return

        topic_id = getattr(self.ctx, "current_topic_id", None)
        storage = self.ctx.storage
        if not (topic_id and storage):
            return

        # 1. 获取未摘要的对话
        try:
            unsummarized = storage.get_unsummarized_conversations(topic_id)
        except Exception as e:
            logger.warning(f"Fetch unsaved conversations failed: {e}")
            return

        if len(unsummarized) <= self.ctx.keep_turns and not force:
            return

        # 2. 确定需要摘要的范围
        num_to_summarize = len(unsummarized) - self.ctx.keep_turns
        convs_to_summarize = unsummarized[:num_to_summarize]

        # 3. 提取对话文本
        old_text = self._conversations_to_text(convs_to_summarize)
        if not old_text:
            return

        # 获取旧摘要
        try:
            old_summary = storage.get_topic_summary(topic_id) or ""
        except Exception:
            old_summary = ""

        # 构建 Prompt
        existing = f"已有摘要：{old_summary}\n\n" if old_summary else ""

        try:
            cli, mdl = get_summarize_client_fn()
            # 判断是否使用便宜模型
            is_cheap = (
                self.ctx.cheap_client is not None and cli is self.ctx.cheap_client
            )

            cheap_params = get_cheap_params("summarizer")
            response = api_component.call_summarize_api(
                cli,
                mdl,
                messages=[
                    {"role": "system", "content": HISTORY_SUMMARIZE_SYSTEM},
                    {
                        "role": "user",
                        "content": HISTORY_SUMMARIZE_USER.format(
                            existing=existing, old_text=old_text
                        ),
                    },
                ],
                temperature=cheap_params["temperature"],
                max_tokens=cheap_params["max_tokens"],
            )

            # 统计 token 用量
            api_component._track_api_usage(response, is_cheap=is_cheap)

            content = response.choices[0].message.content
            if isinstance(content, str):
                new_summary = content.strip()

                # 4. 更新数据库
                last_conv_id = convs_to_summarize[-1]["id"]
                storage.update_topic_summary(
                    topic_id, new_summary, last_summarized_id=last_conv_id
                )
                for conv in convs_to_summarize:
                    storage.mark_as_summarized(conv["id"])

                # 5. 同步内存
                self.ctx._history_summary = new_summary

                # 裁剪 messages，保持与数据库同步
                boundary = self._find_recent_boundary()
                if boundary > 1:
                    self.ctx.messages = [self.ctx.messages[0]] + self.ctx.messages[
                        boundary:
                    ]

                if self.ctx.tool_log:
                    self.ctx.tool_log(f"📝 历史摘要更新：{new_summary}")

        except Exception as e:
            logger.warning(f"History summary failed: error={e}")
            if self.ctx.tool_log:
                self.ctx.tool_log(f"⚠️ 摘要生成失败: {e}")

    def _conversations_to_text(
        self, conversations: list[dict], max_per_msg: int = 500
    ) -> str:
        lines = []
        for conv in conversations:
            # 用户消息
            u_msg = conv.get("user_msg", "")
            lines.append(f"[USER]: {u_msg[:max_per_msg]}")

            # AI 消息（含工具调用链）
            rounds = conv.get("rounds_json_parsed")
            if rounds and conv.get("is_func_calling"):
                for rd in rounds:
                    role = rd.get("role", "")
                    content = rd.get("content", "")
                    if role == "assistant" and rd.get("tool_calls"):
                        tc_names = [tc["function"]["name"] for tc in rd["tool_calls"]]
                        lines.append(f"[ASSISTANT 调用工具]: {', '.join(tc_names)}")
                        if content:
                            lines.append(f"[ASSISTANT]: {content[:max_per_msg]}")
                    elif role == "tool":
                        lines.append(f"[工具结果]: {content[:max_per_msg]}")
                    elif role == "assistant" and content:
                        lines.append(f"[ASSISTANT]: {content[:max_per_msg]}")
            else:
                ai_msg = conv.get("ai_msg", "")
                lines.append(f"[ASSISTANT]: {ai_msg[:max_per_msg]}")

        return "\n".join(lines)

    def _find_recent_boundary(self) -> int:
        user_count = 0

        for i in range(len(self.ctx.messages) - 1, 0, -1):
            msg = self.ctx.messages[i]
            if msg.get("role") == "user":
                user_count += 1
                if user_count >= self.ctx.keep_turns:
                    return i

        # 不足 keep_turns 轮，保留全部
        return 1
