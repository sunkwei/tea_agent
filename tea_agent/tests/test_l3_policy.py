"""L2→L3 触发策略回归测试（tea_agent/l3_policy.py + push_to_level2/trim_level2）。

## 背景（2026-10 需求）

1. **告急立即压缩**：上下文 token 水位越过 75% 窗口即触发 L2→L3，不等轮次水位。
2. **批处理**：keep_turns 默认 10；L2 越过 keep_turns 后不每多一条就摘要，
   而是攒到 ``keep_turns + keep_turns//2`` 再一次性压回 ``keep_turns`` 条。

## 断言取向

策略是纯函数，边界（恰好等于阈值 / 差一条 / 告急）全部秒级可测，不依赖 LLM、
不依赖时间。store 层用最小 stub（只覆盖 get/set_level2），不碰 sqlite。
"""

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from tea_agent.l3_policy import (  # noqa: E402
    DEFAULT_KEEP_TURNS,
    DEFAULT_URGENT_RATIO,
    exceeds_urgent_ratio,
    plan_l2_overflow,
    resolve_l2_batch,
    resolve_l2_keep,
    resolve_urgent_ratio,
)
from tea_agent.store._summaries import SummaryStore  # noqa: E402

# ════════════════════════════════════════════════════════════
# 1. 纯策略：水位 / 批大小 / 溢出条数
# ════════════════════════════════════════════════════════════

class TestResolveKeep:
    def test_default_keep_turns_is_ten(self):
        """需求：keep_turns 默认值改为 10。"""
        assert DEFAULT_KEEP_TURNS == 10
        assert resolve_l2_keep() == 10

    def test_cap_only_tightens(self):
        """history_l2_max 只作上限约束：小则收紧，大则无影响。"""
        assert resolve_l2_keep(10, 4) == 4
        assert resolve_l2_keep(10, 30) == 10
        assert resolve_l2_keep(10, 0) == 10  # 0=不约束

    def test_invalid_inputs_fall_back(self):
        """非法/替身值不得把水位算成 1（MagicMock 会被 int() 静默转 1）。"""
        assert resolve_l2_keep(None) == 10
        assert resolve_l2_keep(True) == 10
        assert resolve_l2_keep("abc") == 10
        # 0/负数 = **未指定**（不是"压到 0 条"）：水位为 0 会让 L2 恒空、
        # 历史完全依赖 L3，属误配而非意图 → 回落默认 10。
        assert resolve_l2_keep(0) == DEFAULT_KEEP_TURNS
        assert resolve_l2_keep(-5) == DEFAULT_KEEP_TURNS


class TestResolveBatch:
    def test_auto_batch_is_half_keep_turns(self):
        """需求：0.5 * keep_turns —— 10 → 5。"""
        assert resolve_l2_batch() == 5
        assert resolve_l2_batch(10) == 5
        assert resolve_l2_batch(4) == 2

    def test_explicit_batch_wins(self):
        assert resolve_l2_batch(10, 3) == 3
        assert resolve_l2_batch(10, 0) == 5  # 0=自动

    def test_batch_never_zero(self):
        """keep_turns=1 时 1//2=0 → 必须兜底为 1，否则闸门恒开（等于回到旧行为）。"""
        assert resolve_l2_batch(1) == 1


class TestPlanL2Overflow:
    """核心闸门：不要每多一条就摘要。"""

    def test_under_keep_no_overflow(self):
        assert plan_l2_overflow(10) == 0
        assert plan_l2_overflow(1) == 0
        assert plan_l2_overflow(0) == 0

    def test_between_keep_and_keep_plus_batch_holds(self):
        """越过 keep_turns 但未攒够一批 → 一条都不压（这是需求 2 的关键）。"""
        for n in range(11, 16):  # keep=10, batch=5 → 触发点 n>15
            assert plan_l2_overflow(n) == 0, f"n={n} 不应触发摘要"

    def test_at_batch_threshold_still_holds(self):
        """恰好 n == keep+batch 不触发（严格大于才触发，边界钉死）。"""
        assert plan_l2_overflow(15) == 0

    def test_one_over_threshold_compresses_back_to_keep(self):
        """n=16 → 一次性压回 keep=10，溢出 6 条（不是 1 条）。"""
        assert plan_l2_overflow(16) == 6

    def test_compress_result_equals_keep(self):
        """压缩后 L2 条数恒等于 keep_turns（不越压越少）。"""
        for n in (16, 20, 37, 100):
            assert n - plan_l2_overflow(n) == 10

    def test_urgent_ignores_batch_gate(self):
        """告急：无视批处理闸门，只留 keep 条。"""
        assert plan_l2_overflow(11, urgent=True) == 1
        assert plan_l2_overflow(30, urgent=True) == 20
        # n <= keep 时无可压（不能压成负数）
        assert plan_l2_overflow(10, urgent=True) == 0
        assert plan_l2_overflow(3, urgent=True) == 0

    def test_urgent_result_also_equals_keep(self):
        for n in (11, 12, 25, 50):
            assert n - plan_l2_overflow(n, urgent=True) == 10

    def test_cap_limits_keep_waterline(self):
        """上限约束生效：cap=4 → 压回 4 条，触发点 4+2=6。"""
        assert plan_l2_overflow(6, 10, 0, cap=4) == 0
        assert plan_l2_overflow(7, 10, 0, cap=4) == 3


