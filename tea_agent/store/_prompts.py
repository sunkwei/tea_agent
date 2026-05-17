"""
@2026-05-16 gen by tea_agent, PromptStore — 系统提示词版本管理
"""
from typing import Dict, List, Optional
from ._base import StoreComponent


class PromptStore(StoreComponent):
    """系统提示词版本管理：添加、查询、停用、回滚。"""

    def add_system_prompt(self, content: str, reason: str = "",
                           source_reflection_id: Optional[str] = None) -> str:
        c = self.conn.cursor()
        c.execute("SELECT MAX(CAST(version AS INTEGER)) FROM system_prompts")
        row = c.fetchone()
        max_ver = (row[0] or 0) if row else 0
        new_ver = str(max_ver + 1)
        pid = self._new_id()
        c.execute(
            "INSERT INTO system_prompts (id, version, content, reason, source_reflection_id, created_at) "
            "VALUES (?, ?, ?, ?, ?, datetime('now', 'localtime'))",
            (pid, new_ver, content, reason, source_reflection_id),
        )
        self.conn.commit()
        c.close()
        return pid

    def get_latest_system_prompt(self) -> Optional[Dict]:
        c = self.conn.cursor()
        c.execute(
            "SELECT * FROM system_prompts WHERE is_active = 1 "
            "ORDER BY CAST(version AS INTEGER) DESC LIMIT 1"
        )
        row = c.fetchone()
        c.close()
        return dict(row) if row else None

    def get_system_prompt_history(self, limit: int = 20) -> List[Dict]:
        c = self.conn.cursor()
        c.execute(
            "SELECT * FROM system_prompts ORDER BY CAST(version AS INTEGER) DESC LIMIT ?",
            (limit,),
        )
        rows = c.fetchall()
        c.close()
        return [dict(r) for r in rows]

    def deactivate_system_prompt(self, prompt_id: str) -> bool:
        c = self.conn.cursor()
        c.execute("UPDATE system_prompts SET is_active = 0 WHERE id = ?", (prompt_id,))
        self.conn.commit()
        affected = c.rowcount
        c.close()
        return affected > 0

    def rollback_system_prompt(self, prompt_id: str) -> bool:
        c = self.conn.cursor()
        c.execute("UPDATE system_prompts SET is_active = 0 WHERE is_active = 1")
        c.execute("UPDATE system_prompts SET is_active = 1 WHERE id = ?", (prompt_id,))
        self.conn.commit()
        affected = c.rowcount
        c.close()
        return affected > 0

    def get_system_prompt_count(self) -> int:
        c = self.conn.cursor()
        c.execute("SELECT COUNT(*) FROM system_prompts")
        count = c.fetchone()[0]
        c.close()
        return count
