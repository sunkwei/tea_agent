"""toolkit_evo_bench — EvolutionBench 基准入口（Agent 可自调用）。

把「自进化效果」从主观描述变成可复现数字：
- run     : 跑确定性基准（无 LLM），可选记录到进化曲线
- history : 查看曲线数据点（分数随时间/git 版本的变化）
- compare : keep-or-rollback 决策（delta > threshold 才建议保留）

依赖：tea_agent/evaluation/evo_bench.py
"""

import logging

logger = logging.getLogger("toolkit")


def meta_toolkit_evo_bench():
    """Meta toolkit evo bench."""
    return {
        "type": "function",
        "function": {
            "name": "toolkit_evo_bench",
            "description": (
                "EvolutionBench 自进化基准：对 tea_agent 自身做确定性打分（纯代码 check，无 LLM）。"
                "action=run 执行基准并可记录到进化曲线；action=history 查看历史数据点；"
                "action=compare 对改进做 keep-or-rollback 决策（分数未提升则建议回滚）。"
                "用于验证自我修改是否真的带来提升，而非只靠「测试通过」。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["run", "history", "compare"],
                        "description": "run=执行基准; history=查看进化曲线; compare=保留/回滚决策",
                    },
                    "kind": {
                        "type": "string",
                        "description": "只跑指定类别：safety / tooling / all（默认 all）",
                    },
                    "root": {
                        "type": "string",
                        "description": "项目根目录，默认当前目录",
                    },
                    "record": {
                        "type": "boolean",
                        "description": "run 时是否记录进进化曲线（默认 false）",
                    },
                    "tag": {
                        "type": "string",
                        "description": "本次快照标签，如 after-B2",
                    },
                    "threshold": {
                        "type": "number",
                        "description": "compare 的保留阈值：delta 需大于此值才 keep（默认 0）",
                    },
                    "verbose": {
                        "type": "boolean",
                        "description": "run 时是否返回逐 check 明细（默认 true）",
                    },
                },
                "required": ["action"],
            },
        },
    }


def toolkit_evo_bench(action: str = "run", kind: str = "", root: str = ".",
                      record: bool = False, tag: str = "", threshold: float = 0.0,
                      verbose: bool = True) -> dict:
    """EvolutionBench 基准入口。

    Args:
        action: run / history / compare
        kind: 类别过滤（safety/tooling/all），空=all
        root: 项目根目录
        record: run 时是否记录进曲线
        tag: 快照标签
        threshold: compare 的保留阈值
        verbose: 是否返回逐 check 明细

    Returns:
        dict：基准结果 / 历史 / 决策；失败时含 ``error``
    """
    logger.info(f"toolkit_evo_bench called: action={action!r}, kind={kind!r}, record={record!r}")

    try:
        from tea_agent.evaluation.evo_bench import (
            compare_with_history,
            history,
            history_path,
            run_bench,
        )
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"基准引擎不可用: {e}"}

    act = (action or "run").strip().lower()
    k = (kind or "").strip().lower()
    kind_arg = None if k in ("", "all") else k

    if act == "run":
        agg = run_bench(root=root or ".", kind=kind_arg, record=bool(record),
                        tag=(tag or None))
        agg["ok"] = bool(agg.get("ok"))
        agg["history_path"] = history_path()
        if not verbose:
            agg.pop("results", None)
        return agg

    if act == "history":
        pts = history(limit=0)
        return {
            "ok": True,
            "points": len(pts),
            "path": history_path(),
            "series": [
                {"ts": p.get("ts"), "tag": p.get("tag"), "score": p.get("score"),
                 "passed": p.get("passed"), "total": p.get("total"), "git": p.get("git")}
                for p in pts[-20:]
            ],
        }

    if act == "compare":
        pts = history(limit=0)
        if not pts:
            return {"ok": False, "error": "进化曲线为空：先运行 action=run, record=true"}
        candidate = pts[-1]
        if len(pts) < 2:
            return {"ok": False, "error": "曲线仅 1 个数据点，无法对比基线", "candidate": candidate}
        res = compare_with_history(baseline=pts[-2], candidate=candidate,
                                   threshold=float(threshold))
        res["baseline_point"] = pts[-2]
        res["candidate_point"] = candidate
        return res

    return {"ok": False, "error": f"未知 action: {action!r}（可选 run/history/compare）"}
