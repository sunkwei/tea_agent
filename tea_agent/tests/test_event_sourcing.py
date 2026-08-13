"""P2 事件溯源（Append-only Session Event Log）回归测试。

覆盖：
- 事件 append（turn/start, user/message, assistant/message, turn/end, tool/*）
- seq 递增 + 只追加（无 UPDATE/DELETE 接口）
- derive_messages 派生视图（Model-visible means logged）
- replay 完整重放
- fork_events 血统复制（payload._fork_source）
- stats 统计
- 与 conversations 表共存（渐进式改造，不破坏现有存储）
"""

import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from tea_agent.store._core import Storage  # noqa: E402


@pytest.fixture
def storage():
    """临时数据库 Storage 实例。"""
    db_path = os.path.join(tempfile.mkdtemp(), "test_events.db")
    st = Storage(db_path)
    yield st
    try:
        st.close()
    except Exception:
        pass


def test_append_and_seq(storage):
    """事件 append：seq 严格递增。"""
    tid = storage.topics.create_topic("ES")
    s1 = storage.events.append_event(tid, "turn/start", {})
    s2 = storage.events.append_event(tid, "user/message", {"content": "hi"})
    s3 = storage.events.append_event(tid, "assistant/message", {"content": "hello"})
    assert s1 == 1 and s2 == 2 and s3 == 3


def test_append_only_no_update_delete(storage):
    """审计约束：事件表无 UPDATE/DELETE 公开接口。"""
    assert not hasattr(storage.events, "update_event")
    assert not hasattr(storage.events, "delete_event")


def test_save_msg_records_turn_events(storage):
    """save_msg + update_msg_rounds 自动记录完整事件链。"""
    tid = storage.topics.create_topic("ES")
    cid = storage.conversations.save_msg(tid, "问题", "", False)
    storage.conversations.update_msg_rounds(
        cid, "答案", True,
        [{"role": "assistant", "content": "答案",
          "tool_calls": [{"function": {"name": "toolkit_search", "arguments": "{}"}}]}],
    )
    events = storage.events.replay(tid)
    types = [e["event_type"] for e in events]
    assert types == ["turn/start", "user/message", "assistant/message", "turn/end"]
    # assistant/message 的 payload 含 tool_calls 概览
    asst = [e for e in events if e["event_type"] == "assistant/message"][0]
    assert asst["payload"]["tool_calls"][0]["name"] == "toolkit_search"


def test_derive_messages(storage):
    """派生视图：从事件流 fold 出消息历史（审计核心能力）。"""
    tid = storage.topics.create_topic("ES")
    cid = storage.conversations.save_msg(tid, "用户问题", "", False)
    storage.conversations.update_msg_rounds(cid, "AI回答", False)
    msgs = storage.events.derive_messages(tid)
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert msgs[0]["content"] == "用户问题"
    assert msgs[1]["content"] == "AI回答"


def test_replay_order(storage):
    """重放保持 seq 顺序。"""
    tid = storage.topics.create_topic("ES")
    for i in range(5):
        storage.events.append_event(tid, "user/message", {"content": f"m{i}"})
    evs = storage.events.replay(tid)
    assert [e["seq"] for e in evs] == list(range(1, 6))
    assert [e["payload"]["content"] for e in evs] == [f"m{i}" for i in range(5)]


def test_fork_events_lineage(storage):
    """fork 事件复制：保留 _fork_source 血统。"""
    src = storage.topics.create_topic("源")
    storage.conversations.save_msg(src, "u", "", False)
    storage.events.append_event(src, "tool/call", {"name": "toolkit_x"})
    storage.topics.create_topic("分支", topic_id="fork1")
    n = storage.events.fork_events(src, "fork1")
    assert n == 3  # turn/start + user/message + tool/call
    evs = storage.events.replay("fork1")
    assert len(evs) == 3
    for e in evs:
        assert e["payload"]["_fork_source"]["topic_id"] == src


def test_stats(storage):
    """事件统计。"""
    tid = storage.topics.create_topic("ES")
    storage.events.append_event(tid, "tool/call", {"name": "a"})
    storage.events.append_event(tid, "tool/call", {"name": "b"})
    storage.events.append_event(tid, "tool/result", {"result": "x"})
    stats = storage.events.stats(tid)
    assert stats["total"] == 3
    assert stats["by_type"]["tool/call"] == 2
    assert stats["by_type"]["tool/result"] == 1


def test_coexists_with_conversations(storage):
    """渐进式改造：事件日志与 conversations 共存，互不干扰。"""
    tid = storage.topics.create_topic("ES")
    cid = storage.conversations.save_msg(tid, "你好", "", False)
    storage.conversations.update_msg_rounds(cid, "你好！", False)
    convs = storage.conversations.get_conversations(tid, limit=0)
    events = storage.events.replay(tid)
    assert len(convs) == 1
    assert len(events) == 4
    assert convs[0]["user_msg"] is not None
