"""
Storage 委派 + StoreComponent 基类测试。

覆盖:
- StoreComponent._new_id() 生成 UUID
- DB 短连接上下文管理器
- _db() 与 _get_connection() 上下文
- 线程局部连接 (self.conn property)
- Storage 委派属性 (topics, memories, conversations 等)
- __getattr__ 自动路由方法调用到子组件
- get_storage() 单例工厂
"""
import sqlite3
import pytest
import uuid
from tea_agent.store._component import DB, StoreComponent


class TestStoreComponent:
    """StoreComponent 基类"""

    def test_new_id_returns_uuid_string(self):
        sid = StoreComponent._new_id()
        assert isinstance(sid, str)
        # 验证是有效 UUID
        uuid.UUID(sid)

    def test_new_id_is_unique(self):
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


# ============================================================
# 短连接模式新增测试
# ============================================================

class TestDB:
    """DB 短连接上下文管理器"""

    def test_db_enter_exit_creates_and_closes_conn(self, tmp_path):
        """__enter__ 创建连接，__exit__ 关闭"""
        db_path = tmp_path / "test.db"
        db = DB(str(db_path))
        assert db.conn is None

        with db:
            assert db.conn is not None
            assert db.conn.execute("SELECT 1").fetchone()[0] == 1

        assert db.conn is None  # __exit__ 后关闭

    def test_db_auto_commit(self, tmp_path):
        """正常退出自动 commit"""
        db_path = tmp_path / "auto_commit.db"
        with DB(str(db_path)) as db:
            db.execute("CREATE TABLE t (v TEXT)")
            db.execute("INSERT INTO t VALUES ('hello')")

        # 新连接验证数据已提交
        c = sqlite3.connect(str(db_path))
        row = c.execute("SELECT v FROM t").fetchone()
        assert row[0] == "hello"
        c.close()

    def test_db_auto_rollback_on_error(self, tmp_path):
        """异常退出自动 rollback（显式事务回滚）。"""
        db_path = tmp_path / "rollback.db"
        try:
            with DB(str(db_path)) as db:
                db.execute("CREATE TABLE t (k INT, v TEXT)")
                db.execute("INSERT INTO t VALUES (1, 'persisted')")
                # 提交隐式事务，再手动开启显式事务
                db.conn.commit()
                db.execute("BEGIN")
                db.execute("INSERT INTO t VALUES (2, 'rollback_me')")
                raise RuntimeError("模拟错误")
        except RuntimeError:
            pass

        # DDL + 第一个 INSERT 已提交，第二个 INSERT 在显式事务中回滚
        c = sqlite3.connect(str(db_path))
        rows = c.execute("SELECT v FROM t ORDER BY k").fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "persisted"
        c.close()

    def test_db_cursor_returns_sqlite_cursor(self, tmp_path):
        """cursor() 返回标准 sqlite3.Cursor"""
        db_path = tmp_path / "cursor.db"
        with DB(str(db_path)) as db:
            c = db.cursor()
            assert c is not None

    def test_db_row_factory(self, tmp_path):
        """row_factory 设为 sqlite3.Row"""
        db_path = tmp_path / "row_factory.db"
        with DB(str(db_path)) as db:
            db.execute("CREATE TABLE t (k TEXT, v TEXT)")
            db.execute("INSERT INTO t VALUES ('key1', 'val1')")
            row = db.execute("SELECT k, v FROM t").fetchone()
            assert row["k"] == "key1"
            assert row["v"] == "val1"

    def test_db_wal_enabled(self, tmp_path):
        """WAL 模式已启用"""
        db_path = tmp_path / "wal.db"
        with DB(str(db_path)) as db:
            mode = db.execute("PRAGMA journal_mode").fetchone()[0]
            assert mode.upper() == "WAL"


class TestStoreComponentDB:
    """StoreComponent._db() 上下文管理器"""

    def test_db_context_works(self, tmp_db_path):
        """_db() 返回可用 DB 实例"""
        comp = StoreComponent(db_path=tmp_db_path)

        with comp._db() as db:
            db.execute("CREATE TABLE IF NOT EXISTS test_db (v TEXT)")
            db.execute("INSERT INTO test_db VALUES ('ok')")

        # 验证提交
        c = sqlite3.connect(tmp_db_path)
        assert c.execute("SELECT v FROM test_db").fetchone()[0] == "ok"
        c.close()

    def test_get_connection_backward_compat(self, tmp_db_path):
        """_get_connection() 向后兼容，返回 conn"""
        comp = StoreComponent(db_path=tmp_db_path)

        with comp._get_connection() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS test_gc (v TEXT)")
            conn.execute("INSERT INTO test_gc VALUES ('ok')")

        c = sqlite3.connect(tmp_db_path)
        assert c.execute("SELECT v FROM test_gc").fetchone()[0] == "ok"
        c.close()


