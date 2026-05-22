"""
会话记忆组件

负责会话记忆注入与自动提取。
从 SessionMemoryMixin 重构而来，使用组合模式替代 Mixin。
"""

from typing import List, Dict, Optional, TYPE_CHECKING
from .session_context import SessionComponent, SessionContext

if TYPE_CHECKING:
    from tea_agent.memory import MemoryManager

import logging

logger = logging.getLogger("session.memory")

def _get_cheap_params():
    """返回 cheap 模型 {temperature, max_tokens}，失败时使用保守默认值。"""
    try:
        from .config import get_config
        eff = get_config().get_effective_params("cheap", "mixed")
        return {
            "temperature": eff.get("temperature", 0.3),
            "max_tokens": eff.get("max_tokens", 1000),
        }
    except Exception:
        return {"temperature": 0.3, "max_tokens": 1000}

class MemoryComponent(SessionComponent):
    """
    会话记忆组件。
    
    通过 self.ctx 访问共享状态（memory, storage, messages, pipeline, _injected_memories 等）。
    """
    
    @property
    def name(self) -> str:
        """Name."""
        return "memory"
    
    def initialize(self) -> None:
        """初始化 Memory 管理器（需要 storage 已设置）"""
        if not self.ctx.storage:
            return
        
        from tea_agent.memory import MemoryManager
        threshold = self.ctx.memory_extraction_threshold
        dedup = self.ctx.memory_dedup_threshold
        try:
            self.ctx.memory = MemoryManager(
                self.ctx.storage,
                extraction_threshold=threshold,
                dedup_threshold=dedup,
            )
            logger.info("MemoryManager 初始化成功 (dedup_threshold=%.2f)", dedup)
        except Exception as e:
            logger.warning(f"MemoryManager 初始化失败: {e}")
            self.ctx.memory = None

    def inject_memories(self, context: Dict) -> List:
        """
        从长期记忆（用户+项目）中注入相关记忆。

        Args:
            context: 包含 user_msg, msg 等字段

        Returns:
            更新后的消息列表
        """
        if not self.ctx.memory:
            return self.ctx.messages

        user_msg = context.get("user_msg", "") or context.get("msg", "")
        all_memory_texts = []

        # ── 用户记忆 ──
        try:
            memories = self.ctx.memory.select_memories(user_msg)
        except Exception as e:
            logger.warning(f"记忆选择失败: {e}")
            memories = []

        if memories:
            try:
                formatted = self.ctx.memory.format_memories(memories)
                if formatted:
                    all_memory_texts.append(formatted)
                    logger.info(f"注入了 {len(memories)} 条用户记忆")
            except Exception:
                pass

        # ── 项目记忆 ──
        try:
            from tea_agent.project_memory import ProjectMemoryManager
            pm = ProjectMemoryManager()
            pm_memories = pm.get_all(limit=30)
            if pm_memories:
                pm_formatted = pm.format_memories(pm_memories)
                if pm_formatted:
                    all_memory_texts.append(pm_formatted)
                    logger.info(f"注入了 {len(pm_memories)} 条项目记忆")
        except Exception as e:
            logger.debug(f"项目记忆加载跳过: {e}")

        # ── 合并 ──
        if all_memory_texts:
            self.ctx._injected_memories_text = "\n\n".join(all_memory_texts)
            self.ctx._injected_memories = memories
        else:
            self.ctx._injected_memories_text = ""
            self.ctx._injected_memories = []

        return self.ctx.messages

    def trigger_memory_extraction(self, topic_id: int) -> int:
        """
        从当前会话的未摘要对话中提取新记忆（使用便宜模型）。

        Args:
            topic_id: 当前主题 ID

        Returns:
            新增记忆数量，出错返回 -1
        """
        if not self.ctx.memory or not self.ctx.storage:
            return -1

        # 获取未摘要的对话
        try:
            unsummarized = self.ctx.storage.get_unsummarized_conversations(topic_id)
        except Exception as e:
            logger.warning(f"获取未摘要对话失败: {e}")
            return -1

        if not self.ctx.memory.is_extraction_needed(len(unsummarized)):
            return 0

        # 构建对话文本
        conv_text = self._build_conversation_text(unsummarized)
        if not conv_text.strip():
            return 0

        # 调用 LLM 提取
        try:
            client, model = self._get_summarize_client()
            is_cheap = (client is self.ctx.cheap_client and self.ctx.cheap_client is not None)
            messages = self.ctx.memory.build_extraction_prompt(conv_text)

            response = client.chat.completions.create(
                model=model,
                messages=messages,
                stream=False,
                extra_body={"thinking": {"type": "disabled"}},
                **_get_cheap_params(),
            )

            # 追踪 token（通过 context 上的 api 组件）
            if self.ctx.api_comp and hasattr(self.ctx.api_comp, '_track_api_usage'):
                self.ctx.api_comp._track_api_usage(response, is_cheap=is_cheap)

            # 2026-05-21 gen by Tea Agent, 修复: 便宜 token 在后台线程累加，
            # 但 _post_chat_pipeline 在此之前已读取并入库（值为 0），
            # 且下一轮 reset_session_state 会清零，导致便宜 token 从未持久化。
            # 此处直接在记忆提取完成后将便宜 token 写入 DB，独立于主流程时序。
            if is_cheap and hasattr(response, 'usage') and response.usage:
                try:
                    usage = response.usage
                    c_total = getattr(usage, 'total_tokens', 0) or 0
                    c_prompt = getattr(usage, 'prompt_tokens', 0) or 0
                    c_completion = getattr(usage, 'completion_tokens', 0) or 0
                    if c_total > 0:
                        # 用直接 UPDATE 避免 add_topic_tokens 的 conversation_count+1
                        conn = self.ctx.storage.conn
                        conn.execute('''
                            INSERT INTO topic_token_stats (
                                topic_id, total_cheap_tokens, total_cheap_prompt_tokens,
                                total_cheap_completion_tokens, last_update
                            ) VALUES (?, ?, ?, ?, datetime('now', 'localtime'))
                            ON CONFLICT(topic_id) DO UPDATE SET
                                total_cheap_tokens = total_cheap_tokens + excluded.total_cheap_tokens,
                                total_cheap_prompt_tokens = total_cheap_prompt_tokens + excluded.total_cheap_prompt_tokens,
                                total_cheap_completion_tokens = total_cheap_completion_tokens + excluded.total_cheap_completion_tokens,
                                last_update = datetime('now', 'localtime')
                        ''', (topic_id, c_total, c_prompt, c_completion))
                        conn.commit()
                except Exception:
                    pass

            result_text = response.choices[0].message.content or ""
            extracted = self.ctx.memory.parse_extraction_result(result_text)

            if extracted:
                count = self.ctx.memory.ingest_extracted(extracted, topic_id)
                logger.info(f"自动提取了 {count} 条新记忆")
                return count

        except Exception as e:
            logger.warning(f"记忆提取失败: {e}")

        return 0
    def _get_summarize_client(self):
        """获取摘要使用的客户端和模型（便宜模型或主模型）"""
        if self.ctx.cheap_client and self.ctx.cheap_model:
            return self.ctx.cheap_client, self.ctx.cheap_model
        return self.ctx.client, self.ctx.model

    @staticmethod
    def _build_conversation_text(conversations: List[Dict]) -> str:
        """将对话列表构建为纯文本"""
        lines = []
        for conv in conversations:
            lines.append(f"用户: {conv.get('user_msg', '')}")
            lines.append(f"助手: {conv.get('ai_msg', '')[:500]}")  # 截断长回复
            lines.append("")
        return "\n".join(lines)

    def get_injected_memories(self) -> List[Dict]:
        """获取当前会话注入的记忆列表"""
        return list(self.ctx._injected_memories)

    def get_memory_stats(self) -> Dict:
        """获取记忆统计"""
        if not self.ctx.memory or not self.ctx.storage:
            return {"total": 0, "by_category": {}, "by_priority": {}}
        try:
            return self.ctx.storage.get_memory_stats()
        except Exception:
            return {"total": 0, "by_category": {}, "by_priority": {}}
