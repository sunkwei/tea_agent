"""tool_shield — 依据使用统计自动屏蔽长期不用的工具。

目标：60+ 工具全量暴露给模型，既有每请求固定 token 开销，也让模型更容易选错
工具。用 `tool_usage` 表（见 store/_tool_usage.py）把「装了但从不用」的工具从
暴露列表里摘掉。

⚠️ 三条不可妥协的安全不变式（都源于"屏蔽"是**会让 Agent 失去能力**的操作）：

1. **无数据 = 不屏蔽**。空表只代表"还没开始观测"。若按"零使用即不活跃"处理，
   新装机（或换新项目目录）第一次启动就会屏蔽掉全部工具 —— Agent 直接瘫痪。
2. **观测期未满不屏蔽从未用过的工具**。判"长期不用"必须有"长期"这个前提：
   只有当观测已持续 ≥ idle_days（以最早的使用记录为基准）时，零使用才等价于
   "这段时间它确实一次都没被需要"。用过但闲置的工具不受此限制（有 last_used）。
3. **自愈通路永不屏蔽**。屏蔽列表里如果混进了改配置/加工具/重载的工具，
   Agent 就失去了解除屏蔽的能力，故障无法自我恢复。

策略可用环境变量覆盖（无需改码）：
    TEA_TOOL_SHIELD=0            关闭自动屏蔽（应急逃生阀）
    TEA_TOOL_SHIELD_IDLE_DAYS=30 不活跃判定天数
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

from tea_agent.store._tool_usage import TABLE as USAGE_TABLE  # noqa: F401  文档/测试引用

logger = logging.getLogger("tool_shield")

DEFAULT_IDLE_DAYS = 30
# 环境变量阈值的合理上限（100 年）。超过它基本是手误（多打几个 0）——
# 静默接受会让"永不屏蔽"与"已关闭屏蔽"难以区分。
_MAX_IDLE_DAYS = 36500

# 自愈通路：改配置、建/重载/回滚工具、审批闸门。屏蔽它们等于拆掉解除屏蔽的梯子。
# 另加 exec/file —— 屏蔽后连"读代码改代码"都做不到，属于必须存在的最小能力集。
ALWAYS_PINNED = frozenset({
    "toolkit_exec",
    "toolkit_file",
    "toolkit_edit",
    "toolkit_diff",
    "toolkit_reload",
    "toolkit_save",
    "toolkit_config",
    "toolkit_approve",
    "toolkit_tool_usage",   # 本功能的观测/解除入口，屏蔽它自己就再也开不回来
    "toolkit_list_versions",
    "toolkit_rollback",
})


def _env_days() -> int:
    raw = os.environ.get("TEA_TOOL_SHIELD_IDLE_DAYS", "").strip()
    if not raw:
        return DEFAULT_IDLE_DAYS
    try:
        d = int(float(raw))
    except (ValueError, OverflowError):
        # OverflowError 不是可选捕获：float("1e999") == inf，int(inf) 直接抛。
        # 漏掉它会让一个写错的环境变量值在**每次构建工具列表时**抛异常。
        logger.warning("TEA_TOOL_SHIELD_IDLE_DAYS 非数值 (%r)，回退 %d",
                       raw, DEFAULT_IDLE_DAYS)
        return DEFAULT_IDLE_DAYS
    if d <= 0:
        logger.warning("TEA_TOOL_SHIELD_IDLE_DAYS 必须为正数 (%r)，回退 %d",
                       raw, DEFAULT_IDLE_DAYS)
        return DEFAULT_IDLE_DAYS
    if d > _MAX_IDLE_DAYS:
        # 超出百年基本是手误（多打几个 0）。刻意不静默接受：判定会永远不屏蔽，
        # 与"关掉屏蔽"难以区分，回退默认值并告警更容易发现配置错误。
        logger.warning("TEA_TOOL_SHIELD_IDLE_DAYS 超出合理上限 %d (%r)，回退 %d",
                       _MAX_IDLE_DAYS, raw, DEFAULT_IDLE_DAYS)
        return DEFAULT_IDLE_DAYS
    return d


def shield_enabled() -> bool:
    """自动屏蔽是否生效（默认开；TEA_TOOL_SHIELD=0 关闭）。"""
    return os.environ.get("TEA_TOOL_SHIELD", "").strip().lower() not in (
        "0", "false", "no", "off",
    )


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:  # 老数据/手工写入可能是 naive，按 UTC 处理
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def evaluate(usage: dict[str, dict], *, known_tools, idle_days: int | None = None,
             now: datetime | None = None, oldest_observed: str | None = None,
             enabled: bool | None = None) -> dict:
    """纯函数策略求解（不碰 DB，便于单测覆盖边界）。

    Args:
        usage: {tool: {uses, last_used, pin, ...}}，来自 ToolUsageStore.all_usage()
        known_tools: 当前注册表里的工具名（决定"该不该为它做判定"）
        idle_days: 不活跃天数阈值
        now / oldest_observed: 可注入，便于测试时间相关分支
        enabled: 覆盖 shield_enabled()（测试用）

    Returns:
        {"shielded": {tool: reason}, "kept": {tool: reason}, "idle_days": int,
         "reason": str}  —— reason 非空表示整体不生效的原因（可观测性）
    """
    days = idle_days if idle_days is not None else _env_days()
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)
    on = shield_enabled() if enabled is None else bool(enabled)

    known = set(known_tools or ())
    shielded: dict[str, str] = {}
    kept: dict[str, str] = {}

    if not on:
        return {"shielded": {}, "kept": {}, "idle_days": days,
                "reason": "自动屏蔽已关闭（TEA_TOOL_SHIELD=0）"}
    if not usage:
        # 不变式 1：还没有任何观测数据
        return {"shielded": {}, "kept": {}, "idle_days": days,
                "reason": f"{USAGE_TABLE} 表为空，尚无使用数据，不做屏蔽"}

    # 不变式 2：观测期是否已满（以最早使用记录为准）
    observed_since = _parse_ts(oldest_observed) or min(
        (_parse_ts(v.get("first_used")) for v in usage.values()
         if _parse_ts(v.get("first_used"))),
        default=None,
    )
    observation_full = observed_since is not None and observed_since <= cutoff

    for tool in sorted(known):
        if tool in ALWAYS_PINNED:
            kept[tool] = "自愈通路/最小能力集，永不屏蔽"
            continue
        row = usage.get(tool)
        pin = (row or {}).get("pin")
        if pin == 1:
            kept[tool] = "手工保留（pin=1）"
            continue
        if pin == 0:
            shielded[tool] = "手工屏蔽（pin=0）"
            continue
        if row is None:
            # 注册表里有、但从未被调用过（也没有行）
            if observation_full:
                shielded[tool] = (f"观测已满 {days} 天且从未使用")
            else:
                kept[tool] = "尚无使用记录，且观测期未满，暂不屏蔽"
            continue
        uses = int(row.get("uses") or 0)
        last = _parse_ts(row.get("last_used"))
        if uses <= 0 or last is None:
            if observation_full:
                shielded[tool] = f"观测已满 {days} 天且从未使用"
            else:
                kept[tool] = "零使用但观测期未满，暂不屏蔽"
            continue
        if last <= cutoff:
            # 边界取「含」：闲置天数**恰好等于**阈值即视为不活跃（"30 天没用"
            # 按 30 天阈值就该屏蔽），避免边界语义悬空导致行为随浮点误差漂移。
            shielded[tool] = f"已闲置 {(now - last).days} 天（阈值 {days} 天）"
        else:
            kept[tool] = f"{uses} 次使用，最近 {(now - last).days} 天内"

    return {"shielded": shielded, "kept": kept, "idle_days": days, "reason": ""}


def _storage_or_none():
    """取**已存在**的 Storage；没有则 None（屏蔽逻辑永不阻断会话构建）。

    必须用 peek_storage 而非 get_storage：本函数在每次构建工具列表时被调用，
    用 get_storage 会在「裸用 Toolkit / 无会话」的进程里为了**决定不屏蔽任何东西**
    而顺手建出一个数据库文件 —— 读路径不该有写副作用。
    """
    try:
        from tea_agent.store import peek_storage

        return peek_storage()
    except Exception as e:  # noqa: BLE001 — 无库/只读库等环境下静默降级
        logger.debug("tool_shield: 取 storage 失败，跳过屏蔽: %s", e)
        return None


def shielded_tools(known_tools, storage=None) -> set[str]:
    """返回应屏蔽的工具名集合。fail-open：异常/无数据时返回空集。"""
    if not shield_enabled():
        return set()
    st = storage if storage is not None else _storage_or_none()
    if st is None:
        return set()
    try:
        store = st.tool_usage
        usage = store.all_usage()
        verdict = evaluate(usage, known_tools=known_tools,
                           oldest_observed=store.oldest_observed())
    except Exception as e:  # noqa: BLE001
        logger.warning("tool_shield: 判定失败，本次不屏蔽任何工具: %s", e)
        return set()
    if verdict.get("reason"):
        logger.debug("tool_shield: %s", verdict["reason"])
    return set(verdict["shielded"])


def apply_shield(tools: list[dict], known_names=None, storage=None,
                 log: bool = True) -> tuple[list[dict], set[str]]:
    """从工具定义列表剔除被屏蔽者。返回 (保留列表, 屏蔽名集合)。

    tools 元素为 OpenAI function schema；known_names 缺省时从 tools 自身提取。
    """
    if not tools:
        return tools, set()
    names = set(known_names) if known_names is not None else {
        t.get("function", {}).get("name") for t in tools
    }
    hidden = shielded_tools(names, storage=storage)
    if not hidden:
        return tools, set()
    kept = [t for t in tools
            if t.get("function", {}).get("name") not in hidden]
    if log:
        logger.info("tool_shield: 屏蔽 %d/%d 个长期未使用工具: %s",
                    len(hidden), len(tools), ", ".join(sorted(hidden)))
    return kept, hidden
