"""
tea_agent_mini — Tea Agent 精简版，面向嵌入式设备。

核心特性：
- ✅ Agent（lightweight / full / lite 三种模式）
- ✅ Storage（SQLite 持久化存储）
- ✅ Toolkit（70+ 内置工具函数）
- ✅ LiteSession / LiteAgent（轻量级会话和子任务执行）
- ✅ Server（REST API + Web UI + OpenAI 兼容接口）

不包含（需用完整版 tea_agent）：
- ❌ GUI（Tkinter / pywebview）
- ❌ TUI / CLI
- ❌ ACP Protocol
- ❌ LSP 支持
- ❌ SDK
- ❌ 调度器存储 / 自动修复

用法：
    # 启动 Web 服务器
    python -m tea_agent_mini

    # 在代码中使用
    from tea_agent_mini import Agent, Storage, LiteSession, LiteAgent
"""

# ── 核心 Agent ──
from tea_agent.agent import Agent
from tea_agent.litesession import LiteSession

# ── 存储 ──
from tea_agent.store import Storage, get_storage

# ── 轻量子 Agent ──
from tea_agent.multi_agent import LiteAgent

# ── Server ──
from tea_agent.server import create_app, run_server, main as run_server_main

# ── Toolkit ──
# Toolkit 由 Agent 内部管理，通过 tlk._get_toolkit() 访问
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
