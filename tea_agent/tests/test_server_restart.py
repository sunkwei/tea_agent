"""server 重启功能回归测试。

覆盖实测发现的两个「静默失效」缺陷：

1. ``_build_restart_args`` 悬空 flag —— 旧实现用 ``[m for m in [...] if m]``
   过滤空串，flag 保留而值被丢弃，config/api_key 为空时产生
   ``--config --api-key``，新进程 argparse 直接报错退出。
2. 端口竞态 —— 旧实现先 Popen 新进程、后置 ``should_exit``，新进程在旧进程
   仍占用端口时 bind 失败即退出。

注意：本文件不启动真实 server（端到端验证见 test_server_restart_e2e.py）。
"""

from __future__ import annotations

import argparse
import socket
from unittest.mock import patch

import pytest

from tea_agent.server import server as srv

_FLAGS = {"--host", "--port", "--config", "--api-key"}


def _dangling_flags(args: list[str]) -> list[str]:
    """返回悬空的 flag（后一个 token 缺失或本身是 flag）。"""
    bad: list[str] = []
    i = 0
    while i < len(args):
        tok = args[i]
        if tok in _FLAGS:
            if i + 1 >= len(args) or args[i + 1].startswith("--"):
                bad.append(tok)
            i += 2
        else:
            i += 1
    return bad


class _FakeUvicornServer:
    """替代 uvicorn.Server 的最小替身（只需 should_exit）。"""

    def __init__(self) -> None:
        self.should_exit = False


@pytest.fixture(autouse=True)
def _reset_module_globals():
    """隔离模块级全局，避免测试相互污染。"""
    srv._uvicorn_server = None
    srv._restart_requested = False
    srv._restart_args = []
    yield
    srv._uvicorn_server = None
    srv._restart_requested = False
    srv._restart_args = []


# ── 1. 重启参数构造 ────────────────────────────────────────────


class TestBuildRestartArgs:
    def test_both_empty_produces_no_flag(self):
        args = srv._build_restart_args("127.0.0.1", 8282, None, None)
        assert _dangling_flags(args) == []
        assert "--config" not in args
        assert "--api-key" not in args

    def test_config_only(self):
        args = srv._build_restart_args("127.0.0.1", 8282, "C:/x/config.yaml", None)
        assert _dangling_flags(args) == []
        assert args[args.index("--config") + 1] == "C:/x/config.yaml"
        assert "--api-key" not in args

    def test_api_key_only(self):
        args = srv._build_restart_args("127.0.0.1", 8282, None, "sk-abc")
        assert _dangling_flags(args) == []
        assert args[args.index("--api-key") + 1] == "sk-abc"
        assert "--config" not in args

    def test_both_present(self):
        args = srv._build_restart_args("0.0.0.0", 9001, "C:/x/config.yaml", "sk-abc")
        assert _dangling_flags(args) == []
        assert args[args.index("--config") + 1] == "C:/x/config.yaml"
        assert args[args.index("--api-key") + 1] == "sk-abc"

    def test_empty_string_treated_as_absent(self):
        """空串等价于未提供：不得留下悬空 flag（旧实现正是在此崩掉）。"""
        args = srv._build_restart_args("127.0.0.1", 8282, "", "")
        assert _dangling_flags(args) == []

    def test_offset_with_real_argparse(self):
        """用真实 argparse 解析，确保新进程不会启动即报错退出。"""
        parser = argparse.ArgumentParser()
        parser.add_argument("--host", default="127.0.0.1")
        parser.add_argument("--port", type=int, default=8282)
        parser.add_argument("--api-key", default="")
        parser.add_argument("--config", default=None)
        # 去掉 "-m tea_agent.server" 前缀，模拟 main() 解析
        for cfg, key in ((None, None), ("C:/x/config.yaml", None), (None, "sk-abc")):
            args = srv._build_restart_args("127.0.0.1", 9000, cfg, key)[2:]
            ns = parser.parse_args(args)  # 解析失败会抛 SystemExit → 测试失败
            assert ns.host == "127.0.0.1"
            assert ns.port == 9000

    def test_positive_control_legacy_expr_was_broken(self):
        """阳性对照：复现旧实现，证明上面的检测手段确实能发现问题。"""
        legacy = [m for m in ["-m", "tea_agent.server", "--host", "127.0.0.1",
                              "--port", "8282", "--config", "", "--api-key", ""] if m]
        assert _dangling_flags(legacy) == ["--config"]  # 旧实现必然悬空
        assert srv._build_restart_args("127.0.0.1", 8282, None, None) != legacy


# ── 2. 端口工具 ────────────────────────────────────────────────


