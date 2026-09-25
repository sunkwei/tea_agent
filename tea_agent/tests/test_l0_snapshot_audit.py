"""L0 富化系统提示词快照 — 严格审计回归测试。

背景（审计缺口）：
    发给模型的 system 消息**不是**裸 ``system_prompt``，而是
    ``build_api_messages`` → ``_build_l0_enriched_system()`` 运行时合成的
    结果（OS 信息 / AGENTS.md / context_fragments / 小模型约束）。该合成
    结果此前**从不落盘** → 历史任一回合都无法复原「它当时看到的 L0」，
    因为配置与 AGENTS.md 早已变化。这是 L0-L3 提取里唯一完全缺失的一层。

设计的三个行为契约（测试钉这些，而非实现细节）：

1. **回合起始值不可被覆盖** —— 一个回合内 ``build_api_messages`` 会被调用
   数百次（工具循环每轮一次）。快照必须是**回合开始时**那份，不能被回合
   中期的 L0（技能加载/TODO 提醒可能改变注入）覆盖，否则审计看到的是
   「回合结束时的 L0」，失去复原意义。
2. **旁路绝不改写控制流** —— 记录钩子的调用点位于 tool_loop_runner 的
   「API 失败→重试」``try`` 内。若钩子抛异常，会被误判为 API 错误而触发
   **无谓重试与错误归因**。故钩子必须可证明不抛错。
3. **「未记录」与「记录为空」可区分** —— 旧回合（功能上线前）为未记录，
   新回合可能记录了空 L0。二者语义不同，不可混为一谈。
"""

from __future__ import annotations

import pytest

from tea_agent.store._conversations import l0_content_hash


@pytest.fixture()
def storage(tmp_path):
    from tea_agent.store import Storage

    s = Storage(db_path=str(tmp_path / "chat.db"))
    yield s
    s.close()


# ════════════════════════════════════════════════════════════
# 1. 内容地址（纯函数）
# ════════════════════════════════════════════════════════════


class TestContentHash:
    def test_deterministic_and_sha256_length(self):
        """同一内容恒等，且是完整 sha256（64 字符）—— 截断会削弱完整性比对。"""
        a = l0_content_hash("系统提示词")
        b = l0_content_hash("系统提示词")
        assert a == b
        assert len(a) == 64
        assert all(ch in "0123456789abcdef" for ch in a)

    def test_empty_returns_empty(self):
        """空内容返回空串（不产生 hash）—— 用于区分「无 L0」与「有 L0」。"""
        assert l0_content_hash("") == ""
        assert l0_content_hash(None) == ""

    def test_different_content_different_hash(self):
        assert l0_content_hash("A") != l0_content_hash("B")


# ════════════════════════════════════════════════════════════
# 2. 写入 / 读取
# ════════════════════════════════════════════════════════════


class TestRecordAndRead:
    def test_record_writes_snapshot_and_pointer(self, storage):
        """记录后：快照表有内容，conversations 上有指纹指针。"""
        tid = storage.create_topic("t")
        cid = storage.create_turn(tid, "问题")

        h = storage.record_l0_snapshot(cid, "L0 富化内容")
        assert h == l0_content_hash("L0 富化内容")

        snap = storage.get_l0_snapshot(cid)
        assert snap is not None
        assert snap["content"] == "L0 富化内容"
        assert snap["hash"] == h
        assert snap["chars"] == len("L0 富化内容")

    def test_empty_content_not_recorded(self, storage):
        """空 L0 不写快照（无 hash 可寻址），且不置「已记录」位。"""
        tid = storage.create_topic("t")
        cid = storage.create_turn(tid, "问题")
        assert storage.record_l0_snapshot(cid, "") == ""
        assert storage.get_l0_snapshot(cid) is None

    def test_missing_conversation_does_not_create_row(self, storage):
        """回合不存在时返回空串，且**不得隐式建行**（生命周期归 create_turn）。"""

        def _count():
            c = storage.conn.cursor()
            try:
                return c.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]
            finally:
                c.close()

        before = _count()
        assert storage.record_l0_snapshot("nonexistent-id", "内容") == ""
        assert _count() == before, "record_l0_snapshot 隐式创建了 conversation 行"

    def test_unrecorded_returns_none(self, storage):
        """未记录（功能上线前的旧回合）返回 None —— 与「记录为空」不同。"""
        tid = storage.create_topic("t")
        cid = storage.create_turn(tid, "问题")
        assert storage.get_l0_snapshot(cid) is None

    def test_get_nonexistent_conversation_returns_none(self, storage):
        assert storage.get_l0_snapshot("does-not-exist") is None

    def test_empty_conversation_id_is_noop(self, storage):
        assert storage.record_l0_snapshot("", "内容") == ""
        assert storage.get_l0_snapshot("") is None


