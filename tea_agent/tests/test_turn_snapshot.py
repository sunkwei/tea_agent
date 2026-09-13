"""turn_snapshot 单元测试 — 在途回合快照（重启后恢复已产出事件）。"""

from __future__ import annotations

import pytest

from tea_agent.server import turn_snapshot as ts


@pytest.fixture()
def db(tmp_path, monkeypatch):
    """隔离的临时快照库。"""
    p = tmp_path / "server_state.db"
    monkeypatch.setenv("TEA_SERVER_STATE_DB", str(p))
    ts._last_write.clear()
    return str(p)


# ── 1. 生命周期 ────────────────────────────────────────────────


class TestLifecycle:
    def test_begin_creates_active_snapshot(self, db):
        ts.begin_turn("t1", conv_id="c1")
        snap = ts.read_snapshot("t1")
        assert snap is not None
        assert snap["status"] == "active"
        assert snap["conv_id"] == "c1"
        assert snap["events"] == []
        assert snap["partial_text"] == ""
        assert snap["last_event_index"] == -1

    def test_begin_without_topic_is_noop(self, db):
        ts.begin_turn("")
        assert ts.read_snapshot("") is None

    def test_record_requires_begin(self, db):
        """未 begin 的 topic（如无 topic 的临时对话）静默跳过，不建行。"""
        assert ts.record_event("nope", {"type": "content", "text": "x"}, 0, force=True) is False
        assert ts.read_snapshot("nope") is None

    def test_record_then_read(self, db):
        ts.begin_turn("t1")
        assert ts.record_event("t1", {"type": "content", "text": "hi"}, 0, force=True) is True
        snap = ts.read_snapshot("t1")
        assert snap["last_event_index"] == 0
        assert snap["seen"] == 1
        assert snap["partial_text"] == "hi"
        assert [e["index"] for e in snap["events"]] == [0]

    def test_finish_marks_status(self, db):
        ts.begin_turn("t1")
        ts.finish_turn("t1", status="done")
        assert ts.read_snapshot("t1")["status"] == "done"

    def test_begin_resets_previous_turn(self, db):
        ts.begin_turn("t1")
        ts.record_event("t1", {"type": "content", "text": "old"}, 0, force=True)
        ts.begin_turn("t1")
        snap = ts.read_snapshot("t1")
        assert snap["events"] == []
        assert snap["partial_text"] == ""
        assert snap["status"] == "active"


class TestEnsureTurn:
    """前台断连 → 后台接管：不得清空已累积内容。"""

    def test_creates_when_absent(self, db):
        ts.ensure_turn("t1")
        snap = ts.read_snapshot("t1")
        assert snap["status"] == "active"
        assert snap["last_event_index"] == -1

    def test_preserves_active_snapshot(self, db):
        ts.begin_turn("t1")
        ts.record_event("t1", {"type": "content", "text": "前台已产出"}, 0, force=True)
        ts.ensure_turn("t1")   # 后台接管
        snap = ts.read_snapshot("t1")
        assert snap["partial_text"] == "前台已产出"
        assert len(snap["events"]) == 1

    def test_resets_finished_snapshot(self, db):
        ts.begin_turn("t1")
        ts.record_event("t1", {"type": "content", "text": "x"}, 0, force=True)
        ts.finish_turn("t1", status="done")
        ts.ensure_turn("t1")
        snap = ts.read_snapshot("t1")
        assert snap["status"] == "active"
        assert snap["partial_text"] == ""

    def test_empty_topic_is_noop(self, db):
        ts.ensure_turn("")
        assert ts.read_snapshot("") is None


class TestAutoIndex:
    """index=None 时自动递增，保证两条写入路径序号单调（不倒退）。"""

    def test_auto_index_increments(self, db):
        ts.begin_turn("t1")
        ts.record_event("t1", {"type": "content", "text": "a"}, force=True)
        ts.record_event("t1", {"type": "content", "text": "b"}, force=True)
        ts.record_event("t1", {"type": "content", "text": "c"}, force=True)
        snap = ts.read_snapshot("t1")
        assert [e["index"] for e in snap["events"]] == [0, 1, 2]
        assert snap["last_event_index"] == 2

    def test_auto_index_continues_after_handoff(self, db):
        """前台写 0/1（显式）→ 后台接管用 auto，必须接着 2 而不是重头开始。"""
        ts.begin_turn("t1")
        ts.record_event("t1", {"type": "content", "text": "前台0"}, 0, force=True)
        ts.record_event("t1", {"type": "content", "text": "前台1"}, 1, force=True)
        ts.ensure_turn("t1")
        ts.record_event("t1", {"type": "content", "text": "后台接管"}, force=True)
        snap = ts.read_snapshot("t1")
        assert [e["index"] for e in snap["events"]] == [0, 1, 2]
        assert snap["seen"] == 3

    def test_explicit_index_still_supported(self, db):
        ts.begin_turn("t1")
        ts.record_event("t1", {"type": "content", "text": "a"}, 7, force=True)
        assert ts.read_snapshot("t1")["last_event_index"] == 7


