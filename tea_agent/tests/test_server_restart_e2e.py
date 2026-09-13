"""server 无感重启 — 端到端验收（真实进程、真实 HTTP）。

为什么需要它：test_server_restart.py 只做单元级验证（参数构造、drain 信号、
端口等待）。而实测发现的两个缺陷（悬空 flag / 端口竞态）恰恰只在**真实拉起
子进程**时才暴露 —— 旧实现单测全绿，实际重启却从未成功。故此处必须起真进程。

隔离性：使用独立端口 + 临时 config/db，绝不影响正在运行的 server。
覆盖：POST /api/restart?mode=immediate → 端口被新进程重新监听（PID 变化）。
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _free_port() -> int:
    """取一个空闲端口（避免与真实 server 的 8282 冲突）。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _health(port: int, timeout: float = 2.0) -> bool:
    """GET /health 是否返回 2xx。"""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=timeout) as r:
            return 200 <= r.status < 300
    except (urllib.error.URLError, OSError, ValueError):
        return False


def _wait_health(port: int, timeout: float = 60.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _health(port):
            return True
        time.sleep(0.5)
    return False


def _listener_pid(port: int) -> int | None:
    """返回正在 LISTEN 该端口的进程 PID（用于证明进程确实被换掉）。"""
    try:
        out = subprocess.run(["netstat", "-ano"], capture_output=True, text=True,
                             timeout=20).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[0].upper().startswith("TCP") \
                and parts[1].endswith(f":{port}") and parts[3].upper() == "LISTENING":
            try:
                return int(parts[4])
            except ValueError:
                return None
    return None


def _kill(pid: int | None) -> None:
    if not pid:
        return
    try:
        subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                       capture_output=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        pass


def _post_restart(port: int, mode: str = "immediate") -> dict:
    """POST /api/restart 并返回结构化结果。"""
    import json

    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/restart?mode={mode}",
        data=b"{}", method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


@pytest.mark.timeout(240)
def test_restart_replaces_process_e2e(tmp_path):
    """真实重启后：端口由**新进程**（不同 PID）重新监听且 /health 正常。

    这是「重启确实生效」的最终判据 —— 旧实现在此必定失败（悬空 flag 使新进程
    argparse 退出，端口竞态使其 bind 失败）。
    """
    port = _free_port()
    cfg = tmp_path / "config.yaml"
    cfg.write_text("main_model:\n  provider: DeepSeek\n  model: deepseek-v4-flash\n",
                   encoding="utf-8")

    env = dict(os.environ)
    env["TEA_SERVER_STATE_DB"] = str(tmp_path / "server_state.db")

    proc = subprocess.Popen(
        [sys.executable, "-m", "tea_agent.server", "--host", "127.0.0.1",
         "--port", str(port), "--config", str(cfg)],
        cwd=PROJECT_ROOT, env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    old_pid = pid_after = None
    try:
        assert _wait_health(port, timeout=90), "初始 server 未在 90s 内就绪"
        old_pid = _listener_pid(port)
        assert old_pid, "未能识别监听进程 PID"

        result = _post_restart(port, mode="immediate")
        assert result.get("ok") is True, f"restart 未受理: {result}"
        assert result.get("mode") == "immediate"

        # 旧进程退出 → 鉴权/连接失败窗口 → 新进程就绪
        assert _wait_health(port, timeout=90), "重启后服务未在 90s 内恢复"
        pid_after = _listener_pid(port)

        assert pid_after, "重启后未能识别监听进程 PID"
        assert pid_after != old_pid, (
            f"端口仍由旧进程监听（PID {old_pid}）→ 重启未真正替换进程")
    finally:
        _kill(_listener_pid(port))
        _kill(old_pid)
        _kill(pid_after)
        try:
            proc.terminate()
        except OSError:
            pass
