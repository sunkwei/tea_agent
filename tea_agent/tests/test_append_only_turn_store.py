"""回合级 append-only 存储回归测试。

背景（实测真实库 79.45 MB）：
  1. **归属断裂**：conversations 行由回合结束的 save_msg 创建，而工具调用发生在
     回合**进行中** —— 那时没有 conversation_id 可挂。实测 session_events 中
     tool/call 的 conversation_id **100% 为 NULL**（404/404），轮次级审计失效。
  2. **冗余存储**：conversations.rounds_json 与 agent_rounds 存同一份内容，
     合计 30.52 MB / 占库 38.4%（单轮最大 8.79 MB）。
  3. **删除不可审计**：delete_topic 级联硬删（conversations/agent_rounds/images），
     删完行数归零，无法回溯「用户删过什么」；且漏掉 pending 图片。

修复方向（用户主张）：db 为唯一存储点 + append only + 删除即标记。
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest


@pytest.fixture()
def storage(tmp_path):
    from tea_agent.store import Storage

    s = Storage(db_path=str(tmp_path / "chat.db"))
    yield s
    s.close()


def _png() -> bytes:
    from PIL import Image
    import io

    b = io.BytesIO()
    Image.new("RGB", (30, 20), (10, 90, 200)).save(b, format="PNG")
    return b.getvalue()


# ════════════════════════════════════════════════════════════
# 1. 回合生命周期
# ════════════════════════════════════════════════════════════


class TestTurnLifecycle:
    def test_create_turn_makes_pending_row(self, storage):
        """回合开始即建行（pending），使回合中事件有 id 可挂。"""
        tid = storage.create_topic("t")
        cid = storage.create_turn(tid, {"text": "问题"})

        row = storage.conn.execute(
            "SELECT status, ai_msg, user_msg FROM conversations WHERE id = ?", (cid,)
        ).fetchone()
        assert row is not None, "create_turn 未建行"
        assert row["status"] == "pending"
        assert row["ai_msg"] == ""
        assert json.loads(row["user_msg"])["text"] == "问题"

    def test_create_turn_sets_events_with_conv_id(self, storage):
        """turn/start 与 user/message 必须带 conversation_id（可归属）。"""
        tid = storage.create_topic("t")
        cid = storage.create_turn(tid, "问题")

        evs = storage.events.query_events(tid)
        assert [e["event_type"] for e in evs] == ["turn/start", "user/message"]
        assert all(e["conversation_id"] == cid for e in evs), \
            f"事件未归属到回合：{[e['conversation_id'] for e in evs]}"

    def test_append_round_is_idempotent(self, storage):
        """同一 round_num 重复提交被跳过（重试/恢复场景）。"""
        tid = storage.create_topic("t")
        cid = storage.create_turn(tid, "q")

        assert storage.append_round(cid, 0, "assistant", "首次") is True
        assert storage.append_round(cid, 0, "assistant", "重复") is False

        rows = storage.conn.execute(
            "SELECT content FROM agent_rounds WHERE conversation_id = ?", (cid,)
        ).fetchall()
        assert [r[0] for r in rows] == ["首次"]

    def test_finalize_turn_does_not_duplicate_rounds(self, storage):
        """回合中已实时落盘的轮次，定稿时兜底补齐不得重复。"""
        tid = storage.create_topic("t")
        cid = storage.create_turn(tid, "q")
        storage.append_round(cid, 0, "assistant", "实时写入")

        storage.finalize_turn(cid, "最终回复", rounds=[
            {"role": "assistant", "content": "实时写入"},
            {"role": "tool", "content": "补写"},
        ])

        n = storage.conn.execute(
            "SELECT COUNT(*) FROM agent_rounds WHERE conversation_id = ?", (cid,)
        ).fetchone()[0]
        assert n == 2, f"轮次重复：{n}"
        row = storage.conn.execute(
            "SELECT status, ai_msg FROM conversations WHERE id = ?", (cid,)
        ).fetchone()
        assert row["status"] == "done" and row["ai_msg"] == "最终回复"

    def test_finalize_writes_terminal_events(self, storage):
        """定稿写入 assistant/message + turn/end，且带 conv_id。"""
        tid = storage.create_topic("t")
        cid = storage.create_turn(tid, "q")
        storage.finalize_turn(cid, "答")

        evs = storage.events.query_events(tid)
        types = [e["event_type"] for e in evs]
        assert "assistant/message" in types and "turn/end" in types
        tail = [e for e in evs if e["event_type"] in ("assistant/message", "turn/end")]
        assert all(e["conversation_id"] == cid for e in tail)


# ════════════════════════════════════════════════════════════
# 2. rounds 单一事实源（消除 30 MB 双写）
# ════════════════════════════════════════════════════════════


class TestRoundsSingleSource:
    def test_rounds_json_not_written(self, storage):
        """rounds_json 列不再写入（与 agent_rounds 重复存储，实测占库 38.4%）。"""
        tid = storage.create_topic("t")
        cid = storage.create_turn(tid, "q")
        storage.update_msg_rounds(cid, "答", True, rounds=[
            {"role": "assistant", "content": "a"},
            {"role": "tool", "content": "b"},
        ])

        v = storage.conn.execute(
            "SELECT rounds_json FROM conversations WHERE id = ?", (cid,)
        ).fetchone()[0]
        assert v is None, f"rounds_json 仍在写入（冗余）：{str(v)[:60]}"

    def test_get_conversations_derives_rounds(self, storage):
        """get_conversations 的 rounds_json_parsed 从 agent_rounds 派生。"""
        tid = storage.create_topic("t")
        cid = storage.create_turn(tid, "q")
        storage.append_round(cid, 0, "assistant", "调用工具",
                             tool_calls=[{"id": "c1", "function": {"name": "tk"}}])
        storage.append_round(cid, 1, "tool", "结果", tool_call_id="c1")
        storage.finalize_turn(cid, "答")

        conv = storage.get_conversations(tid, limit=0, include_rounds=True)[0]
        rounds = conv["rounds_json_parsed"]
        assert [r["role"] for r in rounds] == ["assistant", "tool"]
        assert rounds[0]["tool_calls"] == [{"id": "c1", "function": {"name": "tk"}}]
        assert rounds[1]["tool_call_id"] == "c1"

    def test_reasoning_content_in_own_column(self, storage):
        """RC 独立成列，不再被拼进 content 的 '[思考] ' 前缀。"""
        tid = storage.create_topic("t")
        cid = storage.create_turn(tid, "q")
        storage.append_round(cid, 0, "assistant", "正文", reasoning_content="思考内容")

        row = storage.conn.execute(
            "SELECT content, reasoning_content FROM agent_rounds WHERE conversation_id = ?",
            (cid,)).fetchone()
        assert row["content"] == "正文", f"content 被污染：{row['content']!r}"
        assert row["reasoning_content"] == "思考内容"
        # 派生视图能还原为结构化 rounds（DeepSeek 要求 RC 原样回传）
        assert storage.get_rounds(cid)[0]["reasoning_content"] == "思考内容"

    def test_derived_rounds_feed_load_history_shape(self, storage):
        """派生结果与旧 rounds_json 结构兼容（可直接喂 load_history）。"""
        tid = storage.create_topic("t")
        cid = storage.create_turn(tid, "q")
        storage.append_round(cid, 0, "assistant", "x",
                             tool_calls=[{"id": "c1"}], reasoning_content="rc")

        r = storage.get_rounds(cid)[0]
        assert set(r) <= {"role", "content", "tool_calls", "tool_call_id", "reasoning_content"}
        assert r["role"] == "assistant" and r["tool_calls"] == [{"id": "c1"}]


# ════════════════════════════════════════════════════════════
# 3. 软删除（append-only：删除是标记，不是物理删除）
# ════════════════════════════════════════════════════════════


class TestSoftDelete:
    def _seed(self, storage):
        tid = storage.create_topic("待删")
        cid = storage.create_turn(tid, "q")
        storage.append_round(cid, 0, "assistant", "a")
        img = storage.add_pending_image(_png(), "image/png")
        storage.finalize_turn(cid, "答")
        return tid, cid, img

    def test_rows_are_kept_after_delete(self, storage):
        """软删后行仍在库中（可审计/可恢复），只是打了标记。"""
        tid, cid, _img = self._seed(storage)
        assert storage.soft_delete_topic(tid) is True

        c = storage.conn.cursor()
        assert c.execute("SELECT COUNT(*) FROM topics").fetchone()[0] == 1
        assert c.execute("SELECT COUNT(*) FROM conversations").fetchone()[0] == 1
        assert c.execute("SELECT COUNT(*) FROM agent_rounds").fetchone()[0] == 1
        c.close()
        # 标记已写入
        assert storage.conn.execute(
            "SELECT deleted_at FROM conversations WHERE id = ?", (cid,)).fetchone()[0]

    def test_public_delete_topic_keeps_rows(self, storage):
        """对外 delete_topic 也必须是标记删除 —— 不能物理清空。

        回归锚点：旧实现级联硬删 conversations/agent_rounds/images/topics，
        删完行数归零，无法回溯「用户删过什么」。此用例走**公开 API**
        （server/UI 实际调用的入口），而非直接调 soft_delete_topic ——
        后者无法判别「delete_topic 是否被改回硬删」。
        """
        tid, cid, _img = self._seed(storage)
        assert storage.delete_topic(tid) is True

        c = storage.conn.cursor()
        assert c.execute("SELECT COUNT(*) FROM conversations").fetchone()[0] == 1, \
            "delete_topic 物理删除了 conversations（应为标记删除）"
        assert c.execute("SELECT COUNT(*) FROM agent_rounds").fetchone()[0] == 1, \
            "delete_topic 物理删除了 agent_rounds"
        assert c.execute("SELECT COUNT(*) FROM topics").fetchone()[0] == 1, \
            "delete_topic 物理删除了 topics"
        c.close()
        # 读路径不可见（语义上已删除）
        assert storage.get_topic(tid) is None
        assert storage.get_conversations(tid, limit=0) == []

    def test_session_events_untouched(self, storage):
        """审计日志不受删除影响 —— 删除事实本身也要留痕。"""
        tid, _cid, _img = self._seed(storage)
        before = storage.events.stats(tid)["total"]
        storage.soft_delete_topic(tid)
        assert storage.events.stats(tid)["total"] == before

    def test_soft_delete_is_idempotent(self, storage):
        tid, _cid, _img = self._seed(storage)
        assert storage.soft_delete_topic(tid) is True
        assert storage.soft_delete_topic(tid) is False

    def test_unknown_topic_returns_false(self, storage):
        assert storage.soft_delete_topic("nope") is False


class TestReadPathFiltersDeleted:
    def test_deleted_topic_invisible(self, storage):
        tid = storage.create_topic("t")
        cid = storage.create_turn(tid, "q")
        storage.finalize_turn(cid, "a")
        assert len(storage.list_topics()) == 1

        storage.soft_delete_topic(tid)
        assert storage.get_topic(tid) is None
        assert storage.list_topics() == []
        assert storage.get_conversations(tid, limit=0) == []
        assert storage.get_rounds(cid) == []


# ════════════════════════════════════════════════════════════
# 4. 工具轮实时落盘（崩溃不丢）
# ════════════════════════════════════════════════════════════


class _FakeCtx:
    def __init__(self, storage, conv_id):
        self.storage = storage
        self.conversation_id = conv_id
        self.topic_id = "t"
        self._rounds_collector = []
        self.supports_reasoning = True
        self.messages = []


class TestToolComponentPersists:
    def test_collect_persists_immediately(self, storage):
        """collect_* 应实时写库 —— 崩溃/强杀不丢已发生的工具轮。"""
        from tea_agent.session.components.tool import ToolComponent

        tid = storage.create_topic("t")
        cid = storage.create_turn(tid, "q")
        comp = ToolComponent.__new__(ToolComponent)
        comp.ctx = _FakeCtx(storage, cid)

        comp.collect_tool_call_round("c1", "工具结果")

        rows = storage.get_rounds(cid)
        assert len(rows) == 1, f"未实时落盘：{rows}"
        assert rows[0]["role"] == "tool" and rows[0]["tool_call_id"] == "c1"

    def test_no_conv_id_is_silent(self, storage):
        """无 conversation_id（非 Web 路径）时静默跳过，不抛错。"""
        from tea_agent.session.components.tool import ToolComponent

        comp = ToolComponent.__new__(ToolComponent)
        comp.ctx = _FakeCtx(storage, "")
        comp.collect_tool_call_round("c1", "结果")   # 不应抛异常
        assert comp.ctx._rounds_collector, "collector 仍应记录（内存）"


# ════════════════════════════════════════════════════════════
# 5. 接线（判别性：还原旧实现必须变红）
# ════════════════════════════════════════════════════════════


def _fn_source(path: str, func_name: str) -> str:
    """按函数名截取源码（静态契约检查用）。"""
    import ast

    with open(path, encoding="utf-8") as f:
        src = f.read()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func_name:
            return ast.get_source_segment(src, node) or ""
    raise AssertionError(f"{func_name} not found in {path}")


class TestHandlerWiring:
    def test_chat_handler_creates_turn_before_thread(self):
        """回合开始即建行 —— 否则工具/增量事件无归属（实测 100% NULL）。"""
        import tea_agent.server.route_handlers as rh

        body = _fn_source(rh.__file__, "handle_web_chat")
        assert "storage.create_turn(" in body, "handler 未在回合开始建行"
        # 必须在快照记录之前（先有 id，事件才能归属）
        assert body.index("storage.create_turn(") < body.index('"user_message"'), \
            "建行晚于快照记录 → 事件仍无归属"

    def test_stream_handler_creates_turn(self):
        """API 流式路径同样在回合开始建行。"""
        from tea_agent.server.modules import agent_module as am

        body = _fn_source(am.__file__, "_run_stream")
        assert "storage.create_turn(" in body, "API 流式路径未建行"

    def test_conversation_id_written_to_context(self):
        """建行后必须同步到 ctx，工具组件才拿得到。"""
        import tea_agent.server.route_handlers as rh

        body = _fn_source(rh.__file__, "handle_web_chat")
        assert "conversation_id" in body, "未把 conv_id 同步到 context"

    def test_tool_component_persists_round(self):
        """工具组件收集轮次时必须实时落盘。"""
        from tea_agent.session.components import tool as tool_mod

        body = _fn_source(tool_mod.__file__, "_collect_round")
        assert "append_round" in body, "collect 未实时落盘"

    def test_collect_round_is_module_level(self):
        """落盘辅助必须是模块级函数，替身（仅含 ctx）才能调用。

        回归锚点：曾写成 ``self._collect(entry)`` 方法 —— 鸭子类型替身
        （``ToolComponent.collect_xxx(stub, ...)``，stub 只有 ctx）会因缺少该
        方法抛 AttributeError（实测 test_reasoning_empty_rc 两用例变红）。
        """
        from tea_agent.session.components import tool as tool_mod

        assert hasattr(tool_mod, "_collect_round"), "应为模块级函数"
        stub = SimpleNamespace(ctx=SimpleNamespace(
            supports_reasoning=True, _rounds_collector=[]))
        tool_mod.ToolComponent.collect_assistant_text_round(stub, "x", "")
        assert stub.ctx._rounds_collector[0]["role"] == "assistant"


class _FakeEvents:
    """记录 append_event 调用的替身（不需要真库）。"""

    def __init__(self):
        self.calls = []

    def append_event(self, topic_id, event_type, payload, conversation_id=""):
        self.calls.append({
            "topic_id": topic_id,
            "event_type": event_type,
            "payload": payload,
            "conversation_id": conversation_id,
        })
        return len(self.calls)


def _self_ctx_attrs(path):
    """AST 精确找出 ``self.ctx`` 的**两种**误用形态（排除注释/字符串误报）。

    1. 属性访问 ``self.ctx``
    2. 字符串查找 ``getattr(self, "ctx", ...)``

    历史缺陷是第 2 种（``getattr(self, "ctx", None)``）—— 只查第 1 种会漏掉，
    护栏就成了摆设（元验证实测：只查属性访问时，缺陷实现下该用例仍绿）。
    """
    import ast

    tree = ast.parse(open(path, encoding="utf-8").read())
    hits = []
    for node in ast.walk(tree):
        # 形态 1: self.ctx
        if (isinstance(node, ast.Attribute) and node.attr == "ctx"
                and isinstance(node.value, ast.Name) and node.value.id == "self"):
            hits.append((node.lineno, "self.ctx"))
        # 形态 2: getattr(self, "ctx", ...)
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "getattr" and len(node.args) >= 2
                and isinstance(node.args[0], ast.Name) and node.args[0].id == "self"
                and isinstance(node.args[1], ast.Constant) and node.args[1].value == "ctx"):
            hits.append((node.lineno, 'getattr(self, "ctx")'))
    return hits


class TestEventAttribution:
    """事件必须归属到轮次 —— 否则轮次级审计断链。

    回归锚点（实测真实库）：某轮 ``user/message``、``tool/call``、
    ``tool/result`` 均已归属，唯独 ``assistant/chunk`` 恒为 ``conv=NULL``。
    根因：写成 ``getattr(self, "ctx", None)`` —— ``OnlineToolSession``
    **没有** ``ctx`` 属性（那是 ``SessionComponent`` 的约定，见
    ``session/context.py`` 的 ``self.ctx = context``），``getattr`` 的
    兜底把属性名写错这件事**静默吞成空串**。

    这类缺陷的特征：不抛异常、不报错、测试若只断言「事件已落盘」全绿，
    只有断言「归属正确」才判别得出来。
    """

    @staticmethod
    def _stub(conv_id="cv-1", misleading_ctx=False):
        from tea_agent.onlinesession import OnlineToolSession

        events = _FakeEvents()
        stub = SimpleNamespace(
            current_topic_id="t-1",
            storage=SimpleNamespace(events=events),
            context=SimpleNamespace(conversation_id=conv_id),
        )
        if misleading_ctx:
            # 故意放一个值不同的 ctx：实现若误用 self.ctx 会取到 WRONG
            stub.ctx = SimpleNamespace(conversation_id="WRONG")
        return OnlineToolSession, stub, events

    def test_chunk_carries_conversation_id(self):
        cls, stub, events = self._stub()
        cls._log_assistant_chunk(stub, "增量文本")
        assert events.calls, "未落盘 assistant/chunk"
        assert events.calls[0]["conversation_id"] == "cv-1", (
            "assistant/chunk 未归属到轮次（conversation_id 丢失）"
        )

    def test_chunk_uses_context_not_ctx(self):
        """钉住属性名：取 self.context，绝不取 self.ctx。"""
        cls, stub, events = self._stub(misleading_ctx=True)
        cls._log_assistant_chunk(stub, "x")
        assert events.calls[0]["conversation_id"] == "cv-1", (
            "实现用了 self.ctx（OnlineToolSession 无此属性）"
        )

    def test_chunk_reasoning_also_attributed(self):
        """仅思考链（无正文）时同样要归属。"""
        cls, stub, events = self._stub()
        cls._log_assistant_chunk(stub, "", "思考中")
        assert events.calls[0]["conversation_id"] == "cv-1"
        assert events.calls[0]["payload"].get("reasoning") == "思考中"

    def test_turn_end_marker_carries_conversation_id(self):
        """中断标记同样要归属（否则「哪一轮中断」无法定位）。"""
        cls, stub, events = self._stub()
        cls._log_turn_end_marker(stub, "interrupted")
        assert events.calls, "未落盘 turn/end"
        assert events.calls[0]["event_type"] == "turn/end"
        assert events.calls[0]["conversation_id"] == "cv-1"

    def test_no_storage_is_silent(self):
        """无 storage 时静默返回，不抛异常（旁路失败不得带崩主流程）。"""
        cls, stub, _ = self._stub()
        stub.storage = None
        stub.context = SimpleNamespace()
        cls._log_assistant_chunk(stub, "x")  # 不应抛

    def test_onlinesession_has_no_self_ctx(self):
        """静态护栏：onlinesession.py 不得出现 ``self.ctx``。

        ``OnlineToolSession`` 的属性是 ``self.context``；写成 ``self.ctx``
        只会静默取到空值，是「不报错的错」。AST 检查排除注释误报。
        """
        import tea_agent.onlinesession as m

        hits = _self_ctx_attrs(m.__file__)
        assert not hits, (
            "onlinesession.py 出现 self.ctx（行 %s）—— 应为 self.context" % hits
        )
