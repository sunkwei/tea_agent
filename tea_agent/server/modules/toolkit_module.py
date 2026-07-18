"""
ToolkitModule — 热重载 Toolkit 模块。

管理工具加载/注册/执行引擎。
热重载时重新扫描 toolkit/ 目录并注册所有工具函数。
依赖：无（最底层模块）
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from ..module import HotReloadModule, ModuleRegistry, _module_path_for

logger = logging.getLogger("hot_reload.toolkit")


class ToolkitModule(HotReloadModule):
    """Toolkit 热重载模块。

    封装 tlk.Toolkit，提供工具加载/列表/执行能力。
    热重载时重新扫描工具目录，重新注册所有工具函数。
    """

    name: str = "toolkit"
    dependencies: list[str] = []

    # 运行时状态（实例级别，类方法通过 cls._instance 访问）
    _instance: Any = None  # tlk.Toolkit 实例
    _tool_dir: str = ""

    @classmethod
    def _load(cls, registry: ModuleRegistry) -> bool:
        """加载 Toolkit 模块。

        1. 确定工具目录（从配置或默认路径）
        2. 创建 tlk.Toolkit 实例
        3. 扫描并注册所有工具函数
        """
        from tea_agent import tlk
        from tea_agent.config import load_config

        try:
            cfg = load_config()
            tool_dir = str(Path(cfg.paths.toolkit_dir_abs))
        except Exception:
            # 回退到默认路径
            tool_dir = str(Path(__file__).parent.parent.parent / "toolkit")

        Path(tool_dir).mkdir(parents=True, exist_ok=True)
        cls._tool_dir = tool_dir

        # 创建 Toolkit 实例
        toolkit = tlk.Toolkit(tool_dir)
        tlk.toolkit = toolkit
        toolkit._is_server = True
        cls._instance = toolkit

        logger.info(f"Toolkit loaded | tools: {len(toolkit.func_map)} | dir: {tool_dir}")
        return True

    @classmethod
    def _unload(cls) -> None:
        """卸载 Toolkit 模块。"""
        cls._instance = None
        cls._tool_dir = ""

    # ── 公开接口 ──

    @classmethod
    def get_toolkit(cls) -> Any:
        """获取 tlk.Toolkit 实例。"""
        return cls._instance

    @classmethod
    def list_tools(cls) -> list[dict[str, Any]]:
        """列出所有已注册工具。"""
        toolkit = cls._instance
        if toolkit is None:
            return []
        tools = []
        for name, meta in toolkit.meta_map.items():
            fn = meta.get("function", {})
            tools.append({
                "name": fn.get("name", name),
                "description": fn.get("description", ""),
                "parameters": fn.get("parameters", {}),
            })
        return tools

    @classmethod
    def run_tool(cls, tool_name: str, arguments: dict) -> dict:
        """执行指定工具。"""
        toolkit = cls._instance
        if toolkit is None:
            return {"ok": False, "error": "Toolkit not loaded"}
        func = toolkit.func_map.get(tool_name)
        if func is None:
            func = toolkit.func_map.get(f"toolkit_{tool_name}")
        if func is None:
            return {"ok": False, "error": f"Tool '{tool_name}' not found"}
        try:
            result = func(**arguments)
            return {"ok": True, "tool": tool_name, "result": str(result)}
        except Exception as e:
            return {"ok": False, "error": str(e), "tool": tool_name}

    @classmethod
    def get_func_map(cls) -> dict:
        """获取函数映射表。"""
        if cls._instance:
            return cls._instance.func_map
        return {}

    @classmethod
    def get_meta_map(cls) -> dict:
        """获取元数据映射表。"""
        if cls._instance:
            return cls._instance.meta_map
        return {}

    @classmethod
    def save_tool(cls, name: str, meta: dict, pycode: str) -> dict:
        """保存新工具。"""
        from tea_agent import tlk
        if cls._instance:
            return cls._instance.save_func(name, meta, pycode)
        return {"ok": False, "error": "Toolkit not loaded"}

    @classmethod
    def reload_tools(cls) -> dict:
        """重新加载所有工具。"""
        from tea_agent import tlk
        if cls._instance:
            tlk.reload_funcs()
            return {"ok": True, "count": len(cls._instance.func_map)}
        return {"ok": False, "error": "Toolkit not loaded"}


# 设置模块路径（用于文件监控）
_module_path_for(ToolkitModule)
