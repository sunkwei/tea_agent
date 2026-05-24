"""
@2026-05-19 gen by claude, LSP 工具 — 实时代码智能诊断/补全/跳转/悬停/引用
依赖: jedi (代码智能), ruff (诊断)
"""

from typing import Optional
import os
import logging

logger = logging.getLogger("toolkit_lsp")

def toolkit_lsp(
    action: str,
    filepath: str,
    line: int = 1,
    col: int = 0,
    project_root: Optional[str] = None,
    symbol: Optional[str] = None,
):
    """实时代码智能工具。基于 jedi + ruff。

    Args:
        action: diagnose/completion/definition/hover/references/context
        filepath: 目标文件路径
        line: 行号 (1-based)
        col: 列号 (0-based)
        project_root: 项目根目录，默认自动检测
        symbol: [context] 要追踪的符号名
    """
    from tea_agent.lsp.lsp_engine import (
        diagnose, completion, goto_definition, hover, references, collect_context
    )

    if not project_root:
        project_root = os.path.dirname(os.path.abspath(filepath)) if filepath else os.getcwd()
        d = os.path.abspath(project_root)
        while d != os.path.dirname(d):
            if os.path.exists(os.path.join(d, "pyproject.toml")) or os.path.exists(os.path.join(d, ".git")):
                project_root = d
                break
            d = os.path.dirname(d)

    if filepath and action != "diagnose" and not os.path.isfile(filepath):
        return {"ok": False, "error": f"文件不存在: {filepath}"}

    try:
        if action == "diagnose":
            return diagnose(project_root, filepath)
        elif action == "completion":
            return completion(project_root, filepath, line, col)
        elif action == "definition":
            return goto_definition(project_root, filepath, line, col)
        elif action == "hover":
            return hover(project_root, filepath, line, col)
        elif action == "references":
            return references(project_root, filepath, line, col)
        elif action == "context":
            return collect_context(project_root, filepath, symbol)
        else:
            return {"ok": False, "error": f"不支持: {action}"}
    except Exception as e:
        logger.exception(f"LSP {action} 失败")
        return {"ok": False, "error": str(e)}

def meta_toolkit_lsp():
    """Meta toolkit lsp"""
    return {
        "type": "function",
        "function": {
            "name": "toolkit_lsp",
            "description": "实时代码智能: diagnose/completion/definition/hover/references/context。基于 jedi + ruff。",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["diagnose", "completion", "definition", "hover", "references", "context"]},
                    "filepath": {"type": "string"},
                    "line": {"type": "integer", "default": 1},
                    "col": {"type": "integer", "default": 0},
                    "project_root": {"type": "string"},
                    "symbol": {"type": "string"},
                },
                "required": ["action", "filepath"],
            },
        },
    }
