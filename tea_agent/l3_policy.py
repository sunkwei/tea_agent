"""L2→L3 摘要触发策略 — 纯函数，无 IO，可在秒级单测里覆盖全部边界。

L2（主题级滚动窗口的完整 user/thinking/assistant 条目）向 L3（主题级语义摘要）
的溢出有**两条通道**，本模块只承载其中的纯判定部分，落库/调 LLM 由调用方负责：

1. **常压（轮次水位 + 批处理）**
   L2 条数越过 ``keep_turns`` 后不立刻摘要，而是继续攒到
   ``keep_turns + batch``（``batch`` 默认 ``keep_turns // 2``，即 10 → 5）
   一次性把 L2 压回 ``keep_turns`` 条。
   —— 避免"每多一条就摘要一次"：那会把便宜模型调用打散成每轮一次，
   既费 token 又让 L3 摘要被高频重写（观测到 L2 条数在 keep 附近抖动）。
   压缩后 L2 恒为 ``keep_turns`` 条，故也不会出现"越压越少"的回退。

2. **紧急（token 水位）**
   上下文用量越过 ``urgent_ratio``（默认 0.75 × 窗口）时立即压缩，
   无视轮次水位——此时等待"攒够一批"已无意义，必须马上腾空间。

``history_l2_max`` 只作为**上限约束**参与（``keep = min(keep_turns, cap)``）：
历史配置值（旧模板写 30）不会再被当成"压回目标"，从而不会一次砍掉过多 L2。
"""

from __future__ import annotations

import math
from typing import Any

#: keep_turns 缺省（与 config.AgentConfig.keep_turns / SessionContext.keep_turns 一致）
DEFAULT_KEEP_TURNS = 10
#: 上下文告急水位（占窗口比例）——越过即立即触发 L2→L3
DEFAULT_URGENT_RATIO = 0.75


def _as_int(value: Any, default: int) -> int:
    """宽松取整：拒绝 bool 与不可数字化的替身对象（MagicMock 会被 int() 静默转 1）。"""
    if isinstance(value, bool) or value is None:
        return default
    if isinstance(value, (int, float)):
        try:
            if isinstance(value, float) and math.isnan(value):
                return default
        except Exception:
            return default
        return int(value)
    if isinstance(value, str):
        try:
            return int(float(value.strip()))
        except (TypeError, ValueError):
            return default
    return default


def _as_ratio(value: Any, default: float) -> float:
    """取 (0, 1] 区间内的比例；非法/越界一律回落默认值。"""
    if isinstance(value, bool) or value is None:
        return default
    try:
        r = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(r) or r <= 0.0 or r > 1.0:
        return default
    return r


def resolve_l2_keep(keep_turns: Any = DEFAULT_KEEP_TURNS, cap: Any = 0) -> int:
    """L2 压缩后的目标条数（= 压回水位）。

    Args:
        keep_turns: 配置的保留轮数；``0``/负数/非法一律视为**未指定**，
            回落 :data:`DEFAULT_KEEP_TURNS`（不是"压到 0 条"——水位为 0
            会让 L2 恒为空、历史完全依赖 L3，属误配而非意图）。
        cap: ``history_l2_max`` 上限约束（>0 时取 ``min``，0/非法=不约束）。

    Returns:
        至少为 1 的整数条数。
    """
    raw = _as_int(keep_turns, DEFAULT_KEEP_TURNS)
    keep = raw if raw > 0 else DEFAULT_KEEP_TURNS
    c = _as_int(cap, 0)
    if c > 0:
        keep = min(keep, c)
    return max(1, keep)


def resolve_l2_batch(keep_turns: Any = DEFAULT_KEEP_TURNS, batch: Any = 0, cap: Any = 0) -> int:
    """一次批量摘要至少需要积攒的**新增溢出量**。

    显式 ``batch > 0`` 时直接采用；否则按 ``keep_turns // 2`` 推导
    （keep_turns=10 → 5），且至少为 1。
    """
    b = _as_int(batch, 0)
    if b > 0:
        return b
    return max(1, resolve_l2_keep(keep_turns, cap) // 2)


def plan_l2_overflow(
    count: Any,
    keep_turns: Any = DEFAULT_KEEP_TURNS,
    batch: Any = 0,
    urgent: bool = False,
    cap: Any = 0,
) -> int:
    """判定本轮应从 L2 移出多少条交给 L3 摘要。

    Args:
        count: 当前（含本轮新增后）L2 条数。
        keep_turns: 压缩后保留条数。
        batch: 批大小（0=按 ``keep_turns // 2`` 推导）。
        urgent: 上下文告急（越过 ``urgent_ratio``）→ 无视轮次水位立即压。
        cap: ``history_l2_max`` 上限约束。

    Returns:
        需要移出的条目数（0 = 本就不压缩，L2 原样保留）。
    """
    n = _as_int(count, 0)
    if n <= 0:
        return 0
    keep = resolve_l2_keep(keep_turns, cap)
    if urgent:
        # 告急：只留 keep 条，剩下的立即交给 L3（n<=keep 时无可压）
        return max(0, n - keep)
    b = resolve_l2_batch(keep_turns, batch, cap)
    if n <= keep + b:
        # 未攒够一批 → 不动（这是"不要每多一条就摘要"的核心闸门）
        return 0
    # 一次性压回 keep；因 n > keep + batch 且 batch ≥ 1，结果恒 ≥ keep
    return n - keep


def resolve_urgent_ratio(context: Any = None) -> float:
    """告急水位阈值：``context.l3_urgent_ratio`` 优先，默认 0.75。"""
    raw = getattr(context, "l3_urgent_ratio", None) if context is not None else None
    return _as_ratio(raw, DEFAULT_URGENT_RATIO)


def exceeds_urgent_ratio(ratio: Any, context: Any = None) -> bool:
    """当前 token 水位是否越过告急线（越过 → 应置 ``ctx._l2_urgent``）。

    Args:
        ratio: 已用输入 / 可用输入预算。
        context: 可选，读取 ``l3_urgent_ratio`` 覆盖阈值。

    Returns:
        True 表示应立即把 L2 压给 L3。
    """
    if isinstance(ratio, bool) or ratio is None:
        return False
    try:
        r = float(ratio)
    except (TypeError, ValueError):
        return False
    if math.isnan(r):
        return False
    return r >= resolve_urgent_ratio(context)
