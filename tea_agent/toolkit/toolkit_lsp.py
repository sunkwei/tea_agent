"""
@2026-05-19 gen by claude, LSP 工具 — 实时代码智能诊断/补全/跳转/悬停/引用
依赖: jedi (代码智能), ruff (诊断)
"""

from typing import Optional
import os
import json
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
        action: diagnose(诊断)/completion(补全)/definition(跳转定义)/hover(悬停)/references(引用)/context(仓库上下文)
        filepath: 目标文件路径
        line: 行号 (1-based)
        col: 列号 (0-based)
        project_root: 项目根目录，默认自动检测
        symbol: [context] 要追踪的符号名
    """
    from tea_agent.lsp.lsp_engine import (
        diagnose, completion, goto_definition, hover, references, collect_context
    )

    # 自动检测项目根目录
    if not project_root:
        project_root = os.path.dirname(os.path.abspath(filepath)) if filepath else os.getcwd()
        # 向上找 pyproject.toml / .git
        d = os.path.abspath(project_root)
        while d != os.path.dirname(d):
            if os.path.exists(os.path.join(d, "pyproject.toml")) or os.path.exists(os.path.join(d, ".git")):
                project_root = d
                break
            d = os.path.dirname(d)

    # 检查文件是否存在
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
            return {"ok": False, "error": f"不支持的操作: {action}，可选: diagnose/completion/definition/hover/references/context"}
    except Exception as e:
        logger.exception(f"LSP {action} 失败")
        return {"ok": False, "error": str(e)}


def meta_toolkit_lsp():
    """工具元数据"""
    return {
        "name": "toolkit_lsp",
        "description": "实时代码智能工具：诊断(diagnose)/补全(completion)/跳转定义(definition)/悬停(hover)/引用(references)/上下文收集(context)。基于 jedi + ruff。",
        "parameters": {
            "action": {"type": "string", "enum": ["diagnose", "completion", "definition", "hover", "references", "context"], "description": "操作类型"},
            "filepath": {"type": "string", "description": "目标文件路径"},
            "line": {"type": "integer", "description": "行号(1-based)，默认1", "default": 1},
            "col": {"type": "integer", "description": "列号(0-based)，默认0", "default": 0},
            "project_root": {"type": "string", "description": "项目根目录，默认自动检测"},
            "symbol": {"type": "string", "description": "[context] 要追踪的符号名"},
        },
        "required": ["action", "filepath"],
    }
