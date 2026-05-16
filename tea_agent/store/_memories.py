"""
@2026-05-16 gen by tea_agent, MemoryStore — 长期记忆 CRUD + FIFO 淘汰
"""
import logging
from typing import Dict, List, Optional
from ._base import StoreComponent

logger = logging.getLogger("Storage.Memories")


class MemoryStore(StoreComponent):
    """长期记忆管理：增删改查、过期清理、CRITICAL FIFO 淘汰。"""

    # ── CRUD ──

    def add_memory(
        self, content: str, category: str = "general", priority: int = 2,
        importance: int = 3, expires_at: Optional[str] = None, tags: str = "",
        source_topic_id: Optional[str] = None,
    ) -> str:
        if priority == 0:
            self._enforce_critical_limit(max_critical=15)
        c = self.conn.cursor()
        mid = self._new_id()
        c.execute(
            "INSERT INTO memories (id, content, category, priority, importance, "
            "expires_at, tags, source_topic_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (mid, content, category, priority, importance, expires_at, tags, source_topic_id),
        )
        self.conn.commit()
        c.close()
        return mid

    def _enforce_critical_limit(self, max_critical: int = 15):
        c = self.conn.cursor()
        c.execute(
            "SELECT COUNT(*) FROM memories WHERE is_active = 1 AND priority = 0"
        )
        count = c.fetchone()[0]
        if count >= max_critical:
            overflow = count - max_critical + 1
            c.execute(
                "UPDATE memories SET is_active = 0, updated_at = CURRENT_TIMESTAMP "
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
        allowed = {
            "content", "category", "priority", "importance",
            "expires_at", "is_active", "tags", "last_accessed_at",
        }
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return False
        if updates.get("priority") == 0:
            self._enforce_critical_limit(max_critical=15)
        updates["updated_at"] = "CURRENT_TIMESTAMP"
        set_clause = ", ".join(
            f"{k} = ?" if k != "updated_at" else f"{k} = CURRENT_TIMESTAMP"
            for k in updates
        )
        values = [v for k, v in updates.items() if k != "updated_at"]
        c = self.conn.cursor()
        c.execute(
            f"UPDATE memories SET {set_clause} WHERE id = ?", values + [memory_id]
        )
        self.conn.commit()
        affected = c.rowcount
        c.close()
        return affected > 0

    def deactivate_memory(self, memory_id: str) -> bool:
        return self.update_memory(memory_id, is_active=0)

    def delete_memory(self, memory_id: str) -> bool:
        c = self.conn.cursor()
        c.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
        self.conn.commit()
        affected = c.rowcount
        c.close()
        return affected > 0

    def get_active_memories(self, limit: int = 50) -> List[Dict]:
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
        c = self.conn.cursor()
        c.execute(
            "UPDATE memories SET is_active = 0, updated_at = CURRENT_TIMESTAMP "
            "WHERE is_active = 1 AND expires_at IS NOT NULL AND expires_at < datetime('now')"
        )
        self.conn.commit()
        affected = c.rowcount
        c.close()
        return affected

    def touch_memory(self, memory_id: str):
        c = self.conn.cursor()
        c.execute(
            "UPDATE memories SET last_accessed_at = CURRENT_TIMESTAMP WHERE id = ?",
            (memory_id,),
        )
        self.conn.commit()
        c.close()

    def get_memory_stats(self) -> Dict:
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
