"""
打断知识闭环 M1 测试 — 内存锚点记录 + corrected 降级注入。

覆盖:
- _record_interruption_anchor（tool_loop_runner 模块级函数）
- OnlineToolSession._inject_interruption_knowledge（注入 + 幂等 + 容错）
- reset_session_state 不清除锚点（保证 chat_stream 入口注入可靠）
- chat_stream 入口集成（pipeline mock）
"""

from unittest.mock import MagicMock

import pytest

from tea_agent.onlinesession import OnlineToolSession
from tea_agent.session.tool_loop_runner import _record_interruption_anchor


class TestRecordInterruptionAnchor:
    """_record_interruption_anchor: 打断锚点内存记录"""

    def test_records_full_anchor(self):
        session = MagicMock()
        session._last_interruption = None
        _record_interruption_anchor(
            session, iterations=3, last_tool_names=["toolkit_exec", "toolkit_file"],
            full_reply="partial reply text",
        )
        ev = session._last_interruption
        assert ev is not None
        assert ev["iteration"] == 3
        assert ev["tool_name"] == "toolkit_exec,toolkit_file"
        assert ev["partial_reply"] == "partial reply text"
        assert ev["phase"] == "tool_loop"
        assert ev["status"] == "pending"
        assert "timestamp" in ev

    def test_truncates_long_partial_reply(self):
        session = MagicMock()
        session._last_interruption = None
        _record_interruption_anchor(session, 1, [], "x" * 5000)
        assert len(session._last_interruption["partial_reply"]) == 2000

    def test_no_tool_names_is_none(self):
        session = MagicMock()
        session._last_interruption = None
        _record_interruption_anchor(session, 0, [], "")
        assert session._last_interruption["tool_name"] is None

    def test_exception_safe_on_plain_object(self):
        """普通 object 不允许属性赋值 → 函数应静默容错，不抛异常"""
        session = object()
        _record_interruption_anchor(session, 1, ["t"], "x")  # 不应抛异常


class TestInjectInterruptionKnowledge:
    """OnlineToolSession._inject_interruption_knowledge"""

    @pytest.fixture(autouse=True)
    def _no_embedding(self, monkeypatch):
        """M1 测试确定性：模拟 embedding 不可用 → 降级 corrected"""
        monkeypatch.setattr(
            "tea_agent.embedding_util.get_embedding_engine", lambda: None
        )

    def _make_session(self, **kwargs):
        mock_tk = MagicMock()
        mock_tk.meta_map = {}
        defaults = {
            "toolkit": mock_tk, "api_key": "sk-test",
            "api_url": "https://api.test.com/v1",
            "model": "test-model", "enable_thinking": False,
            "storage": None, "no_stream_chunk": True,
        }
        defaults.update(kwargs)
        return OnlineToolSession(**defaults)

    def test_injects_corrected_when_anchor_exists(self):
        sess = self._make_session()
        sess._last_interruption = {
            "timestamp": "2026-08-03 06:00:00",
            "iteration": 2,
            "tool_name": "toolkit_exec",
            "partial_reply": "I'll refactor the store",
            "phase": "tool_loop",
            "status": "pending",
        }
        ok = sess._inject_interruption_knowledge("不是这样，重新做")
        assert ok is True
        # 幂等：注入后清除锚点
        assert sess._last_interruption is None
        # system 消息插入位置1（初始 system 之后）
        assert len(sess.context.messages) >= 2
        sys_msg = sess.context.messages[1]
        assert sys_msg["role"] == "system"
        content = sys_msg["content"]
        assert "toolkit_exec" in content       # 工具名
        assert "第 2 轮" in content            # 迭代轮次
        assert "不是这样" in content           # 用户后续指令
        sess.close()

    def test_no_injection_without_anchor(self):
        sess = self._make_session()
        sess._last_interruption = None
        ok = sess._inject_interruption_knowledge("hello")
        assert ok is False
        assert len(sess.context.messages) == 1  # 仅初始 system
        sess.close()

    def test_followup_truncated_to_300(self):
        sess = self._make_session()
        sess._last_interruption = {"iteration": 1, "tool_name": "t", "partial_reply": "p"}
        ok = sess._inject_interruption_knowledge("长指令" * 200)
        assert ok is True
        # 300 字符截断：恰好 100 个"长指令"，再多一个就不应出现
        assert "长指令" * 100 in sess.context.messages[1]["content"]
        assert "长指令" * 101 not in sess.context.messages[1]["content"]
        sess.close()

    def test_reset_session_state_keeps_anchor(self):
        """关键：reset_session_state 不清除锚点，保证 chat_stream 入口注入可靠"""
        sess = self._make_session()
        anchor = {"iteration": 1, "tool_name": "toolkit_exec"}
        sess._last_interruption = dict(anchor)
        sess.reset_session_state()
        assert sess._last_interruption == anchor
        sess.close()

    def test_chat_stream_entry_injects(self):
        """集成：chat_stream 入口在 reset 后自动注入 corrected 提示"""
        sess = self._make_session()
        sess._last_interruption = {
            "iteration": 1, "tool_name": "toolkit_exec",
            "partial_reply": "old direction", "phase": "tool_loop",
        }
        # mock pipeline 与依赖，跳过真实 API 调用
        mock_pipeline = MagicMock()
        mock_pipeline.execute.return_value = {
            "full_reply": "ok", "used_tools": False, "iterations": 1,
        }
        sess.pipeline = mock_pipeline
        sess.reflection_manager = None
        # mock _auto_detect_mode / _analyze_intent / _build_tools
        sess._auto_detect_mode = MagicMock()
        sess._analyze_intent = MagicMock(return_value={})
        sess._build_tools = MagicMock()

        cb = MagicMock()
        reply, used = sess.chat_stream("请按我说的重新做", cb)
        assert reply == "ok"
        assert used is False
        # 注入已发生：位置1是打断知识 system 消息
        sys_msg = sess.context.messages[1]
        assert sys_msg["role"] == "system"
        assert "toolkit_exec" in sys_msg["content"]
        assert "请按我说的重新做" in sys_msg["content"]
        # 锚点已消费
        assert sess._last_interruption is None
        sess.close()


