"""上下文填充治理回归测试（2026-09）。

背景：多轮对话很快打满 max_context_tokens。实测单轮（356 条消息）
reasoning_content 1.5M 字符 ≈ 37.5 万 token，是首要填充源；另有
L2 单条 thinking 无上限（1.5MB）、L2 只在"条数 ≥30"时触发 L3、
源码文件回放不截断、provider.yaml 的 384K max_output_tokens 被当作
每次请求的输出预留（输入预算只剩 446K）等问题。

本文件覆盖对应修复：
- L1: reasoning_content 限步回传（保留最近 N 步，其余置空并回写定型）
- L1: max_history 真正生效（限制保留的最近用户轮数）
- L2: thinking 限幅 + 总量（字符）触发 L3 摘要
- L2/L1: 重复轮次去重
- 预算: provider.yaml 自动 max_tokens 按窗口比例限幅
"""

import pytest

from tea_agent.config import AgentConfig, _parse_model_configs, auto_max_tokens_cap
from tea_agent.session.context import SessionContext
from tea_agent.session.history_builder import (
    _blank_stale_reasoning,
    _drop_level2_duplicates,
    _get_max_history_turns,
    _get_rc_keep_steps,
    build_api_messages,
)
from tea_agent.store._summaries import SummaryStore


def _assistant_with_rc(idx: int, rc: str = "思考内容") -> dict:
    return {
        "role": "assistant",
        "content": "",
        "reasoning_content": f"{rc}-{idx}",
        "tool_calls": [{
            "id": f"c{idx}", "type": "function",
            "function": {"name": "toolkit_file", "arguments": "{}"},
        }],
    }


def _build_ctx(turns: int, rc_keep_steps: int = 0) -> SessionContext:
    ctx = SessionContext(model="test-model", supports_reasoning=True)
    ctx.max_context_tokens = 1_000_000
    ctx.rc_keep_steps = rc_keep_steps
    ctx.messages = [{"role": "system", "content": "system"}]
    for i in range(turns):
        ctx.messages.append({"role": "user", "content": f"u{i}"})
        ctx.messages.append(_assistant_with_rc(i))
        ctx.messages.append({"role": "tool", "content": "ok", "tool_call_id": f"c{i}"})
    return ctx


class TestReasoningKeepSteps:
    """L1 reasoning_content 分块限步回传（第一主因修复）。

    语义：以 keep_steps 为块大小，只保留**最近一块**的全文（1..keep_steps 步），
    更早的块整体置空。分块而非滑窗 —— 滑窗每步都要改写"第 N+1 步"，会让其后
    N 步内容每步都缓存未命中；分块只在跨块边界改写一次。
    """

    def test_last_chunk_keeps_full_rc(self):
        ctx = _build_ctx(turns=4, rc_keep_steps=2)
        msgs = build_api_messages(ctx, "sp")
        asst = [m for m in msgs if m.get("role") == "assistant" and m.get("tool_calls")]
        assert len(asst) == 4
        # 最后一块（步 2、3）保留全文，更早的块置空（字段保留）
        assert asst[-1]["reasoning_content"] == "思考内容-3"
        assert asst[-2]["reasoning_content"] == "思考内容-2"
        for m in asst[:-2]:
            assert m["reasoning_content"] == ""
            assert "reasoning_content" in m  # 字段必须存在（V4 要求）

    def test_partial_chunk_keeps_remainder_only(self):
        """5 步 / 每块 2 步 → 最后一块只有 1 步（剩下的 4 步全部置空）。"""
        ctx = _build_ctx(turns=5, rc_keep_steps=2)
        msgs = build_api_messages(ctx, "sp")
        asst = [m for m in msgs if m.get("role") == "assistant" and m.get("tool_calls")]
        rc = [m["reasoning_content"] for m in asst]
        assert rc == ["", "", "", "", "思考内容-4"]

    def test_writeback_keeps_prefix_solidified(self):
        ctx = _build_ctx(turns=4, rc_keep_steps=2)
        build_api_messages(ctx, "sp")
        src = [m for m in ctx.messages if m.get("role") == "assistant"]
        assert [m["reasoning_content"] for m in src] == [
            "", "", "思考内容-2", "思考内容-3",
        ]
        # 幂等：再次构建形态不变（前缀稳定，不会反复翻转）
        msgs2 = build_api_messages(ctx, "sp")
        asst2 = [m for m in msgs2 if m.get("role") == "assistant" and m.get("tool_calls")]
        assert [m["reasoning_content"] for m in asst2] == [
            "", "", "思考内容-2", "思考内容-3",
        ]

    def test_chunk_boundary_flips_once_then_stays_stable(self):
        """跨块边界只翻转一次：块内新增步不引发新的缓存改写。"""
        ctx = _build_ctx(turns=4, rc_keep_steps=2)
        build_api_messages(ctx, "sp")  # 保留步 2、3

        # 追加第 5 步 → 跨块：步 2、3 一次性置空，步 4 保留
        ctx.messages.append({"role": "user", "content": "u4"})
        ctx.messages.append(_assistant_with_rc(4))
        ctx.messages.append({"role": "tool", "content": "ok", "tool_call_id": "c4"})
        msgs = build_api_messages(ctx, "sp")
        asst = [m for m in msgs if m.get("role") == "assistant" and m.get("tool_calls")]
        assert [m["reasoning_content"] for m in asst] == [
            "", "", "", "", "思考内容-4",
        ]

        # 追加第 6 步 → 仍在同一块（索引 4、5）→ 不再有任何改写
        ctx.messages.append({"role": "user", "content": "u5"})
        ctx.messages.append(_assistant_with_rc(5))
        ctx.messages.append({"role": "tool", "content": "ok", "tool_call_id": "c5"})
        msgs2 = build_api_messages(ctx, "sp")
        asst2 = [m for m in msgs2 if m.get("role") == "assistant" and m.get("tool_calls")]
        assert [m["reasoning_content"] for m in asst2] == [
            "", "", "", "", "思考内容-4", "思考内容-5",
        ]

    def test_negative_disables_optimization(self):
        """rc_keep_steps < 0 → 全量回传（旧行为，端点不接受空串时回退）。"""
        ctx = _build_ctx(turns=4, rc_keep_steps=-1)
        assert _get_rc_keep_steps(ctx) == 0
        msgs = build_api_messages(ctx, "sp")
        asst = [m for m in msgs if m.get("role") == "assistant" and m.get("tool_calls")]
        assert [m["reasoning_content"] for m in asst] == [
            f"思考内容-{i}" for i in range(4)
        ]

    def test_blank_helper_returns_count_and_is_idempotent(self):
        ctx = _build_ctx(turns=4, rc_keep_steps=1)
        msgs = [dict(m, _src_idx=i) for i, m in enumerate(ctx.messages)
                if m.get("role") == "assistant"]
        assert _blank_stale_reasoning(ctx, msgs, 1) == 3
        assert _blank_stale_reasoning(ctx, msgs, 1) == 0  # 二次调用无变化

    def test_keep_steps_zero_is_noop(self):
        ctx = _build_ctx(turns=3, rc_keep_steps=0)
        ctx.rc_keep_steps = -1  # 显式关闭（0 表示读配置）
        msgs = build_api_messages(ctx, "sp")
        asst = [m for m in msgs if m.get("role") == "assistant" and m.get("tool_calls")]
        assert all(m["reasoning_content"] for m in asst)


