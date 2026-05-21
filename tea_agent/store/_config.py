"""
"""
from typing import Dict, List, Optional
from ._base import StoreComponent

class ConfigHistoryStore(StoreComponent):
    """配置变更追踪：记录每次配置修改的历史。"""

    def add_config_change(
        self, key: str, new_value: str, old_value: Optional[str] = None,
        reason: str = "", source_reflection_id: Optional[str] = None,
    ) -> str:
        """Add config change.
        
        Args:
            key: Description.
            new_value: Description.
            old_value: Description.
            reason: Description.
            source_reflection_id: Description.
        """
        c = self.conn.cursor()
        cid = self._new_id()
        c.execute(
            "INSERT INTO config_history (id, key, old_value, new_value, reason, source_reflection_id, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, datetime('now', 'localtime'))",
            (
                cid, key,
                str(old_value) if old_value is not None else None,
                str(new_value), reason, source_reflection_id,
            ),
        )
        self.conn.commit()
        c.close()
        return cid

    def get_config_history(self, key: str = "", limit: int = 20) -> List[Dict]:
        """Get the config history.
        
        Args:
            key: Description.
            limit: Description.
        """
        c = self.conn.cursor()
        if key:
            c.execute(
                "SELECT * FROM config_history WHERE key = ? ORDER BY created_at DESC LIMIT ?",
                (key, limit),
            )
        else:
            c.execute(
                "SELECT * FROM config_history ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )
        rows = c.fetchall()
        c.close()
        return [dict(r) for r in rows]

    def get_config_changes_since(self, since_id: str = "0") -> List[Dict]:
        """Get the config changes since.
        
        Args:
            since_id: Description.
        """
        c = self.conn.cursor()
        c.execute(
            "SELECT * FROM config_history WHERE id > ? ORDER BY created_at ASC",
            (since_id,),
        )
        rows = c.fetchall()
        c.close()
        return [dict(r) for r in rows]