# ════════════════════════════════════════════════════════════
# M2: 三分类 + 事件持久化
# ════════════════════════════════════════════════════════════

import os
import tempfile

import pytest

from tea_agent.onlinesession import (
    INTERRUPT_SIMILARITY_THRESHOLD,
    classify_interruption,
)
from tea_agent.store._interruptions import InterruptionStore


class FakeEmbeddingEngine:
    """可控相似度的假 embedding 引擎。"""

    def __init__(self, sim: float = 0.9):
        self._sim = sim
        self.calls = 0

    def embed(self, text: str) -> list:
        self.calls += 1
        return [1.0, 0.0]

    def cosine_similarity(self, a: list, b: list) -> float:
        return self._sim


class TestClassifyInterruption:
    """classify_interruption: 三分类信号判定"""

    def test_silent_when_no_message(self):
        assert classify_interruption({"partial_reply": "x"}, "") == ("silent", None)
        assert classify_interruption({"partial_reply": "x"}, "   ") == ("silent", None)

    def test_fallback_corrected_without_engine(self):
        """无 embedding → 降级 corrected（宁缺毋滥）"""
        cls, sim = classify_interruption({"partial_reply": "x"}, "继续")
        assert cls == "corrected"
        assert sim is None

    def test_fallback_corrected_without_partial(self):
        cls, sim = classify_interruption({}, "继续", FakeEmbeddingEngine())
        assert cls == "corrected"

    def test_corrected_when_high_similarity(self):
        cls, sim = classify_interruption(
            {"partial_reply": "重构存储层"}, "继续重构存储层", FakeEmbeddingEngine(0.92)
        )
        assert cls == "corrected"
        assert sim == pytest.approx(0.92)

    def test_abandoned_when_low_similarity(self):
        cls, sim = classify_interruption(
            {"partial_reply": "重构存储层"}, "今天天气怎么样", FakeEmbeddingEngine(0.3)
        )
        assert cls == "abandoned"
        assert sim == pytest.approx(0.3)

    def test_threshold_boundary(self):
        """边界：恰好等于阈值 → corrected"""
        cls, _ = classify_interruption(
            {"partial_reply": "x"}, "y", FakeEmbeddingEngine(INTERRUPT_SIMILARITY_THRESHOLD)
        )
        assert cls == "corrected"

    def test_embedding_exception_falls_back(self, monkeypatch):
        class BoomEngine:
            def embed(self, text):
                raise RuntimeError("api down")

        cls, sim = classify_interruption(
            {"partial_reply": "x"}, "继续", BoomEngine()
        )
        assert cls == "corrected"  # 异常降级


