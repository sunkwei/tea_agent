"""
会话记忆组件

负责会话记忆注入与自动提取。
从 SessionMemoryMixin 重构而来，使用组合模式替代 Mixin。
"""

import json
import requests
from datetime import datetime
from typing import List, Dict, Optional, TYPE_CHECKING
from .session._context import SessionComponent, SessionContext
from tea_agent.session._params import get_cheap_params

if TYPE_CHECKING:
    from tea_agent.memory import MemoryManager

import logging

logger = logging.getLogger("session.memory")

# 向后兼容别名
_get_cheap_params = lambda: get_cheap_params("memory")

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
                logger.exception("operation failed")


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

    def trigger_memory_extraction(self, topic_id: str) -> int:
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
            messages = self.ctx.memory.build_extraction_prompt(conv_text)

            response = client.chat.completions.create(
                model=model,
                messages=messages,
                stream=False,
                extra_body={"thinking": {"type": "disabled"}},
                **_get_cheap_params(),
            )

            # 追踪 token
            # 通过 context 上的 api 组件追踪（如果存在）
            if hasattr(self, '_track_api_usage'):
                self._track_api_usage(response, is_cheap=True)

            result_text = response.choices[0].message.content or ""
            extracted = self.ctx.memory.parse_extraction_result(result_text)

            if extracted:
                count = self.ctx.memory.ingest_extracted(extracted, topic_id)
                # 标记已提取（避免重复提取）
                self._mark_conversations_extracted(unsummarized)
                logger.info(f"自动提取了 {count} 条新记忆")
                return count

        except Exception as e:
            logger.warning(f"记忆提取失败: {e}")

        return 0

    def _mark_conversations_extracted(self, conversations: List[Dict]):
        """标记对话为已提取，避免重复处理。"""
        if not conversations or not self.ctx.storage:
            return
        try:
            c = self.ctx.storage.conn.cursor()
            for conv in conversations:
                c.execute("UPDATE conversations SET is_summarized = 1 WHERE id = ?", (conv["id"],))
            self.ctx.storage.conn.commit()
            c.close()
        except Exception as e:
            logger.debug(f"标记已提取失败: {e}")

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


# ══════════════════════════════════════════════════════════════
# AutoMemoryExtractor — 从 store/_auto_memory.py 迁入
# 独立提取器，不依赖会话上下文，可直接用 storage 实例化
# ══════════════════════════════════════════════════════════════

EXTRACTION_PROMPT = """Analyze the following conversation and extract information worth long-term preservation.

Conversation:
{conversation}

Return a JSON array of memories. Each memory object:
- "content": concise memory content (50-200 chars, in Chinese)
- "category": one of [instruction, preference, fact, reminder, general]
- "importance": 1-5 (1=trivial, 5=critical)
- "tags": comma-separated keywords

Guidelines:
- instruction = user's clear request/rule
- preference = user's habit or preference
- fact = technical fact or knowledge point
- reminder = something to remember
- general = other useful info

Only extract truly valuable information. Return empty array [] if nothing worth saving.

Format: [{"content": "...", "category": "...", "importance": 3, "tags": "..."}]"""


