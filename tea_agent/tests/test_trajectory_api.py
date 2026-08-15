"""P2 轨迹聚合（get_topic_trajectory）回归测试。

覆盖：
- 事件流 → 轨迹时间线（user / tool_call / tool_result / assistant 按 seq 排序）
- 思考链（reasoning_content）插入到 assistant 回复之前
- turn/start、turn/end 结构性标记不进入时间线
- limit 截断
"""

import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from tea_agent.server.modules.storage_module import StorageModule  # noqa: E402
from tea_agent.store._core import Storage  # noqa: E402


@pytest.fixture
def storage():
    """临时数据库 Storage 实例，并挂载到 StorageModule。"""
    db_path = os.path.join(tempfile.mkdtemp(), "test_trajectory.db")
    st = Storage(db_path)
    StorageModule._instance = st
    yield st
    try:
        st.close()
    except Exception:
        pass
    StorageModule._instance = None


def _build_topic_with_trajectory(storage) -> str:
    """构造含完整轨迹的 topic：用户提问 → 工具调用 → 工具结果 → 思考 → 回复。"""
    tid = storage.topics.create_topic("Traj")
    cid = storage.conversations.save_msg(tid, "查一下天气", "", False)
    # 工具调用 + 结果（模拟运行时写入）
    storage.events.append_event(tid, "tool/call", {
        "name": "toolkit_weather_my", "call_id": "call_1", "args": "{}",
    }, conversation_id=cid)
    storage.events.append_event(tid, "tool/result", {
        "name": "toolkit_weather_my", "call_id": "call_1", "success": True,
        "result": "晴 25°C", "duration_ms": 120.5,
    }, conversation_id=cid)
    # AI 回复 + 思考链（写入 rounds_json 模拟 update_msg_rounds）
    storage.conversations.update_msg_rounds(
        cid, "今天晴天，25 度。", True,
        [
            {"role": "assistant", "content": "",
             "reasoning_content": "用户想知道天气，我调用天气工具",
             "tool_calls": [{"function": {"name": "toolkit_weather_my", "arguments": "{}"}}]},
            {"role": "assistant", "content": "今天晴天，25 度。"},
        ],
    )
    return tid


def test_trajectory_full_chain(storage):
    """完整轨迹：user → tool_call → tool_result → thinking → assistant。"""
    tid = _build_topic_with_trajectory(storage)
    data = StorageModule.get_topic_trajectory(tid)
    timeline = data["timeline"]
    types = [t["type"] for t in timeline]
    assert types == ["user", "tool_call", "tool_result", "thinking", "assistant"]

    # 工具调用条目
    tc = timeline[1]
    assert tc["name"] == "toolkit_weather_my" and tc["call_id"] == "call_1"
    # 工具结果条目
    tr = timeline[2]
    assert tr["success"] is True and tr["result"] == "晴 25°C" and tr["duration_ms"] == 120.5
    # 思考链条目
    th = timeline[3]
    assert th["type"] == "thinking" and "天气" in th["content"]
    # assistant 条目
    asst = timeline[4]
    assert "25" in asst["content"]


def test_trajectory_skips_turn_markers(storage):
    """turn/start、turn/end 不进时间线（save_msg 自动写入的）。"""
    tid = storage.topics.create_topic("Traj2")
    cid = storage.conversations.save_msg(tid, "hello", "", False)
    storage.conversations.update_msg_rounds(cid, "world", False)
    data = StorageModule.get_topic_trajectory(tid)
    types = [t["type"] for t in data["timeline"]]
    assert types == ["user", "assistant"]
    assert "turn/start" not in types and "turn/end" not in types


def test_trajectory_limit(storage):
    """limit 截断时间线（保留最后 N 条）。"""
    tid = storage.topics.create_topic("Traj3")
    cid = storage.conversations.save_msg(tid, "q1", "", False)
    storage.conversations.update_msg_rounds(cid, "a1", False)
    cid2 = storage.conversations.save_msg(tid, "q2", "", False)
    storage.conversations.update_msg_rounds(cid2, "a2", False)
    data = StorageModule.get_topic_trajectory(tid, limit=2)
    assert data["count"] == 2
    # 最后两条是第二轮 user/assistant
    types = [t["type"] for t in data["timeline"]]
    assert types == ["user", "assistant"]


def test_trajectory_no_events(storage):
    """无事件时返回空时间线。"""
    tid = storage.topics.create_topic("Empty")
    data = StorageModule.get_topic_trajectory(tid)
    assert data["timeline"] == [] and data["count"] == 0


def test_trajectory_storage_not_loaded():
    """Storage 未加载时安全返回空。"""
    StorageModule._instance = None
    data = StorageModule.get_topic_trajectory("whatever")
    assert data == {"timeline": [], "count": 0}