# ════════════════════════════════════════════════════════════
# 3. 契约 1：回合起始值不可被覆盖（幂等）
# ════════════════════════════════════════════════════════════


class TestTurnStartImmutability:
    def test_second_record_does_not_overwrite(self, storage):
        """核心契约：同回合重复记录**保留第一份**，不写第二份。

        若这条失效，工具循环中期的 L0 会覆盖回合起始的 L0，
        审计复原出的就是「回合结束时的 L0」——失去复原意义。
        """
        tid = storage.create_topic("t")
        cid = storage.create_turn(tid, "问题")

        first = storage.record_l0_snapshot(cid, "回合起始的 L0")
        second = storage.record_l0_snapshot(cid, "回合中期的 L0")

        assert second == first, "第二次记录返回了不同的 hash（说明发生了覆盖）"
        snap = storage.get_l0_snapshot(cid)
        assert snap["content"] == "回合起始的 L0", "快照内容被回合中期的值覆盖了"

    def test_overwrite_attempt_leaves_no_orphan_snapshot(self, storage):
        """被拒绝的第二份内容不应在 l0_snapshots 里留下孤儿行。"""
        tid = storage.create_topic("t")
        cid = storage.create_turn(tid, "问题")
        storage.record_l0_snapshot(cid, "第一份")
        storage.record_l0_snapshot(cid, "第二份")

        snaps = storage.list_l0_snapshots(tid)
        assert len(snaps) == 1, f"产生了孤儿快照: {snaps}"


# ════════════════════════════════════════════════════════════
# 4. 内容寻址去重
# ════════════════════════════════════════════════════════════


class TestContentAddressing:
    def test_same_content_shared_across_turns(self, storage):
        """同 topic 内 L0 逐字节稳定 → 多回合共享同一快照行（不重复存大文本）。"""
        tid = storage.create_topic("t")
        c1 = storage.create_turn(tid, "问题1")
        c2 = storage.create_turn(tid, "问题2")

        h1 = storage.record_l0_snapshot(c1, "同一份 L0")
        h2 = storage.record_l0_snapshot(c2, "同一份 L0")

        assert h1 == h2
        assert len(storage.list_l0_snapshots(tid)) == 1, "相同内容被重复存储（去重失效）"
        assert storage.get_l0_snapshot(c1)["content"] == "同一份 L0"
        assert storage.get_l0_snapshot(c2)["content"] == "同一份 L0"

    def test_different_content_distinct_rows(self, storage):
        """L0 变化（如 AGENTS.md 改动）→ 各自成行，可做版本差异比对。"""
        tid = storage.create_topic("t")
        c1 = storage.create_turn(tid, "问题1")
        c2 = storage.create_turn(tid, "问题2")

        h1 = storage.record_l0_snapshot(c1, "旧 L0")
        h2 = storage.record_l0_snapshot(c2, "新 L0")

        assert h1 != h2
        assert len(storage.list_l0_snapshots(tid)) == 2

    def test_list_filtered_by_topic(self, storage):
        t1 = storage.create_topic("t1")
        t2 = storage.create_topic("t2")
        storage.record_l0_snapshot(storage.create_turn(t1, "q"), "L0-A")
        storage.record_l0_snapshot(storage.create_turn(t2, "q"), "L0-B")

        assert len(storage.list_l0_snapshots(t1)) == 1
        assert len(storage.list_l0_snapshots(t2)) == 1
        assert len(storage.list_l0_snapshots()) == 2