class AutoMemoryExtractor:
    """自动记忆提取器 v2 — 真实 LLM 调用 + 向量去重"""

    def __init__(self, storage):
        self.storage = storage
        self._model_config = None
        self._load_config()

    def _load_config(self):
        """从配置加载 cheap model 信息。"""
        try:
            from tea_agent.config import get_config
            cfg = get_config()
            self._model_config = cfg.cheap_model
            if not self._model_config or not getattr(self._model_config, 'api_key', None):
                self._model_config = cfg.main_model
            logger.info(f"AutoMemory LLM: {getattr(self._model_config, 'model', 'unknown')}")
        except Exception as e:
            logger.warning(f"加载模型配置失败: {e}")
            self._model_config = None

    def extract_from_topic(self, topic_id: str, force: bool = False) -> Dict:
        """从主题对话中自动提取记忆。"""
        try:
            conversations = self._get_unextracted_conversations(topic_id)
            if not conversations:
                return {"status": "no_new_conversations", "extracted": 0}

            conversation_text = self._merge_conversations(conversations)
            extracted_memories = self._extract_with_llm(conversation_text)

            saved_count = 0
            skipped_count = 0

            for memory in extracted_memories:
                if not force and self._is_duplicate(memory["content"]):
                    skipped_count += 1
                    continue

                self.storage.add_memory(
                    content=memory["content"],
                    category=memory.get("category", "general"),
                    importance=memory.get("importance", 3),
                    tags=memory.get("tags", ""),
                    source_topic_id=topic_id,
                )
                saved_count += 1

            self._mark_conversations_extracted(conversations)
            logger.info(f"Topic {topic_id}: saved {saved_count}, skipped {skipped_count}")

            return {
                "status": "success",
                "extracted": saved_count,
                "skipped": skipped_count,
                "total_conversations": len(conversations),
            }

        except Exception as e:
            logger.error(f"AutoMemory extract failed: {e}")
            return {"status": "error", "error": str(e)}

    def _get_unextracted_conversations(self, topic_id: str) -> List[Dict]:
        c = self.storage.conn.cursor()
        c.execute(
            "SELECT id, user_msg, ai_msg, stamp FROM conversations "
            "WHERE topic_id = ? AND is_summarized = 0 ORDER BY stamp ASC",
            (topic_id,),
        )
        rows = c.fetchall()
        c.close()
        return [dict(r) for r in rows]

    def _merge_conversations(self, conversations: List[Dict]) -> str:
        parts = []
        for conv in conversations[:10]:
            user_msg = (conv.get("user_msg", "") or "")[:500]
            ai_msg = (conv.get("ai_msg", "") or "")[:1000]
            parts.append(f"User: {user_msg}\nAssistant: {ai_msg}")
        return "\n\n".join(parts)

    def _calculate_similarity(self, text1: str, text2: str) -> float:
        """计算两个文本之间的相似度（bigram Jaccard 系数）。"""
        if not text1 or not text2:
            return 0.0
        if text1 == text2:
            return 1.0
        def get_bigrams(text):
            return set(text[i:i+2] for i in range(len(text) - 1))
        bigrams1 = get_bigrams(text1.lower())
        bigrams2 = get_bigrams(text2.lower())
        if not bigrams1 or not bigrams2:
            return 0.0
        intersection = bigrams1 & bigrams2
        union = bigrams1 | bigrams2
        return len(intersection) / len(union) if union else 0.0



    def _extract_with_llm(self, conversation_text: str) -> List[Dict]:
        """真实 LLM 调用，替代旧的 mock 实现。"""
        if self._model_config is None:
            logger.warning("No LLM config, falling back to keyword extraction")
            return self._fallback_extract(conversation_text)

        try:
            prompt = EXTRACTION_PROMPT.format(conversation=conversation_text[:4000])
            url = (getattr(self._model_config, 'api_url', '') or '').rstrip('/')
            if not url.endswith('/v1'):
                url += '/v1' if not url.endswith('/v1') else ''
            url += '/chat/completions'

            headers = {
                "Content-Type": "application/json",
            }
            api_key = getattr(self._model_config, 'api_key', '') or ''
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"

            payload = {
                "model": getattr(self._model_config, 'model', 'gpt-3.5-turbo'),
                "messages": [
                    {"role": "system", "content": "You are a memory extraction assistant. Extract key information from conversations. Reply in Chinese."},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.1,
                "max_tokens": 1024,
            }

            resp = requests.post(url, json=payload, headers=headers, timeout=30)
            resp.raise_for_status()
            data = resp.json()

            content = data["choices"][0]["message"]["content"].strip()
            # Clean markdown code blocks if present
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
                content = content.strip()

            memories = json.loads(content)
            if isinstance(memories, list):
                return memories
            return []

        except Exception as e:
            logger.warning(f"LLM extraction failed: {e}, falling back to keyword")
            return self._fallback_extract(conversation_text)

    def _fallback_extract(self, conversation_text: str) -> List[Dict]:
        """关键词提取作为 LLM 失败的备选。"""
        memories = []
        lines = conversation_text.split('\n')
        for line in lines:
            line = line.strip()
            if any(kw in line for kw in ["记住", "不要", "必须", "偏好", "喜欢", "习惯"]):
                memories.append({
                    "content": line[:150],
                    "category": "instruction" if any(kw in line for kw in ["记住", "不要", "必须"]) else "preference",
                    "importance": 3,
                    "tags": "auto_extracted,keyword_fallback",
                })
        if not memories and len(conversation_text) > 20:
            for line in lines:
                if line.startswith("User:") and len(line) > 20:
                    content = line[5:].strip()[:150]
                    if content:
                        memories.append({
                            "content": content,
                            "category": "general",
                            "importance": 2,
                            "tags": "auto_extracted,fallback",
                        })
                        break
        return memories[:3]

    def _is_duplicate(self, content: str, threshold: float = 0.85) -> bool:
        """使用 embedding 余弦相似度或 content_hash 检测重复。"""
        try:
            engine = getattr(self.storage._memories, 'embedding_engine', None)
            if engine is not None:
                emb = engine.embed(content)
                if emb:
                    similar = self.storage._memories.search_by_vector(
                        emb, top_k=3, min_similarity=threshold
                    )
                    if similar:
                        return True

            import hashlib
            h = hashlib.sha256(content.encode('utf-8')).hexdigest()[:16]
            c = self.storage.conn.cursor()
            c.execute(
                "SELECT COUNT(*) FROM memories WHERE content_hash = ? AND is_active = 1",
                (h,),
            )
            count = c.fetchone()[0]
            c.close()
            return count > 0

        except Exception as e:
            logger.debug(f"Dedup check failed: {e}")
            return False

    def _mark_conversations_extracted(self, conversations: List[Dict]):
        c = self.storage.conn.cursor()
        for conv in conversations:
            c.execute("UPDATE conversations SET is_summarized = 1 WHERE id = ?", (conv["id"],))
        self.storage.conn.commit()
        c.close()

    def get_extraction_stats(self, topic_id: Optional[str] = None) -> Dict:
        c = self.storage.conn.cursor()
        c.execute("SELECT COUNT(*) as total FROM memories WHERE is_active = 1")
        total = c.fetchone()["total"]

        if topic_id:
            c.execute("SELECT COUNT(*) as cnt FROM memories WHERE source_topic_id = ?", (topic_id,))
            from_topic = c.fetchone()["cnt"]
        else:
            from_topic = None

        c.execute("SELECT category, COUNT(*) as cnt FROM memories WHERE is_active = 1 GROUP BY category")
        by_category = {r["category"]: r["cnt"] for r in c.fetchall()}
        c.close()

        return {"total_memories": total, "from_topic": from_topic, "by_category": by_category}

    def get_memory_stats(self) -> Dict:
        """获取记忆统计"""
        if not self.ctx.memory or not self.ctx.storage:
            return {"total": 0, "by_category": {}, "by_priority": {}}
        try:
            return self.ctx.storage.get_memory_stats()
        except Exception:
            return {"total": 0, "by_category": {}, "by_priority": {}}
