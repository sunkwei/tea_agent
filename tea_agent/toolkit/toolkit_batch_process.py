# @2026-07-02 gen by claude, 批量处理工具 — 并行执行同类操作于多个文件
"""
toolkit_batch_process — 批量文件处理工具

对多个文件并行执行相同的处理操作：
  - 批量格式化 (format)
  - 批量审查 (review)
  - 批量编译检查 (compile)
  - 批量 lint (lint)
  - 批量替换文本 (replace)
  - 批量统计 (stats)

支持 glob 匹配、并行执行、进度报告、失败隔离。
"""

import concurrent.futures
import json
import logging
import os
import subprocess
from pathlib import Path

logger = logging.getLogger("toolkit.batch_process")

# ── 内置处理器 ──────────────────────────────────────────

def _handler_compile(abspath: str, **kwargs) -> dict:
    """编译检查"""
    import py_compile
    try:
        py_compile.compile(abspath, doraise=True)
        return {"file": abspath, "ok": True, "result": "编译通过"}
    except py_compile.PyCompileError as e:
        return {"file": abspath, "ok": False, "result": str(e)[:200]}


def _handler_lint(abspath: str, **kwargs) -> dict:
    """Ruff Lint 检查"""
    try:
        r = subprocess.run(["ruff", "check", "--output-format", "json", abspath],
                           capture_output=True, text=True, timeout=30)
        issues = json.loads(r.stdout) if r.stdout.strip() else []
        return {"file": abspath, "ok": len(issues) == 0, "result": f"{len(issues)} 个问题", "issues": issues}
    except Exception as e:
        return {"file": abspath, "ok": False, "result": f"lint 错误: {e}"}


def _handler_format(abspath: str, **kwargs) -> dict:
    """Black 格式化"""
    try:
        r = subprocess.run(["python", "-m", "black", "--quiet", abspath],
                           capture_output=True, text=True, timeout=30)
        ok = r.returncode == 0
        output = r.stdout or r.stderr or ""
        return {"file": abspath, "ok": ok, "result": "已格式化" if ok else output[:200]}
    except Exception as e:
        return {"file": abspath, "ok": False, "result": f"格式化错误: {e}"}


def _handler_stats(abspath: str, **kwargs) -> dict:
    """文件统计"""
    try:
        with open(abspath, encoding="utf-8", errors="replace") as f:
            content = f.read()
        lines = content.split('\n')
        code_lines = sum(1 for l in lines if l.strip() and not l.strip().startswith('#'))
        comment_lines = sum(1 for l in lines if l.strip().startswith('#'))
        blank_lines = sum(1 for l in lines if not l.strip())
        return {
            "file": abspath, "ok": True, "result": {
                "total": len(lines), "code": code_lines,
                "comment": comment_lines, "blank": blank_lines,
                "size_bytes": os.path.getsize(abspath),
            }
        }
    except Exception as e:
        return {"file": abspath, "ok": False, "result": f"统计错误: {e}"}


def _handler_replace(abspath: str, **kwargs) -> dict:
    """文本替换"""
    old = kwargs.get("old", "")
    new = kwargs.get("new", "")
    if not old:
        return {"file": abspath, "ok": False, "result": "需要 old 参数"}
    try:
        with open(abspath, encoding="utf-8", errors="replace") as f:
            content = f.read()
        if old not in content:
            return {"file": abspath, "ok": True, "result": "未匹配到模式", "count": 0}
        count = content.count(old)
        new_content = content.replace(old, new)
        with open(abspath, "w", encoding="utf-8") as f:
            f.write(new_content)
        return {"file": abspath, "ok": True, "result": f"替换 {count} 处", "count": count}
    except Exception as e:
        return {"file": abspath, "ok": False, "result": f"替换错误: {e}"}


