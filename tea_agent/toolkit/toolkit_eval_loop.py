"""
toolkit_eval_loop — 确定性 Rubric 评分闭环（借鉴 PenguinHarness self-evolve 机制）。

设计原则（来自 penguin-harness/examples/self-improving-agent/self-evolve.ts）：
- Rubric = 声明式确定性评分规则（可读、可复现、无 LLM 参与）
- 多轮运行取平均，对抗模型随机性（RUNS 默认 3）
- keep-or-roll-back：仅当平均分提升才保留改进，否则回滚

典型闭环：
1. 定义 rubric 规则列表 rules
2. 改进前: action='evaluate' 对多次执行结果打分 → baseline
3. 改进后: action='evaluate' 重跑同 rules → candidate
4. action='compare' 对比 → keep / rollback / no_change

rules 支持三种格式（自动归一化）：
- 列表（推荐）: [{"pattern": "...", "match": "regex", "description": "..."}]
- 字符串行: 每行 "pattern|match|description"，match 可省略（默认 regex）
- 字典: {"rule_id": {"pattern": "...", "match": "...", "description": "..."}}

match 类型:
- regex         : 正则搜索（默认）
- contains      : 子串包含
- line          : 存在某非空行与 pattern 完全相等
- line_contains : 存在某行包含 pattern
"""

import json
import logging
import re

logger = logging.getLogger("toolkit")

# ── 规则归一化与匹配 ─────────────────────────────────────────────

def _normalize_rules(rules) -> list[dict]:
    """把三种规则格式归一化为 list[dict]：{pattern, match, description}。"""
    if rules is None:
        return []
    if isinstance(rules, dict):
        out = []
        for rid, r in rules.items():
            if isinstance(r, str):
                out.append({"pattern": r, "match": "regex", "description": rid})
            else:
                out.append({
                    "pattern": r.get("pattern", ""),
                    "match": r.get("match", "regex"),
                    "description": r.get("description", rid),
                })
        return out
    if isinstance(rules, str):
        out = []
        for line in rules.strip().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = [p.strip() for p in line.split("|")]
            pattern = parts[0]
            match = parts[1] if len(parts) > 1 and parts[1] else "regex"
            desc = parts[2] if len(parts) > 2 else pattern
            out.append({"pattern": pattern, "match": match, "description": desc})
        return out
    out = []
    for r in rules:
        if isinstance(r, str):
            out.append({"pattern": r, "match": "regex", "description": r})
        else:
            out.append({
                "pattern": r.get("pattern", ""),
                "match": r.get("match", "regex"),
                "description": r.get("description", r.get("pattern", "")),
            })
    return out


def _match_rule(text: str, rule: dict) -> bool:
    """单条规则匹配（确定性，无 LLM）。"""
    pattern = rule.get("pattern", "")
    match_type = rule.get("match", "regex")
    if not pattern:
        return False
    try:
        if match_type == "regex":
            return re.search(pattern, text, re.MULTILINE) is not None
        if match_type == "contains":
            return pattern in text
        if match_type == "line":
            return any(l.strip() == pattern for l in text.splitlines() if l.strip())
        if match_type == "line_contains":
            return any(pattern in l for l in text.splitlines())
    except re.error:
        return False
    return False


def _score_once(text: str, rules: list[dict]) -> dict:
    """单次确定性打分。"""
    detail = []
    score = 0
    for rule in rules:
        ok = _match_rule(text, rule)
        detail.append({
            "ok": ok,
            "points": 1 if ok else 0,
            "description": rule.get("description", ""),
        })
        if ok:
            score += 1
    return {"score": score, "max_score": len(rules), "detail": detail}


# ── 主入口 ───────────────────────────────────────────────────────

