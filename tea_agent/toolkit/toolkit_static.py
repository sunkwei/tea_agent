"""静态代码分析工具。

支持三种分析模式:
- metrics: 单文件圈复杂度/LOC/扇入扇出/注释覆盖
- dead_code: 检测未使用函数/方法和未引用导入
- summary: 目录级聚合度量，标记高复杂度模块
"""

import os
import logging

logger = logging.getLogger("toolkit")



def meta_toolkit_static() -> dict:
    """
    Meta for tool loader

    Returns:
        dict: Description.
    """
    return {
        "type": "function",
        "function": {
            "name": "toolkit_static",
            "description": (
                "静态代码分析工具。action=metrics 计算圈复杂度/LOC/扇入扇出/注释覆盖；"
                "action=dead_code 检测未使用函数/方法/未引用导入；"
                "action=summary 目录级聚合分析（批量扫描所有 .py）。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["metrics", "dead_code", "summary"],
                        "description": "metrics=单文件度量, dead_code=死代码检测, summary=目录聚合",
                    },
                    "file_path": {
                        "type": "string",
                        "description": "[metrics/dead_code] 目标文件路径",
                    },
                    "directory": {
                        "type": "string",
                        "description": "[summary] 项目目录，默认当前目录",
                    },
                    "threshold": {
                        "type": "integer",
                        "description": "[summary] 圈复杂度告警阈值，默认 10",
                        "default": 10,
                    },
                },
                "required": ["action"],
                "type": "object",
            },
        },
    }




def toolkit_static(
    action: str,
    file_path: str = "",
    directory: str = "",
    threshold: int = 10,
) -> dict:
    """执行静态代码分析。

    Args:
        action: metrics | dead_code | summary
        file_path: 目标文件（metrics/dead_code 需要）
        directory: 项目目录（summary 需要，默认 pwd）
        threshold: 圈复杂度告警阈值（summary 使用）

    Returns:
        dict with ok + analysis results
    """
    cwd = os.getcwd()

    if action == "metrics":
        if not file_path:
            return {"ok": False, "error": "metrics 需要 file_path 参数"}
        from tea_agent.lsp.ts_analyzer import compute_metrics
        result = compute_metrics(cwd, file_path)
        return result

    elif action == "dead_code":
        if not file_path:
            return {"ok": False, "error": "dead_code 需要 file_path 参数"}
        from tea_agent.lsp.ts_analyzer import find_dead_code
        result = find_dead_code(cwd, file_path)
        return result

    elif action == "summary":
        project_root = directory or cwd
        return _summary(project_root, threshold)

    else:
        return {"ok": False, "error": f"未知 action: {action}。支持: metrics/dead_code/summary"}


def _summary(project_root: str, threshold: int = 10) -> dict:
    """
    目录级聚合分析：扫描所有 .py 文件，汇总度量。

    Args:
        project_root (str): Description.
        threshold (int): Description.

    Returns:
        dict: Description.
    """
    from pathlib import Path
    from tea_agent.lsp.ts_analyzer import compute_metrics

    py_files = sorted(Path(project_root).rglob("*.py"))
    exclude_dirs = {"__pycache__", ".git", ".tea_agent_run", "build", "dist",
                    ".venv", "venv", "node_modules", ".tox", "egg-info"}
    py_files = [f for f in py_files
                if not any(d in f.parts for d in exclude_dirs)
                and not f.name.startswith("test_")]

    if not py_files:
        return {"ok": False, "error": f"未在 {project_root} 找到 .py 文件"}

    all_files = []
    total_loc = 0
    total_fns = 0
    total_methods = 0
    high_complexity = []

    for pf in py_files:
        rel = str(pf.relative_to(project_root))
        try:
            m = compute_metrics(project_root, str(pf))
        except Exception as e:
            all_files.append({"file": rel, "error": str(e)})
            continue

        if not m.get("ok"):
            all_files.append({"file": rel, "error": m.get("error")})
            continue

        total_loc += m.get("total_loc", 0)
        total_fns += m.get("functions", 0)
        total_methods += m.get("methods", 0)

        alerts = []
        for item in m.get("items", []):
            if item["metrics"]["cyclomatic"] > threshold:
                alerts.append({
                    "name": item["name"],
                    "kind": item["kind"],
                    "cyclomatic": item["metrics"]["cyclomatic"],
                    "loc": item["metrics"]["loc"],
                    "line": item["line"],
                })
        if alerts:
            high_complexity.append({
                "file": rel,
                "alerts": alerts,
                "max_cyclomatic": m.get("max_cyclomatic", 0),
            })

        all_files.append({
            "file": rel,
            "loc": m.get("total_loc", 0),
            "functions": m.get("functions", 0),
            "methods": m.get("methods", 0),
            "avg_cyclomatic": m.get("avg_cyclomatic", 0),
            "max_cyclomatic": m.get("max_cyclomatic", 0),
            "doc_coverage": m.get("docstring_coverage", "N/A"),
        })

    all_files.sort(key=lambda x: x.get("max_cyclomatic", 0), reverse=True)

    return {
        "ok": True,
        "directory": project_root,
        "files_scanned": len(py_files),
        "total_loc": total_loc,
        "total_functions": total_fns,
        "total_methods": total_methods,
        "threshold": threshold,
        "high_complexity_count": len(high_complexity),
        "high_complexity": high_complexity[:15],
        "all_files": all_files[:100],
        "hint": f"{len(py_files)} 文件, {total_fns + total_methods} 可调用项, "
                f"{len(high_complexity)} 个文件有圈复杂度 > {threshold} 的函数",
    }