class TestInterruptionStore:
    """InterruptionStore: 事件表 CRUD + 统计"""

    def _make_store(self, tmp_path):
        db = os.path.join(tmp_path, "chat.db")
        return InterruptionStore(db), db

    def test_insert_and_query(self, tmp_path):
        store, _ = self._make_store(tmp_path)
        # 确保表存在（模拟 init_tables 已执行——用完整 Storage 更稳）
        from tea_agent.store import Storage

        st = Storage(db_path=os.path.join(tmp_path, "chat.db"))
        st.close()
        store = InterruptionStore(os.path.join(tmp_path, "chat.db"))
        ev = {
            "topic_id": "t1", "timestamp": "2026-08-03 06:00:00",
            "iteration": 2, "tool_name": "toolkit_exec",
            "partial_reply": "partial", "phase": "tool_loop",
        }
        eid = store.insert_interruption_event(ev)
        assert eid != ""
        rows = store.query_interruptions(topic_id="t1")
        assert len(rows) == 1
        assert rows[0]["tool_name"] == "toolkit_exec"
        assert rows[0]["status"] == "pending"

    def test_update_classification(self, tmp_path):
        from tea_agent.store import Storage

        db = os.path.join(tmp_path, "chat.db")
        st = Storage(db_path=db)
        st.close()
        store = InterruptionStore(db)
        eid = store.insert_interruption_event({"topic_id": "t1", "tool_name": "toolkit_file"})
        ok = store.update_interruption_classification(
            eid, "abandoned", 0.35, "换个话题", "2026-08-03 06:05:00"
        )
        assert ok is True
        row = store.get_interruption_event(eid)
        assert row["classification"] == "abandoned"
        assert row["similarity"] == pytest.approx(0.35)
        assert row["followup_user_msg"] == "换个话题"
        assert row["status"] == "classified"

    def test_stats_aggregation(self, tmp_path):
        from tea_agent.store import Storage

        db = os.path.join(tmp_path, "chat.db")
        st = Storage(db_path=db)
        st.close()
        store = InterruptionStore(db)
        for i in range(3):
            store.insert_interruption_event(
                {"topic_id": "t1", "tool_name": "toolkit_exec", "timestamp": f"2026-08-0{i+1} 06:00:00"}
            )
        store.insert_interruption_event(
            {"topic_id": "t1", "tool_name": "toolkit_file", "timestamp": "2026-08-04 06:00:00"}
        )
        stats = store.stats_interruptions()
        by_name = {s["tool_name"]: s for s in stats}
        assert by_name["toolkit_exec"]["count"] == 3
        assert by_name["toolkit_file"]["count"] == 1

    def test_cleanup_old_events(self, tmp_path):
        from tea_agent.store import Storage

        db = os.path.join(tmp_path, "chat.db")
        st = Storage(db_path=db)
        st.close()
        store = InterruptionStore(db)
        store.insert_interruption_event(
            {"topic_id": "t1", "tool_name": "toolkit_exec", "timestamp": "2020-01-01 00:00:00"}
        )
        store.insert_interruption_event(
            {"topic_id": "t1", "tool_name": "toolkit_file", "timestamp": "2026-08-03 00:00:00"}
        )
        deleted = store.cleanup_old_events(keep_days=30)
        assert deleted >= 1
        remaining = store.query_interruptions()
        assert all(r["tool_name"] == "toolkit_file" for r in remaining)