def toolkit_eval_loop(
    action: str = "score",
    text: str = None,
    texts: list = None,
    rules: object = None,
    baseline: object = None,
    candidate: object = None,
    threshold: float = 0.0,
    detail: bool = True,
) -> dict:
    """
    确定性 Rubric 评分闭环 — 借鉴 PenguinHarness 自我进化机制。

    参数:
        action: score=单文本打分 / evaluate=多轮平均 / compare=keep-or-rollback / template=输出规则模板
        text: [score] 待评分文本
        texts: [evaluate] 多轮执行结果文本列表（取平均）
        rules: 评分规则（list / dict / 字符串行，见模块 docstring）
        baseline: [compare] 基线分数（float 或 score/evaluate 返回的 dict）
        candidate: [compare] 改进后分数（float 或 dict）
        threshold: [compare] 保留阈值，delta 需 > threshold 才 keep（默认 0）
        detail: 是否返回逐条明细

    返回:
        dict: 含 score/mean_score、max_score、detail、decision 等
    """
    logger.info(f"toolkit_eval_loop called: action={action!r}")

    if action == "template":
        return {
            "ok": True,
            "template": json.dumps([
                {"pattern": r"<!-- ACME -->", "match": "line", "description": "[convention] marker line"},
                {"pattern": r"^# Report:", "match": "regex", "description": "[convention] title format"},
                {"pattern": "Classification: INTERNAL", "match": "contains", "description": "[convention] metadata"},
                {"pattern": "Reviewed-by: Aurora Team", "match": "line", "description": "[convention] sign-off"},
            ], ensure_ascii=False, indent=2),
            "note": "把规则换成你的任务约定；match 支持 regex/contains/line/line_contains",
        }

    if action == "score":
        if text is None:
            return {"ok": False, "error": "action='score' 需要 text 参数"}
        rules_n = _normalize_rules(rules)
        if not rules_n:
            return {"ok": False, "error": "rules 为空，无法评分"}
        result = _score_once(text, rules_n)
        passed = result["score"] / result["max_score"] if result["max_score"] else 0
        out = {
            "ok": True,
            "score": result["score"],
            "max_score": result["max_score"],
            "passed_ratio": round(passed, 4),
            "detail": result["detail"] if detail else None,
        }
        return out

    if action == "evaluate":
        if not texts:
            return {"ok": False, "error": "action='evaluate' 需要 texts（多轮结果文本列表）"}
        rules_n = _normalize_rules(rules)
        if not rules_n:
            return {"ok": False, "error": "rules 为空，无法评分"}
        per_run = []
        for i, t in enumerate(texts):
            r = _score_once(t, rules_n)
            per_run.append({"run": i + 1, "score": r["score"], "detail": r["detail"] if detail else None})
        scores = [p["score"] for p in per_run]
        mean = sum(scores) / len(scores) if scores else 0.0
        # 逐规则通过率（跨轮）
        rule_stats = []
        if detail:
            for idx, rule in enumerate(rules_n):
                hits = sum(1 for p in per_run if p["detail"] and p["detail"][idx]["ok"])
                rule_stats.append({
                    "description": rule.get("description", ""),
                    "hits": hits,
                    "runs": len(per_run),
                    "rate": round(hits / len(per_run), 4) if per_run else 0,
                })
        return {
            "ok": True,
            "mean_score": round(mean, 4),
            "max_score": len(rules_n),
            "runs": len(per_run),
            "per_run": per_run,
            "rule_stats": rule_stats,
            "detail": detail,
        }

    if action == "compare":
        def _extract(v):
            if isinstance(v, (int, float)):
                return float(v)
            if isinstance(v, dict):
                if "mean_score" in v:
                    return float(v["mean_score"])
                if "score" in v:
                    return float(v["score"])
            return None

        b = _extract(baseline)
        c = _extract(candidate)
        if b is None or c is None:
            return {"ok": False, "error": "compare 需要 baseline 和 candidate（分数或 evaluate 返回的 dict）"}
        delta = c - b
        if delta > threshold:
            decision = "keep"
        elif delta < -threshold:
            decision = "rollback"
        else:
            decision = "no_change"
        return {
            "ok": True,
            "baseline": b,
            "candidate": c,
            "delta": round(delta, 4),
            "threshold": threshold,
            "decision": decision,
            "verdict": {
                "keep": f"平均分提升 {delta:+.4f} > {threshold}，保留 N+1",
                "rollback": f"平均分下降 {delta:+.4f}，回滚到基线",
                "no_change": f"平均分变化 {delta:+.4f} 在阈值内，保持现状",
            }[decision],
        }

    return {"ok": False, "error": f"未知 action: {action!r}（支持 score/evaluate/compare/template）"}


def meta_toolkit_eval_loop() -> dict:
    """OpenAI 工具 schema 元数据 — 供 tlk.py 扫描注册。"""
    return {
        "type": "function",
        "function": {
            "name": "toolkit_eval_loop",
            "description": (
                "确定性 Rubric 评分闭环（借鉴 PenguinHarness self-evolve）。"
                "score=单文本按规则打分; evaluate=多轮结果取平均(对抗随机性); "
                "compare=对比基线/改进后分数做 keep-or-rollback 决策; template=规则模板。"
                "规则为纯代码确定性匹配(regex/contains/line)，无 LLM 参与，可复现。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["score", "evaluate", "compare", "template"],
                        "description": "score=单文本打分 / evaluate=多轮平均 / compare=keep-or-rollback / template=规则模板",
                        "default": "score",
                    },
                    "text": {"type": "string", "description": "[score] 待评分文本"},
                    "texts": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "[evaluate] 多轮执行结果文本列表(取平均)",
                    },
                    "rules": {
                        "type": "array",
                        "items": {"type": "object", "properties": {"pattern": {"type": "string"}, "match": {"type": "string", "enum": ["regex", "contains", "line", "line_contains"]}, "description": {"type": "string"}}, "required": ["pattern", "match"]},
                        "description": (
                            "评分规则列表: [{\"pattern\": \"...\", \"match\": \"regex|contains|line|line_contains\", \"description\": \"...\"}]。"
                            "（运行时也接受单个对象或 'pattern|match|description' 字符串行）"
                        ),
                    },
                    "baseline": {
                        "type": "object",
                        "description": "[compare] 基线分数：evaluate/score 返回的 dict，或直接传数字（JSON 数字亦接受）",
                    },
                    "candidate": {
                        "type": "object",
                        "description": "[compare] 改进后分数：evaluate/score 返回的 dict，或直接传数字（JSON 数字亦接受）",
                    },
                    "threshold": {
                        "type": "number",
                        "description": "[compare] 保留阈值，delta 需 > threshold 才 keep",
                        "default": 0.0,
                    },
                    "detail": {
                        "type": "boolean",
                        "description": "是否返回逐条明细",
                        "default": True,
                    },
                },
                "required": [],
            },
        },
    }
