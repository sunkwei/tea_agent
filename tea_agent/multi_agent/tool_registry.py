"""
ToolRegistry — 统一工具注册与发现机制。

核心设计:
  将所有「能力」统一注册为可发现的服务：
    - 普通函数工具（Python callable）
    - Agent-as-Tool（RoleAgent 包装）
    - 外部服务（MCP/HTTP API）
    - 动态组合工具

  支持：
    - 按名称/能力/标签发现
    - 能力查询（"谁能做代码审查？"）
    - 动态注册/注销
    - 优先级路由

用法:
    from tea_agent.multi_agent import ToolRegistry, registry

    # 注册一个函数工具
    @registry.register(name="my_tool", tags=["utility"])
    def my_tool(x: int) -> int:
        return x * 2

    # 注册 Agent-as-Tool
    registry.register_agent_tool(agent_tool)

    # 发现
    tools = registry.discover("代码审查")
    for t in tools:
        print(t.name, t.description)
"""

import logging
import threading
import uuid
from collections.abc import Callable
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


class ToolEntry:
    """
    工具注册条目。

    统一表示所有类型的「可调用能力」。
    """

    def __init__(
        self,
        name: str,
        description: str = "",
        callable_obj: Callable | None = None,
        tool_type: str = "function",
        tags: list[str] | None = None,
        metadata: dict | None = None,
    ):
        self.id = str(uuid.uuid4())[:8]
        self.name = name
        self.description = description or f"工具 {name}"
        self.callable_obj = callable_obj
        self.tool_type = tool_type  # "function", "agent", "service", "composite"
        self.tags = tags or []
        self.metadata = metadata or {}
        self.created_at = datetime.now().isoformat()
        self.updated_at = self.created_at
        self.call_count = 0
        self.last_error: str | None = None

    def call(self, *args, **kwargs) -> Any:
        """调用此工具。"""
        if self.callable_obj is None:
            raise RuntimeError(f"工具 {self.name} 没有可调用对象")
        self.call_count += 1
        return self.callable_obj(*args, **kwargs)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "tool_type": self.tool_type,
            "tags": self.tags,
            "metadata": self.metadata,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "call_count": self.call_count,
        }

    def __repr__(self) -> str:
        return f"<ToolEntry {self.name!r} [{self.tool_type}]>"