class TestThreadLocalConn:
    """self.conn 线程局部连接"""

    def test_conn_is_cached_in_thread(self, tmp_db_path):
        """同一线程内多次访问返回同一对象"""
        comp = StoreComponent(db_path=tmp_db_path)

        c1 = comp.conn
        c2 = comp.conn
        assert c1 is c2

    def test_conn_isolation_between_threads(self, tmp_db_path):
        """不同线程返回不同连接"""
        import threading
        comp = StoreComponent(db_path=tmp_db_path)

        conns = []

        def capture():
            conns.append(comp.conn)

        t = threading.Thread(target=capture)
        t.start()
        t.join()

        assert len(conns) == 1
        assert comp.conn is not conns[0]

    def test_close_thread_conn_cleans_up(self, tmp_db_path):
        """close_thread_conn 关闭并清空连接"""
        comp = StoreComponent(db_path=tmp_db_path)

        c = comp.conn
        StoreComponent.close_thread_conn()

        # close 后重新访问应获取新连接
        c2 = comp.conn
        assert c2 is not c

    def test_conn_supports_cursor_execute_commit(self, tmp_db_path):
        """self.conn 支持 cursor/execute/commit 等标准操作"""
        comp = StoreComponent(db_path=tmp_db_path)

        comp.conn.execute("CREATE TABLE IF NOT EXISTS test_conn (v TEXT)")
        comp.conn.execute("INSERT INTO test_conn VALUES ('data')")
        comp.conn.commit()

        # 使用同一连接验证（比新建连接更可靠）
        row = comp.conn.execute("SELECT v FROM test_conn").fetchone()
        assert row[0] == "data"


# ============================================================
# Cursor 上下文管理器测试
# ============================================================

class TestCursor:
    """Cursor 上下文管理器"""

    def test_cursor_enter_exit_closes(self, tmp_path):
        """__enter__ 返回 cursor，__exit__ 关闭"""
        db_path = tmp_path / "cursor_ctx.db"
        from tea_agent.store._component import DB, Cursor

        with DB(str(db_path)) as db:
            c_obj = None
            with Cursor(db) as c:
                c_obj = c
                assert c is not None
                c.execute("CREATE TABLE IF NOT EXISTS t (v TEXT)")
                c.execute("INSERT INTO t VALUES ('hello')")
            # 退出 with 后 c 仍存在但已关闭
            # 验证数据已通过 DB.__exit__ 提交
        # 新连接验证
        c2 = sqlite3.connect(str(db_path))
        assert c2.execute("SELECT v FROM t").fetchone()[0] == "hello"
        c2.close()

    def test_cursor_with_db_multi_statements(self, tmp_path):
        """with Cursor(db) 中执行多条语句"""
        from tea_agent.store._component import DB, Cursor
        db_path = tmp_path / "multi.db"

        with DB(str(db_path)) as db:
            with Cursor(db) as c:
                c.execute("CREATE TABLE t (k INT, v TEXT)")
                c.execute("INSERT INTO t VALUES (1, 'a')")
                c.execute("INSERT INTO t VALUES (2, 'b')")
                rows = c.execute("SELECT v FROM t ORDER BY k").fetchall()
                assert [r[0] for r in rows] == ["a", "b"]

    def test_cursor_execute_with_params(self, tmp_path):
        """带参数执行"""
        from tea_agent.store._component import DB, Cursor
        db_path = tmp_path / "params.db"

        with DB(str(db_path)) as db:
            with Cursor(db) as c:
                c.execute("CREATE TABLE t (k INT, v TEXT)")
                c.execute("INSERT INTO t VALUES (?, ?)", (1, "param_test"))
                row = c.execute("SELECT v FROM t WHERE k=?", (1,)).fetchone()
                assert row[0] == "param_test"

    def test_cursor_fetchone_fetchall(self, tmp_path):
        """fetchone / fetchall 正常工作"""
        from tea_agent.store._component import DB, Cursor
        db_path = tmp_path / "fetch.db"

        with DB(str(db_path)) as db:
            with Cursor(db) as c:
                c.execute("CREATE TABLE t (v TEXT)")
                c.execute("INSERT INTO t VALUES ('x'), ('y'), ('z')")
                c.execute("SELECT v FROM t ORDER BY v")
                first = c.fetchone()
                assert first[0] == "x"
                rest = c.fetchall()
                assert [r[0] for r in rest] == ["y", "z"]

    def test_cursor_rowcount(self, tmp_path):
        """rowcount 属性可用"""
        from tea_agent.store._component import DB, Cursor
        db_path = tmp_path / "rowcount.db"

        with DB(str(db_path)) as db:
            with Cursor(db) as c:
                c.execute("CREATE TABLE t (v TEXT)")
                c.execute("INSERT INTO t VALUES ('a'), ('b'), ('c')")
                c.execute("UPDATE t SET v='x' WHERE v='a'")
                assert c.rowcount == 1

    def test_db_cursor_backward_compat(self, tmp_path):
        """DB.cursor() 仍可用（向后兼容）"""
        from tea_agent.store._component import DB
        db_path = tmp_path / "backward.db"

        with DB(str(db_path)) as db:
            c = db.cursor()
            assert c is not None
            c.execute("CREATE TABLE t (v TEXT)")
            c.execute("INSERT INTO t VALUES ('compat')")
            c.close()

        c2 = sqlite3.connect(str(db_path))
        assert c2.execute("SELECT v FROM t").fetchone()[0] == "compat"
        c2.close()