class TestUrgentRatio:
    def test_default_is_75_percent(self):
        assert DEFAULT_URGENT_RATIO == 0.75
        assert exceeds_urgent_ratio(0.75) is True
        assert exceeds_urgent_ratio(0.7499) is False

    def test_context_override(self):
        class _Ctx:
            l3_urgent_ratio = 0.5

        assert resolve_urgent_ratio(_Ctx()) == 0.5
        assert exceeds_urgent_ratio(0.6, _Ctx()) is True
        assert exceeds_urgent_ratio(0.4, _Ctx()) is False

    def test_invalid_ratio_falls_back(self):
        """越界/非法阈值回落默认 0.75，不得变成"恒告急"。"""
        class _Ctx:
            l3_urgent_ratio = 0.0

        class _Ctx2:
            l3_urgent_ratio = 1.5

        assert resolve_urgent_ratio(_Ctx()) == 0.75
        assert resolve_urgent_ratio(_Ctx2()) == 0.75
        assert resolve_urgent_ratio(None) == 0.75

    def test_nan_and_junk_never_urgent(self):
        assert exceeds_urgent_ratio(float("nan")) is False
        assert exceeds_urgent_ratio(None) is False
        assert exceeds_urgent_ratio("x") is False
        assert exceeds_urgent_ratio(True) is False


# ════════════════════════════════════════════════════════════
# 2. store 层：push_to_level2 / trim_level2
# ════════════════════════════════════════════════════════════

class _L2Store(SummaryStore):
    """最小 L2 存储 stub：只覆盖 get/set_level2（不触碰 sqlite）。

    直接继承 ``SummaryStore`` 而非 ``Storage``：被测的 ``push_to_level2`` /
    ``trim_level2`` 就定义在这里，无需经 ``Storage._summaries`` 转发
    （那条路要求完整初始化 sqlite，单测里既慢又脆）。
    """

    def __init__(self):
        self._l2: list[dict] = []

    def get_level2(self, topic_id: str) -> list:
        return list(self._l2)

    def set_level2(self, topic_id: str, level2: list) -> None:
        self._l2 = list(level2)


def _push(store, n=1, **kw):
    out = None
    for i in range(n):
        out = store.push_to_level2("t", f"u{i}", f"a{i}", thinking_max_chars=0, **kw)
    return out


class TestPushToLevel2Batching:
    def test_holds_until_batch_accumulates(self):
        """10 条不触发；第 16 条才触发，且一次性压回 10 条。"""
        store = _L2Store()
        for _i in range(15):
            _count, overflow, should = _push(store, keep_turns=10, l3_batch=0, max_level2_chars=0)
            assert should is False, "未攒够一批不应触发摘要"
        assert len(store._l2) == 15

        _count, overflow, should = _push(store, keep_turns=10, l3_batch=0, max_level2_chars=0)
        assert should is True
        assert len(overflow) == 6
        assert len(store._l2) == 10, "压缩后 L2 必须回到 keep_turns 条"

    def test_urgent_compresses_immediately(self):
        """告急：第 11 条即压回 10 条（不等批）。"""
        store = _L2Store()
        _push(store, 10, keep_turns=10, max_level2_chars=0)
        _count, overflow, should = _push(store, 1, keep_turns=10, max_level2_chars=0, urgent=True)
        assert should is True and len(overflow) == 1
        assert len(store._l2) == 10

    def test_explicit_batch_respected(self):
        store = _L2Store()
        for _i in range(12):
            _c, _o, should = _push(store, keep_turns=10, l3_batch=2, max_level2_chars=0)
            assert should is False
        _c, overflow, should = _push(store, keep_turns=10, l3_batch=2, max_level2_chars=0)
        assert should is True and len(overflow) == 3
        assert len(store._l2) == 10

    def test_cap_from_history_l2_max(self):
        """history_l2_max 作为上限约束传入（不再充当压回目标）。

        cap=4 → keep=min(10,4)=4，batch=max(1, 4//2)=2 → 触发点 n>6。
        """
        store = _L2Store()
        for _i in range(6):
            _c, _o, should = _push(store, keep_turns=10, max_level2=4, max_level2_chars=0)
            assert should is False, "n<=keep+batch 不应触发"
        assert len(store._l2) == 6

        _c, overflow, should = _push(store, keep_turns=10, max_level2=4, max_level2_chars=0)
        assert should is True and len(overflow) == 3  # 7 - 4
        assert len(store._l2) == 4

    def test_char_threshold_still_triggers_before_count(self):
        """字符总量水位仍然生效（不因批处理改造而失效）。

        条数远未到水位（keep=99），但字符总量已越线 → 仍须溢出并请求摘要。
        """
        store = _L2Store()
        seen = []
        for _i in range(3):  # 每条 user+assistant ≈ 4 字符，3 条 ≈ 12 ≥ 10
            seen.append(_push(store, keep_turns=99, max_level2=99, max_level2_chars=10))
        assert seen[-1][2] is True
        assert seen[-1][1], "总量触发必须给出溢出条目"
        assert len(store._l2) == 2  # 至少溢出 1 条，且不把 L2 清空


