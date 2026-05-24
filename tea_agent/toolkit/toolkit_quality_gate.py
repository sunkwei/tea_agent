"""代码质量门禁。

支持两种模式:
- gating: 单文件门禁检查，复杂度/LOC/注释覆盖率超标则拒绝
- report: 目录级质量报告，标记风险文件
"""

import os
import logging

logger = logging.getLogger("toolkit")


def toolkit_quality_gate(
    action: str,
    file_path: str = None,
    directory: str = None,
    max_cyclomatic: int = 15,
    max_loc: int = 200,
    min_doc_coverage: float = 0.5,
    fail_fast: bool = True,
    output_format: str = "summary",
) -> dict:
    """
    代码质量门禁 — 复杂度/LOC/注释覆盖 三重检查

    Args:
        action (str): Description.
        file_path (str): Description.
        directory (str): Description.
        max_cyclomatic (int): Description.
        max_loc (int): Description.
        min_doc_coverage (float): Description.
        fail_fast (bool): Description.
        output_format (str): Description.

    Returns:
        dict: Description.
    """
    cwd = os.getcwd()
    if action == "gating":
        return _run_gating(cwd, file_path, max_cyclomatic, max_loc,
                           min_doc_coverage, fail_fast)
    elif action == "report":
        return _run_report(cwd, directory, max_cyclomatic, max_loc,
                           min_doc_coverage, output_format)
    else:
        return {"ok": False, "error": f"未知 action: {action}，可用: gating, report"}


def _run_gating(cwd, file_path, max_cyclomatic, max_loc,
                min_doc_coverage, fail_fast):
    """
    运行单文件门禁检查

    Args:
        cwd: Description.
        file_path: Description.
        max_cyclomatic: Description.
        max_loc: Description.
        min_doc_coverage: Description.
        fail_fast: Description.
    """
    from tea_agent.lsp.ts_analyzer import compute_metrics, find_dead_code

    full = file_path if os.path.isabs(file_path) else os.path.join(cwd, file_path)
    if not os.path.isfile(full):
        return {"ok": False, "error": f"文件不存在: {full}"}

    metrics = compute_metrics(cwd, full)
    if not metrics.get("ok"):
        return {"ok": False, "error": f"度量计算失败: {metrics.get('error', 'unknown')}"}

    violations = []
    passed = True
    for item in metrics.get("items", []):
        m = item["metrics"]
        item_violations = _check_item_rules(m, item["kind"], max_cyclomatic, max_loc)
        if item_violations:
            violations.append({
                "name": item["name"], "kind": item["kind"],
                "line": item["line"], "violations": item_violations,
            })
            passed = False
            if fail_fast:
                break

    total_defined = metrics.get("functions", 0)
    with_docs = metrics.get("with_docstrings", 0)
    doc_ratio = with_docs / total_defined if total_defined > 0 else 1.0
    if doc_ratio < min_doc_coverage:
        passed = False
        violations.append(_make_global_violation("doc_coverage",
            f"{doc_ratio:.0%}", f"{min_doc_coverage:.0%}", "medium"))

    dead = find_dead_code(cwd, full)
    if dead.get("dead_count", 0) > 0:
        real_dead = [d for d in dead.get("dead_functions", [])
                     if not d.startswith(("toolkit_", "meta_", "test_"))]
        if real_dead:
            passed = False
            violations.append(_make_global_violation("dead_code",
                f"{len(real_dead)} dead: {real_dead}", "0", "medium"))

    return {
        "ok": True, "passed": passed, "file": file_path,
        "total_items": len(metrics.get("items", [])),
        "violations": violations, "violation_count": len(violations),
        "thresholds": {"max_cyclomatic": max_cyclomatic,
                       "max_loc": max_loc, "min_doc_coverage": min_doc_coverage},
    }


def _check_item_rules(m, kind, max_cyclomatic, max_loc):
    """
    检查单项指标是否违规

    Args:
        m: Description.
        kind: Description.
        max_cyclomatic: Description.
        max_loc: Description.
    """
    item_violations = []
    if m["cyclomatic"] > max_cyclomatic:
        item_violations.append({
            "rule": "cyclomatic", "actual": m["cyclomatic"],
            "limit": max_cyclomatic,
            "severity": "critical" if m["cyclomatic"] > max_cyclomatic * 2 else "high",
        })
    if m["loc"] > max_loc:
        item_violations.append({
            "rule": "loc", "actual": m["loc"], "limit": max_loc,
            "severity": "high" if m["loc"] > max_loc * 2 else "medium",
        })
    if not m["has_docstring"] and kind in ("function", "method"):
        item_violations.append({
            "rule": "docstring", "actual": "missing",
            "limit": "required", "severity": "low",
        })
    return item_violations


