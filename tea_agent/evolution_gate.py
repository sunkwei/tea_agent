"""进化闸门 — 把 keep-or-rollback 接进自进化流程（B2）。

背景：toolkit_self_evolve 原有门槛只有「编译通过 + 测试通过」，
无法回答「这一版是否比上一版更好」。本模块在 self_evolve 成功返回时，
自动跑 EvolutionBench（确定性、无 LLM）并把分数写进进化曲线，
再与上一数据点对比给出 keep / rollback 建议（对齐 toolkit_eval_loop 闭环）。

三档模式（config evolution.gate 或环境变量 TEA_EVOLVE_GATE）：
- off      : 完全关闭（零开销）
- advisory : 跑基准 + 记录曲线 + 在结果里附建议（默认，不改变任何文件）
- enforce  : 决策为 rollback 时，自动从 self_evolve 生成的 .bak 恢复该文件

阈值：TEA_EVOLVE_GATE_THRESHOLD（默认 0.0，即「必须严格提升才算 keep」）
"""

from __future__ import annotations

import glob
import logging
import os
import shutil

logger = logging.getLogger("tea_agent.evolution.gate")

__all__ = ["gate_mode", "gate_threshold", "evaluate_evolution", "install_evolution_gate"]

_VALID_MODES = ("off", "advisory", "enforce")


def gate_mode() -> str:
    """解析闸门模式：环境变量 > config evolution.gate > advisory（默认）。"""
    env = os.environ.get("TEA_EVOLVE_GATE", "").strip().lower()
    if env in _VALID_MODES:
        return env
    try:
        from tea_agent.config import get_config

        raw = getattr(get_config(), "evolution", None)
        val = None
        if isinstance(raw, dict):
            val = raw.get("gate")
        elif raw is not None:
            val = getattr(raw, "gate", None)
        if isinstance(val, str) and val.strip().lower() in _VALID_MODES:
            return val.strip().lower()
    except Exception:  # noqa: BLE001 — 配置不可用时保持默认
        pass
    return "advisory"


def gate_threshold() -> float:
    """保留阈值：delta 必须严格大于它才算 keep。"""
    env = os.environ.get("TEA_EVOLVE_GATE_THRESHOLD", "").strip()
    if env:
        try:
            return float(env)
        except ValueError:
            pass
    try:
        from tea_agent.config import get_config

        raw = getattr(get_config(), "evolution", None)
        val = raw.get("gate_threshold") if isinstance(raw, dict) else getattr(raw, "gate_threshold", None)
        if val is not None:
            return float(val)
    except Exception:  # noqa: BLE001
        pass
    return 0.0


def _restore_latest_backup(rel_path: str) -> dict:
    """从 self_evolve 生成的 .bak.<ts> 恢复文件（取最新一份）。"""
    directory = os.path.dirname(rel_path) or "."
    base = os.path.basename(rel_path)
    try:
        cands = sorted(glob.glob(os.path.join(directory, base + ".bak.*")))
    except OSError:
        return {"ok": False, "error": "备份扫描失败"}
    if not cands:
        return {"ok": False, "error": f"未找到 {base}.bak.* 备份"}
    latest = cands[-1]
    try:
        shutil.copy2(latest, rel_path)
    except OSError as e:
        return {"ok": False, "error": f"恢复失败: {e}"}
    logger.warning("evolution_gate: 已回滚 %s ← %s", rel_path, os.path.basename(latest))
    return {"ok": True, "restored_from": os.path.basename(latest)}


def evaluate_evolution(kind: str = "safety", threshold: float | None = None,
                       tag: str = "post-evolve") -> dict:
    """跑基准 + 记录曲线 + 与上一数据点对比 → keep/rollback 建议。

    Args:
        kind: 基准类别（默认只跑 safety，秒级；"all" 跑全量）
        threshold: 保留阈值（None = gate_threshold()）
        tag: 曲线快照标签

    Returns:
        {mode, bench, gate, threshold}
    """
    from tea_agent.evaluation.evo_bench import compare_with_history, run_bench

    thr = gate_threshold() if threshold is None else float(threshold)
    kind_arg = None if (kind or "").lower() in ("", "all") else kind
    agg = run_bench(root=".", kind=kind_arg, record=True, tag=tag)
    gate = compare_with_history(baseline=None, candidate=agg, threshold=thr)
    return {"mode": gate_mode(), "bench": agg, "gate": gate, "threshold": thr}


def install_evolution_gate(registry) -> None:
    """在工具执行链路挂 post-hook：self_evolve 成功后做基准快照与回滚判定。

    Args:
        registry: ToolHookRegistry 实例（tea_agent.tool_hooks.tool_hooks）
    """
    if getattr(registry, "_evolution_gate_installed", False):
        return

    def _post(tool_name, args, result):
        if tool_name != "toolkit_self_evolve" or gate_mode() == "off":
            return None
        if not (isinstance(result, dict) and result.get("ok")):
            return None  # 只有成功落地才值得度量
        try:
            ev = evaluate_evolution()
        except Exception as e:  # noqa: BLE001 — 度量失败不得污染自进化主流程
            logger.debug("evolution_gate: 基准执行跳过: %s", e)
            return None

        gate = ev.get("gate") or {}
        info = {
            "mode": ev.get("mode"),
            "decision": gate.get("decision"),
            "score": gate.get("candidate"),
            "baseline": gate.get("baseline"),
            "delta": gate.get("delta"),
            "threshold": ev.get("threshold"),
            "advice": gate.get("advice"),
        }

        # enforce + rollback → 从 .bak 自动恢复
        if info["mode"] == "enforce" and info["decision"] == "rollback":
            info["rollback"] = _restore_latest_backup(str(args.get("file_path", "")))

        try:
            from tea_agent.audit_log import audit_log

            audit_log.record("evolve/gate", tool=tool_name,
                             status=str(info.get("decision") or "unknown"),
                             detail={k: v for k, v in info.items() if k != "advice"})
        except Exception:  # noqa: BLE001 — 审计不可用不影响结论
            pass

        if isinstance(result, dict):
            result["evolution_gate"] = info
            return {"result": result}
        return None

    registry.register_post("toolkit_self_evolve", _post)
    registry._evolution_gate_installed = True
    logger.debug("evolution_gate: 已挂载 (mode=%s)", gate_mode())
