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
        self,
        api_component,
        get_summarize_client_fn,
        force: bool = False,
        urgent: bool = False,
    ) -> None:
        """将旧对话历史压缩为摘要（并在同一边界把 L2 溢出条目并入 L3）。

        两条通道：

        - **常压（轮次 + 批处理）**：未摘要轮数越过 ``keep_turns`` 后不立刻摘要，
          需再积攒 ``l3_batch`` 条（0=自动 → ``keep_turns // 2``，默认 10→5）
          才一次性压回 ``keep_turns`` 条 —— 避免"每多一条就调一次便宜模型"。
        - **强制**：``force``（token 预算用尽，S5）或 ``urgent``（上下文越过
          ``l3_urgent_ratio``，默认 75%）时无视上述阈值，立即压缩。

        Args:
            api_component: API 组件
            get_summarize_client_fn: 获取摘要客户端的回调
            force: S5 强制压缩标志 — token 预算已用尽时忽略 keep_turns
                轮次阈值，无条件执行摘要（即使未摘要对话较少也压缩）。
            urgent: 上下文告急（token 水位越过 l3_urgent_ratio）— 与 force 同效，
                但语义独立：由 ``ctx._l2_urgent`` 消费而来，便于日志区分归因。
        """
        # 检查是否禁用摘要（disable_l3 或向后兼容的 disable_summary）
        if self.ctx.disable_summary or getattr(self.ctx, "disable_l3", False):
            return

        # ⚠️ topic_id 必须取 ctx.topic_id（回合入口在 chat_stream 里同步）。
        # Component 不持有 session，而 SessionContext 上**没有** current_topic_id
        # 这个字段 —— 早期版本写成 getattr(self.ctx, "current_topic_id", None)，
        # 恒为 None → 本函数每次都在此静默早退，L3 历史摘要**完全失效**
        # （实测：连 get_unsummarized_conversations 都不会被调用）。
        # 与 session/components/tool.py 的 _log_tool_event 是同一类缺陷。
        topic_id = self.ctx.topic_id or getattr(self.ctx, "current_topic_id", None)
        storage = self.ctx.storage
        if not (topic_id and storage):
            return

        # 1. 获取未摘要的对话
        try:
            unsummarized = storage.get_unsummarized_conversations(topic_id)
        except Exception as e:
            logger.warning(f"Fetch unsaved conversations failed: {e}")
            return

        keep_turns = max(1, int(getattr(self.ctx, "keep_turns", 10) or 10))
        l3_batch = self._resolve_l3_batch()
        forced = bool(force or urgent)
        if not forced and len(unsummarized) < keep_turns + l3_batch:
            # 批处理闸门：未攒够一批 → 不动（这是"不要每多一条就摘要"的核心）
            return

        # 2. 确定需要摘要的范围（压缩后未摘要轮数回到 keep_turns）
        num_to_summarize = max(0, len(unsummarized) - keep_turns)
        convs_to_summarize = unsummarized[:num_to_summarize]
        if not convs_to_summarize:
            # 告急但轮次未越水位 → 无新增对话可摘要，仍可压 L2（见下方兜底）
            self._compress_l2_to_l3(topic_id, get_summarize_client_fn, urgent=forced)
            return

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
            is_cheap = self.ctx.cheap_client is not None and cli is self.ctx.cheap_client

            cheap_params = get_cheap_params("summarizer")
            response = api_component.call_summarize_api(
                cli,
                mdl,
                messages=[
                    {"role": "system", "content": HISTORY_SUMMARIZE_SYSTEM},
                    {
                        "role": "user",
                        "content": HISTORY_SUMMARIZE_USER.format(existing=existing, old_text=old_text),
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
                storage.update_topic_summary(topic_id, new_summary, last_summarized_id=last_conv_id)
                for conv in convs_to_summarize:
                    storage.mark_as_summarized(conv["id"])

                # 5. 同步内存
                self.ctx._history_summary = new_summary

                # 裁剪 messages，保持与数据库同步
                boundary = self._find_recent_boundary()
                if boundary > 1:
                    self.ctx.messages = [self.ctx.messages[0]] + self.ctx.messages[boundary:]

                if self.ctx.tool_log:
                    self.ctx.tool_log(f"📝 历史摘要更新：{new_summary}")

            # 6. 同一边界压缩 L2 → L3（两条通道共用同一水位判定事实源）：
            #    常压走批处理闸门，告急（urgent）则无视闸门立即压回 keep_turns。
            self._compress_l2_to_l3(topic_id, get_summarize_client_fn, urgent=forced)

        except Exception as e:
            logger.warning(f"History summary failed: error={e}")
            if self.ctx.tool_log:
                self.ctx.tool_log(f"⚠️ 摘要生成失败: {e}")

    def _resolve_l3_batch(self) -> int:
        """L2→L3 批大小：ctx.l3_batch 优先（0=自动 → keep_turns//2）。"""
        from tea_agent.l3_policy import resolve_l2_batch

        keep_turns = getattr(self.ctx, "keep_turns", 10)
        raw = getattr(self.ctx, "l3_batch", 0)
        cap = getattr(self.ctx, "history_l2_max", 0)
        return resolve_l2_batch(keep_turns, raw, cap)

    def _compress_l2_to_l3(self, topic_id: str, get_summarize_client_fn, urgent: bool = False) -> None:
        """把 L2 溢出条目并入 L3 语义摘要（失败隔离，不影响主流程）。

        与 ``push_to_level2`` 共用 ``tea_agent/l3_policy`` 的水位判定；
        裁剪由 ``storage.trim_level2`` 完成（不新增条目），摘要由
        ``storage.generate_l2_to_l3_summary`` 生成，成功后同步 ``ctx._semantic_summary``。

        Args:
            topic_id: 主题 ID。
            get_summarize_client_fn: 获取摘要客户端的回调。
            urgent: 告急 → 无视轮次水位立即压缩。
        """
        storage = self.ctx.storage
        if storage is None or not topic_id:
            return
        trim = getattr(storage, "trim_level2", None)
        gen = getattr(storage, "generate_l2_to_l3_summary", None)
        if not callable(trim) or not callable(gen):
            return  # 鸭子类型替身/精简 storage：静默跳过（非失败）
        try:
            _count, overflow_items, should = trim(
                topic_id,
                keep_turns=getattr(self.ctx, "keep_turns", 10),
                l3_batch=getattr(self.ctx, "l3_batch", 0),
                urgent=urgent,
                max_level2=getattr(self.ctx, "history_l2_max", 0),
                max_level2_chars=getattr(self.ctx, "l2_max_chars", 120000),
            )
        except Exception:
            logger.debug("trim_level2 failed (isolated)", exc_info=True)
            return
        if not should or not overflow_items:
            return
        try:
            cli, mdl = get_summarize_client_fn()
            existing = storage.get_semantic_summary(topic_id) or ""
            extra = get_cheap_params("summarizer")
            new_summary, _usage = gen(topic_id, overflow_items, existing, cli, mdl, extra_params=extra)
            if new_summary:
                self.ctx._semantic_summary = new_summary
            if self.ctx.tool_log:
                self.ctx.tool_log(f"🗜️ L2→L3 压缩：{len(overflow_items)} 条并入摘要")
        except Exception as e:
            logger.warning(f"L2→L3 压缩失败（隔离）: {e}")

    def _conversations_to_text(self, conversations: list[dict], max_per_msg: int = 500) -> str:
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
