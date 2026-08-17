"""P1 三项能力回归测试：
1. 工具执行 post-hooks 系统（结果改写 + 审批 + additionalContexts + 异常隔离）
2. Session fork（conversations 复制 + fork lineage + 边界 fork）
3. 防御模式（正交结果独立报告 + dispose 静止态）
"""

import importlib.util
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from tea_agent.tool_hooks import tool_hooks  # noqa: E402

# ═══ 1. post-hooks 系统 ═══════════════════════════════════

class TestToolHooks:
    def setup_method(self):
        tool_hooks.clear()

    def test_post_hook_result_rewrite(self):
        """post-hook 可以改写工具结果。"""
        @tool_hooks.on_post("toolkit_demo")
        def _rewrite(tool_name, args, result):
            return {"result": {"ok": True, "data": "rewritten"}}

        final, contexts = tool_hooks.run_post("toolkit_demo", {}, {"ok": True, "data": "orig"})
        assert final == {"ok": True, "data": "rewritten"}
        assert contexts == []

    def test_post_hook_additional_context(self):
        """post-hook 可附加 additionalContexts。"""
        @tool_hooks.on_post("toolkit_demo")
        def _with_ctx(tool_name, args, result):
            return {"result": result, "additional_context": {"source": "demo", "note": "extra"}}

        final, contexts = tool_hooks.run_post("toolkit_demo", {}, {"ok": True})
        assert contexts == [{"source": "demo", "note": "extra"}]

    def test_pre_hook_deny(self):
        """pre-hook 可拒绝执行并给出原因。"""
        @tool_hooks.on_pre("toolkit_demo")
        def _deny(tool_name, args):
            if args.get("action") == "write":
                return {"deny": True, "reason": "写操作被禁止"}
            return True

        allow, reason = tool_hooks.run_pre("toolkit_demo", {"action": "write"})
        assert allow is False and "写操作被禁止" in reason
        allow2, _ = tool_hooks.run_pre("toolkit_demo", {"action": "read"})
        assert allow2 is True

    def test_hook_exception_isolated(self):
        """hook 抛异常被隔离，不影响后续 hook 与结果。"""
        calls = []

        @tool_hooks.on_post("toolkit_demo")
        def _bad(tool_name, args, result):
            raise RuntimeError("boom")

        @tool_hooks.on_post("toolkit_demo")
        def _good(tool_name, args, result):
            calls.append("good")
            return {"result": {"ok": True, "passed": True}}

        final, _ = tool_hooks.run_post("toolkit_demo", {}, {"ok": False})
        assert final == {"ok": True, "passed": True}
        assert calls == ["good"]

    def test_wildcard_hook_matches_all(self):
        """全局钩子（*）匹配所有工具。"""
        @tool_hooks.on_post()
        def _global(tool_name, args, result):
            return {"result": {"tool": tool_name}}

        final, _ = tool_hooks.run_post("toolkit_any", {}, {})
        assert final == {"tool": "toolkit_any"}

    def test_context_fifo_drain(self):
        """additionalContexts FIFO 注入与排空。"""
        tool_hooks.inject_context({"a": 1})
        tool_hooks.inject_context({"b": 2})
        ctxs = tool_hooks.drain_contexts()
        assert ctxs == [{"a": 1}, {"b": 2}]
        assert tool_hooks.drain_contexts() == []


# ═══ 2. Session fork ══════════════════════════════════════

class TestSessionFork:
    def _make_storage(self):
        from tea_agent.store._core import Storage
        db = os.path.join(tempfile.mkdtemp(), "test_fork.db")
        return Storage(db)

    def test_fork_full_copy(self):
        st = self._make_storage()
        tid = st.topics.create_topic("原主题")
        st.conversations.save_msg(tid, "用户1", "AI1", False)
        st.conversations.save_msg(tid, "用户2", "AI2", False)
        r = st.conversations.fork_topic(tid, "target1", "分支")
        assert r["ok"] and r["copied"] == 2
        # 验证新 topic 有 2 条且 fork_source_id 已标记
        rows = st.conversations.get_conversations("target1", limit=0)
        assert len(rows) == 2
        assert all(x.get("fork_source_id") for x in rows)
        # forks 表 lineage
        lineage = st.conversations.get_fork_lineage("target1")
        assert len(lineage) == 1 and lineage[0]["source_topic_id"] == tid

    def test_fork_boundary(self):
        st = self._make_storage()
        tid = st.topics.create_topic("原主题")
        st.conversations.save_msg(tid, "用户1", "AI1", False)
        st.conversations.save_msg(tid, "用户2", "AI2", False)
        c = st.conn.cursor()
        c.execute("SELECT id FROM conversations WHERE topic_id=? ORDER BY rowid LIMIT 1", (tid,))
        first_id = c.fetchone()["id"]
        c.close()
        r = st.conversations.fork_topic(tid, "target2", "边界分支", first_id)
        assert r["ok"] and r["copied"] == 1
        rows = st.conversations.get_conversations("target2", limit=0)
        assert len(rows) == 1 and "用户1" in rows[0]["user_msg"]

    def test_fork_missing_source(self):
        st = self._make_storage()
        r = st.conversations.fork_topic("nonexistent", "target3", "分支")
        assert r["ok"] and r["copied"] == 0


# ═══ 3. 防御模式 ═════════════════════════════════════════

def _load_exec_module():
    path = os.path.join(os.path.dirname(__file__), "..", "toolkit", "toolkit_exec.py")
    spec = importlib.util.spec_from_file_location("tk_exec_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestOrthogonalReporting:
    def test_normal_command(self):
        m = _load_exec_module()
        r = m.toolkit_exec(app="echo", args=["hi"])
        assert r["ok"] and r["returncode"] == 0
        assert r["timed_out"] is False and r["timeout_kind"] == ""

    def test_timeout_reported_independently(self):
        m = _load_exec_module()
        r = m.toolkit_exec(app="python", args=["-c", "import time; time.sleep(30)"], timeout=1)
        # 超时被终止 → 独立字段报告，ok 强制 False（即使进程自身可能 exit 0）
        assert r["timed_out"] is True
        assert r["ok"] is False
        assert r["timeout_kind"] in ("monitor", "hardlimit")

    def test_scrubbed_env(self):
        m = _load_exec_module()
        import os as _os
        _os.environ["TEST_API_KEY_X"] = "secret"
        scrubbed = m._build_scrubbed_env()
        assert "TEST_API_KEY_X" not in scrubbed
        assert "PATH" in scrubbed


class TestDisposeQuiescence:
    def test_stop_analyzer_reaches_quiescence(self):
        from tea_agent import agent_background as ab
        t = ab.start_interruption_analyzer(interval_h=0.00001)
        assert t is not None and t.is_alive()
        time.sleep(0.3)  # 让线程至少跑一次
        reached = ab.stop_interruption_analyzer(t, timeout=3.0)
        assert reached is True
        assert not t.is_alive()
