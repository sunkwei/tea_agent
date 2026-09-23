"""P1 工具轨迹事件（tool/call + tool/result 运行时写入）回归测试。

覆盖：
- _summarize_json 摘要截断（短值原样 / 长值首尾截断 / dict 序列化）
- _log_tool_event 写入 session_events（tool/call + tool/result 落库且 payload 正确）
- 事件类型合法性（EVENT_TYPES 包含 tool/*）
"""

import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from tea_agent.onlinesession import ToolComponent, _summarize_json  # noqa: E402
from tea_agent.store._core import Storage  # noqa: E402
from tea_agent.store._events import EVENT_TYPES  # noqa: E402


@pytest.fixture
def storage():
    """临时数据库 Storage 实例。"""
    db_path = os.path.join(tempfile.mkdtemp(), "test_tool_trace.db")
    st = Storage(db_path)
    yield st
    try:
        st.close()
    except Exception:
        pass


def _make_comp(storage, topic_id):
    """构造**真实** ToolComponent（配真实 SessionContext）。

    刻意不用替身。历史缺陷：本文件原先的 ``_FakeSession`` 手动设了
    ``self.current_topic_id``，而真实 ToolComponent **没有**该属性
    （topic_id 在 session 上，Component 只持有 ctx）—— 于是
    ``_log_tool_event`` 里 ``getattr(self, "current_topic_id", None)`` 恒为 None，
    工具事件**从不落库**（轨迹视图只剩 user/assistant，工具段永远空白），
    而测试因替身属性齐全始终为绿。

    现在 topic_id 走 ``ctx.topic_id``（回合入口 ``chat_stream`` 每轮同步的字段），
    测试必须走同一条路 —— 否则又会把缺陷固化成绿色契约。

    Args:
        storage: Storage 实例
        topic_id: 当前主题 ID（空串模拟"无 topic"场景）

    Returns:
        真实的 ToolComponent 实例
    """
    from tea_agent.session.components.tool import ToolComponent as _TC
    from tea_agent.session.context import SessionContext

    ctx = SessionContext()
    ctx.storage = storage
    ctx.topic_id = topic_id
    return _TC(ctx)


def _log_event(comp, event_type, payload):
    """调用真实 _log_tool_event。"""
    comp._log_tool_event(event_type, payload)


# ── _summarize_json ──

def test_summarize_short_value_unchanged():
    """短值原样返回。"""
    assert _summarize_json({"a": 1}, limit=100) == '{"a": 1}'
    assert _summarize_json("hi", limit=100) == '"hi"'


def test_summarize_long_value_truncated():
    """超长值首尾截断并标注信息。"""
    long_str = "x" * 5000
    out = _summarize_json(long_str, limit=100)
    assert "截断" in out and "B→100B" in out
    assert len(out) < 200


def test_summarize_unserializable_value():
    """不可序列化值降级为 str()。"""
    class _Weird:
        def __str__(self):
            return "weird-obj"

    out = _summarize_json(_Weird(), limit=100)
    assert "weird-obj" in out


# ── 事件类型合法性 ──

def test_tool_event_types_registered():
    """tool/call 与 tool/result 是合法事件类型。"""
    assert "tool/call" in EVENT_TYPES
    assert "tool/result" in EVENT_TYPES


# ── _log_tool_event 落库 ──

def test_log_tool_call_event(storage):
    """tool/call 事件写入 session_events，payload 含 name/call_id/args。"""
    tid = storage.topics.create_topic("TT")
    comp = _make_comp(storage, tid)
    _log_event(comp, "tool/call", {
        "name": "toolkit_search",
        "call_id": "call_1",
        "args": '{"query": "test"}',
    })
    events = storage.events.query_events(tid, event_type="tool/call")
    assert len(events) == 1
    ev = events[0]
    assert ev["payload"]["name"] == "toolkit_search"
    assert ev["payload"]["call_id"] == "call_1"
    assert "test" in ev["payload"]["args"]


def test_log_tool_result_event(storage):
    """tool/result 事件写入 session_events，payload 含 success/result/duration。"""
    tid = storage.topics.create_topic("TT")
    comp = _make_comp(storage, tid)
    _log_event(comp, "tool/result", {
        "name": "toolkit_search",
        "call_id": "call_1",
        "success": True,
        "error": None,
        "result": "found 3 items",
        "duration_ms": 12.5,
    })
    events = storage.events.query_events(tid, event_type="tool/result")
    assert len(events) == 1
    ev = events[0]
    assert ev["payload"]["success"] is True
    assert ev["payload"]["result"] == "found 3 items"
    assert ev["payload"]["duration_ms"] == 12.5


