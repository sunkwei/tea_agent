"""
Tea Agent HTTP API Server

Provides RESTful API and OpenAI-compatible interface for external integration.
"""

from tea_agent.server.server import create_app, run_server, get_server_version, main

__all__ = ["create_app", "run_server", "get_server_version", "main"]
__version__ = "0.1.0"
