"""Store 组件基类 — 零依赖，避免循环导入。"""
import uuid
import sqlite3


class StoreComponent:
    """所有 Store 委派组件的基类，提供 conn 访问和 ID 生成。"""

    def __init__(self, conn, db_path=None):
        self.conn = conn
        self.db_path = db_path

    def _get_connection(self):
        """获取数据库连接，每次访问都创建新的连接"""
        if self.db_path:
            return sqlite3.connect(self.db_path)
        return self.conn

    @staticmethod
    def _new_id() -> str:
        return str(uuid.uuid4())