def test_log_tool_event_seq_increments(storage):
    """tool/call 与 tool/result 交替写入，seq 严格递增。"""
    tid = storage.topics.create_topic("TT")
    comp = _make_comp(storage, tid)
    _log_event(comp, "tool/call", {"name": "a", "call_id": "c1", "args": "{}"})
    _log_event(comp, "tool/result", {"name": "a", "call_id": "c1", "success": True, "result": "r1"})
    _log_event(comp, "tool/call", {"name": "b", "call_id": "c2", "args": "{}"})
    _log_event(comp, "tool/result", {"name": "b", "call_id": "c2", "success": False, "error": "boom"})
    events = storage.events.replay(tid)
    assert [e["seq"] for e in events] == [1, 2, 3, 4]
    assert [e["event_type"] for e in events] == [
        "tool/call", "tool/result", "tool/call", "tool/result",
    ]


def test_log_tool_event_isolated_on_no_topic(storage):
    """无 topic_id 时静默跳过（异常隔离，不抛错）。"""
    comp = _make_comp(storage, "")  # 空 topic
    _log_event(comp, "tool/call", {"name": "x", "call_id": "c", "args": "{}"})
    # 不应抛异常，也不产生事件
    assert storage.events.stats()["total"] == 0


def test_log_tool_event_rejects_unknown_type(storage):
    """非 tool/* 事件类型被忽略。"""
    tid = storage.topics.create_topic("TT")
    comp = _make_comp(storage, tid)
    _log_event(comp, "turn/start", {})  # 应被忽略
    assert storage.events.stats(tid)["total"] == 0


# ── 回合入口同步（ctx.topic_id 的来源）────────────────────────

def _make_real_session(topic_id):
    """构造真实 OnlineToolSession（API 客户端指向假地址，不发起请求）。

    Returns:
        (session, storage) —— storage 为 None 时表示未启用存储
    """
    from unittest.mock import MagicMock

    from tea_agent.onlinesession import OnlineToolSession

    tk = MagicMock()
    tk.meta_map = {}
    sess = OnlineToolSession(
        toolkit=tk, api_key="sk-test", api_url="https://api.test.invalid/v1",
        model="test-model", max_history=5, enable_thinking=False, storage=None,
    )
    return sess


def test_chat_stream_syncs_ctx_topic_id():
    """chat_stream 必须把 topic_id 写进 ctx（否则工具事件落不到正确主题）。

    这是端到端的接线契约：``_log_tool_event`` 读 ``ctx.topic_id``，
    而该字段只有回合入口会写。若此处漏写，工具事件会静默丢弃 ——
    轨迹视图只剩 user/assistant，工具调用段永远空白。
    """
    sess = _make_real_session("t-sync")
    try:
        # 用空 pipeline 结果短路真实 LLM 调用：同步发生在 pipeline 之前
        sess.pipeline.execute = lambda ctx: {"full_reply": "ok", "used_tools": False}
        sess.chat_stream("hi", callback=lambda s: None, topic_id="topic-abc")
        assert sess.context.topic_id == "topic-abc", (
            f"ctx.topic_id 未同步: {sess.context.topic_id!r}"
        )
    finally:
        sess.close()


def test_ctx_topic_id_used_by_log_tool_event():
    """串联验证：chat_stream 同步的 topic_id 能被 _log_tool_event 消费并落库。"""
    import tempfile

    from tea_agent.store._core import Storage

    db = os.path.join(tempfile.mkdtemp(), "sync.db")
    st = Storage(db)
    tid = st.topics.create_topic("同步验证")

    sess = _make_real_session(tid)
    try:
        sess.context.storage = st  # 接入真实 storage
        sess.pipeline.execute = lambda ctx: {"full_reply": "ok", "used_tools": False}
        sess.chat_stream("hi", callback=lambda s: None, topic_id=tid)

        # 回合入口已同步 → 组件记录工具事件应落到该 topic
        sess.tools_comp._log_tool_event(
            "tool/call", {"name": "toolkit_exec", "call_id": "c1", "args": "{}"}
        )
        evs = st.events.query_events(tid, event_type="tool/call")
        assert len(evs) == 1, f"工具事件未落库（轨迹工具段将空白）: {len(evs)} 条"
        assert evs[0]["payload"]["name"] == "toolkit_exec"
    finally:
        sess.close()
        try:
            st.close()
        except Exception:
            pass
