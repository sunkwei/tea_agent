# version: 2.0.0
# @2026-06-07 gen by deepseek-v4-pro, Step5: 替换 mock LLM 为真实 API 调用

"""
自动记忆提取模块 (AutoMemoryExtractor) — v2

在对话结束时自动分析并提取值得长期保存的记忆：
1. 获取对话摘要
2. 通过 LLM API 分析：哪些信息值得长期保存
3. 自动分类：instruction/preference/fact
4. 去重检查（基于 embedding 余弦相似度）
5. 自动入库
"""

import logging
import json
import requests
from typing import Dict, List, Optional
from datetime import datetime

logger = logging.getLogger("Storage.AutoMemory")

# 记忆提取提示词（优化版）
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
        # Extract Chinese sentences with key indicators
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
            # Extract first meaningful user request
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
        return memories[:3]  # max 3 from fallback

    def _calculate_similarity(self, text1: str, text2: str) -> float:
        """计算两个文本之间的相似度（bigram Jaccard 系数）。
        
        Args:
            text1: 第一个文本
            text2: 第二个文本
            
        Returns:
            相似度分数 0-1，1 表示完全相同
        """
        if not text1 or not text2:
            return 0.0
        if text1 == text2:
            return 1.0
            
        # 生成 bigrams
        def get_bigrams(text):
            return set(text[i:i+2] for i in range(len(text) - 1))
        
        bigrams1 = get_bigrams(text1.lower())
        bigrams2 = get_bigrams(text2.lower())
        
        if not bigrams1 or not bigrams2:
            return 0.0
            
        # Jaccard 相似度
        intersection = bigrams1 & bigrams2
        union = bigrams1 | bigrams2
        return len(intersection) / len(union) if union else 0.0

    def _is_duplicate(self, content: str, threshold: float = 0.85) -> bool:
        """使用 embedding 余弦相似度检测重复（替代旧的 Jaccard 系数）。"""
        try:
            # Try vector-based dedup first
            engine = getattr(self.storage._memories, 'embedding_engine', None)
            if engine is not None:
                emb = engine.embed(content)
                if emb:
                    similar = self.storage._memories.search_by_vector(
                        emb, top_k=3, min_similarity=threshold
                    )
                    if similar:
                        return True

            # Fallback: content_hash exact match
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