"""
Hot-reloadable modules for Tea Agent Server.

每个模块都是 HotReloadModule 的子类，通过 ModuleRegistry 统一管理。
修改模块代码后，调用 /api/modules/{name}/reload 即可热生效。

模块列表：
  - toolkit_module  — Toolkit（工具注册/执行引擎）
  - storage_module  — Storage（持久化存储）
  - agent_module    — Agent（会话管理/对话引擎）
  - pipeline_module — Pipeline（后处理流水线）
"""

from __future__ import annotations

import logging

from ..module import HotReloadModule, ModuleRegistry, get_registry

logger = logging.getLogger("hot_reload.modules")


def register_all(registry: ModuleRegistry | None = None) -> ModuleRegistry:
    """注册所有模块到 Registry。

    调用时机：服务器启动时，或在热重载后重新注册。

    Args:
        registry: 可选，不传则使用全局单例

    Returns:
        ModuleRegistry 实例
    """
    if registry is None:
        registry = get_registry()

    # 延迟导入，避免循环依赖
    from .agent_module import AgentModule
    from .pipeline_module import PipelineModule
    from .storage_module import StorageModule
    from .toolkit_module import ToolkitModule

    registry.register(ToolkitModule)
    registry.register(StorageModule)
    registry.register(AgentModule)
    registry.register(PipelineModule)

    logger.info(f"Registered {len(registry._modules)} modules: {list(registry._modules.keys())}")
    return registry


def load_all(registry: ModuleRegistry | None = None) -> dict[str, bool]:
    """注册并加载所有模块。

    Returns:
        {module_name: success_bool}
    """
    if registry is None:
        registry = get_registry()
    if not registry._modules:
        register_all(registry)
    return registry.load_all()


__all__ = [
    "register_all",
    "load_all",
    "HotReloadModule",
    "ModuleRegistry",
    "get_registry",
]
