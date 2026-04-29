# @2026-04-29 gen by deepseek-v4-pro, SessionMemoryMixin: 会话记忆注入与自动提取
"""
会话记忆注入 Mixin
在每次对话中注入相关长期记忆，并支持自动提取新记忆。
"""

from typing import List, Dict, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from tea_agent.memory import MemoryManager

import logging

logger = logging.getLogger("session_memory")


class SessionMemoryMixin:
    """
    记忆注入 Mixin。

    期望使用者提供：
    - self.memory: MemoryManager 实例
    - self.messages: 消息列表
    - self.storage: Storage 实例
    - self._build_api_messages(): 构建 API 消息的方法
    - self.pipeline: SessionPipeline 实例
    """

    def __init__(self):
        self.memory: Optional["MemoryManager"] = None
        self._injected_memories_text: str = ""
        self._injected_memories: List[Dict] = []

    def _setup_memory(self):
        """初始化 Memory 管理器（需要 self.storage 已设置）"""
        if not self.storage:
            return
        from tea_agent.memory import MemoryManager
        try:
            self.memory = MemoryManager(self.storage)
            logger.info("MemoryManager 初始化成功")
        except Exception as e:
            logger.warning(f"MemoryManager 初始化失败: {e}")
            self.memory = None

    # ------------------------------------------------------------------
    # Pipeline 步骤：记忆注入
    # ------------------------------------------------------------------

    def _pipeline_inject_memories(self, context: Dict) -> List:
        """
        Pipeline 步骤：选择并格式化相关记忆。

        Args:
            context: 包含 user_msg, msg 等字段

        Returns:
            更新后的消息列表
        """
        if not self.memory:
            return self.messages

        user_msg = context.get("user_msg", "") or context.get("msg", "")

        try:
            memories = self.memory.select_memories(user_msg, limit=5)
        except Exception as e:
            logger.warning(f"记忆选择失败: {e}")
            memories = []

        if not memories:
            self._injected_memories_text = ""
            self._injected_memories = []
            return self.messages

        try:
            formatted = self.memory.format_memories(memories)
        except Exception:
            formatted = ""

        self._injected_memories_text = formatted
        self._injected_memories = memories

        if formatted:
            logger.info(f"注入了 {len(memories)} 条记忆")

        return self.messages

    # ------------------------------------------------------------------
    # 记忆自动提取
    # ------------------------------------------------------------------

    def trigger_memory_extraction(self, topic_id: int) -> int:
        """
        从当前会话的未摘要对话中提取新记忆（使用便宜模型）。

        Args:
            topic_id: 当前主题 ID

        Returns:
            新增记忆数量，出错返回 -1
        """
        if not self.memory or not self.storage:
            return -1

        # 获取未摘要的对话
        try:
            unsummarized = self.storage.get_unsummarized_conversations(topic_id)
        except Exception as e:
            logger.warning(f"获取未摘要对话失败: {e}")
            return -1

        if not self.memory.is_extraction_needed(len(unsummarized)):
            return 0

        # 构建对话文本
        conv_text = self._build_conversation_text(unsummarized)
        if not conv_text.strip():
            return 0

        # 调用 LLM 提取
        try:
            client, model = self._get_summarize_client()
            messages = self.memory.build_extraction_prompt(conv_text)

            response = client.chat.completions.create(
                model=model,
                messages=messages,
                stream=False,
                extra_body={"thinking": {"type": "disable"}},
                temperature=0.3,
                max_tokens=1000,
            )

            # 追踪 token
            if hasattr(self, '_track_api_usage'):
                self._track_api_usage(response, is_cheap=True)

            result_text = response.choices[0].message.content or ""
            extracted = self.memory.parse_extraction_result(result_text)

            if extracted:
                count = self.memory.ingest_extracted(extracted, topic_id)
                logger.info(f"自动提取了 {count} 条新记忆")
                return count

        except Exception as e:
            logger.warning(f"记忆提取失败: {e}")

        return 0

    @staticmethod
    def _build_conversation_text(conversations: List[Dict]) -> str:
        """将对话列表构建为纯文本"""
        lines = []
        for conv in conversations:
            lines.append(f"用户: {conv.get('user_msg', '')}")
            lines.append(f"助手: {conv.get('ai_msg', '')[:500]}")  # 截断长回复
            lines.append("")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # 暴露给 API / GUI
    # ------------------------------------------------------------------

    def get_injected_memories(self) -> List[Dict]:
        """获取当前会话注入的记忆列表"""
        return list(self._injected_memories)

    def get_memory_stats(self) -> Dict:
        """获取记忆统计"""
        if not self.memory or not self.storage:
            return {"total": 0, "by_category": {}, "by_priority": {}}
        try:
            return self.storage.get_memory_stats()
        except Exception:
            return {"total": 0, "by_category": {}, "by_priority": {}}
