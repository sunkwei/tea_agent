"""
Extension API + 生命周期事件系统 — 借鉴 Pi Agent Harness 的扩展架构

功能：
  - 生命周期事件：session_start, session_shutdown, before_tool, after_tool, etc.
  - Extension 注册：register_tool, register_command, register_shortcut
  - 自动发现：~/.tea_agent/extensions/ 和 .tea_agent/extensions/
  - 热重载支持
  - 事件拦截：可以阻止或修改工具调用

用法：
    # 在扩展文件中（~/.tea_agent/extensions/my_ext.py）
    def setup(api):
        \"\"\"扩展入口函数。\"\"\"

        @api.on("before_tool_call")
        def check_before(ctx, tool_name, args):
            if tool_name == "toolkit_exec" and "rm -rf" in args.get("command", ""):
                return {"block": True, "reason": "危险操作被拦截"}

        @api.on("session_start")
        def on_start(ctx):
            ctx.log("扩展已加载！")

        api.register_tool(
            name="my_greet",
            description="Say hello",
            handler=lambda name: f"Hello, {name}!"
        )
"""

import importlib
import importlib.util
import inspect
import logging
import os
import sys
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger("session.extension_api")


# ═══ 事件系统 ═══════════════════════════════════════════

class EventBus:
    """事件总线 — 管理事件的注册与触发。

    支持：
    - 同步/异步事件处理器
    - 拦截器（返回 dict 可阻塞事件）
    - 优先级排序
    - 处理器异常隔离
    """

    def __init__(self):
        self._handlers: dict[str, list[dict]] = {}  # event_name -> [{handler, priority}]

    def on(self, event: str, handler: Callable, priority: int = 0):
        """注册事件处理器。

        Args:
            event: 事件名称
            handler: 处理器函数，接收 (context, **data) 参数
            priority: 优先级（越大越先执行）
        """
        if event not in self._handlers:
            self._handlers[event] = []
        self._handlers[event].append({
            "handler": handler,
            "priority": priority,
        })
        # 按优先级降序排列
        self._handlers[event].sort(key=lambda h: h["priority"], reverse=True)
        logger.debug(f"📡 注册事件处理器: {event}")

    def off(self, event: str, handler: Callable | None = None):
        """移除事件处理器。

        Args:
            event: 事件名称
            handler: 要移除的处理器（None=移除所有）
        """
        if event not in self._handlers:
            return
        if handler is None:
            del self._handlers[event]
        else:
            self._handlers[event] = [
                h for h in self._handlers[event]
                if h["handler"] != handler
            ]

    def emit(self, event: str, context: Any = None, **data) -> list[Any]:
        """触发同步事件。

        Args:
            event: 事件名称
            context: 事件上下文
            data: 事件数据

        Returns:
            所有处理器的返回值列表

        如果某个处理器返回 dict 且包含 "block": True，则后续处理器不再执行。
        """
        results = []
        handlers = self._handlers.get(event, [])

        for h_info in handlers:
            try:
                result = h_info["handler"](context, **data)
                results.append(result)

                # 拦截机制：如果处理器返回 {"block": True, ...}，阻止后续执行
                if isinstance(result, dict) and result.get("block"):
                    logger.info(f"🚫 事件 {event} 被拦截: {result.get('reason', '')}")
                    break
            except Exception as e:
                logger.warning(f"⚠️ 事件处理器异常 [{event}]: {e}")

        return results

    def has_listeners(self, event: str) -> bool:
        """检查是否有事件监听器。"""
        return event in self._handlers and len(self._handlers[event]) > 0

    def listener_count(self, event: str) -> int:
        """获取事件监听器数量。"""
        return len(self._handlers.get(event, []))

    def clear(self):
        """清空所有处理器。"""
        self._handlers.clear()


# ═══ 扩展系统 ═══════════════════════════════════════════

# 预定义事件列表
EVENTS = [
    "session_start",          # 会话开始
    "session_shutdown",       # 会话关闭
    "before_tool_call",       # 工具调用前（可拦截）
    "after_tool_call",        # 工具调用后
    "before_llm_call",        # LLM 调用前
    "after_llm_call",         # LLM 调用后
    "message_received",       # 收到用户消息
    "message_sent",           # 发送助理消息
    "tool_result",            # 工具返回结果
    "error_occurred",         # 发生错误
    "extension_loaded",       # 扩展加载完成
    "extension_unloaded",     # 扩展卸载
]


