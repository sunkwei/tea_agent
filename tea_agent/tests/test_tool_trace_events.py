"""P1 工具轨迹事件（tool/call + tool/result 运行时写入）回归测试。

覆盖：
- _summarize_json 摘要截断（短值原样 / 长值首尾截断 / dict 序列化）
- _log_tool_event 写入 session_events（tool/call + tool/result 落库且 payload 正确）
- 事件类型合法性（EVENT_TYPES 包含 tool/*）
"""

import os
import sys
import tempfile
from types import SimpleNamespace

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


class _FakeSession:
    """模拟 OnlineToolSession 的最小对象（仅含 _log_tool_event 依赖的属性）。"""

    def __init__(self, storage, topic_id):
        self.current_topic_id = topic_id
        self.ctx = SimpleNamespace(storage=storage)


def _log_event(fake, event_type, payload):
    """以未绑定方法方式调用真实 _log_tool_event（ToolComponent 方法）。"""
    ToolComponent._log_tool_event(fake, event_type, payload)


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
    fake = _FakeSession(storage, tid)
    _log_event(fake, "tool/call", {
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
    fake = _FakeSession(storage, tid)
    _log_event(fake, "tool/result", {
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
    fake = _FakeSession(storage, tid)
    _log_event(fake, "tool/call", {"name": "a", "call_id": "c1", "args": "{}"})
    _log_event(fake, "tool/result", {"name": "a", "call_id": "c1", "success": True, "result": "r1"})
    _log_event(fake, "tool/call", {"name": "b", "call_id": "c2", "args": "{}"})
    _log_event(fake, "tool/result", {"name": "b", "call_id": "c2", "success": False, "error": "boom"})
    events = storage.events.replay(tid)
    assert [e["seq"] for e in events] == [1, 2, 3, 4]
    assert [e["event_type"] for e in events] == [
        "tool/call", "tool/result", "tool/call", "tool/result",
    ]


def test_log_tool_event_isolated_on_no_topic(storage):
    """无 topic_id 时静默跳过（异常隔离，不抛错）。"""
    fake = _FakeSession(storage, "")  # 空 topic
    _log_event(fake, "tool/call", {"name": "x", "call_id": "c", "args": "{}"})
    # 不应抛异常，也不产生事件
    assert storage.events.stats()["total"] == 0


def test_log_tool_event_rejects_unknown_type(storage):
    """非 tool/* 事件类型被忽略。"""
    tid = storage.topics.create_topic("TT")
    fake = _FakeSession(storage, tid)
    _log_event(fake, "turn/start", {})  # 应被忽略
    assert storage.events.stats(tid)["total"] == 0
