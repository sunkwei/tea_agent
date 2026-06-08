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

