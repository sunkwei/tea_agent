"""
# @2026-06-07 gen by deepseek-v4-pro, Step 1: 记忆写入时自动计算并存储 embedding
"""
import logging
import hashlib
import numpy as np
from typing import Dict, List, Optional
from ._component import StoreComponent

logger = logging.getLogger("Storage.Memories")

class MemoryStore(StoreComponent):
    """长期记忆管理：增删改查、嵌入存取、过期清理、CRITICAL FIFO 淘汰。"""

    # 嵌入引擎（由 Storage 在初始化后注入）
    embedding_engine = None

    # ── CRUD ──

    def add_memory(
        self, content: str, category: str = "general", priority: int = 2,
        importance: int = 3, expires_at: Optional[str] = None, tags: str = "",
        source_topic_id: Optional[str] = None, pinned: int = 0,
        embedding: Optional[List[float]] = None,
    ) -> str:
        """Add memory with optional embedding (auto-computes via embedding_engine)."""
        if priority == 0:
            self._enforce_critical_limit(max_critical=15)
        # Auto-compute embedding if engine available
        if embedding is None and self.embedding_engine is not None:
            try:
                embedding = self.embedding_engine.embed(content)
            except Exception as e:
                logger.warning(f"compute embedding failed: {e}")
        content_hash = hashlib.sha256(content.encode('utf-8')).hexdigest()[:16]
        embedding_blob = None
        if embedding:
            try:
                arr = np.array(embedding, dtype=np.float32)
                embedding_blob = arr.tobytes()
            except Exception as e:
                logger.warning(f"serialize embedding failed: {e}")
        c = self.conn.cursor()
        mid = self._new_id()
        c.execute(
            "INSERT INTO memories (id, content, category, priority, importance, "
            "expires_at, tags, source_topic_id, pinned, content_hash, embedding, "
            "created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
            "datetime('now', 'localtime'), datetime('now', 'localtime'))",
            (mid, content, category, priority, importance, expires_at, tags,
             source_topic_id, pinned, content_hash, embedding_blob),
        )
        self.conn.commit()
        c.close()
        return mid

    def _enforce_critical_limit(self, max_critical: int = 15):
        """Internal: enforce critical limit.
        
        Args:
            max_critical: Description.
        """
        c = self.conn.cursor()
        c.execute(
            "SELECT COUNT(*) FROM memories WHERE is_active = 1 AND priority = 0"
        )
        count = c.fetchone()[0]
        if count >= max_critical:
            overflow = count - max_critical + 1
            c.execute(
                "UPDATE memories SET is_active = 0, updated_at = datetime('now', 'localtime') "
                "WHERE id IN (SELECT id FROM memories WHERE is_active = 1 AND priority = 0 "
                "ORDER BY id ASC LIMIT ?)",
                (overflow,),
            )
            self.conn.commit()
            logger.info(
                f"CRITICAL FIFO 淘汰: 软删除 {overflow} 条旧记忆 (阈值={max_critical})"
            )
        c.close()

    def update_memory(self, memory_id: str, **fields) -> bool:
        """Update memory.
        
        Args:
            memory_id: Description.
        """
        allowed = {
            "content", "category", "priority", "importance",
            "expires_at", "is_active", "tags", "last_accessed_at", "pinned",
            "created_at",  # 允许更新创建时间（用于LLM升级重置年龄）
        }
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return False
        if updates.get("priority") == 0:
            self._enforce_critical_limit(max_critical=15)
        from datetime import datetime
        updates["updated_at"] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        # 动态构建 SET 子句：全部使用参数化查询，消除 SQL 函数拼接
        set_parts = []
        values = []
        for k, v in updates.items():
            set_parts.append(f"{k} = ?")
            values.append(v)

        c = self.conn.cursor()
        c.execute(
            f"UPDATE memories SET {', '.join(set_parts)} WHERE id = ?", values + [memory_id]
        )
        self.conn.commit()
        affected = c.rowcount
        c.close()
        return affected > 0

    def deactivate_memory(self, memory_id: str) -> bool:
        """Deactivate memory.
        
        Args:
            memory_id: Description.
        """
        return self.update_memory(memory_id, is_active=0)

    def delete_memory(self, memory_id: str) -> bool:
        """Delete memory.
        
        Args:
            memory_id: Description.
        """
        c = self.conn.cursor()
        c.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
        self.conn.commit()
        affected = c.rowcount
        c.close()
        return affected > 0

    def get_active_memories(self, limit: int = 50) -> List[Dict]:
        """Get the active memories.
        
        Args:
            limit: Description.
        """
        self.cleanup_expired_memories()
        c = self.conn.cursor()
        c.execute(
            "SELECT * FROM memories WHERE is_active = 1 "
            "ORDER BY priority ASC, last_accessed_at DESC LIMIT ?",
            (limit,),
        )
        rows = c.fetchall()
        c.close()
        return [dict(r) for r in rows]

    def get_instructions(self) -> List[Dict]:
        """Get the instructions."""
        self.cleanup_expired_memories()
        c = self.conn.cursor()
        c.execute(
            "SELECT * FROM memories WHERE is_active = 1 AND priority = 0 "
            "ORDER BY last_accessed_at DESC"
        )
        rows = c.fetchall()
        c.close()
        return [dict(r) for r in rows]

    def search_memories(
        self, query: str = "", category: str = "",
        tags: Optional[List[str]] = None, min_importance: int = 0, limit: int = 20,
    ) -> List[Dict]:
        """Search memories.
        
        Args:
            query: Description.
            category: Description.
            tags: Description.
            min_importance: Description.
            limit: Description.
        """
        self.cleanup_expired_memories()
        conditions = ["is_active = 1"]
        params: list = []
        if query:
            conditions.append("content LIKE ?")
            params.append(f"%{query}%")
        if category:
            conditions.append("category = ?")
            params.append(category)
        if min_importance:
            conditions.append("importance >= ?")
            params.append(min_importance)
        where = " AND ".join(conditions)
        c = self.conn.cursor()
        c.execute(
            f"SELECT * FROM memories WHERE {where} "
            "ORDER BY priority ASC, last_accessed_at DESC LIMIT ?",
            params + [limit],
        )
        rows = c.fetchall()
        c.close()
        results = [dict(r) for r in rows]
        if tags:
            tag_set = set(t.lower() for t in tags)
            results = [
                r for r in results
                if tag_set & set(t.strip().lower() for t in (r.get("tags", "") or "").split(","))
            ]
        return results[:limit]

    def cleanup_expired_memories(self) -> int:
        """Cleanup expired memories."""
        c = self.conn.cursor()
        c.execute(
            "UPDATE memories SET is_active = 0, updated_at = datetime('now', 'localtime') "
            "WHERE is_active = 1 AND expires_at IS NOT NULL AND expires_at < datetime('now')"
        )
        self.conn.commit()
        affected = c.rowcount
        c.close()
        return affected

    def touch_memory(self, memory_id: str):
        """Touch memory.
        
        Args:
            memory_id: Description.
        """
        c = self.conn.cursor()
        c.execute(
            "UPDATE memories SET last_accessed_at = datetime('now', 'localtime') WHERE id = ?",
            (memory_id,),
        )
        self.conn.commit()
        c.close()

    # ── Embedding 存取 ──

    def get_memory_embedding(self, memory_id: str) -> Optional[List[float]]:
        """读取记忆的 embedding 向量。"""
        c = self.conn.cursor()
        c.execute("SELECT embedding FROM memories WHERE id = ?", (memory_id,))
        row = c.fetchone()
        c.close()
        if row and row["embedding"]:
            try:
                arr = np.frombuffer(row["embedding"], dtype=np.float32)
                return arr.tolist()
            except Exception:
                return None
        return None

    def batch_get_embeddings(self, limit: int = 200) -> List[Dict]:
        """批量获取有 embedding 的活跃记忆（用于相似度扫描）。"""
        c = self.conn.cursor()
        c.execute(
            "SELECT id, content, embedding, priority, importance FROM memories "
            "WHERE is_active = 1 AND embedding IS NOT NULL "
            "ORDER BY created_at DESC LIMIT ?", (limit,)
        )
        rows = c.fetchall()
        c.close()
        results = []
        for row in rows:
            d = dict(row)
            blob = d.pop("embedding", None)
            if blob:
                try:
                    d["embedding"] = np.frombuffer(blob, dtype=np.float32).tolist()
                except Exception:
                    d["embedding"] = None
            else:
                d["embedding"] = None
            results.append(d)
        return results

    def search_by_vector(self, query_embedding: List[float], top_k: int = 10,
                          min_similarity: float = 0.3) -> List[Dict]:
        """基于向量相似度搜索记忆。"""
        all_mems = self.batch_get_embeddings(limit=200)
        if not all_mems:
            return []

        query_arr = np.array(query_embedding, dtype=np.float32)
        q_norm = np.linalg.norm(query_arr)
        if q_norm == 0:
            return []

        scored = []
        for mem in all_mems:
            emb = mem.get("embedding")
            if not emb or len(emb) != len(query_embedding):
                continue
            mem_arr = np.array(emb, dtype=np.float32)
            sim = float(mem_arr @ query_arr) / (q_norm * np.linalg.norm(mem_arr))
            if sim >= min_similarity:
                scored.append({**mem, "similarity": round(sim, 4)})

        scored.sort(key=lambda x: x["similarity"], reverse=True)
        return scored[:top_k]

    # ── 重复检测与合并提权 ──

    def detect_duplicates(self, threshold: float = 0.92) -> List[tuple]:
        """Scan all active memories for near-duplicate pairs using cosine similarity."""
        mems = self.batch_get_embeddings(limit=200)
        if len(mems) < 2:
            return []

        pairs = []
        for i in range(len(mems)):
            emb_i = mems[i].get('embedding')
            if emb_i is None:
                continue
            arr_i = np.array(emb_i, dtype=np.float32)
            ni = np.linalg.norm(arr_i)
            if ni == 0:
                continue
            for j in range(i + 1, len(mems)):
                emb_j = mems[j].get('embedding')
                if emb_j is None or len(emb_j) != len(emb_i):
                    continue
                arr_j = np.array(emb_j, dtype=np.float32)
                sim = float(arr_i @ arr_j) / (ni * np.linalg.norm(arr_j))
                if sim >= threshold:
                    pairs.append((mems[i]['id'], mems[j]['id'], round(sim, 4)))

        pairs.sort(key=lambda x: x[2], reverse=True)
        return pairs

    def merge_duplicates(self, keep_id: str, remove_id: str) -> bool:
        """Merge two duplicate memories: combine content, boost priority+importance, soft-delete."""
        c = self.conn.cursor()
        try:
            c.execute('SELECT * FROM memories WHERE id = ?', (keep_id,))
            keep = c.fetchone()
            c.execute('SELECT * FROM memories WHERE id = ?', (remove_id,))
            remove = c.fetchone()
            if not keep or not remove:
                logger.warning(f'Merge failed: memory not found keep={keep_id} remove={remove_id}')
                return False

            keep_dict = dict(keep)
            remove_dict = dict(remove)

            # Merge content: keep longer, include shorter as context
            merged = keep_dict['content']
            if remove_dict['content'] not in merged:
                merged = keep_dict['content'] + '\n---\n' + remove_dict['content']

            # Merge tags
            ktags = set(t.strip() for t in (keep_dict.get('tags','') or '').split(',') if t.strip())
            rtags = set(t.strip() for t in (remove_dict.get('tags','') or '').split(',') if t.strip())
            merged_tags = ','.join(sorted(ktags | rtags))

            # Boost
            new_priority = max(0, keep_dict['priority'] - 1)  # lower = more important
            new_importance = min(5, (keep_dict['importance'] or 3) + 1)

            from datetime import datetime
            now = __import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            c.execute(
                "UPDATE memories SET content = ?, tags = ?, priority = ?, "
                "importance = ?, updated_at = ? WHERE id = ?",
                (merged, merged_tags, new_priority, new_importance, now, keep_id),
            )
            c.execute(
                "UPDATE memories SET is_active = 0, updated_at = ? WHERE id = ?",
                (now, remove_id),
            )
            self.conn.commit()
            logger.info(f'Merged: {remove_id} -> {keep_id}, priority={new_priority}, importance={new_importance}')
            return True

        except Exception as e:
            self.conn.rollback()
            logger.error(f'Merge failed: {e}')
            return False
        finally:
            c.close()

    def auto_dedup(self, threshold: float = 0.92) -> Dict:
        """Auto-detect and merge all duplicate memory pairs."""
        pairs = self.detect_duplicates(threshold=threshold)
        merged = 0
        errors = 0
        processed = set()
        for a_id, b_id, sim in pairs:
            if a_id in processed or b_id in processed:
                continue
            if self.merge_duplicates(a_id, b_id):
                merged += 1
                processed.add(a_id)
                processed.add(b_id)
            else:
                errors += 1
        return {'scanned': len(pairs), 'merged': merged, 'errors': errors, 'threshold': threshold}


    # ── 反思归纳 ──

    def reflect_and_summarize(self, max_memories: int = 50, min_cluster_size: int = 2) -> Dict:
        """反思归纳：按类别聚类近期记忆，生成摘要并归档旧记忆。"""
        c = self.conn.cursor()
        c.execute(
            "SELECT id, content, category, priority, importance, created_at FROM memories "
            "WHERE is_active = 1 ORDER BY created_at DESC LIMIT ?",
            (max_memories,),
        )
        rows = c.fetchall()
        c.close()

        if not rows:
            return {'summarized': 0, 'degraded': 0, 'summary_ids': []}

        groups = {}
        for r in rows:
            d = dict(r)
            cat = d['category'] or 'general'
            groups.setdefault(cat, []).append(d)

        summary_ids = []
        degraded = 0

        for cat, mems in groups.items():
            if len(mems) < min_cluster_size:
                continue
            texts = [m['content'] for m in mems if m['content']]
            if not texts:
                continue

            summary = self._generate_summary(texts, cat)

            sid = self.add_memory(
                content=summary,
                category='reflection',
                priority=0,
                importance=5,
                tags='summary,' + cat,
            )
            summary_ids.append(sid)

            now = __import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            for m in mems:
                new_imp = max(1, (m['importance'] or 3) - 1)
                if new_imp != m['importance']:
                    cc = self.conn.cursor()
                    cc.execute(
                        "UPDATE memories SET importance = ?, updated_at = ? WHERE id = ?",
                        (new_imp, now, m['id']),
                    )
                    self.conn.commit()
                    cc.close()
                    degraded += 1

            logger.info(f'归纳 [{cat}]: {len(mems)}条 -> 摘要 {sid[:8]}, 降级 {degraded}条')

        return {'summarized': len(summary_ids), 'degraded': degraded, 'summary_ids': summary_ids}

    def _generate_summary(self, texts: List[str], category: str) -> str:
        """基于关键词从同类记忆中生成摘要。"""
        from collections import Counter
        if not texts:
            return f"[{category}] 暂无内容"
        if len(texts) == 1:
            return f"[{category}] {texts[0][:200]}"

        all_words = []
        for t in texts:
            all_words.extend(t.lower().split())

        word_counts = Counter(all_words)
        keywords = [w for w, c in word_counts.most_common(10) if len(w) > 1][:5]

        date_info = __import__('datetime').datetime.now().strftime('%Y-%m-%d')
        parts = [
            f"[{category.upper()}] 反思归纳 ({date_info})",
            f"涵盖 {len(texts)} 条相关记忆",
        ]
        if keywords:
            parts.append(f"关键词: {', '.join(keywords)}")
        parts.append("---")
        for i, t in enumerate(texts[:5]):
            parts.append(f"{i+1}. {t.strip()[:100]}")
        if len(texts) > 5:
            parts.append(f"... 及其他 {len(texts)-5} 条")

        return chr(10).join(parts)
    def get_memory_stats(self) -> Dict:
        """Get the memory stats."""
        c = self.conn.cursor()
        c.execute("SELECT COUNT(*) as total FROM memories WHERE is_active = 1")
        total = c.fetchone()["total"]
        c.execute(
            "SELECT category, COUNT(*) as cnt FROM memories WHERE is_active = 1 GROUP BY category"
        )
        by_category = {r["category"]: r["cnt"] for r in c.fetchall()}
        c.execute(
            "SELECT priority, COUNT(*) as cnt FROM memories WHERE is_active = 1 GROUP BY priority"
        )
        by_priority = {r["priority"]: r["cnt"] for r in c.fetchall()}
        c.close()
        return {"total": total, "by_category": by_category, "by_priority": by_priority}

