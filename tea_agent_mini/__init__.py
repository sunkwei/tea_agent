"""
tea_agent_mini — Tea Agent 精简版，面向嵌入式设备。

核心特性：
- ✅ Agent（lightweight / full / lite 三种模式）
- ✅ Storage（SQLite 持久化存储）
- ✅ Toolkit（64 内置工具函数）
- ✅ LiteSession / LiteAgent（轻量级会话和子任务执行）
- ✅ Server（REST API + Web UI + OpenAI 兼容接口）

不包含（需用完整版 tea_agent）：
- ❌ ACP Protocol
- ❌ LSP 支持
- ❌ SDK
- ❌ 调度器存储 / 自动修复

注：GUI（Tkinter）/ TUI / CLI 三种交互界面已于 v0.16.x 从**整个项目**移除
（不只是精简版），交互面统一为 Web + REST API。

用法：
    # 启动 Web 服务器
    python -m tea_agent_mini

    # 在代码中使用
    from tea_agent_mini import Agent, Storage, LiteSession, LiteAgent
"""

# ── 版本号（历史缺陷: 此前无 __version__，运行时版本检测直接 AttributeError）──
# wheel 安装后读自身 dist-info；源码树运行（未打包）时回落主包 tea_agent 的版本。
try:
    from importlib.metadata import PackageNotFoundError
    from importlib.metadata import version as _pkg_version

    try:
        __version__ = _pkg_version("tea_agent_mini")
    except PackageNotFoundError:
        __version__ = _pkg_version("tea_agent")
except Exception:
    __version__ = "0.0.0"

# ── 核心 Agent ──
from tea_agent.agent import Agent
from tea_agent.litesession import LiteSession

# ── 轻量子 Agent ──
from tea_agent.multi_agent import LiteAgent

# ── Server ──
from tea_agent.server import create_app, run_server
from tea_agent.server import main as run_server_main

# ── 存储 ──
from tea_agent.store import Storage, get_storage

# ── Toolkit ──
# Toolkit 由 Agent 内部管理，完成后会写入 tlk.toolkit 模块全局供外部读取
# 如需直接使用：from tea_agent.tlk import Toolkit

__all__ = [
    # Agent
    "Agent",
    "LiteSession",
    # Storage
    "Storage",
    "get_storage",
    # Lite Agent
    "LiteAgent",
    # Server
    "create_app",
    "run_server",
    "run_server_main",
]