def _make_global_violation(rule, actual, limit, severity):
    """
    创建模块级违规条目

    Args:
        rule: Description.
        actual: Description.
        limit: Description.
        severity: Description.
    """
    return {
        "name": "⚠全局", "kind": "module", "line": 0,
        "violations": [{"rule": rule, "actual": actual,
                        "limit": limit, "severity": severity}],
    }



def _run_report(cwd, directory, max_cyclomatic, max_loc,
                min_doc_coverage, output_format):
    """
    运行目录质量报告

    Args:
        cwd: Description.
        directory: Description.
        max_cyclomatic: Description.
        max_loc: Description.
        min_doc_coverage: Description.
        output_format: Description.
    """
    from tea_agent.lsp.ts_analyzer import compute_metrics

    target = directory or cwd
    if not os.path.isabs(target):
        target = os.path.join(cwd, target)
    if not os.path.isdir(target):
        return {"ok": False, "error": f"目录不存在: {target}"}

    import glob as _glob
    py_files = _glob.glob(os.path.join(target, "**", "*.py"), recursive=True)
    py_files = [f for f in py_files
                if not any(s in f for s in (".tea_agent_run/", "__pycache__/",
                                            ".git/", "/build/", "/dist/"))]

    results = []
    total_pass = 0
    total_fail = 0
    all_violations = []

    for pf in py_files:
        rel = os.path.relpath(pf, cwd)
        metrics = compute_metrics(cwd, pf)
        if not metrics.get("ok"):
            continue

        file_violations = []
        for item in metrics.get("items", []):
            m = item["metrics"]
            if m["cyclomatic"] > max_cyclomatic:
                file_violations.append({
                    "file": rel, "name": item["name"], "kind": item["kind"],
                    "line": item["line"], "rule": "cyclomatic",
                    "actual": m["cyclomatic"], "limit": max_cyclomatic,
                })

        if file_violations:
            total_fail += 1
            all_violations.extend(file_violations)
            results.append({"file": rel, "passed": False,
                           "violations": file_violations})
        else:
            total_pass += 1
            results.append({"file": rel, "passed": True, "violations": []})

    results.sort(key=lambda r: len(r["violations"]), reverse=True)
    all_violations.sort(key=lambda v: v["actual"], reverse=True)

    return {
        "ok": True, "directory": target,
        "files_scanned": len(results),
        "passed": total_pass, "failed": total_fail,
        "pass_rate": f"{total_pass / len(results):.0%}" if results else "N/A",
        "top_violations": all_violations[:20] if output_format == "summary"
                          else all_violations,
        "failed_files": [r for r in results if not r["passed"]][:20],
        "thresholds": {"max_cyclomatic": max_cyclomatic,
                       "max_loc": max_loc,
                       "min_doc_coverage": min_doc_coverage},
    }


def meta_toolkit_quality_gate() -> dict:
    """
    Meta toolkit quality gate.

    Returns:
        dict: Description.
    """
    return {
        "type": "function",
        "function": {
            "name": "toolkit_quality_gate",
            "description": "代码质量门禁工具。gating=单文件检查(复杂度/LOC/注释覆盖/死代码), report=目录质量报告。",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string",
                               "enum": ["gating", "report"],
                               "description": "gating=单文件门禁, report=目录质量报告"},
                    "file_path": {"type": "string",
                                  "description": "[gating] 目标文件路径"},
                    "directory": {"type": "string",
                                  "description": "[report] 目标目录"},
                    "max_cyclomatic": {"type": "integer",
                                       "description": "圈复杂度上限，默认 15", "default": 15},
                    "max_loc": {"type": "integer",
                                "description": "函数最大行数，默认 200", "default": 200},
                    "min_doc_coverage": {"type": "number",
                                         "description": "最低注释覆盖率 (0.0-1.0)，默认 0.5", "default": 0.5},
                    "fail_fast": {"type": "boolean",
                                  "description": "首个违规即停止，默认 True", "default": True},
                    "output_format": {"type": "string",
                                      "enum": ["summary", "full"],
                                      "description": "输出格式，默认 summary", "default": "summary"},
                },
                "required": ["action"],
            },
        },
    }