class TestM2Injection:
    """M2: 三分类注入 + 事件回写"""

    def _make_session(self, **kwargs):
        mock_tk = MagicMock()
        mock_tk.meta_map = {}
        defaults = {
            "toolkit": mock_tk, "api_key": "sk-test",
            "api_url": "https://api.test.com/v1",
            "model": "test-model", "enable_thinking": False,
            "storage": None, "no_stream_chunk": True,
        }
        defaults.update(kwargs)
        return OnlineToolSession(**defaults)

    def _anchor(self, **kw):
        a = {
            "id": "ev-1", "topic_id": "t1", "iteration": 2,
            "tool_name": "toolkit_exec", "partial_reply": "重构存储层",
            "phase": "tool_loop", "status": "pending",
        }
        a.update(kw)
        return a

    def test_abandoned_injection(self, monkeypatch):
        """低相似度 → abandoned 模板注入（不回旧话题）"""
        monkeypatch.setattr(
            "tea_agent.embedding_util.get_embedding_engine",
            lambda: FakeEmbeddingEngine(0.3),
        )
        sess = self._make_session()
        sess._last_interruption = self._anchor()
        ok = sess._inject_interruption_knowledge("今天天气怎么样")
        assert ok is True
        content = sess.context.messages[1]["content"]
        assert "弃用" in content
        assert "不要主动回到" in content
        assert "重构存储层" not in content  # 不引用旧方向细节
        sess.close()

    def test_corrected_injection_with_high_similarity(self, monkeypatch):
        monkeypatch.setattr(
            "tea_agent.embedding_util.get_embedding_engine",
            lambda: FakeEmbeddingEngine(0.91),
        )
        sess = self._make_session()
        sess._last_interruption = self._anchor()
        ok = sess._inject_interruption_knowledge("继续重构存储层，但换种方式")
        assert ok is True
        content = sess.context.messages[1]["content"]
        assert "重新规划" in content
        assert "toolkit_exec" in content
        sess.close()

    def test_persist_classification_called(self, monkeypatch):
        """分类结果回写事件表（storage 有值且锚点有 id）"""
        monkeypatch.setattr(
            "tea_agent.embedding_util.get_embedding_engine",
            lambda: FakeEmbeddingEngine(0.91),
        )
        mock_storage = MagicMock()
        sess = self._make_session(storage=mock_storage)
        sess._last_interruption = self._anchor()
        ok = sess._inject_interruption_knowledge("继续重构")
        assert ok is True
        mock_storage.update_interruption_classification.assert_called_once()
        args = mock_storage.update_interruption_classification.call_args[0]
        assert args[0] == "ev-1"
        assert args[1] == "corrected"
        assert args[2] == pytest.approx(0.91)
        sess.close()

    def test_silent_no_injection_but_persisted(self, monkeypatch):
        """silent（无消息）→ 不注入，但事件仍回写为 silent"""
        mock_storage = MagicMock()
        sess = self._make_session(storage=mock_storage)
        sess._last_interruption = self._anchor()
        ok = sess._inject_interruption_knowledge("")
        assert ok is False
        assert len(sess.context.messages) == 1  # 无注入
        assert sess._last_interruption is None  # 锚点已消费
        mock_storage.update_interruption_classification.assert_called_once()
        assert mock_storage.update_interruption_classification.call_args[0][1] == "silent"
        sess.close()

    def test_record_anchor_persists_event(self):
        """_record_interruption_anchor：有 storage 时写入事件表 + 生成 id"""
        mock_storage = MagicMock()
        session = MagicMock()
        session.storage = mock_storage
        session.current_topic_id = "t1"
        session._last_interruption = None
        _record_interruption_anchor(session, 2, ["toolkit_exec"], "partial")
        ev = session._last_interruption
        assert ev["id"]
        assert ev["topic_id"] == "t1"
        mock_storage.insert_interruption_event.assert_called_once()
        inserted = mock_storage.insert_interruption_event.call_args[0][0]
        assert inserted["id"] == ev["id"]


# ════════════════════════════════════════════════════════════
# M3: 后台打断模式分析（agent_background.py）
# ════════════════════════════════════════════════════════════

from tea_agent.agent_background import analyze_interruptions
from tea_agent.store import Storage


