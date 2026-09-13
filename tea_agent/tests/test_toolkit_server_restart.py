"""toolkit_server_restart 测试 — Agent 可在对话中安排 server 无感重启。"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from tea_agent.toolkit import toolkit_server_restart as tsr


def _patch_restart(return_value):
    """替换 server.restart_server（工具内部为延迟导入，故打补丁到源模块）。"""
    import tea_agent.server.server as srv
    return patch.object(srv, "restart_server", return_value=return_value)


class TestRegistration:
    def test_meta_shape(self):
        meta = tsr.meta_toolkit_server_restart()
        fn = meta["function"]
        assert fn["name"] == "toolkit_server_restart"
        props = fn["parameters"]["properties"]
        assert set(props) == {"mode", "wait_seconds", "reason"}
        assert fn["parameters"]["required"] == []

    def test_registered_in_toolkit(self):
        from tea_agent.tlk import Toolkit
        tk = Toolkit()
        assert "toolkit_server_restart" in tk.meta_map
        assert "toolkit_server_restart" in tk.func_map


class TestDeferMode:
    def test_default_is_defer(self):
        with _patch_restart({"ok": True, "message": "Restart initiated (graceful)",
                             "inflight_turns": 1}):
            r = tsr.toolkit_server_restart()
        assert r["ok"] is True
        assert r["mode"] == "defer"
        assert "优雅重启" in r["message"]

    def test_passes_graceful_and_wait(self):
        import tea_agent.server.server as srv
        with patch.object(srv, "restart_server",
                          return_value={"ok": True, "inflight_turns": 2}) as m:
            tsr.toolkit_server_restart(mode="defer", wait_seconds=42)
        m.assert_called_once_with(graceful=True, wait_seconds=42.0)

    def test_reason_appended(self):
        with _patch_restart({"ok": True, "inflight_turns": 0}):
            r = tsr.toolkit_server_restart(reason="应用新配置")
        assert "应用新配置" in r["message"]

    def test_inflight_reported(self):
        with _patch_restart({"ok": True, "inflight_turns": 3}):
            assert tsr.toolkit_server_restart()["inflight_turns"] == 3

    def test_negative_wait_clamped(self):
        import tea_agent.server.server as srv
        with patch.object(srv, "restart_server",
                          return_value={"ok": True, "inflight_turns": 0}) as m:
            tsr.toolkit_server_restart(wait_seconds=-5)
        assert m.call_args.kwargs["wait_seconds"] == 0.0

    def test_bad_wait_falls_back(self):
        import tea_agent.server.server as srv
        with patch.object(srv, "restart_server",
                          return_value={"ok": True, "inflight_turns": 0}) as m:
            tsr.toolkit_server_restart(wait_seconds="abc")  # type: ignore[arg-type]
        assert m.call_args.kwargs["wait_seconds"] == 300.0


class TestImmediateMode:
    def test_immediate_passes_not_graceful(self):
        import tea_agent.server.server as srv
        with patch.object(srv, "restart_server",
                          return_value={"ok": True, "inflight_turns": 1}) as m:
            r = tsr.toolkit_server_restart(mode="immediate")
        m.assert_called_once()
        assert m.call_args.kwargs["graceful"] is False
        assert r["mode"] == "immediate"
        assert "切断" in r["message"]

    def test_mode_case_insensitive(self):
        with _patch_restart({"ok": True, "inflight_turns": 0}):
            assert tsr.toolkit_server_restart(mode="  DEFER ")["mode"] == "defer"

    def test_invalid_mode_rejected(self):
        r = tsr.toolkit_server_restart(mode="now")
        assert r["ok"] is False
        assert "defer|immediate" in r["error"]


class TestFailureIsolation:
    def test_not_in_server_process(self):
        """非 server 进程（导入失败）→ 清晰报错，不抛异常。"""
        with patch.dict("sys.modules", {"tea_agent.server.server": None}):
            r = tsr.toolkit_server_restart()
        assert r["ok"] is False
        assert "server" in r["error"]

    def test_rejected_by_server(self):
        with _patch_restart({"ok": False, "error": "Server not running"}):
            r = tsr.toolkit_server_restart()
        assert r["ok"] is False
        assert r["error"] == "Server not running"

    def test_concurrent_restart_rejected(self):
        with _patch_restart({"ok": False, "error": "Restart already in progress"}):
            r = tsr.toolkit_server_restart()
        assert r["ok"] is False
        assert "progress" in r["error"]

    def test_exception_in_restart_is_caught(self):
        import tea_agent.server.server as srv
        with patch.object(srv, "restart_server", side_effect=OSError("boom")):
            r = tsr.toolkit_server_restart()
        assert r["ok"] is False
        assert "boom" in r["error"]


class TestEndToEndWithRealRestartServer:
    """与真实 restart_server 联动（不启动 server，仅验证参数契约一致）。"""

    def test_defer_reaches_real_restart_server(self):
        import tea_agent.server.server as srv
        srv._uvicorn_server = None
        srv._restart_requested = False
        try:
            r = tsr.toolkit_server_restart()   # 真实调用，未运行 → 应被拒
            assert r["ok"] is False
            assert "not running" in r["error"].lower()
        finally:
            srv._uvicorn_server = None
            srv._restart_requested = False

    def test_defer_with_running_server_marks_requested(self):
        import tea_agent.server.server as srv

        class _Fake:
            should_exit = False

        srv._uvicorn_server = _Fake()
        srv._restart_requested = False
        try:
            with patch.object(srv, "_inflight_turns", return_value=1), \
                 patch.object(srv, "_drain_then_exit"), \
                 patch("threading.Thread"):
                r = tsr.toolkit_server_restart(wait_seconds=7)
            assert r["ok"] is True
            assert r["wait_seconds"] == 7.0
            assert srv._restart_requested is True
            assert srv._uvicorn_server.should_exit is False  # 不立即切断
        finally:
            srv._uvicorn_server = None
            srv._restart_requested = False