class TestPortHelpers:
    def test_port_free_true_when_unused(self):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        assert srv._port_free("127.0.0.1", port) is True

    def test_port_free_false_when_bound(self):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            s.listen(1)
            port = s.getsockname()[1]
            assert srv._port_free("127.0.0.1", port) is False

    def test_wait_port_free_returns_true(self):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        assert srv._wait_port_free("127.0.0.1", port, timeout=2.0) is True

    def test_wait_port_free_times_out_when_held(self):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            s.listen(1)
            port = s.getsockname()[1]
            assert srv._wait_port_free("127.0.0.1", port, timeout=0.3) is False


# ── 3. restart_server 守卫与模式 ───────────────────────────────


class TestRestartServer:
    def test_not_running(self):
        r = srv.restart_server()
        assert r["ok"] is False
        assert "not running" in r["error"].lower()

    def test_already_in_progress_is_rejected(self):
        srv._uvicorn_server = _FakeUvicornServer()
        srv._restart_requested = True
        r = srv.restart_server()
        assert r["ok"] is False
        assert "progress" in r["error"].lower()

    def test_immediate_sets_should_exit(self):
        fake = _FakeUvicornServer()
        srv._uvicorn_server = fake
        r = srv.restart_server(graceful=False)
        assert r["ok"] is True
        assert "immediate" in r["message"]
        assert fake.should_exit is True

    def test_graceful_spawns_drain_and_does_not_exit_now(self):
        fake = _FakeUvicornServer()
        srv._uvicorn_server = fake
        with patch.object(srv, "_inflight_turns", return_value=1), \
             patch.object(srv, "_drain_then_exit") as drain, \
             patch("threading.Thread") as thread:
            r = srv.restart_server(graceful=True, wait_seconds=0.01)
        assert r["ok"] is True
        assert r["wait_seconds"] == 0.01
        assert r["inflight_turns"] == 1
        thread.assert_called_once()
        drain.assert_not_called()          # 由线程执行，未同步阻塞
        assert fake.should_exit is False   # 关键：未立即退出（不切断 SSE）

    def test_graceful_marks_requested_once(self):
        srv._uvicorn_server = _FakeUvicornServer()
        with patch.object(srv, "_inflight_turns", return_value=0), \
             patch.object(srv, "_drain_then_exit"), \
             patch("threading.Thread"):
            assert srv.restart_server(graceful=True)["ok"] is True
            assert srv._restart_requested is True
            # 第二次请求被拒（避免并发拉起多个新进程）
            assert srv.restart_server(graceful=True)["ok"] is False


# ── 4. 排空与拉起 ──────────────────────────────────────────────


class TestDrainAndSpawn:
    def test_drain_exits_after_turns_finish(self):
        fake = _FakeUvicornServer()
        srv._uvicorn_server = fake
        with patch.object(srv, "_inflight_turns", side_effect=[1, 0]):
            srv._drain_then_exit(1.0)
        assert fake.should_exit is True

    def test_drain_exits_when_idle(self):
        fake = _FakeUvicornServer()
        srv._uvicorn_server = fake
        with patch.object(srv, "_inflight_turns", return_value=0):
            srv._drain_then_exit(1.0)
        assert fake.should_exit is True

    def test_drain_forced_exit_on_timeout(self):
        """在途回合始终不结束 → 到点强制退出（避免永久挂起）。"""
        fake = _FakeUvicornServer()
        srv._uvicorn_server = fake
        with patch.object(srv, "_inflight_turns", return_value=1):
            srv._drain_then_exit(0.3)
        assert fake.should_exit is True

    def test_drain_noop_without_server(self):
        srv._uvicorn_server = None
        srv._drain_then_exit(0.1)  # 不抛异常即可

    def test_spawn_successor_true_when_ready(self):
        srv._restart_args = ["-m", "tea_agent.server"]
        with patch.object(srv, "_wait_port_free", return_value=True), \
             patch.object(srv, "_wait_ready", return_value=True), \
             patch("subprocess.Popen") as popen:
            popen.return_value.pid = 4321
            assert srv._spawn_successor("127.0.0.1", 8282) is True
        assert popen.call_count == 1

    def test_spawn_successor_retries_then_gives_up(self):
        with patch.object(srv, "_wait_port_free", return_value=True), \
             patch.object(srv, "_wait_ready", return_value=False), \
             patch("subprocess.Popen") as popen:
            popen.return_value.pid = 1
            assert srv._spawn_successor("127.0.0.1", 8282,
                                        attempts=2, wait_ready=0.01) is False
        assert popen.call_count == 2   # 确认有重试

    def test_spawn_skipped_while_port_busy(self):
        """端口未释放时不得拉起新进程（竞态修复的核心断言）。"""
        with patch.object(srv, "_wait_port_free", return_value=False), \
             patch("subprocess.Popen") as popen:
            assert srv._spawn_successor("127.0.0.1", 8282, attempts=2) is False
        popen.assert_not_called()

    def test_spawn_handles_popen_failure(self):
        with patch.object(srv, "_wait_port_free", return_value=True), \
             patch("subprocess.Popen", side_effect=OSError("boom")):
            assert srv._spawn_successor("127.0.0.1", 8282, attempts=2) is False
