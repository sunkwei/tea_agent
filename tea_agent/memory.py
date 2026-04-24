"""
记忆模块
为 Agent 提供长期记忆能力，使用 SQLite 存储
"""

import sqlite3
import json
import os
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional, cast


class Memory:
    """
    Agent 长期记忆类

    使用 SQLite 存储记忆摘要，支持分类、标签、重要度等元数据。
    数据库文件存储在 $HOME/.tea_agent/memory.db
    """

    DB_PATH = str(Path.home() / ".tea_agent" / "memory.db")

    CATEGORIES = [
        "user_preference",
        "fact",
        "project_info",
        "decision",
        "experience",
        "code_pattern",
        "tool_usage",
        "environment",
        "general",
    ]

    def __init__(self, db_path: str=""):
        self.db_path = db_path if db_path else self.DB_PATH
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        """获取数据库连接，启用 WAL 模式和性能优化"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        # WAL 模式提升并发性能
        conn.execute("PRAGMA journal_mode=WAL")
        # 降低刷盘延迟
        conn.execute("PRAGMA synchronous=NORMAL")
        # 增大缓存
        conn.execute("PRAGMA cache_size=-8000")
        return conn

    def _init_db(self):
        """初始化数据库表"""
        conn = self._get_conn()
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    category TEXT NOT NULL DEFAULT 'general',
                    summary TEXT NOT NULL,
                    tags TEXT NOT NULL DEFAULT '[]',
                    importance INTEGER NOT NULL DEFAULT 3,
                    source_topic TEXT,
                    created_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_category ON memories(category)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_importance ON memories(importance DESC)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_timestamp ON memories(timestamp)
            """)
            conn.commit()
        finally:
            conn.close()

    def add_memory(
        self,
        summary: str,
        category: str = "general",
        tags: List[str] = None,
        importance: int = 3,
        source_topic: str = ""
    ) -> int:
        """
        添加一条记忆

        Args:
            summary: 记忆摘要内容
            category: 分类
            tags: 标签列表
            importance: 重要度 1-5
            source_topic: 来源话题

        Returns:
            int: 新插入的记忆ID
        """
        if category not in self.CATEGORIES:
            category = "general"
        importance = max(1, min(5, importance))
        tags = tags or []
        tags_json = json.dumps(tags, ensure_ascii=False)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        conn = self._get_conn()
        try:
            cursor = conn.execute(
                """INSERT INTO memories (timestamp, category, summary, tags, importance, source_topic, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (now, category, summary, tags_json, importance, source_topic, now)
            )
            last_rowid = cast(int, cursor.lastrowid)
            conn.commit()
            return last_rowid
        finally:
            conn.close()

    def search_memories(
        self,
        query: str = "",
        category: str = "",
        tags: List[str] = None,
        min_importance: int = 0,
        limit: int = 20
    ) -> List[Dict]:
        """
        搜索记忆

        Args:
            query: 关键词搜索
            category: 按分类过滤
            tags: 按标签过滤（包含任一标签即可）
            min_importance: 最低重要度
            limit: 返回数量限制

        Returns:
            List[Dict]: 记忆列表
        """
        tags = tags or []
        conditions = []
        params = []

        if query:
            conditions.append("summary LIKE ?")
            params.append(f"%{query}%")
        if category:
            conditions.append("category = ?")
            params.append(category)
        if min_importance is not None:
            conditions.append("importance >= ?")
            params.append(min_importance)
        if tags:
            tag_conditions = []
            for tag in tags:
                tag_conditions.append("tags LIKE ?")
                params.append(f"%{tag}%")
            conditions.append(f"({' OR '.join(tag_conditions)})")

        where = " AND ".join(conditions) if conditions else "1=1"
        sql = f"SELECT * FROM memories WHERE {where} ORDER BY importance DESC, created_at DESC LIMIT ?"
        params.append(limit)

        conn = self._get_conn()
        try:
            rows = conn.execute(sql, params).fetchall()
            return [self._row_to_dict(row) for row in rows]
        finally:
            conn.close()

    def get_recent_memories(self, limit: int = 20, category: str = "") -> List[Dict]:
        """获取最近的记忆"""
        if category:
            return self.search_memories(category=category, limit=limit)

        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT * FROM memories ORDER BY created_at DESC LIMIT ?",
                (limit,)
            ).fetchall()
            return [self._row_to_dict(row) for row in rows]
        finally:
            conn.close()

    def get_important_memories(self, limit: int = 20) -> List[Dict]:
        """获取重要记忆（importance >= 4）"""
        return self.search_memories(min_importance=4, limit=limit)

    def get_memories_by_category(self, category: str, limit: int = 20) -> List[Dict]:
        """按分类获取记忆"""
        return self.search_memories(category=category, limit=limit)

    def delete_memory(self, memory_id: int) -> bool:
        """删除指定记忆"""
        conn = self._get_conn()
        try:
            conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
            conn.commit()
            return True
        finally:
            conn.close()

    def update_memory(
        self,
        memory_id: int,
        summary: str = "",
        category: str = "",
        tags: List[str] = None,
        importance: int = 0
    ) -> bool:
        """更新记忆"""
        fields = []
        params = []

        if summary is not None:
            fields.append("summary = ?")
            params.append(summary)
        if category is not None:
            if category not in self.CATEGORIES:
                category = "general"
            fields.append("category = ?")
            params.append(category)
        if tags is not None:
            fields.append("tags = ?")
            params.append(json.dumps(tags, ensure_ascii=False))
        if importance is not None:
            importance = max(1, min(5, importance))
            fields.append("importance = ?")
            params.append(importance)

        if not fields:
            return False

        params.append(memory_id)
        sql = f"UPDATE memories SET {', '.join(fields)} WHERE id = ?"

        conn = self._get_conn()
        try:
            conn.execute(sql, params)
            conn.commit()
            return True
        finally:
            conn.close()

    def get_all_categories(self) -> List[str]:
        """获取所有已使用的分类"""
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT DISTINCT category FROM memories ORDER BY category"
            ).fetchall()
            return [row["category"] for row in rows]
        finally:
            conn.close()

    def get_stats(self) -> Dict:
        """获取记忆统计信息"""
        conn = self._get_conn()
        try:
            total = conn.execute(
                "SELECT COUNT(*) as cnt FROM memories").fetchone()["cnt"]
            by_category = {}
            for row in conn.execute("SELECT category, COUNT(*) as cnt FROM memories GROUP BY category"):
                by_category[row["category"]] = row["cnt"]
            return {
                "total": total,
                "by_category": by_category,
                "db_path": self.db_path
            }
        finally:
            conn.close()

    def _row_to_dict(self, row) -> Dict:
        """将 sqlite3.Row 转换为 dict"""
        d = dict(row)
        if "tags" in d and isinstance(d["tags"], str):
            try:
                d["tags"] = json.loads(d["tags"])
            except json.JSONDecodeError:
                d["tags"] = []
        return d

    def close(self):
        """关闭连接"""
        pass


# ====================== 全局单例 ======================
_memory_instance: Optional[Memory] = None


def get_memory() -> Memory:
    """获取全局 Memory 单例"""
    global _memory_instance
    if _memory_instance is None:
        _memory_instance = Memory()
    return _memory_instance