# ════════════════════════════════════════════════════════════
# 5. 契约 3：悬空指针可见（不静默）
# ════════════════════════════════════════════════════════════


class TestDanglingPointer:
    def test_missing_snapshot_row_is_flagged_not_silent(self, storage):
        """快照行消失（清理/跨库搬迁）时返回 missing 标记，而非假装内容为空。

        静默返回空内容会让审计误判「当时 L0 就是空的」——这是「静默失效」
        类缺陷，必须留痕。
        """
        tid = storage.create_topic("t")
        cid = storage.create_turn(tid, "问题")
        h = storage.record_l0_snapshot(cid, "内容")

        # 模拟快照行被清理（指针仍在）
        c = storage.conn.cursor()
        c.execute("DELETE FROM l0_snapshots WHERE hash = ?", (h,))
        storage.conn.commit()
        c.close()

        snap = storage.get_l0_snapshot(cid)
        assert snap is not None
        assert snap.get("missing") is True, "悬空指针未被标记出来（静默失效）"


# ════════════════════════════════════════════════════════════
# 6. 契约 2：写钩子绝不抛错（旁路不得改写控制流）
# ════════════════════════════════════════════════════════════


class _StubCtx:
    """最小 ctx 替身（鸭子类型），只带 storage / conversation_id。"""

    def __init__(self, storage=None, conv_id=""):
        self.storage = storage
        self.conversation_id = conv_id


class TestHookNeverRaises:
    """调用点位于 tool_loop_runner 的重试 try 内 —— 抛错会被误判为 API 失败。"""

    def test_storage_write_failure_is_swallowed(self):
        """storage.record_l0_snapshot 抛错时必须被吞掉。"""

        class Boom:
            def record_l0_snapshot(self, conv_id, content):
                raise RuntimeError("DB 爆炸")

        from tea_agent.session.history_builder import _maybe_record_l0_snapshot

        # 不应抛出
        _maybe_record_l0_snapshot(_StubCtx(Boom(), "c1"), "内容")

    def test_storage_without_method_is_skipped(self):
        """鸭子类型替身没有该方法 → 静默跳过，不 AttributeError。"""
        from tea_agent.session.history_builder import _maybe_record_l0_snapshot

        ctx = _StubCtx(storage=object(), conv_id="c1")
        _maybe_record_l0_snapshot(ctx, "内容")
        # 未真正记录 → 不应置位（给后续调用留机会）
        assert getattr(ctx, "_l0_recorded_conv", "") == ""

    def test_no_storage_is_noop(self):
        from tea_agent.session.history_builder import _maybe_record_l0_snapshot

        _maybe_record_l0_snapshot(_StubCtx(None, "c1"), "内容")

    def test_no_conversation_id_is_noop(self):
        from tea_agent.session.history_builder import _maybe_record_l0_snapshot

        _maybe_record_l0_snapshot(_StubCtx(object(), ""), "内容")

    def test_empty_content_is_noop(self):
        from tea_agent.session.history_builder import _maybe_record_l0_snapshot

        _maybe_record_l0_snapshot(_StubCtx(object(), "c1"), "")

    def test_exotic_context_attribute_error_is_swallowed(self):
        """context 的属性查找本身抛错时也不能冒泡。"""

        class Hostile:
            @property
            def conversation_id(self):
                raise AttributeError("属性查找爆炸")

        from tea_agent.session.history_builder import _maybe_record_l0_snapshot

        _maybe_record_l0_snapshot(Hostile(), "内容")