class ToolRegistry:
    """
    统一工具注册与发现中心。

    线程安全。支持多种注册方式、灵活查询、事件通知。
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._entries: dict[str, ToolEntry] = {}  # name → entry
        self._entries_by_tag: dict[str, list[str]] = {}  # tag → [name, ...]

        # 变更回调
        self._on_register_hooks: list[Callable] = []
        self._on_unregister_hooks: list[Callable] = []

        # 自动发现：工具导入时的默认注册
        self._auto_discovery_enabled = True

    # ── 注册 ────────────────────────────────────────

    def register(
        self,
        name: str = "",
        description: str = "",
        tags: list[str] | None = None,
        metadata: dict | None = None,
    ) -> Callable:
        """
        装饰器：注册一个函数工具。

        @registry.register(name="my_tool", tags=["utility"])
        def my_tool(x): ...
        """
        def decorator(func: Callable) -> Callable:
            tool_name = name or func.__name__
            tool_desc = description or (func.__doc__ or "").strip() or f"工具 {tool_name}"

            entry = ToolEntry(
                name=tool_name,
                description=tool_desc,
                callable_obj=func,
                tool_type="function",
                tags=tags or [],
                metadata=metadata or {},
            )
            self._add_entry(entry)
            return func
        return decorator

    def register_tool(
        self,
        name: str,
        callable_obj: Callable,
        description: str = "",
        tags: list[str] | None = None,
        metadata: dict | None = None,
    ):
        """直接注册一个工具。"""
        entry = ToolEntry(
            name=name,
            description=description or (callable_obj.__doc__ or "").strip() or f"工具 {name}",
            callable_obj=callable_obj,
            tool_type="function",
            tags=tags or [],
            metadata=metadata or {},
        )
        self._add_entry(entry)

    def register_agent_tool(self, agent_tool, tags: list[str] | None = None):
        """
        注册 AgentTool。

        Args:
            agent_tool: AgentTool 实例
        """
        entry = ToolEntry(
            name=agent_tool.name,
            description=agent_tool.description,
            callable_obj=lambda task, **kw: agent_tool.call(task, **kw),
            tool_type="agent",
            tags=(tags or []) + ["agent", "ai"],
            metadata={
                "agent_role": getattr(agent_tool.agent, "role", ""),
                "max_concurrent": agent_tool.max_concurrent,
                "stats": agent_tool.to_dict().get("stats", {}),
            },
        )
        self._add_entry(entry)

    def register_service(
        self,
        name: str,
        url: str = "",
        callable_fn: Callable | None = None,
        description: str = "",
        tags: list[str] | None = None,
    ):
        """注册一个外部服务。"""
        entry = ToolEntry(
            name=name,
            description=description or f"外部服务 {name}",
            callable_obj=callable_fn,
            tool_type="service",
            tags=(tags or []) + ["service"],
            metadata={"url": url},
        )
        self._add_entry(entry)

    def _add_entry(self, entry: ToolEntry):
        """内部：添加条目并触发回调。"""
        with self._lock:
            self._entries[entry.name] = entry

            # 更新标签索引
            for tag in entry.tags:
                if tag not in self._entries_by_tag:
                    self._entries_by_tag[tag] = []
                if entry.name not in self._entries_by_tag[tag]:
                    self._entries_by_tag[tag].append(entry.name)

        # 回调
        for hook in self._on_register_hooks:
            try:
                hook(entry)
            except Exception as e:
                logger.warning(f"register hook 失败: {e}")

        logger.debug(f"📦 注册: {entry.name} [{entry.tool_type}] tags={entry.tags}")

    # ── 注销 ────────────────────────────────────────

    def unregister(self, name: str) -> bool:
        """注销工具。"""
        with self._lock:
            entry = self._entries.pop(name, None)
            if entry is None:
                return False

            # 清理标签索引
            for tag in entry.tags:
                if tag in self._entries_by_tag:
                    self._entries_by_tag[tag] = [n for n in self._entries_by_tag[tag] if n != name]

        for hook in self._on_unregister_hooks:
            try:
                hook(entry)
            except Exception:
                pass

        logger.debug(f"🗑️ 注销: {name}")
        return True

    # ── 发现 ────────────────────────────────────────

    def discover(self, query: str = "", limit: int = 10) -> list[ToolEntry]:
        """
        发现工具（按名称/描述/标签模糊匹配）。

        Args:
            query: 搜索关键词
            limit: 返回上限

        Returns:
            匹配的 ToolEntry 列表
        """
        if not query:
            with self._lock:
                return list(self._entries.values())[:limit]

        query_lower = query.lower()
        results = []

        with self._lock:
            for entry in self._entries.values():
                # 名称匹配
                if query_lower in entry.name.lower():
                    results.append(entry)
                    continue
                # 描述匹配
                if query_lower in entry.description.lower():
                    results.append(entry)
                    continue
                # 标签匹配
                for tag in entry.tags:
                    if query_lower in tag.lower():
                        results.append(entry)
                        break

        return results[:limit]

    def find_by_name(self, name: str) -> ToolEntry | None:
        """精确查找。"""
        with self._lock:
            return self._entries.get(name)

    def find_by_tag(self, tag: str) -> list[ToolEntry]:
        """按标签查找。"""
        with self._lock:
            names = self._entries_by_tag.get(tag, [])
            return [self._entries[n] for n in names if n in self._entries]

    def find_by_capability(self, capability: str) -> list[ToolEntry]:
        """
        按能力描述查找（语义搜索）。
        当前实现：关键词匹配 name/description/tags
        """
        return self.discover(capability)

    # ── 调用 ────────────────────────────────────────

    def call(self, name: str, *args, **kwargs) -> Any:
        """调用已注册的工具。"""
        entry = self.find_by_name(name)
        if entry is None:
            raise KeyError(f"工具 '{name}' 未注册")
        return entry.call(*args, **kwargs)

    def safe_call(self, name: str, *args, **kwargs) -> dict:
        """安全调用（捕获异常返回 dict）。"""
        try:
            result = self.call(name, *args, **kwargs)
            return {"success": True, "result": result}
        except Exception as e:
            logger.error(f"❌ 调用 {name} 失败: {e}")
            return {"success": False, "error": str(e)}

    # ── 能力查询 ────────────────────────────────────

    def who_can(self, task_description: str) -> list[dict]:
        """
        查询谁能做某任务。

        Returns:
            [{"name": str, "description": str, "tags": [...]}, ...]
        """
        entries = self.discover(task_description)
        return [e.to_dict() for e in entries]

    def capabilities(self) -> list[str]:
        """列出所有注册能力。"""
        with self._lock:
            return list(self._entries.keys())

    # ── 生命周期管理 ────────────────────────────────

    def add_register_hook(self, hook: Callable):
        """注册新工具时的回调。"""
        self._on_register_hooks.append(hook)

    def add_unregister_hook(self, hook: Callable):
        """注销工具时的回调。"""
        self._on_unregister_hooks.append(hook)

    def count(self) -> int:
        with self._lock:
            return len(self._entries)

    def list(self, tool_type: str = "") -> list[dict]:
        """列出所有工具信息。"""
        with self._lock:
            entries = list(self._entries.values())
            if tool_type:
                entries = [e for e in entries if e.tool_type == tool_type]
            return [e.to_dict() for e in entries]

    def stats(self) -> dict:
        """注册表统计。"""
        with self._lock:
            type_counts = {}
            for entry in self._entries.values():
                type_counts[entry.tool_type] = type_counts.get(entry.tool_type, 0) + 1
            return {
                "total": len(self._entries),
                "by_type": type_counts,
                "by_tag": {t: len(ns) for t, ns in self._entries_by_tag.items()},
                "total_calls": sum(e.call_count for e in self._entries.values()),
            }

    def clear(self):
        """清空所有注册。"""
        with self._lock:
            self._entries.clear()
            self._entries_by_tag.clear()


# ── 全局单例 ────────────────────────────────────

_default_registry: ToolRegistry | None = None
_registry_lock = threading.Lock()


def get_tool_registry() -> ToolRegistry:
    """获取全局 ToolRegistry 单例。"""
    global _default_registry
    if _default_registry is None:
        with _registry_lock:
            if _default_registry is None:
                _default_registry = ToolRegistry()
    return _default_registry


def reset_tool_registry():
    """重置注册表（测试用）。"""
    global _default_registry
    with _registry_lock:
        _default_registry = None


# 便捷引用
registry = get_tool_registry()
