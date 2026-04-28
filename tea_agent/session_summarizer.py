"""
会话摘要模块
负责历史摘要、Topic 摘要、消息压缩等功能

摘要生命周期:
1. 历史摘要 (History Summary) - 将会话早期的旧消息压缩为摘要
2. Topic 摘要 (Topic Summary)  - 为整个会话主题生成简短标题
3. 消息压缩 (Message Compact)  - 截断超长消息，控制 Token 消耗
"""

import re
from typing import List, Dict, Tuple, Any, Optional, Callable

from tea_agent.session_prompts import (
    HISTORY_SUMMARIZE_SYSTEM,
    HISTORY_SUMMARIZE_USER,
    TOPIC_SUMMARY_SYSTEM,
    TOPIC_SUMMARY_USER_TEMPLATE,
)


class SessionSummarizerMixin:
    """
    摘要管理 Mixin 类，提供历史摘要、Topic 摘要、消息压缩功能。

    依赖属性 (由使用者提供):
        messages: 消息列表，当前会话的完整对话历史
        keep_turns: 保留最近 N 轮对话 (默认 3)
        max_tool_output: 工具输出最大字符数 (默认 128KB)
        max_assistant_content: 助手回复最大字符数 (默认 128KB)
        tool_log: 可选的日志回调函数
        _get_summarize_client(): 获取摘要客户端的方法

    内部状态:
        _history_summary: 累积的历史摘要文本
    """

    def __init__(self):
        self.messages: List[Dict] = []

        # 摘要配置
        self.keep_turns: int = 2
        self.max_tool_output: int = 128 * 1024
        self.max_assistant_content: int = 128 * 1024

        # 日志回调
        self.tool_log: Optional[Callable[[str], None]] = None

    # ──────────────────────────────────────────────
    # 历史摘要 (History Summary)
    # ──────────────────────────────────────────────

    def count_user_msg(self) -> int:
        return sum([m.get("role") == "user" for m in self.messages])

    def _summarize_old_history(self) -> None:
        """
        持久化摘要逻辑：
            总是将 _history_summary 与当前 self.messages 中的倒数第 self.keep_turns 轮对话压缩为摘要
            并存储
        """
        ## 如果 user count 超过 keep_turns，触发摘要更新
        old_text = ""
        topic_id = getattr(self, "current_topic_id", None)
        storage = getattr(self, "storage", None)

        old_summary = storage.get_topic_summary(topic_id) if topic_id and storage else ""

        count = self.count_user_msg()
        if count > self.keep_turns:
            ## 提取倒数 self.keep_turns 轮对话（user + assistant) 与 _history_summary 合并
            begin_idx, end_idx = self._find_last_need_summary_pair()
            if 0 <= begin_idx < end_idx < len(self.messages):
                ## 需要提取更新摘要
                messages = self.messages[begin_idx:end_idx]
                old_text = self._messages_to_text(messages, max_per_msg=300)

        if old_text:
            ## 调用 LLM 更新摘要
            # 构建 Prompt
            existing = (
                f"已有摘要：{old_summary}\n\n"
                if old_summary
                else ""
            )

            try:
                cli, mdl = self._get_summarize_client()
                response = cli.chat.completions.create(
                    model=mdl,
                    messages=[
                        {"role": "system", "content": HISTORY_SUMMARIZE_SYSTEM},
                        {
                            "role": "user",
                            "content": HISTORY_SUMMARIZE_USER.format(
                                existing=existing, old_text=old_text
                            ),
                        },
                    ],
                    temperature=0.1,
                    max_tokens=500,
                )
                content = response.choices[0].message.content
                if isinstance(content, str):
                    new_summary = content.strip()
                    
                    # 同步到内存和数据库
                    self._history_summary = new_summary

                    if topic_id and storage:
                        storage.update_topic_summary(topic_id, new_summary)

                    if self.tool_log:
                        self.tool_log(f"📝 历史摘要更新：{new_summary}")

            except Exception as e:
                if self.tool_log:
                    self.tool_log(f"⚠️ 摘要生成失败: {e}")
        return None

    def _get_memory_priority_for_compression(self) -> str:
        """
        根据记忆优先级决定压缩策略。
        
        Returns:
            压缩策略描述字符串
        """
        if not hasattr(self, 'memory') or not self.memory:
            return ""
        
        try:
            # 获取高优先级记忆（重要性 >= 4）
            important_memories = self.memory.get_important_memories(limit=5)
            
            if not important_memories:
                return "标准压缩，无高优先级记忆"
            
            # 统计高优先级记忆的数量和类别
            high_priority_count = len(important_memories)
            categories = set(m.get('category', 'unknown') for m in important_memories)
            
            return f"保留 {high_priority_count} 条高优先级记忆相关的细节，类别: {', '.join(categories)}"
        except Exception:
            return ""

    # ──────────────────────────────────────────────
    # Topic 摘要 (Topic Summary)
    # ──────────────────────────────────────────────

    def generate_topic_summary(
        self, conversations: List[Dict]
    ) -> Optional[str]:
        """
        根据最近对话通过 LLM 生成不超过 20 字的摘要标题。

        Args:
            conversations: 最近的对话列表（按时间正序），
                          每项包含 user_msg 和 ai_msg 字段

        Returns:
            不超过 20 字的摘要字符串；若生成失败则返回 None
        """
        if not conversations:
            return None
            
        # 提取用户消息和 AI 回复
        user_msgs = self._extract_user_messages(conversations, max_len=200)

        if not user_msgs:
            return None

        # 构建 Prompt
        user_content = TOPIC_SUMMARY_USER_TEMPLATE.format(
            user_msgs="\n".join(user_msgs)
        )

        # 调用 LLM
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

            # 安全检查返回值
            if not response.choices or len(response.choices) == 0:
                return None
                
            content = response.choices[0].message.content
            if not content or not isinstance(content, str):
                return None
                
            raw = content.strip()

            # 清洗和截断
            cleaned = self._clean_topic_summary(raw)

            return cleaned if cleaned else None

        except Exception:
            return None

    def _extract_user_messages(
        self, conversations: List[Dict], max_len: int = 200
    ) -> List[str]:
        """
        从对话列表中提取用户消息和 AI 回复。

        Args:
            conversations: 对话列表
            max_len: 单条消息最大长度

        Returns:
            格式化的用户消息列表
        """
        user_msgs: List[str] = []

        for conv in conversations:
            um = conv.get("user_msg", "").strip()
            ai = conv.get("ai_msg", "").strip()
            
            if um:
                # 截断超长消息
                if len(um) > max_len:
                    um = um[:max_len] + "..."
                user_msgs.append(f"用户：{um}")
            
            # 同时提取 AI 回复，提供更完整的上下文
            if ai:
                if len(ai) > max_len:
                    ai = ai[:max_len] + "..."
                user_msgs.append(f"AI：{ai}")

        return user_msgs

    def _clean_topic_summary(self, raw: str) -> Optional[str]:
        """
        清洗 Topic 摘要文本。

        去除引号、截断超长文本。

        Args:
            raw: 原始摘要文本

        Returns:
            清洗后的摘要 (不超过 20 字)
        """
        if not raw or not raw.strip():
            return None
        
        # 去除首尾引号（支持中英文引号）
        cleaned = re.sub(r'^["""\'""\']+|["""\'""\']+$', '', raw).strip()

        # 截断超长文本（20个字符，中文字符也算1个）
        if len(cleaned) > 20:
            cleaned = cleaned[:20]

        return cleaned if cleaned else None

    # ──────────────────────────────────────────────
    # 消息压缩 (Message Compact)
    # ──────────────────────────────────────────────

    def _build_api_messages(self) -> List[Dict]:
        """
        构建发送给 API 的消息列表。

        压缩策略:
            1. 系统提示词 (始终第一条)  self.messages[0]
            2. 历史摘要 (如有，替代旧消息)  self._history_summary
            3. 最新 n 轮完整对话 (不压缩，保留原始内容)
        
        工具循环内部不调用任何压缩逻辑，仅对输入和返回的历史做压缩。

        Returns:
            消息列表
        """
        result: List[Dict] = []

        # 1. 系统提示词 (始终第一)
        result.append(self.messages[0])

        ## 历史摘要内容：该内容总是
        # 2. 历史摘要：作为 user + assistant 对添加
        if self._history_summary:
            result.append({
                "role": "user",
                "content": f"这是我们之前对话的摘要：\n{self._history_summary}"
            })
            result.append({
                "role": "assistant",
                "content": "好的，我已经了解了之前的对话背景。请问有什么我可以帮您的？"
            })

        # 4. 最新 N 轮完整对话 (不压缩)
        boundary = self._find_recent_boundary()
        # 注意：如果 boundary 刚好指向了摘要消息，我们需要跳过它，因为它已经在上面添加过了
        for i in range(boundary, len(self.messages)):
            msg = self.messages[i]
            result.append(msg)

        return result
    
    def _compact_message(self, msg: Dict) -> Dict:
        """
        创建消息的紧凑副本，截断超长内容。

        Args:
            msg: 原始消息字典

        Returns:
            紧凑版消息字典 (浅拷贝，超长内容被截断)
        """
        compact = dict(msg)  # 浅拷贝
        role = msg.get("role", "")
        content = msg.get("content")

        # 截断工具输出
        if role == "tool" and content and len(content) > self.max_tool_output:
            compact["content"] = (
                content[: self.max_tool_output] + "\n...[已截断]"
            )
        # 截断助手回复
        elif (
            role == "assistant"
            and content
            and len(content) > self.max_assistant_content
        ):
            compact["content"] = content[: self.max_assistant_content] + "...[已截断]"

        return compact

    # ──────────────────────────────────────────────
    # 辅助方法
    # ──────────────────────────────────────────────

    def _messages_to_text(
        self, messages: List[Dict], max_per_msg: int = 500
    ) -> str:
        """
        将消息列表转为文本，用于摘要生成。

        Args:
            messages: 消息列表
            max_per_msg: 单条消息最大长度

        Returns:
            格式化的文本，每行格式: [ROLE]: content
        """
        lines: List[str] = []

        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")

            if role == "tool":
                truncated = (
                    content[:max_per_msg] + "..."
                    if len(content) > max_per_msg
                    else content
                )
                lines.append(f"[工具结果]: {truncated}")

            elif role in ("user", "assistant") and content:
                truncated = (
                    content[:max_per_msg] + "..."
                    if len(content) > max_per_msg
                    else content
                )
                lines.append(f"[{role.upper()}]: {truncated}")

            elif role == "assistant" and msg.get("tool_calls"):
                tc_names = [
                    tc["function"]["name"] for tc in msg["tool_calls"]
                ]
                lines.append(f"[ASSISTANT 调用工具]: {', '.join(tc_names)}")

        return "\n".join(lines)

    def _find_recent_boundary(self) -> int:
        """
        找到最近 keep_turns 轮对话的起始索引。

        从后向前遍历消息列表，统计用户消息数量（排除摘要消息），找到第 keep_turns 个
        用户消息的位置。

        Returns:
            最近 N 轮对话的起始索引 (至少为 1，跳过系统消息)
        """
        user_count = 0

        for i in range(len(self.messages) - 1, 0, -1):
            msg = self.messages[i]
            if msg.get("role") == "user":                
                user_count += 1
                if user_count >= self.keep_turns:
                    return i

        # 不足 keep_turns 轮，保留全部 (跳过系统消息)
        return 1
    
    def _find_last_need_summary_pair(self) -> Tuple[int, int]:
        """
        找到需要提取摘要的最后一个对话对，可能包含 user, assistant, tool 的消息
        """
        end_index = -1
        begin_index = -1

        skip_count = self.keep_turns

        ## 往前找，跳过 keep_turns 个 user，找到后，往后找到第一个 user 之前的 assistant
        for i in range(len(self.messages) - 1, 0, -1):
            ## 先跳过 skip_count 轮 assistant
            role = self.messages[i].get("role")
            if role == "user":
                if skip_count > 0:
                    skip_count -= 1
                else:
                    begin_index = i
                    break

        if begin_index >= 0:
            for j in range(begin_index + 1, len(self.messages)):
                role = self.messages[j].get("role")
                if role == "user":
                    end_index = j
                    break

        return begin_index, end_index

    # ──────────────────────────────────────────────
    # 状态重置
    # ──────────────────────────────────────────────

    def reset_summary_state(self) -> None:
        """
        重置摘要状态（用于新会话开始前）。

        清空历史摘要，但不影响 messages 中的原始消息。
        """
        self._history_summary = ""
