"""
Tea Agent Unified Server — Hot-Reloadable Module Architecture

Provides REST API + Web UI + OpenAI-compatible interface + Module Hot-Reload.
All business logic is delegated to hot-reload modules (Agent/Toolkit/Storage/Pipeline).

Quick start:
    python -m tea_agent.server

Module management:
    GET  /api/modules                  — list all modules
    GET  /api/modules/{name}           — get module health
    POST /api/modules/{name}/reload    — hot-reload a module
    POST /api/modules/reload           — reload all modules
    POST /api/modules/watcher/start    — start file watcher (auto-reload)
    POST /api/modules/watcher/stop     — stop file watcher
"""

from tea_agent.server.server import create_app, get_server, run_server, main, __version__

__all__ = ["create_app", "run_server", "get_server", "main"]
__version__ = __version__