# ════════════════════════════════════════════════════════════
# 7. 进程内幂等（避免工具循环数百次打 DB）
# ════════════════════════════════════════════════════════════


class TestProcessLevelMemo:
    def test_second_call_skips_storage(self):
        """同回合第二次调用不应再打 DB（工具循环内 build 被调数百次）。"""
        calls = []

        class Counting:
            def record_l0_snapshot(self, conv_id, content):
                calls.append(conv_id)
                return "hash"

        from tea_agent.session.history_builder import _maybe_record_l0_snapshot

        ctx = _StubCtx(Counting(), "c1")
        _maybe_record_l0_snapshot(ctx, "内容")
        _maybe_record_l0_snapshot(ctx, "内容")
        _maybe_record_l0_snapshot(ctx, "内容")
        assert calls == ["c1"], f"重复打了 {len(calls)} 次 DB（进程内幂等失效）"

    def test_new_turn_resets_memo(self):
        """换回合（新 conversation_id）必须重新记录。"""
        calls = []

        class Counting:
            def record_l0_snapshot(self, conv_id, content):
                calls.append(conv_id)
                return "hash"

        from tea_agent.session.history_builder import _maybe_record_l0_snapshot

        ctx = _StubCtx(Counting(), "c1")
        _maybe_record_l0_snapshot(ctx, "内容")
        ctx.conversation_id = "c2"
        _maybe_record_l0_snapshot(ctx, "内容")
        assert calls == ["c1", "c2"]


# ════════════════════════════════════════════════════════════
# 8. 端到端：build_api_messages 真的落盘了
# ════════════════════════════════════════════════════════════


class TestEndToEndWiring:
    """钉住「接线存在」这一契约 —— 否则功能写完却永不触发（静默失效）。"""

    @staticmethod
    def _ctx_with_storage(storage, conv_id):
        from tea_agent.session.context import SessionContext

        ctx = SessionContext(model="test-model", supports_reasoning=True)
        ctx.max_context_tokens = 1_000_000
        ctx.messages = [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "你好"},
        ]
        ctx.storage = storage
        ctx.conversation_id = conv_id
        return ctx

    def test_build_api_messages_records_l0(self, storage):
        from tea_agent.session.history_builder import build_api_messages

        tid = storage.create_topic("t")
        cid = storage.create_turn(tid, "问题")
        ctx = self._ctx_with_storage(storage, cid)

        msgs = build_api_messages(ctx, "原始系统提示词")

        snap = storage.get_l0_snapshot(cid)
        assert snap is not None, "build_api_messages 未落盘 L0 快照（接线丢失）"
        # 快照必须等于真正发给模型的 system 消息，而非裸 prompt
        assert snap["content"] == msgs[0]["content"]
        assert snap["content"]

    def test_snapshot_survives_repeated_builds(self, storage):
        """多轮构建（工具循环）后，快照仍是第一次那份。"""
        from tea_agent.session.history_builder import build_api_messages

        tid = storage.create_topic("t")
        cid = storage.create_turn(tid, "问题")
        ctx = self._ctx_with_storage(storage, cid)

        build_api_messages(ctx, "SP")
        first = storage.get_l0_snapshot(cid)["content"]

        for _ in range(5):
            build_api_messages(ctx, "SP")
        assert storage.get_l0_snapshot(cid)["content"] == first

    def test_ctx_without_storage_does_not_crash(self):
        """LiteSession / 单测的轻量 ctx 无 storage —— 必须静默跳过。"""
        from tea_agent.session.context import SessionContext
        from tea_agent.session.history_builder import build_api_messages

        ctx = SessionContext(model="m", supports_reasoning=False)
        ctx.max_context_tokens = 1_000_000
        ctx.messages = [{"role": "user", "content": "hi"}]
        msgs = build_api_messages(ctx, "SP")
        assert msgs[0]["role"] == "system"