# ── 2. partial_text 累积 ───────────────────────────────────────


class TestPartialText:
    def test_content_events_accumulate(self, db):
        ts.begin_turn("t1")
        for i, chunk in enumerate(["你", "好", "世界"]):
            ts.record_event("t1", {"type": "content", "text": chunk}, i, force=True)
        assert ts.read_snapshot("t1")["partial_text"] == "你好世界"

    def test_token_event_also_counted(self, db):
        ts.begin_turn("t1")
        ts.record_event("t1", {"type": "token", "text": "abc"}, 0, force=True)
        assert ts.read_snapshot("t1")["partial_text"] == "abc"

    def test_reasoning_not_counted(self, db):
        """think 属于推理，不应混入助手正文。"""
        ts.begin_turn("t1")
        ts.record_event("t1", {"type": "think", "text": "让我想想"}, 0, force=True)
        ts.record_event("t1", {"type": "think_done"}, 1, force=True)
        assert ts.read_snapshot("t1")["partial_text"] == ""

    def test_tool_events_not_counted(self, db):
        ts.begin_turn("t1")
        ts.record_event("t1", {"type": "tool_start", "text": "toolkit_exec"}, 0, force=True)
        assert ts.read_snapshot("t1")["partial_text"] == ""


# ── 3. 节流与有界 ──────────────────────────────────────────────


class TestThrottleAndBounds:
    def test_throttle_skips_rapid_writes(self, db):
        ts.begin_turn("t1")
        assert ts.record_event("t1", {"type": "content", "text": "a"}, 0, now=100.0) is True
        # 同一时间戳（未达间隔）→ 跳过
        assert ts.record_event("t1", {"type": "content", "text": "b"}, 1, now=100.1) is False
        # 超过间隔 → 写入
        assert ts.record_event("t1", {"type": "content", "text": "c"}, 2,
                               now=100.0 + ts.DEFAULT_MIN_INTERVAL + 0.01) is True
        assert [e["index"] for e in ts.read_snapshot("t1")["events"]] == [0, 2]

    def test_force_bypasses_throttle(self, db):
        ts.begin_turn("t1")
        ts.record_event("t1", {"type": "content", "text": "a"}, 0, now=1.0)
        assert ts.record_event("t1", {"type": "content", "text": "b"}, 1,
                               now=1.0, force=True) is True

    def test_seen_advances_even_when_write_skipped(self, db):
        """节流跳过的写不影响最终一致性：后一次写会带上更高的 index。"""
        ts.begin_turn("t1")
        ts.record_event("t1", {"type": "content", "text": "a"}, 0, now=1.0)
        ts.record_event("t1", {"type": "content", "text": "b"}, 1, now=1.01)  # 跳过
        ts.record_event("t1", {"type": "content", "text": "c"}, 2, now=1.6)
        snap = ts.read_snapshot("t1")
        assert snap["last_event_index"] == 2
        assert snap["seen"] == 3

    def test_events_are_bounded(self, db):
        ts.begin_turn("t1")
        for i in range(10):
            ts.record_event("t1", {"type": "content", "text": str(i)}, i,
                            force=True, max_events=3)
        events = ts.read_snapshot("t1")["events"]
        assert [e["index"] for e in events] == [7, 8, 9]

    def test_long_fields_truncated(self, db):
        ts.begin_turn("t1")
        ts.record_event("t1", {"type": "tool_result", "text": "x" * 5000}, 0,
                        force=True, max_field=100)
        ev = ts.read_snapshot("t1")["events"][0]["event"]
        assert len(ev["text"]) < 200
        assert ev["text"].endswith("[truncated]")

    def test_nested_structure_truncated(self, db):
        ts.begin_turn("t1")
        payload = {"type": "tool_result", "data": {"rows": [{"v": "y" * 4000}]}}
        ts.record_event("t1", payload, 0, force=True, max_field=50)
        ev = ts.read_snapshot("t1")["events"][0]["event"]
        assert ev["data"]["rows"][0]["v"].endswith("[truncated]")


# ── 4. 恢复 ────────────────────────────────────────────────────


class _FakeState:
    """替身：记录重建后的缓冲区内容。"""

    def __init__(self):
        self.buffers = {}
        self.done = set()

    def create_background_buffer(self, topic_id):
        self.buffers[topic_id] = []
        return {"events": [], "done": False}

    def append_to_buffer(self, topic_id, event, index):
        self.buffers.setdefault(topic_id, []).append({"index": index, "event": event})

    def mark_buffer_done(self, topic_id):
        self.done.add(topic_id)


