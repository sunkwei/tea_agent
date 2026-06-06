"""
Storage 委派 + StoreComponent 基类测试。

覆盖:
- StoreComponent._new_id() 生成 UUID
- Storage 委派属性 (topics, memories, conversations 等)
- __getattr__ 自动路由方法调用到子组件
- get_storage() 单例工厂
"""
import pytest
import uuid


class TestStoreComponent:
    """StoreComponent 基类"""

    def test_new_id_returns_uuid_string(self):
        from tea_agent.store._component import StoreComponent
        sid = StoreComponent._new_id()
        assert isinstance(sid, str)
        # 验证是有效 UUID
        uuid.UUID(sid)

    def test_new_id_is_unique(self):
        from tea_agent.store._component import StoreComponent
        ids = {StoreComponent._new_id() for _ in range(100)}
        assert len(ids) == 100


class TestStorageDelegation:
    """Storage 委派给 8 个子组件"""

    def test_explicit_attribute_access(self, storage):
        """显式属性应可直接访问"""
        assert storage.topics is not None
        assert storage.conversations is not None
        assert storage.summaries is not None
        assert storage.memories is not None
        assert storage.prompts is not None
        assert storage.reflections is not None
        assert storage.config_history is not None
        assert storage.vectors is not None

    def test_getattr_routes_to_delegate(self, storage):
        """__getattr__ 将方法调用路由到委派组件"""
        # topics 子组件有 create_topic 方法
        tid = storage.create_topic("test delegation topic")
        assert isinstance(tid, str)
        uuid.UUID(tid)

    def test_getattr_routes_memory_operations(self, storage):
        """记忆操作通过 __getattr__ 路由到 MemoryStore"""
        mid = storage.add_memory("test memory content", category="test")
        assert isinstance(mid, str)
        uuid.UUID(mid)

    def test_getattr_unknown_attr_raises(self, storage):
        """未知属性应抛 AttributeError"""
        with pytest.raises(AttributeError):
            _ = storage.nonexistent_method_xyz

    def test_private_attr_not_routed(self, storage):
        """私有属性不被路由"""
        with pytest.raises(AttributeError):
            _ = storage._nonexistent_private

    def test_save_msg_bridge(self, storage):
        """save_msg 桥接方法正确工作"""
        tid = storage.create_topic("bridge test")
        cid = storage.save_msg(tid, "hello", "world", False)
        assert isinstance(cid, str)
        uuid.UUID(cid)


class TestGetStorage:
    """get_storage() 单例工厂"""

    def test_returns_storage_instance(self, tmp_db_path):
        from tea_agent.store import Storage, get_storage
        s = get_storage(db_path=tmp_db_path)
        assert isinstance(s, Storage)
        s.close()

    def test_same_db_path_returns_same_instance(self, tmp_db_path):
        from tea_agent.store import get_storage
        s1 = get_storage(db_path=tmp_db_path)
        s2 = get_storage(db_path=tmp_db_path)
        assert s1 is s2
        s1.close()

    def test_different_db_path_returns_new_instance(self, tmp_db_path):
        import os
        from tea_agent.store import get_storage
        s1 = get_storage(db_path=tmp_db_path)
        db2 = os.path.join(os.path.dirname(tmp_db_path), "other.db")
        s2 = get_storage(db_path=db2)
        assert s1 is not s2
        s1.close()
        s2.close()
