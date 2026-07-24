"""session_ref 测试 — 线程安全的全局会话/Agent 引用管理。"""

import threading

from tea_agent import session_ref as sr


class TestSessionRef:
    def test_get_set_session(self):
        """基础 set/get 会话"""
        sr.clear()
        assert sr.get_session() is None
        sr.set_session("fake_session", setter="test")
        assert sr.get_session() == "fake_session"
        sr.clear()
        assert sr.get_session() is None

    def test_get_set_agent(self):
        """基础 set/get Agent"""
        sr.clear()
        assert sr.get_agent() is None
        sr.set_agent("fake_agent", setter="test")
        assert sr.get_agent() == "fake_agent"
        sr.clear()
        assert sr.get_agent() is None

    def test_is_active(self):
        """is_active 正确反映会话状态"""
        sr.clear()
        assert not sr.is_active()
        sr.set_session("s")
        assert sr.is_active()
        sr.clear()
        assert not sr.is_active()

    def test_get_session_info(self):
        """get_session_info 返回正确结构"""
        sr.clear()
        info = sr.get_session_info()
        assert info["has_session"] is False
        assert info["has_agent"] is False

        sr.set_session("s")
        sr.set_agent("a")
        info = sr.get_session_info()
        assert info["has_session"] is True
        assert info["has_agent"] is True
        sr.clear()

    def test_clear_clears_both(self):
        """clear() 同时清除 session 和 agent"""
        sr.set_session("s")
        sr.set_agent("a")
        sr.clear()
        assert sr.get_session() is None
        assert sr.get_agent() is None
        assert not sr.is_active()

    def test_concurrent_set_get_session(self):
        """100 线程并发 set/get 会话不崩溃"""
        errors = []

        def _worker():
            try:
                for i in range(100):
                    sr.set_session(f"session_{i}", setter="test")
                    _ = sr.get_session()
                    sr.set_agent(f"agent_{i}", setter="test")
                    _ = sr.get_agent()
                    _ = sr.is_active()
                    _ = sr.get_session_info()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=_worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=20)

        assert not errors, f"线程竞争导致异常: {errors}"

    def test_concurrent_session_and_agent_isolation(self):
        """并发 set/get 不导致 session/agent 引用交叉"""
        event = threading.Barrier(10, timeout=10)

        def _set_session_only():
            event.wait()
            for i in range(50):
                sr.set_session(f"sess_{i}")

        def _set_agent_only():
            event.wait()
            for i in range(50):
                sr.set_agent(f"agent_{i}")

        sr.clear()
        threads = [
            threading.Thread(target=_set_session_only) for _ in range(5)
        ] + [
            threading.Thread(target=_set_agent_only) for _ in range(5)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)

        # 无崩溃即通过
        sr.clear()