class TestMaxHistoryTurns:
    """max_history 真正生效（此前只存不用）。"""

    def test_caps_l1_user_turns(self):
        ctx = SessionContext(max_history=2)
        ctx.max_context_tokens = 1_000_000
        ctx.messages = [{"role": "system", "content": "s"}]
        for i in range(5):
            ctx.messages.append({"role": "user", "content": f"u{i}"})
            ctx.messages.append({"role": "assistant", "content": f"a{i}"})
        assert _get_max_history_turns(ctx) == 2
        msgs = build_api_messages(ctx, "sp")
        users = [m["content"] for m in msgs
                 if m.get("role") == "user" and str(m.get("content", "")).startswith("u")]
        assert users == ["u3", "u4"]

    def test_zero_means_unlimited(self):
        ctx = SessionContext(max_history=-1)
        assert _get_max_history_turns(ctx) == 0


class TestLevel2Dedup:
    """L2 与 L1 重复轮次去重（同一轮被两层同时注入）。"""

    def _ctx(self) -> SessionContext:
        ctx = SessionContext()
        ctx.messages = [
            {"role": "system", "content": "s"},
            {"role": "user", "content": "帮我审查代码\n\n[运行状态 — 自动注入]"},
            {"role": "assistant", "content": "好的"},
        ]
        return ctx

    def test_drops_duplicate_of_l1_window(self):
        ctx = self._ctx()
        filtered = [
            {"kind": "full", "user": "帮我审查代码", "assistant": "好的"},
            {"kind": "full", "user": "另一件事怎么办", "assistant": "这样做"},
        ]
        out = _drop_level2_duplicates(ctx, filtered, start_idx=1)
        assert [i["user"] for i in out] == ["另一件事怎么办"]

    def test_keeps_summary_items_and_short_texts(self):
        ctx = self._ctx()
        filtered = [
            {"kind": "summary", "content": "User: 帮我审查代码... → Assistant: 好的..."},
            {"kind": "full", "user": "短", "assistant": "x"},
        ]
        out = _drop_level2_duplicates(ctx, filtered, start_idx=1)
        assert len(out) == 2

    def test_no_l1_window_keeps_everything(self):
        ctx = SessionContext()
        ctx.messages = [{"role": "system", "content": "s"}]
        filtered = [{"kind": "full", "user": "帮我审查代码", "assistant": "好的"}]
        assert _drop_level2_duplicates(ctx, filtered, start_idx=1) == filtered


class _L2Store(SummaryStore):
    """最小 L2 存储 stub：只覆盖 get/set_level2（不触碰 sqlite）。"""

    def __init__(self):
        self._l2: list[dict] = []

    def get_level2(self, topic_id: str) -> list:
        return list(self._l2)

    def set_level2(self, topic_id: str, level2: list) -> None:
        self._l2 = list(level2)


