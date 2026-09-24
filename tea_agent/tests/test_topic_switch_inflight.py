"""会话进行中切换主题 → 切回时的可见性回归测试。

背景（修复前的缺陷，端到端实测）：
  回合进行中切走主题 → SSE 断连 → 服务端把 session 移入后台并启动缓冲区读取器。
  但读取器**只消费队列**，而断连前已产出的事件早已被前台 SSE 消费掉（只写进
  turn_snapshot，不再进队列）。于是切回主题时 ``/stream-buffer`` 是空数组：

      turn_snapshot.partial_text = '甲段内容乙段内容丙段内容'   ← 内容明明在
      /stream-buffer            → {"events": [], "done": false}  ← 却拿不到

  前端虽因 ``status.active/background`` 启动了轮询，却什么也补不出来；
  用户提问更糟 —— 它在回合结束时才写库，此时 DB 与事件流里都没有。

两个修复点：
  1. 缓冲区接管时先回放快照已有事件（``_seed_buffer_from_snapshot``），
     且序号与后续队列事件连续（快照 0..N → 队列 N+1），前端按 since 增量
     拉取时既不错位也不重复。
  2. 发起对话时把用户提问记为快照事件（序号 0），切回时可渲染出提问。
"""

from __future__ import annotations

import asyncio
import contextlib
import os

import pytest

from tea_agent.server import turn_snapshot as ts


@pytest.fixture()
def db(tmp_path, monkeypatch):
    """隔离的临时快照库 + 干净的内存态。"""
    p = tmp_path / "server_state.db"
    monkeypatch.setenv("TEA_SERVER_STATE_DB", str(p))
    ts._last_write.clear()
    ts.clear()
    yield str(p)
    ts.clear()


@pytest.fixture()
def state_mod(monkeypatch):
    """真实 state 模块，用完清空全局态。"""
    from tea_agent.server.modules import state as st

    st.clear_all()
    yield st
    st.clear_all()


# ════════════════════════════════════════════════════════════
# 1. 快照 → 缓冲区回放（修复点 1）
# ════════════════════════════════════════════════════════════


class TestSeedBufferFromSnapshot:
    def test_replays_snapshot_events(self, db, state_mod):
        """断连前已产出的事件必须回放进缓冲区（此前完全拿不到）。"""
        from tea_agent.server._compat import _seed_buffer_from_snapshot

        ts.begin_turn("t1")
        ts.record_event("t1", {"type": "user_message", "text": "提问"}, 0, force=True)
        ts.record_event("t1", {"type": "token", "text": "甲"}, 1, force=True)
        ts.record_event("t1", {"type": "token", "text": "乙"}, 2, force=True)

        state_mod.create_background_buffer("t1")
        _seed_buffer_from_snapshot("t1")

        buf = state_mod.read_buffer_since("t1", -1)
        types = [e["event"]["type"] for e in buf["events"]]
        assert types == ["user_message", "token", "token"], types
        texts = [e["event"].get("text") for e in buf["events"]]
        assert texts == ["提问", "甲", "乙"]

    def test_returns_next_index_after_seed(self, db, state_mod):
        """返回的序号必须接在快照末尾之后（队列事件从这里续号）。"""
        from tea_agent.server._compat import _seed_buffer_from_snapshot

        ts.begin_turn("t1")
        ts.record_event("t1", {"type": "token", "text": "甲"}, 0, force=True)
        ts.record_event("t1", {"type": "token", "text": "乙"}, 1, force=True)

        state_mod.create_background_buffer("t1")
        assert _seed_buffer_from_snapshot("t1") == 2

    def test_no_snapshot_returns_zero(self, db, state_mod):
        """无快照（如纯后台回合）→ 返回 0，不影响原有从 0 开始的行为。"""
        from tea_agent.server._compat import _seed_buffer_from_snapshot

        state_mod.create_background_buffer("nope")
        assert _seed_buffer_from_snapshot("nope") == 0

    def test_sequence_continuous_across_seed_and_queue(self, db, state_mod):
        """序号连续无空洞：快照 0..2 → 队列续 3,4（前端 since 增量拉取不错位）。"""
        from tea_agent.server._compat import _seed_buffer_from_snapshot

        ts.begin_turn("t1")
        for i, t in enumerate(["甲", "乙", "丙"]):
            ts.record_event("t1", {"type": "token", "text": t}, i, force=True)

        state_mod.create_background_buffer("t1")
        nxt = _seed_buffer_from_snapshot("t1")
        # 模拟接管后队列继续产出
        state_mod.append_to_buffer("t1", {"type": "token", "text": "丁"}, nxt)
        state_mod.append_to_buffer("t1", {"type": "token", "text": "戊"}, nxt + 1)

        buf = state_mod.read_buffer_since("t1", -1)
        idxs = [e["index"] for e in buf["events"]]
        assert idxs == [0, 1, 2, 3, 4], idxs
        assert len(set(idxs)) == len(idxs), f"序号重复：{idxs}"

    def test_incremental_read_has_no_dup(self, db, state_mod):
        """按 since 增量拉取：第二轮不能重复拿到第一轮的事件。"""
        from tea_agent.server._compat import _seed_buffer_from_snapshot

        ts.begin_turn("t1")
        ts.record_event("t1", {"type": "token", "text": "甲"}, 0, force=True)

        state_mod.create_background_buffer("t1")
        nxt = _seed_buffer_from_snapshot("t1")

        first = state_mod.read_buffer_since("t1", -1)
        assert [e["event"]["text"] for e in first["events"]] == ["甲"]

        state_mod.append_to_buffer("t1", {"type": "token", "text": "乙"}, nxt)
        second = state_mod.read_buffer_since("t1", first["next_index"])
        assert [e["event"]["text"] for e in second["events"]] == ["乙"]


