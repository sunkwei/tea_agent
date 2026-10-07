"""session_events 事件日志 + 投影回归测试。"""

from __future__ import annotations

import pytest

from tea_agent import session_events as se


def _build():
    log = []
    se.append_event(log, topic_id="t", type="turn_start", turn=1)
    se.append_event(log, topic_id="t", type="step_request", turn=1, step=1, data={"starts_request_series": True})
    se.append_event(log, topic_id="t", type="tool_call", turn=1, step=1, data={"name": "toolkit_exec"})
    se.append_event(log, topic_id="t", type="tool_result", turn=1, step=1)
    se.append_event(log, topic_id="t", type="step_request", turn=1, step=2, data={"starts_request_series": False})
    se.append_event(log, topic_id="t", type="turn_end", turn=1)
    return log


def test_append_only_seq_continuous():
    log = _build()
    assert [e.seq for e in log] == [1, 2, 3, 4, 5, 6]


def test_append_rejects_unknown_type():
    with pytest.raises(ValueError):
        se.append_event([], topic_id="t", type="bogus", turn=1)


def test_replay_roundtrip():
    log = _build()
    rows = [e.to_dict() for e in log]
    assert se.replay(rows) == log


def test_replay_skips_gap_and_bad_row():
    rows = [
        {"seq": 1, "topic_id": "t", "type": "turn_start", "turn": 1},
        {"seq": 9, "topic_id": "t", "type": "turn_end", "turn": 1},  # 断裂
        {"seq": "x", "topic_id": "t", "type": "?", "turn": 1},
    ]  # 坏行
    out = se.replay(rows)
    assert [e.seq for e in out] == [1]


def test_project_turns():
    t = se.project_turns(_build())
    assert t == [{"turn": 1, "started": True, "ended": True, "steps": 2, "series_resets": 1, "tool_calls": 1}]


def test_project_steps():
    s = se.project_steps(_build())
    assert len(s) == 2
    assert s[0]["series_reset"] is True and s[0]["tools"] == ["toolkit_exec"]
    assert s[1]["series_reset"] is False and s[1]["tools"] == []


def test_project_l1_view():
    l1 = se.project_l1(_build())
    assert [m["role"] for m in l1] == ["step", "tool_call", "tool_result", "step"]
    assert l1[0]["starts_request_series"] is True


def test_project_l2_l3():
    events = _build()
    assert se.project_l2(events, window=1)[0]["turn"] == 1
    agg = se.project_l3(events)
    assert "2 steps" in agg["topic_summary"]
    assert agg["series_resets"] == 1
