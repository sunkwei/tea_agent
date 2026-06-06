"""Store 组件基类 — 零依赖，避免循环导入。"""
import uuid


class StoreComponent:
    """所有 Store 委派组件的基类，提供 conn 访问和 ID 生成。"""

    def __init__(self, conn):
        self.conn = conn

    @staticmethod
    def _new_id() -> str:
        return str(uuid.uuid4())