# ════════════════════════════════════════════════════════════
# 2. 缓冲区读取器接管时先回放（修复点 1 的接线）
# ════════════════════════════════════════════════════════════


class TestBufferReaderSeedsBeforeQueue:
    def _run_reader(self, topic_id, queue, timeout=1.0):
        from tea_agent.server._compat import _background_buffer_reader

        async def _main():
            task = asyncio.create_task(_background_buffer_reader(topic_id, queue))
            await asyncio.sleep(timeout)
            task.cancel()
            # 预期：本测试主动取消该任务，此处只是等它真正结束
            with contextlib.suppress(asyncio.CancelledError):
                await task

        asyncio.run(_main())

    def test_seeds_snapshot_then_consumes_queue(self, db, state_mod):
        """接管后：快照旧事件 + 队列新事件都在缓冲区，且序号连续。"""
        ts.begin_turn("t1")
        ts.record_event("t1", {"type": "user_message", "text": "提问"}, 0, force=True)
        ts.record_event("t1", {"type": "token", "text": "断连前"}, 1, force=True)

        queue: asyncio.Queue = asyncio.Queue()
        # 断连后新产出的事件（由后台线程投入队列）
        queue.put_nowait({"type": "token", "text": "断连后"})
        queue.put_nowait({"type": "done", "ai_msg": "断连前断连后"})

        self._run_reader("t1", queue)

        buf = state_mod.read_buffer_since("t1", -1)
        texts = [e["event"].get("text") for e in buf["events"]]
        assert "断连前" in texts, f"断连前内容丢失：{texts}"
        assert "断连后" in texts, f"断连后内容丢失：{texts}"
        idxs = [e["index"] for e in buf["events"]]
        assert idxs == sorted(idxs) and len(set(idxs)) == len(idxs), f"序号异常：{idxs}"


# ════════════════════════════════════════════════════════════
# 3. 用户提问进入快照（修复点 2）
# ════════════════════════════════════════════════════════════


def _handler_source(func_name: str) -> str:
    """按函数名截取 route_handlers 中该函数的源码（静态契约检查）。"""
    import ast

    import tea_agent.server.route_handlers as rh

    with open(rh.__file__, encoding="utf-8") as f:
        src = f.read()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func_name:
            return ast.get_source_segment(src, node) or ""
    raise AssertionError(f"{func_name} not found")


class TestUserMessageRecorded:
    def test_chat_handler_records_user_message(self):
        """发起对话时必须把用户提问记为快照事件（否则切回看不到提问）。"""
        body = _handler_source("handle_web_chat")
        assert "user_message" in body, "handle_web_chat 未记录用户提问事件"
        assert "_snapshot.record_event" in body, "未写入快照"

    def test_recorded_before_thread_starts(self):
        """必须在启动后台线程之前记录 —— 否则极短回合可能先落库、事件缺失。"""
        body = _handler_source("handle_web_chat")
        i_rec = body.index("user_message")
        i_thread = body.index("threading.Thread")
        assert i_rec < i_thread, "记录用户提问应在启动流式线程之前"

    def test_user_message_event_roundtrip(self, db, state_mod):
        """事件内容可原样读出（含图片字段），供前端渲染。"""
        ts.begin_turn("t1")
        ts.record_event(
            "t1",
            {"type": "user_message", "text": "看这张图", "images": ["img:3"]},
            0, force=True,
        )
        snap = ts.read_snapshot("t1")
        ev = snap["events"][0]["event"]
        assert ev["type"] == "user_message"
        assert ev["text"] == "看这张图"
        assert ev["images"] == ["img:3"]

    def test_user_message_not_counted_as_partial_text(self, db):
        """提问不得计入 partial_text —— 那是「助手正文」的累积字段。"""
        ts.begin_turn("t1")
        ts.record_event("t1", {"type": "user_message", "text": "提问内容"}, 0, force=True)
        ts.record_event("t1", {"type": "token", "text": "回答内容"}, 1, force=True)
        snap = ts.read_snapshot("t1")
        assert snap["partial_text"] == "回答内容"


