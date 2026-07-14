"""ACP Protocol — Agent Client Protocol implementation for Tea Agent.

Supports two modes:
  - **stdio** (default): JSON-RPC 2.0 over stdin/stdout, used by vscode-acp
  - **http** (legacy): HTTP REST + SSE, used by older integrations

Usage:
    python -m tea_agent.protocol               # stdio mode (default)
    python -m tea_agent.protocol --http         # HTTP mode
    python -m tea_agent.protocol --port 8082    # HTTP on custom port
"""
from tea_agent.protocol.acp_agent import AcpAgent
from tea_agent.protocol.acp_jsonrpc import (
    JsonRpcError,
    JsonRpcMessage,
    JsonRpcTransport,
)
from tea_agent.protocol.acp_server import (
    ACPProtocolServer,
    create_app,
    run_server,
)

__all__ = [
    "AcpAgent",
    "JsonRpcError",
    "JsonRpcMessage",
    "JsonRpcTransport",
    "ACPProtocolServer",
    "create_app",
    "run_server",
]
__version__ = "0.3.0"
