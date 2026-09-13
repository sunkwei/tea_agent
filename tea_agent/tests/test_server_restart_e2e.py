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
    """POST /api/restart 并返回结构化结果。

    immediate 模式下进程随即开始退出，响应可能在读完前被重置连接 —— 这属预期
    行为（真判据是「端口最终由新进程监听」），故此处容错返回而非直接失败。
    """
    import json

    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/restart?mode={mode}",
        data=b"{}", method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError) as e:
        return {"ok": True, "mode": mode,
                "note": f"连接在关闭中重置: {type(e).__name__}"}


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

        # 轮询等待「监听进程被替换」这一状态收敛。
        # 注意：should_exit 只是置标志，uvicorn 需数十~数百 ms 才真正退出并释放
        # 端口；期间 /health 仍由**旧进程**应答。若 POST 后立即断言 PID 变化，
        # 会得到「PID 未变」的假失败（实测踩中）。故此处必须轮询而非即刻断言。
        deadline = time.monotonic() + 90
        pid_after = None
        while time.monotonic() < deadline:
            pid = _listener_pid(port)
            if pid and pid != old_pid and _health(port):
                pid_after = pid
                break
            time.sleep(1)

        assert pid_after, (
            f"重启后端口仍由旧进程监听（PID {old_pid}）→ 重启未真正替换进程")
    finally:
        _kill(_listener_pid(port))
        _kill(old_pid)
        _kill(pid_after)
        try:
            proc.terminate()
        except OSError:
            pass


def test_inflight_events_survive_restart_no_loss_no_dup(tmp_path):
    """重启后，进程死亡前已产出的流式事件必须可续读 —— 不丢、不重。

    这是「无感重启」对用户的最终承诺：对话中断处的内容既不能凭空消失，
    也不能重复渲染。单元测试只验证了 rebuild_buffers 的内存行为；此处走
    真实进程 + 真实 REST 接口，验证「重启 → 续读」这条完整链路。

    手法（不依赖 LLM，确定性）：先把一份「在途回合快照」写进临时状态库 ——
    模拟进程被杀死前的状态（3 条事件，**不**调用 finish_turn）；再拉起真实
    server，其启动恢复（rebuild_buffers）应把这些事件重建为后台缓冲区。
    """
    import json

    from tea_agent.server import turn_snapshot as ts

    db = tmp_path / "server_state.db"
    topic = "e2e-resume-topic"

    # ── 模拟「进程被杀死」：写入事件但不标记回合结束 ──
    os.environ["TEA_SERVER_STATE_DB"] = str(db)
    ts.begin_turn(topic)
    ts.record_event(topic, {"type": "content", "text": "甲"}, 0, force=True)
    ts.record_event(topic, {"type": "content", "text": "乙"}, 1, force=True)
    ts.record_event(topic, {"type": "usage", "total_tokens": 7}, 2, force=True)
    assert ts.read_snapshot(topic)["status"] == "active", "快照应处于在途状态"

    port = _free_port()
    cfg = tmp_path / "config.yaml"
    cfg.write_text("main_model:\n  provider: DeepSeek\n  model: deepseek-v4-flash\n",
                   encoding="utf-8")
    env = dict(os.environ)
    env["TEA_SERVER_STATE_DB"] = str(db)
    proc = subprocess.Popen(
        [sys.executable, "-m", "tea_agent.server", "--host", "127.0.0.1",
         "--port", str(port), "--config", str(cfg)],
        cwd=PROJECT_ROOT, env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    pid = None
    try:
        assert _wait_health(port, timeout=90), "server 未在 90s 内就绪"
        pid = _listener_pid(port)

        url = f"http://127.0.0.1:{port}/api/topic/{topic}/stream-buffer?since=-1"
        with urllib.request.urlopen(url, timeout=30) as r:
            buf = json.loads(r.read().decode("utf-8"))

        events = buf.get("events") or []
        idxs = [e["index"] for e in events]
        types = [e["event"].get("type") for e in events]

        # 不丢：崩溃前的 3 条事件原样可续读（其后是恢复时补的 done 收尾）
        assert types[:3] == ["content", "content", "usage"], \
            f"原始事件丢失或错序：types={types}"
        # 序号连续无空洞 —— 前端按 since=N 增量拉取，空洞会导致错位
        assert idxs == [0, 1, 2, 3], f"序号不连续（续读会错位）：{idxs}"
        # 不重：索引唯一
        assert len(set(idxs)) == len(idxs), f"事件重复：{idxs}"
        # 不重：内容事件恰好「甲、乙」各一次 —— 绝不能再出现累积的「甲乙」。
        # 原实现无条件补发 partial_text，同一内容会渲染两遍，此处即其回归防护。
        texts = [e["event"].get("text") for e in events
                 if e["event"].get("type") == "content"]
        assert texts == ["甲", "乙"], f"内容重复或丢失：{texts}"
        # 收尾：回合已死 → 必须补 done 并标记完成，否则前端无限轮询
        assert types[-1] == "done", f"缺少收尾事件：{types}"
        assert buf.get("done") is True, "恢复的回合未标记 done（前端将无限轮询）"
    finally:
        _kill(_listener_pid(port))
        _kill(pid)