class TestLevel2Governance:
    """L2 thinking 限幅 + 总量（字符）触发 L3 摘要。"""

    def test_thinking_is_capped(self):
        store = _L2Store()
        rounds = [{
            "role": "assistant",
            "content": "中间步骤",
            "reasoning_content": "思考" * 5000,  # 10000 字符
            "tool_calls": [{"id": "c1", "function": {"name": "t", "arguments": "{}"}}],
        }]
        store.push_to_level2(
            "t", "u", "a", rounds=rounds, thinking_max_chars=1000,
        )
        thinking = store._l2[0]["thinking"]
        assert len(thinking) < 1200
        assert "思考链已截断" in thinking
        assert "原长" in thinking

    def test_zero_disables_thinking_cap(self):
        store = _L2Store()
        rounds = [{
            "role": "assistant", "content": "c",
            "reasoning_content": "思考" * 500,
            "tool_calls": [{"id": "c1", "function": {"name": "t", "arguments": "{}"}}],
        }]
        store.push_to_level2("t", "u", "a", rounds=rounds, thinking_max_chars=0)
        assert "思考链已截断" not in store._l2[0]["thinking"]

    def test_char_threshold_triggers_overflow_before_count_limit(self):
        """条数远未到上限，但总量超阈值 → 立即溢出并请求 L3 摘要。"""
        store = _L2Store()
        seen = []
        for _i in range(3):
            count, overflow, should = store.push_to_level2(
                "t", "u" * 40, "a" * 40,
                max_level2=99, max_level2_chars=200, thinking_max_chars=0,
            )
            seen.append((count, len(overflow), should))
        # 第 3 次：总 240 字符 ≥ 200 → 溢出 1 条（至少保留 1 条）
        assert seen[-1][1] >= 1
        assert seen[-1][2] is True
        assert len(store._l2) >= 1

    def test_count_trigger_keeps_five(self):
        store = _L2Store()
        overflow, should = [], False
        for _i in range(8):
            _count, overflow, should = store.push_to_level2(
                "t", "u", "a", max_level2=8, thinking_max_chars=0, max_level2_chars=0,
            )
        assert should is True
        assert len(store._l2) == 5
        assert len(overflow) == 3

    def test_zero_char_threshold_never_char_triggers(self):
        store = _L2Store()
        for _i in range(3):
            _count, overflow, should = store.push_to_level2(
                "t", "u" * 1000, "a" * 1000,
                max_level2=99, max_level2_chars=0, thinking_max_chars=0,
            )
            assert should is False and overflow == []
        assert len(store._l2) == 3


class TestOutputReserveClamp:
    """provider.yaml 的 max_output_tokens 自动填充时按窗口比例限幅。"""

    def test_cap_values(self):
        assert auto_max_tokens_cap(1_000_000) == 250_000
        assert auto_max_tokens_cap(150_000) == 37_500
        assert auto_max_tokens_cap(10_000) == 8_192  # 下限
        assert auto_max_tokens_cap(0) == 8_192       # 未知窗口

    def test_auto_fill_clamped_but_explicit_wins(self, monkeypatch):
        monkeypatch.setattr(
            "tea_agent.config._resolve_ref_model",
            lambda provider, model: {
                "api_key": "k", "api_url": "u", "model": model,
                "max_context_tokens": 1_000_000, "max_output_tokens": 384_000,
                "options": {}, "reasoning_effort": "auto",
            },
        )
        cfg = AgentConfig()
        _parse_model_configs(cfg, {"main_model": {"provider": "P", "model": "m"}})
        assert cfg.main_model.max_context_tokens == 1_000_000
        # 384K（38% 窗口）不再被当作每次请求的输出预留 → 限幅到 25% 窗口
        assert cfg.main_model.max_tokens == 250_000

        cfg2 = AgentConfig()
        _parse_model_configs(
            cfg2,
            {"main_model": {"provider": "P", "model": "m", "max_tokens": 131072}},
        )
        assert cfg2.main_model.max_tokens == 131_072  # 显式配置优先


def test_source_file_replay_threshold_is_bounded():
    """源码文件回放限幅（此前 sys.maxsize 不截断）。"""
    import sys

    from tea_agent.basesession import BaseChatSession

    threshold = BaseChatSession._guess_tool_threshold(
        "toolkit_file", '{"filename": "main.py"}'
    )
    assert threshold == BaseChatSession._SOURCE_FILE_THRESHOLD
    assert threshold != sys.maxsize
    assert threshold <= 65536


@pytest.mark.parametrize("turns", [1, 3])
def test_small_conversations_keep_all_rc_when_within_window(turns):
    """步数 ≤ 保留窗口时不置空任何 RC。"""
    ctx = _build_ctx(turns=turns, rc_keep_steps=8)
    msgs = build_api_messages(ctx, "sp")
    asst = [m for m in msgs if m.get("role") == "assistant" and m.get("tool_calls")]
    assert all(m["reasoning_content"] for m in asst)