class ExtensionAPI:
    """扩展 API 实例 — 传递给每个扩展的入口函数。

    扩展通过此对象与 Agent 交互。
    """

    def __init__(self, event_bus: EventBus, ext_name: str = ""):
        self._event_bus = event_bus
        self._ext_name = ext_name
        self._tools: dict[str, dict] = {}
        self._commands: dict[str, dict] = {}
        self._shortcuts: dict[str, dict] = {}

    # ── 事件 ──

    def on(self, event: str, handler: Callable, priority: int = 0):
        """注册事件处理器。

        支持的事件列表见 EVENTS。

        Args:
            event: 事件名称
            handler: 处理器函数
            priority: 优先级
        """
        if event not in EVENTS:
            logger.warning(f"⚠️ 未知事件 '{event}'，可用: {EVENTS}")
        self._event_bus.on(event, handler, priority)

    def emit(self, event: str, **data):
        """触发事件。"""
        return self._event_bus.emit(event, self, **data)

    # ── 工具注册 ──

    def register_tool(
        self,
        name: str,
        description: str = "",
        handler: Callable | None = None,
        parameters: dict | None = None,
    ):
        """注册一个工具函数（LLM 可调用）。

        Args:
            name: 工具名称
            description: 工具描述
            handler: 处理函数
            parameters: JSON Schema 参数定义
        """
        self._tools[name] = {
            "name": name,
            "description": description,
            "handler": handler,
            "parameters": parameters or {},
            "source": self._ext_name,
        }
        logger.info(f"🔧 扩展 [{self._ext_name}] 注册工具: {name}")

    def register_command(self, name: str, handler: Callable, description: str = ""):
        """注册一个 /command。

        Args:
            name: 命令名（不含 /）
            handler: 处理函数，接收 (args: list[str]) -> str
            description: 命令描述
        """
        self._commands[name] = {
            "name": name,
            "handler": handler,
            "description": description,
            "source": self._ext_name,
        }
        logger.info(f"📟 扩展 [{self._ext_name}] 注册命令: /{name}")

    def register_shortcut(self, key: str, handler: Callable, description: str = ""):
        """注册快捷键。

        Args:
            key: 快捷键，如 'ctrl+shift+p'
            handler: 处理函数
            description: 描述
        """
        self._shortcuts[key] = {
            "key": key,
            "handler": handler,
            "description": description,
            "source": self._ext_name,
        }
        logger.info(f"⌨️ 扩展 [{self._ext_name}] 注册快捷键: {key}")

    # ── 属性 ──

    @property
    def name(self) -> str:
        return self._ext_name

    @property
    def registered_tools(self) -> dict:
        return dict(self._tools)

    @property
    def registered_commands(self) -> dict:
        return dict(self._commands)

    @property
    def registered_shortcuts(self) -> dict:
        return dict(self._shortcuts)


