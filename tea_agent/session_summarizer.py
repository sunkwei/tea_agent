"""
会话摘要模块
负责历史摘要、Topic 摘要、消息压缩等功能
"""

from typing import List, Dict, Tuple, Any, Optional, Callable


class SessionSummarizerMixin:
    """
    摘要管理 mixin 类。
    期望使用者提供以下属性：
    - messages: 消息列表
    - keep_turns: 保留最近 N 轮对话
    - max_tool_output: 工具输出最大字符数
    - max_assistant_content: 助手回复最大字符数
    - _history_summary: 累积的历史摘要
    - tool_log: 可选日志回调
    - _get_summarize_client(): 获取摘要客户端的方法
    """

    def __init__(self):
        self.messages: List[Dict] = []
        self.keep_turns: int = 3
        self.max_tool_output: int = 128 * 1024
        self.max_assistant_content: int = 128 * 1024
        self._history_summary: str = ""
        self.tool_log: Optional[Callable[[str], None]] = None

    def _messages_to_text(
        self, messages: List[Dict], max_per_msg: int = 500
    ) -> str:
        """将消息列表转为文本，用于摘要生成。"""
        lines = []
        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")

            if role == "tool":
                truncated = content[:max_per_msg] + "..." if len(content) > max_per_msg else content
                lines.append(f"[工具结果]: {truncated}")
            elif role in ("user", "assistant") and content:
                truncated = content[:max_per_msg] + "..." if len(content) > max_per_msg else content
                lines.append(f"[{role.upper()}]: {truncated}")
            elif role == "assistant" and msg.get("tool_calls"):
                tc_names = [tc["function"]["name"] for tc in msg["tool_calls"]]
                lines.append(f"[ASSISTANT 调用工具]: {', '.join(tc_names)}")

        return "\n".join(lines)

    def _find_recent_boundary(self) -> int:
        """找到最近 keep_turns 轮对话的起始索引。"""
        user_count = 0
        for i in range(len(self.messages) - 1, 0, -1):
            if self.messages[i].get("role") == "user":
                user_count += 1
                if user_count >= self.keep_turns:
                    return i
        return 1  # 不足 keep_turns 轮，保留全部（跳过系统消息）

    def _compact_message(self, msg: Dict) -> Dict:
        """创建消息的紧凑副本，截断超长内容。"""
        compact = dict(msg)
        role = msg.get("role", "")
        content = msg.get("content")

        if role == "tool" and content and len(content) > self.max_tool_output:
            compact["content"] = content[:self.max_tool_output] + "\n...[已截断]"
        elif role == "assistant" and content and len(content) > self.max_assistant_content:
            compact["content"] = content[:self.max_assistant_content] + "...[已截断]"

        return compact

    def _build_api_messages(self) -> List[Dict]:
        """构建发送给 API 的紧凑消息列表。"""
        result = []

        # 1. 系统提示词（始终第一）
        result.append(self.messages[0])

        # 2. 记忆注入（如有，独立于 self.messages）
        if self._memory_text:  # type: ignore[attr-defined]
            result.append({
                "role": "system",
                "content": f"【记忆参考】\n{self._memory_text}"
            })

        # 3. 历史摘要（如有，替代旧消息）
        if self._history_summary:
            result.append({
                "role": "system",
                "content": f"【历史摘要】\n{self._history_summary}"
            })

        # 4. 最近 N 轮对话（紧凑版，保留完整工具调用链）
        boundary = self._find_recent_boundary()
        for msg in self.messages[boundary:]:
            result.append(self._compact_message(msg))

        return result

    def _summarize_old_history(self):
        """将超出最近 keep_turns 轮的旧消息通过 LLM 生成摘要。"""
        from tea_agent.session_prompts import (
            HISTORY_SUMMARIZE_SYSTEM,
            HISTORY_SUMMARIZE_USER,
        )

        boundary = self._find_recent_boundary()
        old_messages = self.messages[1:boundary]

        if not old_messages:
            return

        old_text = self._messages_to_text(old_messages, max_per_msg=300)

        if not old_text.strip():
            return

        existing = (
            f"已有摘要：{self._history_summary}\n\n"
            if self._history_summary else ""
        )

        try:
            cli, mdl = self._get_summarize_client()
            response = cli.chat.completions.create(
                model=mdl,
                messages=[
                    {"role": "system", "content": HISTORY_SUMMARIZE_SYSTEM},
                    {"role": "user", "content": HISTORY_SUMMARIZE_USER.format(
                        existing=existing, old_text=old_text)},
                ],
                temperature=0.1,
                max_tokens=300,
            )
            if isinstance(response.choices[0].message.content, str):
                self._history_summary = response.choices[0].message.content.strip()

            # 从 self.messages 中移除已摘要的旧消息
            self.messages = [self.messages[0]] + self.messages[boundary:]

            if self.tool_log:
                self.tool_log(
                    f"📝 历史摘要已更新，压缩 {len(old_messages)} 条消息"
                )
        except Exception as e:
            if self.tool_log:
                self.tool_log(f"⚠️ 摘要生成失败: {e}")

    def generate_topic_summary(self, conversations: List[Dict]) -> Optional[str]:
        """
        根据最近3轮对话通过 LLM 生成不超过20字的摘要标题。

        Args:
            conversations: 最近的对话列表（按时间正序）

        Returns:
            不超过20字的摘要字符串；若生成失败则返回 None
        """
        import re
        from tea_agent.session_prompts import (
            TOPIC_SUMMARY_SYSTEM,
            TOPIC_SUMMARY_USER_TEMPLATE,
        )

        user_msgs = []
        for conv in conversations:
            um = conv.get("user_msg", "").strip()
            if um:
                if len(um) > 200:
                    um = um[:200] + "..."
                user_msgs.append(f"用户：{um}")

        if not user_msgs:
            return None

        user_content = TOPIC_SUMMARY_USER_TEMPLATE.format(
            user_msgs="\n".join(user_msgs)
        )

        cli, mdl = self._get_summarize_client()
        try:
            response = cli.chat.completions.create(
                model=mdl,
                messages=[
                    {"role": "system", "content": TOPIC_SUMMARY_SYSTEM},
                    {"role": "user", "content": user_content},
                ],
                temperature=0.3,
                max_tokens=50,
            )
            raw = response.choices[0].message.content.strip()
            raw = re.sub(r'^["""\']+|["""\']+$', '', raw).strip()
            if len(raw) > 20:
                raw = raw[:20]
            return raw if raw else None
        except Exception:
            return None

    def reset_summary_state(self):
        """重置摘要状态（用于新会话开始前）"""
        self._history_summary = ""
