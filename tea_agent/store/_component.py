"""
Store 组件基类 — 零依赖、线程安全、短连接设计。

核心设计：
- StoreComponent: 抽象基类，提供线程级连接管理和短连接上下文
- DB: 短连接上下文管理器（connect → commit/rollback → close）
- Cursor: 游标上下文管理器（open → auto close）

短连接设计说明：
- self.conn 是 #property 返回线程本地连接（Thread-local）
- DB 类用于显式短连接：with DB(path) as db:
- 所有现有使用 self.conn 的方法无需修改即可工作
"""

from __future__ import annotations

import sqlite3
import threading
import uuid
from contextlib import contextmanager
from typing import Any

__all__ = [
    "DB",
    "Cursor",
    "StoreComponent",
]


class DB:
    """Short connection context: with DB(path) as db: -> connect -> commit -> close."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.conn = None

    def __enter__(self):
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            if exc_type is None:
                self.conn.commit()
            else:
                self.conn.rollback()
        finally:
            self.conn.close()
            self.conn = None
        return False

    def cursor(self):
        return self.conn.cursor()

    def execute(self, sql, params=None):
        if params:
            return self.conn.execute(sql, params)
        return self.conn.execute(sql)


class Cursor:
    """Cursor context manager: with Cursor(db) as cur: → open → auto close.

    配合 DB 使用，确保 cursor 在 with 块结束后自动关闭：

        with DB(path) as db:
            with Cursor(db) as cur:
                cur.execute("SELECT * FROM t")
                rows = cur.fetchall()
            # cursor 自动关闭
        # 连接自动 commit + 关闭
    """

    def __init__(self, db: DB):
        self._db = db
        self._cursor = None

    def __enter__(self):
        self._cursor = self._db.conn.cursor()
        return self._cursor

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._cursor:
            self._cursor.close()
            self._cursor = None
        return False


class StoreComponent:
    """Base class for all Store delegate components."""

    _thread_local = threading.local()

    def __init__(self, db_path: str = None):
        self.db_path = db_path

    @property
    def conn(self):
        """Thread-local connection. Returns same connection within a thread."""
        if not hasattr(self._thread_local, 'conn') or self._thread_local.conn is None:
            c = sqlite3.connect(self.db_path)
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA journal_mode=WAL")
            self._thread_local.conn = c
        return self._thread_local.conn

    @classmethod
    def close_thread_conn(cls):
        """Close the thread-local connection. Called by Storage.close()."""
        conn = getattr(cls._thread_local, 'conn', None)
        if conn:
            try:
                conn.commit()
                conn.close()
            except Exception:
                pass
            cls._thread_local.conn = None

    @contextmanager
    def _db(self):
        """Explicit short connection: with self._db() as db:"""
        with DB(self.db_path) as db:
            yield db

    @contextmanager
    def _get_connection(self):
        """Backward compat: same as _db()."""
        with self._db() as db:
            yield db.conn

    @staticmethod
    def _new_id() -> str:
        return str(uuid.uuid4())