class ExtensionLoader:
    """扩展加载器 — 发现 + 加载 + 卸载扩展。

    支持：
    - 自动发现（多个路径）
    - 安全加载（异常隔离）
    - 热重载
    - 依赖管理
    """

    def __init__(self, event_bus: EventBus | None = None):
        self.event_bus = event_bus or EventBus()
        self._loaded_extensions: dict[str, ExtensionAPI] = {}
        self._lock = threading.Lock()

    # ── 发现 ──

    def discover_paths(self) -> list[Path]:
        """发现所有扩展搜索路径。

        按优先级：
        1. 项目级: .tea_agent/extensions/ 或 .tea/extensions/
        2. 用户级: ~/.tea_agent/extensions/
        3. 系统级: 安装目录下的 extensions/
        """
        paths = []

        # 项目级
        cwd = Path.cwd()
        for sub in [".tea_agent", ".tea", ".pi"]:
            p = cwd / sub / "extensions"
            if p.exists():
                paths.append(p)

        # 用户级
        user_ext = Path.home() / ".tea_agent" / "extensions"
        if user_ext.exists():
            paths.append(user_ext)

        # 系统级
        try:
            from tea_agent import __file__ as ta_file
            sys_ext = Path(ta_file).parent / "extensions"
            if sys_ext.exists():
                paths.append(sys_ext)
        except (ImportError, AttributeError):
            pass

        return paths

    def discover_extensions(self) -> list[Path]:
        """扫描所有扩展文件。

        Returns:
            .py 文件路径列表
        """
        ext_files = []
        seen = set()

        for base in self.discover_paths():
            for f in base.iterdir():
                if not f.is_file() or f.suffix != ".py":
                    continue
                if f.name.startswith("_"):
                    continue  # 跳过 __init__.py 等
                if f.stem in seen:
                    continue
                seen.add(f.stem)
                ext_files.append(f)

        return ext_files

    # ── 加载 ──

    def load_extension(self, filepath: Path) -> ExtensionAPI | None:
        """加载单个扩展文件。

        Args:
            filepath: .py 文件路径

        Returns:
            ExtensionAPI 实例（加载成功）或 None（失败）
        """
        ext_name = filepath.stem

        try:
            # 动态导入模块
            spec = importlib.util.spec_from_file_location(
                f"tea_agent_ext_{ext_name}", filepath
            )
            if spec is None or spec.loader is None:
                logger.warning(f"加载扩展失败: {filepath} (spec is None)")
                return None

            module = importlib.util.module_from_spec(spec)
            # 将扩展目录加入 sys.path 以支持相对导入
            ext_dir = str(filepath.parent)
            if ext_dir not in sys.path:
                sys.path.insert(0, ext_dir)

            spec.loader.exec_module(module)

            # 创建 API 实例
            api = ExtensionAPI(event_bus=self.event_bus, ext_name=ext_name)

            # 调用 setup 函数（如果存在）
            if hasattr(module, "setup"):
                setup_fn = module.setup
                if callable(setup_fn):
                    setup_fn(api)
                    logger.info(f"✅ 扩展加载: {ext_name} ({filepath})")
                else:
                    logger.warning(f"扩展 {ext_name} 的 setup 不是可调用对象")
                    return None
            else:
                logger.info(f"📄 扩展加载（无 setup）: {ext_name}")

            # 注册
            with self._lock:
                self._loaded_extensions[ext_name] = api

            # 触发事件
            self.event_bus.emit("extension_loaded", api, name=ext_name)

            return api

        except Exception as e:
            logger.error(f"❌ 扩展加载失败 [{ext_name}]: {e}", exc_info=True)
            return None

    def load_all(self) -> list[ExtensionAPI]:
        """加载所有发现的扩展。"""
        loaded = []
        for fpath in self.discover_extensions():
            api = self.load_extension(fpath)
            if api:
                loaded.append(api)
        logger.info(f"📦 扩展加载完成: {len(loaded)}/{len(self.discover_extensions())}")
        return loaded

    # ── 卸载 ──

    def unload_extension(self, ext_name: str) -> bool:
        """卸载扩展。"""
        with self._lock:
            if ext_name not in self._loaded_extensions:
                return False
            api = self._loaded_extensions.pop(ext_name)
            # 清理注册的工具/命令/快捷键
            self.event_bus.emit("extension_unloaded", api, name=ext_name)
            logger.info(f"🗑️ 扩展卸载: {ext_name}")
            return True

    def reload_all(self) -> list[ExtensionAPI]:
        """热重载所有扩展。"""
        # 先卸载
        names = list(self._loaded_extensions.keys())
        for name in names:
            self.unload_extension(name)

        # 重新加载
        return self.load_all()

    # ── 查询 ──

    @property
    def loaded_extensions(self) -> dict[str, ExtensionAPI]:
        return dict(self._loaded_extensions)

    def get_api(self, ext_name: str) -> ExtensionAPI | None:
        return self._loaded_extensions.get(ext_name)

    def get_all_tools(self) -> dict[str, dict]:
        """获取所有扩展注册的工具。"""
        tools = {}
        for api in self._loaded_extensions.values():
            tools.update(api.registered_tools)
        return tools

    def get_all_commands(self) -> dict[str, dict]:
        """获取所有扩展注册的命令。"""
        cmds = {}
        for api in self._loaded_extensions.values():
            cmds.update(api.registered_commands)
        return cmds


