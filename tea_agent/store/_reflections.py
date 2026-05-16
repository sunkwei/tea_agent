"""
@2026-05-16 gen by tea_agent, ReflectionStore — 反思记录 CRUD
"""
import json
from typing import Dict, List, Optional
from ._base import StoreComponent


class ReflectionStore(StoreComponent):
    """反思记录：元认知反思的增删查改。"""

    def add_reflection(
        self, summary: str, details: str = "",
        tool_stats: Optional[Dict] = None, suggestions: Optional[List[str]] = None,
        topic_id: Optional[str] = None,
    ) -> str:
        c = self.conn.cursor()
        rid = self._new_id()
        c.execute(
            "INSERT INTO reflections (id, topic_id, summary, details, tool_stats, suggestions) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                rid, topic_id, summary, details,
                json.dumps(tool_stats or {}, ensure_ascii=False),
                json.dumps(suggestions or [], ensure_ascii=False),
            ),
        )
        self.conn.commit()
        c.close()
        return rid

    def get_recent_reflections(self, limit: int = 10) -> List[Dict]:
        c = self.conn.cursor()
        c.execute(
            "SELECT * FROM reflections WHERE is_applied = 0 ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
        rows = c.fetchall()
        c.close()
        return [dict(r) for r in rows]

    def mark_reflection_applied(self, reflection_id: str):
        c = self.conn.cursor()
        c.execute(
            "UPDATE reflections SET is_applied = 1 WHERE id = ?", (reflection_id,)
        )
        self.conn.commit()
        c.close()

    def get_reflection_stats(self) -> Dict:
        c = self.conn.cursor()
        c.execute("SELECT COUNT(*) as total FROM reflections")
        total = c.fetchone()["total"]
        c.execute(
            "SELECT COUNT(*) as unapplied FROM reflections WHERE is_applied = 0"
        )
        unapplied = c.fetchone()["unapplied"]
        c.close()
        return {"total": total, "unapplied": unapplied}
