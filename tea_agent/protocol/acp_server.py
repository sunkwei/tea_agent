"""ACP Protocol Server (HTTP/SSE) - Legacy mode for older integrations.

Supports the same ACP protocol as the stdio-based ``acp_agent.py`` but
over HTTP + SSE.  Built with Starlette + Uvicorn.

.. deprecated::
   The stdio mode (``python -m tea_agent.protocol``) is the primary
   transport used by vscode-acp.  This HTTP server is kept for backward
   compatibility.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import threading
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tea_agent.agent import Agent
    from tea_agent.store import Storage

logger = logging.getLogger("acp_server")

try:
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse, StreamingResponse
    from starlette.routing import Route
except ImportError:
    raise ImportError("pip install starlette uvicorn")

from tea_agent.store import get_storage  # noqa: E402

__version__ = "0.3.0"


class ACPProtocolServer:
    """ACP protocol server over HTTP + SSE.

    Provides REST endpoints for agent discovery, chat (sync + streaming),
    and session management.
    """

    def __init__(self, config_path: str | None = None, api_key: str = ""):
        self._config_path = self._ensure_acp_config(config_path)
        self._api_key = api_key or os.environ.get("TEA_API_KEY", "")
        self._lock = threading.Lock()
        self._agent_id = "tea-agent"
        self._start_time = time.time()
        self._storage: Storage | None = None
        self._agent: Agent | None = None

    @staticmethod
    def _ensure_acp_config(config_path: str | None = None) -> str | None:
        """Ensure the ACP-specific config file exists.

        Same logic as :meth:`AcpAgent._ensure_acp_config`.
        """
        if config_path:
            return config_path

        home_dir = Path.home()
        acp_path = home_dir / ".tea_agent" / "config_acp.yaml"
        default_path = home_dir / ".tea_agent" / "config.yaml"

        if acp_path.is_file():
            return str(acp_path)

        if not default_path.is_file():
            logging.getLogger("acp_server").warning(
                "No config.yaml found at %s — using fallback", default_path,
            )
            return None

        try:
            shutil.copy2(str(default_path), str(acp_path))
            import yaml as _yaml
            with open(acp_path, encoding="utf-8") as f:
                data = _yaml.safe_load(f) or {}
            if "paths" not in data or not isinstance(data["paths"], dict):
                data["paths"] = {}
            data["paths"]["db_path"] = "chat_acp.db"
            with open(acp_path, "w", encoding="utf-8") as f:
                _yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
        except Exception as e:
            logging.getLogger("acp_server").warning(
                "Failed to create ACP config: %s", e,
            )
            return str(default_path)

        return str(acp_path)

    def _get_storage(self) -> Storage:
        """Lazy-init storage backend."""
        if self._storage is None:
            self._storage = get_storage()
        return self._storage

    def discover_agents(self) -> dict:
        """Return the list of available agents (always just tea-agent)."""
        return {"object": "list", "data": [{
            "id": self._agent_id,
            "name": "Tea Agent",
            "description": "Self-evolving AI agent with 60+ built-in tools",
            "capabilities": {
                "streaming": True,
                "tool_execution": True,
                "session_management": True,
            },
        }]}

    def get_agent_info(self) -> dict:
        """Return agent metadata including available tools."""
        try:
            tools = self._try_get_tools()
            return {
                "id": self._agent_id,
                "name": "Tea Agent",
                "description": "Self-evolving AI agent with 60+ tools",
                "tools": tools,
                "capabilities": {
                    "streaming": True,
                    "tool_execution": True,
                    "session_management": True,
                },
            }
        except Exception as e:
            return {
                "id": self._agent_id,
                "name": "Tea Agent",
                "tools": [],
                "error": str(e),
            }

    def _try_get_tools(self) -> list[dict]:
        """Attempt to enumerate toolkit tools from the Agent."""
        try:
            from tea_agent.agent import Agent
            agent = Agent(mode="lightweight", config_path=self._config_path)
            tools = []
            for name, meta in agent.toolkit.meta_map.items():
                fn = meta.get("function", {})
                tools.append({
                    "name": fn.get("name", name),
                    "description": fn.get("description", ""),
                    "input_schema": fn.get("parameters", {}),
                })
            return tools
        except Exception:
            return [{
                "name": "chat",
                "description": "Chat with agent",
                "input_schema": {},
            }]

    def _init_agent(self, session_id: str = "") -> Agent:
        """Get (or create) a shared Agent instance, bound to *session_id*."""
        from tea_agent.agent import Agent
        if self._agent is None:
            self._agent = Agent(
                mode="lightweight", config_path=self._config_path
            )
        if session_id:
            self._agent.current_topic_id = session_id
        elif not self._agent.current_topic_id:
            with self._lock:
                if not self._agent.current_topic_id:
                    self._agent.current_topic_id = (
                        self._get_storage().create_topic("ACP")
                    )
        return self._agent

    def chat(
        self, messages: list[dict], session_id: str = ""
    ) -> dict:
        """Synchronous chat (non-streaming).

        Returns the full response at once.
        """
        if not messages:
            return {"error": "messages required"}
        user_msg = messages[-1].get("content", "")
        if not user_msg:
            return {"error": "last message has no content"}
        try:
            agent = self._init_agent(session_id)
            collected: list[str] = []

            def cb(text: str):
                if text and not text.startswith("["):
                    collected.append(text)

            ai_msg, used = agent.sess.chat_stream(
                user_msg,
                callback=cb,
                topic_id=agent.current_topic_id,
            )
            return {
                "id": "chat-" + uuid.uuid4().hex[:12],
                "agent_id": self._agent_id,
                "choices": [{
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": "".join(collected) or ai_msg,
                    },
                    "finish_reason": "stop",
                }],
                "tools_used": used or [],
            }
        except Exception as e:
            return {"error": str(e)}

    async def chat_stream(
        self, messages: list[dict], session_id: str = ""
    ):
        """Streaming chat via SSE.

        Yields ``data:`` lines (JSON) following the SSE protocol,
        ending with ``data: [DONE]``.
        """
        if not messages:
            yield "data: " + json.dumps(
                {"error": "messages required"}
            ) + "\n\n"
            yield "data: [DONE]\n\n"
            return
        user_msg = messages[-1].get("content", "")
        if not user_msg:
            yield "data: " + json.dumps(
                {"error": "last message has no content"}
            ) + "\n\n"
            yield "data: [DONE]\n\n"
            return

        queue: asyncio.Queue[dict] = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def put(event: dict):
            try:
                loop.call_soon_threadsafe(
                    lambda: queue.put_nowait(event)
                )
            except Exception:
                logger.exception('op_failed')

        def cb(text: str):
            if not text or text.startswith("["):
                return
            put({"type": "content", "text": text})

        threading.Thread(
            target=self._run_stream,
            args=(user_msg, session_id, cb, put),
            daemon=True,
        ).start()

        cid = "chat-" + uuid.uuid4().hex[:12]
        now = int(time.time())
        yield (
            "data: "
            + json.dumps({
                "id": cid,
                "object": "chat.chunk",
                "created": now,
                "choices": [{
                    "index": 0,
                    "delta": {"role": "assistant"},
                    "finish_reason": None,
                }],
            })
            + "\n\n"
        )

        while True:
            event = await queue.get()
            if event["type"] == "content":
                yield (
                    "data: "
                    + json.dumps({
                        "id": cid,
                        "object": "chat.chunk",
                        "created": now,
                        "choices": [{
                            "index": 0,
                            "delta": {"content": event["text"]},
                            "finish_reason": None,
                        }],
                    })
                    + "\n\n"
                )
            elif event["type"] == "done":
                yield (
                    "data: "
                    + json.dumps({
                        "id": cid,
                        "object": "chat.chunk",
                        "created": now,
                        "choices": [{
                            "index": 0,
                            "delta": {},
                            "finish_reason": "stop",
                        }],
                    })
                    + "\n\n"
                )
                yield "data: [DONE]\n\n"
                break
            elif event["type"] == "error":
                yield (
                    "data: "
                    + json.dumps({"error": event["error"]})
                    + "\n\n"
                )
                yield "data: [DONE]\n\n"
                break

    def _run_stream(
        self,
        user_msg: str,
        session_id: str,
        cb: callable,
        put: callable,
    ):
        """Run chat_stream in a background thread and feed the asyncio queue."""
        try:
            agent = self._init_agent(session_id)
            ai_msg, used = agent.sess.chat_stream(
                user_msg,
                callback=cb,
                topic_id=agent.current_topic_id,
            )
            put({"type": "done", "ai_msg": ai_msg, "tools_used": used or []})
        except Exception as e:
            put({"type": "error", "error": str(e)})

    def list_sessions(self, limit: int = 50) -> dict:
        """List sessions from storage."""
        s = self._get_storage()
        result = []
        for t in s.list_topics()[:limit]:
            tid = t["topic_id"]
            tk = s.get_topic_tokens(tid)
            result.append({
                "id": tid,
                "title": t.get("title", "") or tid[:8],
                "created": str(t.get("create_stamp", ""))[:19],
                "updated": str(t.get("last_update_stamp", ""))[:19],
                "total_tokens": (tk or {}).get("total_tokens", 0),
            })
        return {"object": "list", "data": result, "total": len(result)}

    def create_session(self, title: str = "ACP") -> dict:
        """Create a new session in storage."""
        tid = self._get_storage().create_topic(title)
        return {"id": tid, "title": title, "object": "session"}

    def get_session(self, sid: str) -> dict | None:
        """Get session metadata, or None if not found."""
        s = self._get_storage()
        t = s.get_topic(sid)
        if not t:
            return None
        tk = s.get_topic_tokens(sid)
        return {
            "id": sid,
            "title": t.get("title", ""),
            "created": str(t.get("create_stamp", "")),
            "updated": str(t.get("last_update_stamp", "")),
            "total_tokens": (tk or {}).get("total_tokens", 0),
        }

    def delete_session(self, sid: str) -> bool:
        """Delete a session from storage."""
        try:
            return self._get_storage().delete_topic(sid)
        except Exception:
            return False

    def get_messages(
        self, sid: str, limit: int = 50
    ) -> dict:
        """Get messages for a session."""
        s = self._get_storage()
        msgs = []
        for c in s.get_conversations(sid, limit=limit, include_rounds=True):
            msgs.append({
                "id": c["id"],
                "role": "user",
                "content": c["user_msg"],
                "stamp": str(c.get("stamp", ""))[:26],
            })
            msgs.append({
                "id": c["id"],
                "role": "assistant",
                "content": c["ai_msg"],
                "stamp": str(c.get("stamp", ""))[:26],
            })
        return {"object": "list", "data": msgs, "total": len(msgs)}

_server_instance = None

def get_server():
    global _server_instance
    if _server_instance is None:
        _server_instance = ACPProtocolServer()
    return _server_instance

async def handle_health(request):
    return JSONResponse({"status": "ok", "server": "tea-agent-acp", "version": __version__})

async def handle_discover_agents(request):
    return JSONResponse(get_server().discover_agents())

async def handle_agent_info(request):
    return JSONResponse(get_server().get_agent_info())

async def handle_agent_chat(request):
    body = await request.json()
    messages = body.get("messages", [])
    stream = body.get("stream", False)
    sid = body.get("session_id", "")
    if not messages:
        return JSONResponse({"error": "messages required"}, status_code=400)
    if stream:
        return StreamingResponse(get_server().chat_stream(messages, session_id=sid),
            media_type="text/event-stream",
            headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"})
    return JSONResponse(get_server().chat(messages, session_id=sid))

async def handle_list_sessions(request):
    return JSONResponse(get_server().list_sessions())

async def handle_create_session(request):
    body = await request.json()
    return JSONResponse(get_server().create_session(body.get("title","ACP")), status_code=201)

async def handle_get_session(request):
    s = get_server().get_session(request.path_params.get("session_id", ""))
    if s is None:
        return JSONResponse({"error": "Not found"}, status_code=404)
    return JSONResponse(s)

async def handle_delete_session(request):
    return JSONResponse({"deleted": get_server().delete_session(request.path_params.get("session_id", ""))})

async def handle_get_messages(request):
    return JSONResponse(get_server().get_messages(
        request.path_params.get("session_id", ""),
        int(request.query_params.get("limit", 50))))

def create_app(config_path=None):
    global _server_instance
    _server_instance = ACPProtocolServer(config_path=config_path)
    routes = [
        Route("/health", endpoint=handle_health),
        Route("/v1/agents", endpoint=handle_discover_agents),
        Route("/v1/agents/tea-agent", endpoint=handle_agent_info),
        Route("/v1/agents/tea-agent/chat", endpoint=handle_agent_chat, methods=["POST"]),
        Route("/v1/sessions", endpoint=handle_list_sessions),
        Route("/v1/sessions", endpoint=handle_create_session, methods=["POST"]),
        Route("/v1/sessions/{session_id:str}", endpoint=handle_get_session),
        Route("/v1/sessions/{session_id:str}", endpoint=handle_delete_session, methods=["DELETE"]),
        Route("/v1/sessions/{session_id:str}/messages", endpoint=handle_get_messages),
    ]
    return Starlette(debug=False, routes=routes)

def run_server(host="127.0.0.1", port=8082, config_path=None):
    try:
        import uvicorn
    except ImportError:
        raise ImportError("pip install uvicorn")
    app = create_app(config_path=config_path)
    logger.info(f"ACP Server: http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="info")

def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8082)
    p.add_argument("--config", default=None)
    args = p.parse_args()
    run_server(host=args.host, port=args.port, config_path=args.config)

if __name__ == "__main__":
    main()