# ════════════════════════════════════════════════════════════
# 4. 前端渲染契约（静态检查）
# ════════════════════════════════════════════════════════════


class TestPinnedUserMessageSurvivesWindow:
    """长回合：事件数远超窗口上限时，开头的 user_message 不得被挤出。

    实测（真实会话）：一轮 1296 个事件、窗口上限 300，index 0 的 user_message
    被淘汰 —— 于是「回合进行中切走再切回」仍看不到自己的提问，
    等于修复只对短回合有效。
    """

    def test_user_message_pinned_when_overflowing(self, db):
        ts.begin_turn("t1")
        ts.record_event("t1", {"type": "user_message", "text": "进行中的问题"},
                        0, force=True)
        for i in range(1, 11):
            ts.record_event("t1", {"type": "think", "text": str(i)}, i,
                            force=True, max_events=3)

        events = ts.read_snapshot("t1")["events"]
        types = [e["event"]["type"] for e in events]
        assert types[0] == "user_message", f"提问被挤出窗口：{types}"
        assert events[0]["event"]["text"] == "进行中的问题"
        # 尾部仍受窗口约束（保头只额外保留被淘汰区里的钉住事件）
        assert [e["index"] for e in events] == [0, 8, 9, 10], \
            f"窗口约束被破坏：{[e['index'] for e in events]}"

    def test_regular_events_still_bounded(self, db):
        """非钉住事件照旧按窗口淘汰（不得因保头而全量留存）。"""
        ts.begin_turn("t1")
        for i in range(10):
            ts.record_event("t1", {"type": "content", "text": str(i)}, i,
                            force=True, max_events=3)
        assert [e["index"] for e in ts.read_snapshot("t1")["events"]] == [7, 8, 9]

    def test_no_duplicate_when_pinned_in_tail(self, db):
        """钉住事件若本就在尾部窗口内，不得被重复追加。"""
        ts.begin_turn("t1")
        ts.record_event("t1", {"type": "user_message", "text": "问题"}, 0, force=True)
        ts.record_event("t1", {"type": "token", "text": "答"}, 1, force=True)

        events = ts.read_snapshot("t1")["events"]
        idxs = [e["index"] for e in events]
        assert idxs == [0, 1], f"重复或错序：{idxs}"
        assert len(set(idxs)) == len(idxs)

    def test_visible_after_switch_back_long_turn(self, db, state_mod):
        """端到端语义：长回合中切回，提问 + 已产出内容都能拿到。"""
        from tea_agent.server._compat import _seed_buffer_from_snapshot

        ts.begin_turn("t1")
        ts.record_event("t1", {"type": "user_message", "text": "进行中的问题",
                               "images": ["img:7"]}, 0, force=True)
        for i in range(1, 21):
            ts.record_event("t1", {"type": "token", "text": f"字{i}"}, i,
                            force=True, max_events=5)

        state_mod.create_background_buffer("t1")
        _seed_buffer_from_snapshot("t1")
        got = state_mod.read_buffer_since("t1", -1)["events"]
        kinds = [e["event"]["type"] for e in got]

        assert kinds[0] == "user_message", f"切回后看不到提问：{kinds}"
        assert got[0]["event"]["images"] == ["img:7"], "图片引用丢失"
        assert kinds.count("token") >= 1, "已产出内容丢失"
        assert got[-1]["event"]["text"] == "字20", "尾部内容丢失"


class TestFrontendContract:
    @staticmethod
    def _app_js() -> str:
        import tea_agent.server.route_handlers as rh

        p = os.path.join(os.path.dirname(rh.__file__), "static", "app.js")
        with open(p, encoding="utf-8") as f:
            return f.read()

    def test_render_buffer_event_handles_user_message(self):
        """缓冲区渲染必须认识 user_message，否则事件到了也不显示。"""
        src = self._app_js()
        assert "case 'user_message'" in src, "前端未处理 user_message 事件"

    def test_user_message_case_dedups(self):
        """去重：切回瞬间若回合恰好落库，历史已有同一提问，不得渲染两条。"""
        src = self._app_js()
        i = src.index("case 'user_message'")
        body = src[i:i + 900]
        assert "break" in body
        assert ".msg.user" in body, "未做重复提问检测"

    def test_image_refs_mapped_for_buffer_events(self):
        """事件里的 img:<id> 引用要映射到回读路由。"""
        src = self._app_js()
        assert "function _mapImageRefs" in src
        assert "/api/image/" in src
