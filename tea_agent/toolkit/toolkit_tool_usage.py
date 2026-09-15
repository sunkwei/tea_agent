"""toolkit_tool_usage — 工具使用统计观测台（读写 tool_usage 表 / 控制自动屏蔽）。

action:
    report        统计表 + 当前生效档位 + 将被屏蔽清单 + 屏蔽开关状态
    pin           永久保留某工具（pin=1）
    unpin         永久屏蔽某工具（pin=0）
    auto          恢复某工具的自动判定（pin=NULL）
    reset         清空统计，重新开始观测
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger("toolkit.tool_usage")

_storage = None


def _store():
    global _storage
    if _storage is not None:
        return _storage
    try:
        from tea_agent.store import get_storage

        _storage = get_storage()
    except Exception as e:  # noqa: BLE001 — 无库/只读环境下仍可报告"未启用"
        logger.debug("toolkit_tool_usage: 取不到 storage: %s", e)
        _storage = None
    return _storage


def _known_tools() -> set:
    """当前注册表中 LLM 可见的工具全集。

    必须以注册表为准、而非统计表：「从未被调用过的工具」正是本功能唯一
    该屏蔽的对象，若以统计表为集合，它们永远不参与判定，功能会静默失效。
    """
    try:
        from tea_agent import tlk

        if tlk.toolkit is not None:
            return set(tlk.llm_tool_names(tlk.toolkit.meta_map.keys()))
    except Exception as e:  # noqa: BLE001 — 取不到活动实例时回退目录扫描
        logger.debug("tlk.toolkit 不可用: %s", e)
    try:
        import os.path as osp

        from tea_agent.tlk import LLM_TOOL_EXCLUDES

        d = osp.join(osp.dirname(osp.dirname(osp.abspath(__file__))), "toolkit")
        return {f[:-3] for f in os.listdir(d)
                if f.startswith("toolkit_") and f.endswith(".py")
                and f[:-3] not in LLM_TOOL_EXCLUDES}
    except OSError:
        return set()


def _status_lines(tu) -> list[str]:
    """汇总屏蔽开关状态（含逃生阀提示）。"""
    from tea_agent.tool_shield import ALWAYS_PINNED, DEFAULT_IDLE_DAYS, shield_enabled

    env_idle = os.environ.get("TEA_TOOL_SHIELD_IDLE_DAYS", "").strip()
    idle_days = tu["idle_days"]
    lines = [f"自动屏蔽: {'开' if shield_enabled() else '关'} | "
             f"闲置阈值: {idle_days} 天"
             + (f"（TEA_TOOL_SHIELD_IDLE_DAYS={env_idle}）"
                if env_idle and str(idle_days) != env_idle else "")]
    if env_idle and str(idle_days) != env_idle:
        lines.append(f"  注：环境变量值非法，已回退 {idle_days} 天")
    if not shield_enabled():
        lines.append(f"  当前默认阈值 {DEFAULT_IDLE_DAYS} 天（关闭状态下不参与判定）")
    lines.append(f"  永不屏蔽（自愈通路）: {len(ALWAYS_PINNED)} 个")
    return lines


def toolkit_tool_usage(action: str = "report", tool: str = "") -> dict:
    """查询/维护工具使用统计与屏蔽策略。"""
    action = (action or "report").strip().lower()
    st = _store()
    if st is None:
        return {"ok": False,
                "error": "无法访问存储（tool_usage 表不可用），功能未启用"}

    if action not in ("report", "pin", "unpin", "auto", "reset"):
        return {"ok": False,
                "error": f"未知 action {action!r}；支持 report/pin/unpin/auto/reset"}

    try:
        tus = st.tool_usage
        usage = tus.all_usage()
    except Exception as e:  # noqa: BLE001
        logger.warning("tool_usage 查询失败: %s", e)
        return {"ok": False, "error": f"存储不可用，功能未启用: {e}"}

    if action in ("pin", "unpin", "auto"):
        if not tool:
            return {"ok": False, "error": f"{action} 需要 tool 参数（工具名）"}
        want = {"pin": 1, "unpin": 0, "auto": None}[action]
        known = _known_tools()
        if known and tool not in known:
            return {"ok": False,
                    "error": f"未注册的工具 {tool!r}；用 report 查看可用工具名"}
        # 允许对「已注册但尚未被调用过」的工具设覆盖：新工具常需要预先 pin=1
        # 保住（否则观测期满即被屏蔽），而它此刻本就没有统计行。
        ok = tus.set_pin(tool, want)
        return {"ok": ok, "tool": tool,
                "pin": want,
                "message": f"{tool} 设为 {'自动判定' if want is None else ('永久保留' if want else '永久屏蔽')}"
                if ok else "设置失败（见日志）"}

    if action == "reset":
        n = 0
        try:
            c = st.conn.cursor()
            n = int(c.execute("DELETE FROM tool_usage").rowcount or 0)
            c.connection.commit()
            c.close()
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": f"清空失败: {e}"}
        return {"ok": True, "cleared": n,
                "message": f"已清空 {n} 条统计；屏蔽判定在攒到新数据前不会生效"}

    # ── report ──
    from tea_agent.tool_shield import ALWAYS_PINNED, evaluate, shield_enabled

    known = _known_tools() or set(usage)

    oldest = None
    try:
        oldest = tus.oldest_observed()
    except Exception as e:  # noqa: BLE001 — 旧库无该列时回退
        logger.debug("oldest_observed 不可用: %s", e)
    v = evaluate(usage, known_tools=known or set(usage), oldest_observed=oldest)

    lines = _status_lines(v)
    out = {
        "ok": True,
        "action": "report",
        "shield_enabled": shield_enabled(),
        "idle_days": v["idle_days"],
        "observed_tools": len(usage),
        "registered_tools": len(known),
        "never_observed": sorted((set(known) | set(v["kept"])) - set(usage)),
        "tools": [{"tool": t, "uses": d.get("uses", 0),
                   "last_used": d.get("last_used"), "pin": d.get("pin")}
                  for t, d in sorted(usage.items(), key=lambda kv: -kv[1]["uses"])],
        "shielded": v["shielded"],
        "kept": {k: r for k, r in v["kept"].items() if k not in ALWAYS_PINNED},
        "message": "\n".join(lines + [
            f"将屏蔽 {len(v['shielded'])} 个：" + (", ".join(sorted(v["shielded"]))
                                              or "（无）")]),
    }
    if v.get("reason"):
        out["note"] = v["reason"]
    return out


def meta_toolkit_tool_usage() -> dict:
    """Meta toolkit tool usage."""
    return {
        "type": "function",
        "function": {
            "name": "toolkit_tool_usage",
            "description": (
                "工具使用次数统计与「长期不用自动屏蔽」的控制。"
                "report=统计表/将屏蔽清单/开关状态；pin=永久保留；unpin=永久屏蔽；"
                "auto=恢复自动判定；reset=清空重新观测。"
                "注：尚无使用数据时不会屏蔽任何工具（避免新环境把工具全屏蔽）。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["report", "pin", "unpin", "auto", "reset"],
                        "default": "report",
                    },
                    "tool": {"type": "string",
                             "description": "目标工具名（pin/unpin/auto 必填）"},
                },
            },
        },
    }
