"""Store component base - zero dependency, avoid circular imports.

Short-connection design:
- self.conn is a #property returning a thread-local connection
- DB class: with DB(path) as db: for explicit short connections
- All existing methods using self.conn work unchanged
"""
import uuid
import sqlite3
import threading
from contextlib import contextmanager


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