@pytest.fixture()
def inter_storage():
    """临时 DB 的 Storage，含 interruption_events 表。"""
    import contextlib
    import time as _time

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    st = Storage(path)
    yield st
    st.close()
    # Windows 句柄释放延迟：重试删除，失败则留给 OS 清理
    for _ in range(3):
        with contextlib.suppress(OSError):
            os.remove(path)
            break
        _time.sleep(0.2)


def _insert_event(st, tool_name, status="classified", topic="t1"):
    eid = st.insert_interruption_event({
        "topic_id": topic,
        "timestamp": "2026-08-01 10:00:00",
        "iteration": 2,
        "tool_name": tool_name,
        "partial_reply": "doing something",
        "phase": "tool_loop",
    })
    if status == "classified":
        st.update_interruption_classification(
            eid, "abandoned", 0.2, "new topic", "2026-08-01 10:01:00",
        )
    return eid


class TestAnalyzeInterruptions:
    """analyze_interruptions: 聚合 + 沉淀 + 幂等 + 阈值"""

    def test_sediments_preference_memory_above_threshold(self, inter_storage):
        _insert_event(inter_storage, "toolkit_exec")
        _insert_event(inter_storage, "toolkit_exec")
        written = analyze_interruptions(storage=inter_storage, days=7, min_count=2)
        assert len(written) == 1
        assert "toolkit_exec" in written[0]
        # 记忆已入库
        mems = inter_storage.memories.search_memories(
            category="preference", tags=["interruption"], limit=10
        )
        assert any("toolkit_exec" in m["content"] for m in mems)

    def test_below_threshold_not_sedimented(self, inter_storage):
        _insert_event(inter_storage, "toolkit_file")
        written = analyze_interruptions(storage=inter_storage, days=7, min_count=2)
        assert written == []

    def test_idempotent_no_duplicate(self, inter_storage):
        _insert_event(inter_storage, "toolkit_exec")
        _insert_event(inter_storage, "toolkit_exec")
        analyze_interruptions(storage=inter_storage, days=7, min_count=2)
        second = analyze_interruptions(storage=inter_storage, days=7, min_count=2)
        assert second == []  # 幂等：不重复沉淀

    def test_no_classified_events_returns_empty(self, inter_storage):
        _insert_event(inter_storage, "toolkit_exec", status="pending")
        written = analyze_interruptions(storage=inter_storage)
        assert written == []

    def test_multiple_tools_only_above_threshold(self, inter_storage):
        _insert_event(inter_storage, "toolkit_exec")
        _insert_event(inter_storage, "toolkit_exec")
        _insert_event(inter_storage, "toolkit_file")
        written = analyze_interruptions(storage=inter_storage, days=7, min_count=2)
        assert len(written) == 1
        assert "toolkit_exec" in written[0]


# ════════════════════════════════════════════════════════════
# M4: 配置项 + prompt_manager 模板 + 清理
# ════════════════════════════════════════════════════════════

from tea_agent.config import get_config
from tea_agent.prompt_manager import (
    INTERRUPT_ABANDONED_TMPL,
    INTERRUPT_CORRECTED_TMPL,
    build_interruption_system_msg,
)
from tea_agent.session.tool_loop_runner import _record_interruption_anchor


class TestInterruptionConfig:
    """interruption.* 配置节"""

    def test_default_values_exist(self):
        cfg = get_config().interruption
        assert cfg["enabled"] is True
        assert cfg["similarity_threshold"] == 0.6
        assert cfg["partial_reply_max"] == 2000
        assert cfg["persist_events"] is True
        assert cfg["analyze_interval_h"] == 1.0
        assert cfg["keep_days"] == 30

    def test_get_interruption_method(self):
        cfg = get_config()
        assert cfg.get_interruption("enabled") is True
        assert cfg.get_interruption("similarity_threshold") == 0.6
        assert cfg.get_interruption("not_exist", "fallback") == "fallback"