class TestTrimLevel2:
    def test_trim_does_not_add_entries(self):
        """trim 只裁剪、不新增（告急路径专用）。"""
        store = _L2Store()
        _push(store, 14, keep_turns=10, max_level2_chars=0)
        count, overflow, should = store.trim_level2("t", keep_turns=10, urgent=True)
        assert should is True
        assert count == 10
        assert len(overflow) == 4
        assert len(store._l2) == 10

    def test_trim_noop_when_under_waterline(self):
        store = _L2Store()
        _push(store, 5, keep_turns=10, max_level2_chars=0)
        count, overflow, should = store.trim_level2("t", keep_turns=10, urgent=True)
        assert (count, overflow, should) == (5, [], False)

    def test_trim_urgent_false_uses_batch_gate(self):
        """非告急的 trim 也走批处理闸门（同一事实源，不因入口不同而漂移）。"""
        store = _L2Store()
        _push(store, 14, keep_turns=10, max_level2_chars=0)
        _count, overflow, should = store.trim_level2("t", keep_turns=10, urgent=False)
        assert should is False and overflow == []


class TestPushTrimShareWaterline:
    """push 与 trim 必须给出**一致**的裁剪结果（同一水位事实源）。

    历史教训：判定散落两处时必然漂移——一条路径改了阈值、另一条没改，
    表现为"手动压缩和自动压缩行为不一样"。本类把两者钉在同一输入上比对。
    """

    @pytest.mark.parametrize("n", [10, 12, 15, 16, 20])
    def test_push_and_trim_share_gate(self, n):
        """常压路径：push 一次的闸门结果 == 对同状态 trim 的结果。"""
        a = _L2Store()
        _push(a, n, keep_turns=10, max_level2_chars=0)
        state_before = list(a._l2)

        _c, o_push, s_push = a.push_to_level2(
            "t", "uX", "aX", keep_turns=10, max_level2_chars=0, thinking_max_chars=0
        )

        # 对"push 前状态 + 同一新条目"做 trim → 结果必须逐项一致
        b = _L2Store()
        b._l2 = state_before + [{"user": "uX", "assistant": "aX"}]
        _cb, o_trim, s_trim = b.trim_level2("t", keep_turns=10, urgent=False)

        assert (len(o_push), s_push) == (len(o_trim), s_trim), (
            f"push 与 trim 判定漂移: push={(len(o_push), s_push)} trim={(len(o_trim), s_trim)}"
        )
        assert len(a._l2) == len(b._l2), "两条路径压回后的 L2 条数必须一致"

    @pytest.mark.parametrize("n", [11, 14, 16, 25])
    def test_urgent_trim_always_lands_on_keep(self, n):
        """告急压缩后 L2 恒为 min(n, keep) 条。

        必须**直接铺底** ``_l2`` 而不能靠连续 push 攒：push 自身也走同一闸门，
        攒到 16 条时已先压回过一次，trim 看到的就不是 n 条了（那样测的
        是 push 而非 trim）。
        """
        store = _L2Store()
        store._l2 = [{"user": f"u{i}", "assistant": f"a{i}"} for i in range(n)]

        count, overflow, should = store.trim_level2("t", keep_turns=10, urgent=True)
        assert count == min(n, 10)
        assert len(overflow) == max(0, n - 10)
        assert should is (n > 10)
        assert len(store._l2) == min(n, 10), "trim 后落库的条数必须等于返回值"
