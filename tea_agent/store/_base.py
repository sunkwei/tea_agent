"""
@2026-05-16 gen by tea_agent, Store 委派组件基类
所有 Store 子组件继承此类，共享 conn 和 ID 生成。
"""
import uuid


class StoreComponent:
    """所有 Store 委派组件的基类，提供 conn 访问和 ID 生成。"""

    def __init__(self, conn):
        self.conn = conn

    @staticmethod
    def _new_id() -> str:
        return str(uuid.uuid4())
