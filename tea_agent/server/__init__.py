"""
Tea Agent Unified Server

Provides REST API + Web UI + OpenAI-compatible interface.
Unified entry point: tea-agent-api / python -m tea_agent.server
"""

from tea_agent.server.server import create_app, run_server, get_server_version, main

__all__ = ["create_app", "run_server", "get_server_version", "main"]
__version__ = "0.2.0"