class TestRecovery:
    def test_load_resumable_excludes_finished(self, db):
        ts.begin_turn("a")
        ts.begin_turn("b")
        ts.finish_turn("b", status="done")
        assert [s["topic_id"] for s in ts.load_resumable()] == ["a"]

    def test_load_resumable_excludes_stale(self, db):
        ts.begin_turn("a")
        assert ts.load_resumable(ttl=10, now=ts.read_snapshot("a")["updated_at"] + 100) == []

    def test_abandon_stale_marks(self, db):
        ts.begin_turn("a")
        updated = ts.read_snapshot("a")["updated_at"]
        n = ts.abandon_stale(ttl=10, now=updated + 100)
        assert n == 1
        assert ts.read_snapshot("a")["status"] == "abandoned"

    def test_rebuild_buffers_restores_events_and_closes(self, db):
        ts.begin_turn("t1")
        ts.record_event("t1", {"type": "content", "text": "部分"}, 0, force=True)
        ts.record_event("t1", {"type": "tool_start", "text": "t"}, 1, force=True)

        fake = _FakeState()
        resumed = ts.rebuild_buffers(state_module=fake)

        assert resumed == ["t1"]
        assert "t1" in fake.buffers
        types = [e["event"]["type"] for e in fake.buffers["t1"]]
        # 原始事件保留 + partial_text 补齐 + done 收尾
        assert types[:2] == ["content", "tool_start"]
        assert types[-2:] == ["content", "done"]
        assert fake.buffers["t1"][-2]["event"]["recovered"] is True
        assert "t1" in fake.done
        # 恢复后标记为 abandoned，不会反复恢复
        assert ts.read_snapshot("t1")["status"] == "abandoned"
        assert ts.rebuild_buffers(state_module=_FakeState()) == []

    def test_rebuild_without_snapshots_is_empty(self, db):
        assert ts.rebuild_buffers(state_module=_FakeState()) == []

    def test_rebuild_skips_foreign_shape(self, db):
        """事件格式异常（非 dict）不致命，仍能收尾。"""
        ts.begin_turn("t1")
        ts.record_event("t1", {"type": "content", "text": "ok"}, 0, force=True)
        fake = _FakeState()
        assert ts.rebuild_buffers(state_module=fake) == ["t1"]

    def test_partial_text_only_recovered_once(self, db):
        ts.begin_turn("t1")
        ts.record_event("t1", {"type": "content", "text": "abc"}, 0, force=True)
        fake = _FakeState()
        ts.rebuild_buffers(state_module=fake)
        # 断言**全部** content 事件（不只是 recovered 的）。
        # 曾因只筛 recovered=True 而漏掉「partial_text 重复补发」缺陷：
        # 原实现无条件再补一条累积文本，导致同一内容出现两遍（端到端实测踩中）。
        texts = [e["event"].get("text") for e in fake.buffers["t1"]
                 if e["event"].get("type") == "content"]
        assert texts == ["abc"], f"内容重复或丢失：{texts}"

    def test_partial_text_used_when_no_content_events(self, db):
        """事件被裁剪/缺失时，partial_text 仍是唯一文本来源 → 应兜底补发。"""
        ts.begin_turn("t1")
        # token 事件计入 partial_text，但事件类型不是 content
        ts.record_event("t1", {"type": "token", "text": "xyz"}, 0, force=True)
        fake = _FakeState()
        ts.rebuild_buffers(state_module=fake)
        texts = [e["event"].get("text") for e in fake.buffers["t1"]
                 if e["event"].get("type") == "content"]
        assert texts == ["xyz"], f"partial_text 兜底失效：{texts}"


# ── 5. 健壮性（fail-open）───────────────────────────────────────


class TestFailOpen:
    def test_read_missing_path_returns_none(self, db):
        assert ts.read_snapshot("never-existed") is None

    def test_clear_removes_all(self, db):
        ts.begin_turn("a")
        ts.begin_turn("b")
        assert ts.clear() >= 2
        assert ts.load_resumable() == []

    def test_record_failure_does_not_raise(self, monkeypatch, db):
        ts.begin_turn("t1")
        monkeypatch.setattr(ts, "_connect", lambda *a, **k: (_ for _ in ()).throw(OSError("boom")))
        assert ts.record_event("t1", {"type": "content", "text": "x"}, 0, force=True) is False

    def test_finish_failure_does_not_raise(self, monkeypatch, db):
        monkeypatch.setattr(ts, "_connect", lambda *a, **k: (_ for _ in ()).throw(OSError("boom")))
        ts.finish_turn("t1")  # 不抛异常即可