class TestPromptManagerTemplates:
    """模板迁移 + build_interruption_system_msg"""

    def test_corrected_template(self):
        msg = build_interruption_system_msg("corrected", tool_name="toolkit_exec", iteration=3, followup="重新做")
        assert "toolkit_exec" in msg
        assert "3" in msg
        assert "重新做" in msg

    def test_abandoned_template(self):
        msg = build_interruption_system_msg("abandoned")
        assert "弃用" in msg
        assert "不要主动回到" in msg

    def test_constants_migrated_to_prompt_manager(self):
        # onlinesession 引用同一份模板（不再各自维护）
        from tea_agent.onlinesession import OnlineToolSession

        assert OnlineToolSession._INTERRUPT_CORRECTED_TMPL is INTERRUPT_CORRECTED_TMPL
        assert OnlineToolSession._INTERRUPT_ABANDONED_TMPL is INTERRUPT_ABANDONED_TMPL


class TestM4InjectionConfig:
    """M4: 注入读配置（enabled / threshold）"""

    def _make_session(self, **kwargs):
        mock_tk = MagicMock()
        mock_tk.meta_map = {}
        defaults = {
            "toolkit": mock_tk, "api_key": "sk-test", "api_url": "https://api.test.com/v1",
            "model": "test-model", "enable_thinking": False, "storage": None,
            "no_stream_chunk": True,
        }
        defaults.update(kwargs)
        return OnlineToolSession(**defaults)

    @pytest.fixture(autouse=True)
    def _restore_config(self, monkeypatch):
        cfg = get_config()
        monkeypatch.setattr(cfg, "interruption", dict(cfg.interruption))

    def test_disabled_skips_injection(self, monkeypatch):
        monkeypatch.setattr("tea_agent.embedding_util.get_embedding_engine", lambda: None)
        cfg = get_config()
        cfg.interruption["enabled"] = False
        sess = self._make_session()
        sess._last_interruption = {"iteration": 1, "tool_name": "toolkit_exec", "partial_reply": "abc"}
        ok = sess._inject_interruption_knowledge("继续")
        assert ok is False
        assert sess._last_interruption is None  # 总开关关闭 → 锚点清除
        assert len(sess.context.messages) == 1  # 未注入
        sess.close()

    def test_threshold_from_config(self, monkeypatch):
        # threshold 0.9 → 相似 0.8 判 abandoned（默认 0.6 会判 corrected）
        monkeypatch.setattr(
            "tea_agent.embedding_util.get_embedding_engine",
            lambda: FakeEmbeddingEngine(0.8),
        )
        cfg = get_config()
        cfg.interruption["similarity_threshold"] = 0.9
        sess = self._make_session()
        sess._last_interruption = {"iteration": 1, "tool_name": "toolkit_exec", "partial_reply": "重构存储层"}
        ok = sess._inject_interruption_knowledge("重构存储层方案")
        assert ok is True
        assert "弃用" in sess.context.messages[1]["content"]  # abandoned 模板
        sess.close()


class TestM4AnchorConfig:
    """M4: 锚点记录读配置（partial_reply_max / persist_events）"""

    @pytest.fixture(autouse=True)
    def _restore_config(self, monkeypatch):
        cfg = get_config()
        monkeypatch.setattr(cfg, "interruption", dict(cfg.interruption))

    def test_partial_reply_max_from_config(self):
        cfg = get_config()
        cfg.interruption["partial_reply_max"] = 100
        session = MagicMock()
        session._last_interruption = None
        session.storage = None
        _record_interruption_anchor(session, 1, [], "x" * 500)
        assert len(session._last_interruption["partial_reply"]) == 100

    def test_persist_events_disabled_skips_db(self):
        cfg = get_config()
        cfg.interruption["persist_events"] = False
        session = MagicMock()
        session._last_interruption = None
        session.storage = MagicMock()
        session.storage.insert_interruption_event = MagicMock()
        _record_interruption_anchor(session, 1, [], "abc")
        assert session._last_interruption is not None  # 内存锚点仍在
        session.storage.insert_interruption_event.assert_not_called()  # 但未落库

    def test_persist_events_enabled_writes_db(self):
        cfg = get_config()
        cfg.interruption["persist_events"] = True
        session = MagicMock()
        session._last_interruption = None
        session.storage = MagicMock()
        _record_interruption_anchor(session, 1, ["toolkit_exec"], "abc")
        session.storage.insert_interruption_event.assert_called_once()
        args = session.storage.insert_interruption_event.call_args[0][0]
        assert args["status"] == "pending"