def _handler_count_lines(abspath: str, **kwargs) -> dict:
    """行数统计"""
    try:
        with open(abspath, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        return {"file": abspath, "ok": True, "result": len(lines)}
    except Exception as e:
        return {"file": abspath, "ok": False, "result": str(e)}


# ── 处理器注册表 ────────────────────────────────────────

BUILTIN_HANDLERS = {
    "compile": _handler_compile,
    "lint": _handler_lint,
    "format": _handler_format,
    "stats": _handler_stats,
    "replace": _handler_replace,
    "count_lines": _handler_count_lines,
}


def _resolve_files(glob_pattern: str, directory: str = "", max_files: int = 100) -> list[str]:
    """解析文件列表"""
    if os.path.isfile(glob_pattern):
        return [os.path.abspath(glob_pattern)]
    base = os.path.abspath(directory) if directory else os.getcwd()
    matched = []
    for f in Path(base).rglob(glob_pattern):
        if f.is_file():
            matched.append(str(f))
            if len(matched) >= max_files:
                break
    return matched


# ── 主入口 ──────────────────────────────────────────────

def toolkit_batch_process(
    action: str = "compile",
    glob_pattern: str = "*.py",
    directory: str = "",
    files: list[str] = None,
    max_files: int = 100,
    parallel: bool = True,
    max_workers: int = 8,
    output: str = "",
    **kwargs,
) -> dict:
    """
    批量文件处理工具。对多个文件并行执行相同的操作。

    Args:
        action: 处理操作: compile/lint/format/stats/replace/count_lines
        glob_pattern: 文件匹配模式，如 "*.py", "test_*.py", "**/*.md"
        directory: 搜索目录（默认当前目录）
        files: 直接指定文件列表（与 glob_pattern 二选一）
        max_files: 最大处理文件数
        parallel: 是否并行执行
        max_workers: 并行工作线程数
        output: 结果输出文件路径（可选 JSON）
        **kwargs: 传递给处理器的额外参数（如 replace 的 old/new）

    Returns: {"ok": bool, "total": N, "success": N, "fail": N, "results": [...], "summary": {...}}
    """
    try:
        # 解析文件列表
        file_list = [os.path.abspath(f) for f in files if os.path.isfile(f)] if files else _resolve_files(glob_pattern, directory, max_files)

        if not file_list:
            return {"ok": False, "error": f"未找到匹配文件: {glob_pattern}", "total": 0, "success": 0, "fail": 0, "results": []}

        # 获取处理器
        handler = BUILTIN_HANDLERS.get(action)
        if handler is None:
            return {"ok": False, "error": f"未知操作: {action}，支持: {', '.join(BUILTIN_HANDLERS.keys())}"}

        # 执行处理
        results = []
        if parallel and len(file_list) > 1:
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_map = {executor.submit(handler, fp, **kwargs): fp for fp in file_list}
                for future in concurrent.futures.as_completed(future_map):
                    try:
                        results.append(future.result())
                    except Exception as e:
                        fp = future_map[future]
                        results.append({"file": fp, "ok": False, "result": str(e)[:200]})
        else:
            for fp in file_list:
                try:
                    results.append(handler(fp, **kwargs))
                except Exception as e:
                    results.append({"file": fp, "ok": False, "result": str(e)[:200]})

        # 统计
        success = sum(1 for r in results if r.get("ok", False))
        fail = len(results) - success

        summary = {
            "action": action,
            "total": len(results),
            "success": success,
            "fail": fail,
            "success_rate": round(success / len(results) * 100, 1) if results else 0,
            "glob_pattern": glob_pattern,
            "parallel": parallel,
        }

        result = {"ok": fail == 0, "total": len(results), "success": success, "fail": fail,
                  "summary": summary, "results": results}

        if output:
            with open(output, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2, default=str)
            result["output_file"] = output

        return result

    except Exception as e:
        logger.exception(f"toolkit_batch_process: {e}")
        return {"ok": False, "error": str(e)[:300], "total": 0, "success": 0, "fail": 0, "results": []}


# ── Meta ────────────────────────────────────────────────

def meta_toolkit_batch_process():
    return {
        "type": "function",
        "function": {
            "name": "toolkit_batch_process",
            "description": "批量文件处理工具。对多个文件并行执行相同的操作（编译检查/lint/格式化/统计/替换等），支持 glob 匹配、并行执行、失败隔离。",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string", "enum": ["compile", "lint", "format", "stats", "replace", "count_lines"],
                        "description": "compile/lint/format/stats/replace/count_lines",
                        "default": "compile"
                    },
                    "glob_pattern": {"type": "string", "description": "文件匹配模式，如 *.py, test_*.py", "default": "*.py"},
                    "directory": {"type": "string", "description": "搜索目录，默认当前目录"},
                    "files": {"type": "array", "items": {"type": "string"}, "description": "直接指定文件列表（与 glob_pattern 二选一）"},
                    "max_files": {"type": "integer", "description": "最大处理文件数", "default": 100},
                    "parallel": {"type": "boolean", "description": "是否并行执行", "default": True},
                    "max_workers": {"type": "integer", "description": "并行工作线程数", "default": 8},
                    "output": {"type": "string", "description": "结果输出 JSON 文件路径（可选）"},
                },
                "required": [],
            },
        },
    }