# ═══ 生命周期钩子（集成到 Agent） ════════════════════════

class LifecycleHooks:
    """生命周期钩子 — 将 EventBus 集成到 Agent 的关键路径。

    用法：
        hooks = LifecycleHooks(event_bus)
        hooks.before_tool_call("toolkit_exec", {"command": "rm -rf /"})
        # 如果被拦截，返回 {"block": True, "reason": "..."}
    """

    def __init__(self, event_bus: EventBus | None = None):
        self.event_bus = event_bus or EventBus()

    def on_session_start(self, session):
        """会话开始时触发。"""
        return self.event_bus.emit("session_start", session)

    def on_session_shutdown(self, session):
        """会话关闭时触发。"""
        return self.event_bus.emit("session_shutdown", session)

    def before_tool_call(self, tool_name: str, args: dict) -> dict | None:
        """工具调用前触发。可返回拦截结果。

        Returns:
            None 或 {"block": True, "reason": "..."} 表示拦截
        """
        results = self.event_bus.emit("before_tool_call", None,
                                       tool_name=tool_name, args=args)
        for r in results:
            if isinstance(r, dict) and r.get("block"):
                return r
        return None

    def after_tool_call(self, tool_name: str, args: dict, result: str):
        """工具调用后触发。"""
        return self.event_bus.emit("after_tool_call", None,
                                    tool_name=tool_name, args=args, result=result)

    def on_message_received(self, content: str):
        """收到用户消息时触发。"""
        return self.event_bus.emit("message_received", None, content=content)

    def on_message_sent(self, content: str):
        """发送助理消息时触发。"""
        return self.event_bus.emit("message_sent", None, content=content)

    def on_error(self, error: Exception):
        """发生错误时触发。"""
        return self.event_bus.emit("error_occurred", None, error=str(error))


# ═══ 全局实例 ═══════════════════════════════════════════

# 全局 EventBus（单例）
_global_event_bus = EventBus()
_global_extension_loader = ExtensionLoader(event_bus=_global_event_bus)
_global_lifecycle_hooks = LifecycleHooks(event_bus=_global_event_bus)


def get_global_event_bus() -> EventBus:
    """获取全局 EventBus 实例。"""
    return _global_event_bus


def get_global_extension_loader() -> ExtensionLoader:
    """获取全局 ExtensionLoader 实例。"""
    return _global_extension_loader


def get_global_lifecycle_hooks() -> LifecycleHooks:
    """获取全局 LifecycleHooks 实例。"""
    return _global_lifecycle_hooks


# ═══ 示例扩展文件模板 ═══════════════════════════════════

SAMPLE_EXTENSION_TEMPLATE = '''"""
Tea Agent 扩展模板

将此文件放入 ~/.tea_agent/extensions/ 或 .tea_agent/extensions/
扩展会自动发现并加载。

用法：
    - 定义 setup(api) 函数
    - 使用 @api.on() 注册事件处理器
    - 使用 api.register_tool() 注册工具
"""

def setup(api):
    """扩展入口函数。"""

    # ── 事件处理器 ──

    @api.on("session_start")
    def on_session_start(ctx):
        print(f"🔌 扩展 [{api.name}] 已激活")

    @api.on("before_tool_call")
    def check_tool(ctx, tool_name, args):
        \"\"\"在工具调用前检查。\"\"\"
        if tool_name == "toolkit_exec":
            command = args.get("command", "")
            if "rm -rf" in command and "/" in command:
                return {"block": True, "reason": "危险操作被拦截：禁止递归删除根目录"}
        # 不返回 {"block": True} 则放行

    @api.on("after_tool_call")
    def on_tool_result(ctx, tool_name, args, result):
        \"\"\"工具调用后记录。\"\"\"
        if tool_name == "toolkit_search":
            print(f"搜索完成: {len(result)} 字符")

    # ── 注册自定义工具 ──

    api.register_tool(
        name="my_hello",
        description="Say hello to someone",
        handler=lambda name: f"Hello, {name}!",
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Name to greet"},
            },
            "required": ["name"],
        },
    )

    # ── 注册命令 ──

    api.register_command(
        name="hello",
        handler=lambda args: f"Hello, {' '.join(args) if args else 'World'}!",
        description="Say hello",
    )
'''
