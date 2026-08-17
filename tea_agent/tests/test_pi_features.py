"""PiFeaturesModule 回归测试 — 会话树/消息队列/手动压缩 (server+web 接口)。

借鉴 earendil-works/pi Agent Harness，通过 server 路由暴露。
覆盖：
  - 会话树：append / branch / switch / summary / 持久化
  - 消息队列：steering / followup 推送、状态、清空、消费
  - 路由可达性：/api/pi/* 全部端点 200
"""

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from tea_agent.server.modules import pi_features_module as _pfm
from tea_agent.server.modules.pi_features_module import PiFeaturesModule as P


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    # 清理测试产生的 JSONL 缓存
    home = pathlib.Path.home() / ".tea_agent" / "session_trees"
    if home.exists():
        for f in home.glob("pi_test_*"):
            f.unlink(missing_ok=True)
    _pfm._trees.clear()
    _pfm._queues.clear()


# ── 会话树 ──────────────────────────────────────────────

def test_tree_append_and_path():
    r1 = P.tree_append("pi_test_1", "user", "你好")
    assert r1["ok"] and r1["role"] == "user"
    P.tree_append("pi_test_1", "assistant", "回复A")
    d = P.tree_get("pi_test_1")
    assert d["stats"]["total_nodes"] == 2
    assert [n["role"] for n in d["current_path"]] == ["user", "assistant"]


def test_tree_branch_and_stats():
    P.tree_append("pi_test_2", "user", "Q1")
    P.tree_append("pi_test_2", "assistant", "A1")
    br = P.tree_branch("pi_test_2", "换个方向", label="方向B")
    assert br["ok"] and br["branch"] and br["label"] == "方向B"
    d = P.tree_get("pi_test_2")
    assert d["stats"]["branch_count"] == 1
    assert len(d["branches"]) == 1
    assert d["branches"][0]["label"] == "方向B"


def test_tree_switch_short_id():
    P.tree_append("pi_test_3", "user", "Q1")
    r2 = P.tree_append("pi_test_3", "assistant", "A1")
    P.tree_branch("pi_test_3", "B")
    # 切回第一条消息（用短 ID）
    r = P.tree_switch("pi_test_3", r2["node_id"])
    assert r["ok"] and r["depth"] == 2


def test_tree_summary_generated():
    P.tree_append("pi_test_4", "user", "核心问题")
    br = P.tree_branch("pi_test_4", "方案B")
    P.tree_append("pi_test_4", "assistant", "方案B细节")
    s = P.tree_summary("pi_test_4", br["node_id"])
    assert s["ok"]
    assert "方案B" in s["summary"]


def test_tree_persist_jsonl():
    P.tree_append("pi_test_5", "user", "持久化测试")
    # 清除内存缓存，模拟重启
    _pfm._trees.clear()
    d = P.tree_get("pi_test_5")
    assert d["stats"]["total_nodes"] == 1
    assert d["current_path"][0]["content"] == "持久化测试"


# ── 消息队列 ────────────────────────────────────────────

def test_queue_push_status_clear():
    r = P.queue_push("pi_test_q", "先暂停", "steering")
    assert r["ok"] and r["type"] == "steering"
    P.queue_push("pi_test_q", "完成后总结", "followup")
    st = P.queue_status("pi_test_q")
    assert st["total_pending"] == 2
    assert len(st["steering"]) == 1 and len(st["followup"]) == 1
    P.queue_clear("pi_test_q")
    assert P.queue_status("pi_test_q")["total_pending"] == 0


def test_queue_drain_steering():
    P.queue_push("pi_test_q2", "即时指令", "steering")
    P.queue_push("pi_test_q2", "后续任务", "followup")
    drained = P.queue_drain("pi_test_q2", "steering")
    assert len(drained["messages"]) == 1
    assert drained["messages"][0]["content"] == "即时指令"
    # steering 已消费，followup 仍在
    st = P.queue_status("pi_test_q2")
    assert len(st["steering"]) == 0 and len(st["followup"]) == 1


# ── 手动压缩 ────────────────────────────────────────────

def test_compact_no_conversation_returns_graceful():
    r = P.compact_topic("pi_test_nonexistent")
    assert r["ok"] is False  # 无对话时优雅报错，不崩溃
    assert "error" in r


# ── HTTP 路由（若 TestClient 可用） ─────────────────────

@pytest.mark.skipif(
    not pathlib.Path("tea_agent/server/server.py").exists(),
    reason="server 文件不可用",
)
def test_http_routes():
    try:
        from starlette.testclient import TestClient
    except ImportError:
        pytest.skip("starlette TestClient 不可用")
    from tea_agent.server.server import create_app

    client = TestClient(create_app())
    tid = "pi_test_http"
    assert client.get("/api/pi/stats").status_code == 200
    assert client.get(f"/api/pi/tree/{tid}").status_code == 200
    assert client.post(
        f"/api/pi/tree/{tid}/append", json={"role": "user", "content": "x"}
    ).status_code == 200
    assert client.post(
        f"/api/pi/tree/{tid}/branch", json={"content": "y"}
    ).status_code == 200
    assert client.post(
        f"/api/pi/queue/{tid}", json={"content": "z", "type": "steering"}
    ).status_code == 200
    assert client.get(f"/api/pi/queue/{tid}").status_code == 200
    assert client.delete(f"/api/pi/queue/{tid}").status_code == 200
    assert client.post(f"/api/pi/compact/{tid}", json={"force": True}).status_code == 200
    client.delete(f"/api/pi/queue/{tid}")
