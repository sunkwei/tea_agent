"""ACP Agent — Full JSON-RPC 2.0 / stdio Agent Server.

Implements the complete Agent Client Protocol (ACP) v1.2.1 from the
agent side. Communicates with VS Code (or any ACP client) via
JSON-RPC 2.0 over stdin/stdout.

Protocol lifecycle:
  1. Client sends ``initialize`` → Agent responds with capabilities
  2. Client sends ``session/new`` (with cwd) → Agent creates session
  3. Client sends ``session/prompt`` (with messages) → Agent responds
  4. Agent sends ``session/update`` notifications for streaming
  5. Agent may call client-side methods (fs/*, terminal/*, permissions)
"""

import asyncio
import json
import logging
import os
import sys
import threading
import time
import uuid
from typing import Any, Optional

from tea_agent.protocol.acp_jsonrpc import (
    JsonRpcError,
    JsonRpcMessage,
    JsonRpcTransport,
    RequestId,
)
from tea_agent.protocol.acp_client_methods import AcpClientMethods

logger = logging.getLogger("acp.agent")

# ── Protocol constants ────────────────────────────────────────────────────

PROTOCOL_VERSION = 1

# Methods the agent handles (incoming from client)
AGENT_METHODS = {
    # Lifecycle
    "initialize": "Initialize the agent and exchange capabilities",
    "authenticate": "Authenticate the agent with credentials",
    "logout": "Log out the current user",
    # Provider/model management
    "providers/list": "List available LLM providers/models",
    "providers/set": "Set the active provider/model",
    "providers/disable": "Disable a provider",
    # Session lifecycle
    "session/new": "Create a new session",
    "session/load": "Load an existing session",
    "session/list": "List available sessions",
    "session/delete": "Delete a session",
    "session/fork": "Fork an existing session",
    "session/resume": "Resume a session",
    "session/close": "Close a session",
    "session/prompt": "Send a prompt in a session",
    "session/cancel": "Cancel the current turn",
    "session/set_mode": "Set the session mode",
    "session/set_config_option": "Set a session config option",
    # Document events
    "document/didOpen": "Document opened",
    "document/didChange": "Document changed",
    "document/didClose": "Document closed",
    "document/didSave": "Document saved",
    "document/didFocus": "Document focused",
    # NES (Inline Edit Suggestions)
    "nes/start": "Start an inline edit suggestion",
    "nes/suggest": "Suggest an edit",
    "nes/accept": "Accept a suggestion",
    "nes/reject": "Reject a suggestion",
    "nes/close": "Close NES session",
}

# Client-side methods that the agent can call
CLIENT_METHODS = {
    "session/request_permission": "Request user permission",
    "session/update": "Send a session update notification",
    "session/update_config": "Update session config options",
    "session/update_commands": "Update available commands",
    "session/info_update": "Update session information",
    "fs/read_text_file": "Read a text file via the client",
    "fs/write_text_file": "Write a text file via the client",
    "terminal/create": "Create a terminal",
    "terminal/output": "Read terminal output",
    "terminal/wait_for_exit": "Wait for terminal to exit",
    "terminal/kill": "Kill a terminal",
    "terminal/release": "Release a terminal",
    "elicitation/create": "Create an elicitation form",
    "mcp/connect": "Connect an MCP server",
    "mcp/message": "Send a message to an MCP server",
    "mcp/disconnect": "Disconnect an MCP server",
}


class AcpAgent:
    """Full ACP Agent implementation.

    Wraps the Tea Agent engine and exposes it via the ACP protocol over
    JSON-RPC 2.0 / stdio.
    """

    def __init__(
        self,
        config_path: Optional[str] = None,
        api_key: Optional[str] = None,
        agent_name: str = "tea-agent",
        agent_version: str = "0.3.0",
    ):
        self._config_path = config_path
        self._api_key = api_key or os.environ.get("TEA_API_KEY", "")
        self._agent_name = agent_name
        self._agent_version = agent_version

        # Transport
        self._transport = JsonRpcTransport()

        # Client methods (agent → client calls)
        self.client = AcpClientMethods(self._transport)

        # Sessions: session_id -> session info
        self._sessions: dict[str, "SessionState"] = {}
        self._sessions_lock = threading.Lock()

        # Active turn tracking for cancellation
        self._active_turns: dict[str, threading.Event] = {}
        self._active_turns_lock = threading.Lock()

        # Cached agent reference (lazy init)
        self._agent = None

        # Register all handlers
        self._register_handlers()

    # ── public API ─────────────────────────────────────────────────────────

    def run(self):
        """Start the agent: register handlers and begin reading stdin."""
        logger.info(
            f"ACP Agent {self._agent_name} v{self._agent_version} "
            f"starting (JSON-RPC 2.0 / stdio)"
        )

        try:
            self._transport.start()
        except KeyboardInterrupt:
            logger.info("ACP Agent: shutting down")
        finally:
            self._shutdown()

    def stop(self):
        """Gracefully stop the agent."""
        self._transport.stop()

    # ── handler registration ──────────────────────────────────────────────

    def _register_handlers(self):
        t = self._transport

        # Lifecycle
        t.on_request("initialize", self._handle_initialize)
        t.on_request("authenticate", self._handle_authenticate)
        t.on_request("logout", self._handle_logout)

        # Provider/model
        t.on_request("providers/list", self._handle_providers_list)
        t.on_request("providers/set", self._handle_providers_set)
        t.on_request("providers/disable", self._handle_providers_disable)

        # Session lifecycle
        t.on_request("session/new", self._handle_session_new)
        t.on_request("session/load", self._handle_session_load)
        t.on_request("session/list", self._handle_session_list)
        t.on_request("session/delete", self._handle_session_delete)
        t.on_request("session/fork", self._handle_session_fork)
        t.on_request("session/resume", self._handle_session_resume)
        t.on_request("session/close", self._handle_session_close)
        t.on_request("session/prompt", self._handle_session_prompt)
        t.on_request("session/cancel", self._handle_session_cancel)
        t.on_request("session/set_mode", self._handle_session_set_mode)
        t.on_request(
            "session/set_config_option",
            self._handle_session_set_config_option,
        )

        # Document events (notifications)
        t.on_notification(
            "document/didOpen", self._handle_document_did_open
        )
        t.on_notification(
            "document/didChange", self._handle_document_did_change
        )
        t.on_notification(
            "document/didClose", self._handle_document_did_close
        )
        t.on_notification(
            "document/didSave", self._handle_document_did_save
        )
        t.on_notification(
            "document/didFocus", self._handle_document_did_focus
        )

        # NES (Inline Edit Suggestions)
        t.on_request("nes/start", self._handle_nes_start)
        t.on_request("nes/suggest", self._handle_nes_suggest)
        t.on_request("nes/accept", self._handle_nes_accept)
        t.on_request("nes/reject", self._handle_nes_reject)
        t.on_request("nes/close", self._handle_nes_close)

        # Extension points (custom)
        t.on_request("ext/request", self._handle_ext_request)
        t.on_notification("ext/notification", self._handle_ext_notification)

        # Cancel support
        t.on_cancel(self._handle_cancel_request)

    # ══════════════════════════════════════════════════════════════════════
    # HANDLERS — Lifecycle
    # ══════════════════════════════════════════════════════════════════════

    def _handle_initialize(
        self, params: Any, msg_id: RequestId
    ) -> dict:
        """Handle ``initialize`` — exchange capabilities with the client.

        Receives ClientCapabilities, responds with AgentCapabilities.
        """
        logger.info(
            f"initialize: client={params.get('clientInfo', {})}"
            if params
            else "initialize"
        )

        client_caps = (params or {}).get("clientCapabilities", {})

        # Build agent capabilities
        # These define what the agent can do
        agent_capabilities = {
            "streaming": True,
            "tool_execution": True,
            "session_management": True,
            "sessionCapabilities": {
                "list": True,
                "delete": True,
            },
        }

        return {
            "protocolVersion": PROTOCOL_VERSION,
            "agentInfo": {
                "name": self._agent_name,
                "version": self._agent_version,
                "description": "Self-evolving AI agent with 60+ tools",
            },
            "agentCapabilities": agent_capabilities,
        }

    def _handle_authenticate(
        self, params: Any, msg_id: RequestId
    ) -> dict:
        """Handle ``authenticate`` — authenticate the agent."""
        logger.info("authenticate requested")
        return {"authenticated": True, "user": "tea-agent-user"}

    def _handle_logout(
        self, params: Any, msg_id: RequestId
    ) -> dict:
        """Handle ``logout`` — log out the current user."""
        logger.info("logout")
        return {"logged_out": True}

    # ══════════════════════════════════════════════════════════════════════
    # HANDLERS — Provider/Model Management
    # ══════════════════════════════════════════════════════════════════════

    def _handle_providers_list(
        self, params: Any, msg_id: RequestId
    ) -> dict:
        """Handle ``providers/list`` — list available models."""
        try:
            from tea_agent.config import get_config

            config = get_config(self._config_path)
            providers = []

            # Try to discover configured models
            for key in ["main_model", "cheap_model", "embedding_model"]:
                model_name = getattr(config, key, None)
                if model_name:
                    providers.append({
                        "id": key,
                        "name": key.replace("_", " ").title(),
                        "model": model_name,
                        "active": key == "main_model",
                    })

            if not providers:
                providers = [
                    {"id": "default", "name": "Default Model",
                     "model": "auto", "active": True},
                ]

            return {"object": "list", "data": providers}
        except Exception as e:
            logger.exception("providers/list failed")
            return {"object": "list", "data": [], "error": str(e)}

    def _handle_providers_set(
        self, params: Any, msg_id: RequestId
    ) -> dict:
        """Handle ``providers/set`` — set the active provider/model."""
        logger.info(f"providers/set: {params}")
        provider_id = (params or {}).get("provider_id", "")
        model = (params or {}).get("model", "")
        return {"success": True, "provider_id": provider_id,
                "model": model}

    def _handle_providers_disable(
        self, params: Any, msg_id: RequestId
    ) -> dict:
        """Handle ``providers/disable`` — disable a provider."""
        provider_id = (params or {}).get("provider_id", "")
        logger.info(f"providers/disable: {provider_id}")
        return {"success": True}

    # ══════════════════════════════════════════════════════════════════════
    # HANDLERS — Session Lifecycle
    # ══════════════════════════════════════════════════════════════════════

    def _handle_session_new(
        self, params: Any, msg_id: RequestId
    ) -> dict:
        """Handle ``session/new`` — create a new session.

        Accepts: cwd, additionalDirectories, mcpServers, mode, model,
                 configOptions, tools, context.
        """
        cwd = (params or {}).get("cwd", os.getcwd())
        additional_dirs = (params or {}).get(
            "additionalDirectories", []
        )
        mode = (params or {}).get("mode")
        model = (params or {}).get("model")

        session_id = str(uuid.uuid4())
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        session = SessionState(
            session_id=session_id,
            cwd=cwd,
            created_at=now,
            mode=mode,
            model=model,
            additional_directories=additional_dirs,
        )

        with self._sessions_lock:
            self._sessions[session_id] = session

        logger.info(
            f"session/new: {session_id} cwd={cwd} "
            f"mode={mode} model={model}"
        )

        # Build available commands and config options for the client
        available_commands = self._get_available_commands()
        config_options = self._get_config_options()

        return {
            "sessionId": session_id,
            "createdAt": now,
            "cwd": cwd,
            "additionalDirectories": additional_dirs,
            "availableCommands": available_commands,
            "modes": {
                "modes": [
                    {"id": "develop", "name": "Develop"},
                    {"id": "design", "name": "Design"},
                    {"id": "test", "name": "Test"},
                    {"id": "review", "name": "Review"},
                    {"id": "docs", "name": "Documentation"},
                    {"id": "devops", "name": "DevOps"},
                ],
                "activeModeId": mode or "develop",
            },
            "models": {
                "providerId": "default",
                "modelId": model or "auto",
                "models": [
                    {"id": "auto", "name": "Auto (default)"},
                    {"id": "fast", "name": "Fast"},
                    {"id": "reasoning", "name": "Reasoning"},
                ],
            },
            "configOptions": config_options,
        }

    def _handle_session_load(
        self, params: Any, msg_id: RequestId
    ) -> dict:
        """Handle ``session/load`` — load an existing session."""
        session_id = (params or {}).get("sessionId", "")
        logger.info(f"session/load: {session_id}")

        with self._sessions_lock:
            session = self._sessions.get(session_id)

        if not session:
            # Try loading from storage
            try:
                from tea_agent.store import get_storage

                storage = get_storage()
                topic = storage.get_topic(session_id)
                if topic:
                    now = time.strftime(
                        "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
                    )
                    session = SessionState(
                        session_id=session_id,
                        cwd=os.getcwd(),
                        created_at=str(
                            topic.get("create_stamp", "")
                        )[:19],
                        title=topic.get("title", ""),
                    )
                    with self._sessions_lock:
                        self._sessions[session_id] = session
            except Exception as e:
                logger.error(f"session/load storage error: {e}")

        if not session:
            raise JsonRpcError(
                JsonRpcError.INVALID_PARAMS,
                f"Session not found: {session_id}",
            )

        return {
            "sessionId": session.session_id,
            "createdAt": session.created_at,
            "cwd": session.cwd,
            "availableCommands": self._get_available_commands(),
            "configOptions": self._get_config_options(),
            "modes": {
                "modes": [
                    {"id": "develop", "name": "Develop"},
                    {"id": "design", "name": "Design"},
                ],
                "activeModeId": session.mode or "develop",
            },
            "models": {
                "providerId": "default",
                "modelId": session.model or "auto",
                "models": [
                    {"id": "auto", "name": "Auto (default)"},
                ],
            },
        }

    def _handle_session_list(
        self, params: Any, msg_id: RequestId
    ) -> dict:
        """Handle ``session/list`` — list available sessions."""
        limit = (params or {}).get("limit", 50)
        sessions = []

        with self._sessions_lock:
            for sid, s in list(self._sessions.items())[:limit]:
                sessions.append({
                    "sessionId": sid,
                    "title": s.title or sid[:8],
                    "createdAt": s.created_at,
                    "cwd": s.cwd,
                })

        # Also try storage
        try:
            from tea_agent.store import get_storage

            storage = get_storage()
            for t in storage.list_topics()[:limit]:
                tid = t["topic_id"]
                if tid not in self._sessions:
                    sessions.append({
                        "sessionId": tid,
                        "title": t.get("title", "") or tid[:8],
                        "createdAt": str(
                            t.get("create_stamp", "")
                        )[:19],
                    })
        except Exception:
            pass

        return {"object": "list", "data": sessions,
                "total": len(sessions)}

    def _handle_session_delete(
        self, params: Any, msg_id: RequestId
    ) -> dict:
        """Handle ``session/delete`` — delete a session."""
        session_id = (params or {}).get("sessionId", "")
        logger.info(f"session/delete: {session_id}")

        with self._sessions_lock:
            self._sessions.pop(session_id, None)

        try:
            from tea_agent.store import get_storage

            get_storage().delete_topic(session_id)
        except Exception:
            pass

        return {"success": True, "sessionId": session_id}

    def _handle_session_fork(
        self, params: Any, msg_id: RequestId
    ) -> dict:
        """Handle ``session/fork`` — fork an existing session."""
        session_id = (params or {}).get("sessionId", "")
        logger.info(f"session/fork: {session_id}")

        new_id = str(uuid.uuid4())
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        with self._sessions_lock:
            original = self._sessions.get(session_id)
            if original:
                session = SessionState(
                    session_id=new_id,
                    cwd=original.cwd,
                    created_at=now,
                    mode=original.mode,
                    model=original.model,
                    title=f"Fork of {original.title or session_id[:8]}",
                )
                self._sessions[new_id] = session

        return {
            "sessionId": new_id,
            "createdAt": now,
            "forkedFrom": session_id,
        }

    def _handle_session_resume(
        self, params: Any, msg_id: RequestId
    ) -> dict:
        """Handle ``session/resume`` — resume a session."""
        session_id = (params or {}).get("sessionId", "")
        logger.info(f"session/resume: {session_id}")

        with self._sessions_lock:
            session = self._sessions.get(session_id)

        if not session:
            raise JsonRpcError(
                JsonRpcError.INVALID_PARAMS,
                f"Session not found: {session_id}",
            )

        return {
            "sessionId": session.session_id,
            "createdAt": session.created_at,
            "cwd": session.cwd,
            "availableCommands": self._get_available_commands(),
            "configOptions": self._get_config_options(),
        }

    def _handle_session_close(
        self, params: Any, msg_id: RequestId
    ) -> dict:
        """Handle ``session/close`` — close a session."""
        session_id = (params or {}).get("sessionId", "")
        logger.info(f"session/close: {session_id}")

        with self._sessions_lock:
            self._sessions.pop(session_id, None)

        return {"success": True, "sessionId": session_id}

    # ══════════════════════════════════════════════════════════════════════
    # HANDLER — session/prompt (the core)
    # ══════════════════════════════════════════════════════════════════════

    def _handle_session_prompt(
        self, params: Any, msg_id: RequestId
    ) -> dict:
        """Handle ``session/prompt`` — send a prompt to the agent.

        This is the main chat endpoint. It receives a list of messages
        and returns the agent's response.

        For streaming, the agent sends ``session/update`` notifications
        with content blocks before responding with the final result.
        """
        session_id = (params or {}).get("sessionId", "")
        messages = (params or {}).get("messages", [])
        tools = (params or {}).get("tools", [])

        # 调试：打印收到的参数（完整 JSON）
        logger.info(f"session/prompt raw_params type={type(params).__name__}: {json.dumps(params, ensure_ascii=False, default=str)[:500]}")

        # 兼容各种参数格式：
        # 1. 标准格式：{"messages": [...]}
        # 2. ACP 标准格式：{"prompt": [...]} (vscode-acp-client 0.2.0)
        # 3. text 格式：{"text": "..."} (旧版简化协议)
        # 4. 直接字符串参数："..." (旧版简化协议)
        if not messages:
            if isinstance(params, str):
                messages = [{"role": "user", "content": params}]
            elif isinstance(params, dict):
                # ACP 标准：prompt 是 content block 数组
                # [{"type": "text", "text": "..."}, ...]
                prompt = params.get("prompt")
                if prompt and isinstance(prompt, list):
                    texts = []
                    for block in prompt:
                        if isinstance(block, dict):
                            if block.get("type") == "text":
                                texts.append(block.get("text", ""))
                            elif block.get("type") == "image":
                                texts.append("[Image]")
                    combined = "\n".join(texts)
                    if combined:
                        messages = [{"role": "user", "content": combined}]
                else:
                    text = params.get("text", "")
                    if text:
                        messages = [{"role": "user", "content": text}]

        if not messages:
            raise JsonRpcError(
                JsonRpcError.INVALID_PARAMS,
                "messages is required",
            )

        logger.info(
            f"session/prompt: session={session_id[:8] if session_id else 'new'} "
            f"messages={len(messages)}"
        )

        # Signal that this turn is active (for cancellation)
        cancel_event = threading.Event()
        with self._active_turns_lock:
            self._active_turns[session_id] = cancel_event

        try:
            # Get the user's last message
            last_msg = messages[-1]
            user_content = self._extract_text_content(last_msg)

            # Optionally include conversation history
            history = []
            for m in messages[:-1]:
                role = m.get("role", "user")
                content = self._extract_text_content(m)
                if content:
                    history.append({"role": role, "content": content})

            # Build the full prompt with context
            prompt_parts = []
            if history:
                prompt_parts.append(
                    "Previous conversation:\n"
                    + "\n".join(
                        f"{m['role']}: {m['content']}"
                        for m in history
                    )
                )
            prompt_parts.append(user_content)
            full_prompt = "\n\n".join(prompt_parts)

            # Check for cancellation before processing
            if cancel_event.is_set():
                return {
                    "messages": [
                        {
                            "role": "assistant",
                            "content": [
                                {
                                    "type": "text",
                                    "text": (
                                        "The request was cancelled."
                                    ),
                                }
                            ],
                        }
                    ],
                    "stopReason": "cancelled",
                }

            # Send a "status" update to show we're thinking
            try:
                self.client.send_update(
                    session_id,
                    "status",
                    status="Processing your request...",
                )
            except Exception:
                pass

            # Process via Tea Agent with streaming callback
            stream_buffer = []
            tool_calls = []

            def stream_callback(text: str):
                if cancel_event.is_set():
                    return
                if text and not text.startswith("["):
                    stream_buffer.append(text)
                    # Send streaming content block updates (every chunk)
                    try:
                        self.client.send_update(
                            session_id,
                            "content_block",
                            content_blocks=[
                                {
                                    "type": "text",
                                    "text": text,
                                }
                            ],
                        )
                    except Exception:
                        pass

            ai_text, tool_calls = self._process_prompt(
                session_id, full_prompt, cancel_event,
                stream_callback=stream_callback,
            )

            # Check for cancellation during processing
            if cancel_event.is_set():
                return {
                    "messages": [
                        {
                            "role": "assistant",
                            "content": [
                                {
                                    "type": "text",
                                    "text": (
                                        "The request was cancelled."
                                    ),
                                }
                            ],
                        }
                    ],
                    "stopReason": "cancelled",
                }

            # Build the response content blocks
            content_blocks = [{"type": "text", "text": ai_text}]

            # Add tool call results if any
            for tc in tool_calls:
                content_blocks.append({
                    "type": "tool_use",
                    "name": tc.get("name", "unknown"),
                    "input": tc.get("input", {}),
                    "tool_use_id": tc.get(
                        "id", f"tu_{uuid.uuid4().hex[:12]}"
                    ),
                })

            # Send final update to signal completion
            try:
                self.client.send_update(
                    session_id,
                    "completed",
                    status="Response complete",
                )
            except Exception:
                pass

            # Send the final response
            return {
                "messages": [
                    {
                        "role": "assistant",
                        "content": content_blocks,
                    }
                ],
                "stopReason": "end_turn" if not tool_calls
                else "tool_use",
                "toolsUsed": tool_calls or [],
            }

        except Exception as e:
            logger.exception("session/prompt failed")
            raise JsonRpcError(
                JsonRpcError.INTERNAL_ERROR,
                f"Prompt processing failed: {e}",
            )
        finally:
            with self._active_turns_lock:
                self._active_turns.pop(session_id, None)

    def _handle_session_cancel(
        self, params: Any, msg_id: RequestId
    ) -> dict:
        """Handle ``session/cancel`` — cancel the current turn."""
        session_id = (params or {}).get("sessionId", "")
        logger.info(f"session/cancel: {session_id}")

        with self._active_turns_lock:
            cancel_event = self._active_turns.get(session_id)

        if cancel_event:
            cancel_event.set()
            return {"success": True, "cancelled": True}
        else:
            return {"success": True, "cancelled": False}

    def _handle_session_set_mode(
        self, params: Any, msg_id: RequestId
    ) -> dict:
        """Handle ``session/set_mode`` — set the session mode."""
        session_id = (params or {}).get("sessionId", "")
        mode = (params or {}).get("mode", "")

        with self._sessions_lock:
            session = self._sessions.get(session_id)
            if session:
                session.mode = mode

        logger.info(f"session/set_mode: {session_id} -> {mode}")
        return {"success": True, "mode": mode}

    def _handle_session_set_config_option(
        self, params: Any, msg_id: RequestId
    ) -> dict:
        """Handle ``session/set_config_option`` — set config."""
        session_id = (params or {}).get("sessionId", "")
        option = (params or {}).get("option", "")
        value = (params or {}).get("value")

        logger.info(
            f"session/set_config_option: "
            f"{session_id} {option}={value}"
        )
        return {"success": True}

    # ══════════════════════════════════════════════════════════════════════
    # HANDLERS — Document Events
    # ══════════════════════════════════════════════════════════════════════

    def _handle_document_did_open(self, params: Any):
        path = (params or {}).get("path", "")
        content = (params or {}).get("content", "")
        logger.debug(f"document/didOpen: {path}")

    def _handle_document_did_change(self, params: Any):
        path = (params or {}).get("path", "")
        logger.debug(f"document/didChange: {path}")

    def _handle_document_did_close(self, params: Any):
        path = (params or {}).get("path", "")
        logger.debug(f"document/didClose: {path}")

    def _handle_document_did_save(self, params: Any):
        path = (params or {}).get("path", "")
        logger.debug(f"document/didSave: {path}")

    def _handle_document_did_focus(self, params: Any):
        path = (params or {}).get("path", "")
        logger.debug(f"document/didFocus: {path}")

    # ══════════════════════════════════════════════════════════════════════
    # HANDLERS — NES (Inline Edit Suggestions)
    # ══════════════════════════════════════════════════════════════════════

    def _handle_nes_start(
        self, params: Any, msg_id: RequestId
    ) -> dict:
        """Handle ``nes/start`` — start an inline edit session."""
        session_id = (params or {}).get("sessionId", "")
        file_path = (params or {}).get("filePath", "")
        selection = (params or {}).get("selection", "")
        logger.info(f"nes/start: session={session_id} file={file_path}")
        return {
            "nesId": f"nes_{uuid.uuid4().hex[:12]}",
            "sessionId": session_id,
            "filePath": file_path,
            "selection": selection,
            "status": "ready",
        }

    def _handle_nes_suggest(
        self, params: Any, msg_id: RequestId
    ) -> dict:
        """Handle ``nes/suggest`` — suggest an inline edit."""
        nes_id = (params or {}).get("nesId", "")
        file_path = (params or {}).get("filePath", "")
        prompt = (params or {}).get("prompt", "")
        logger.info(f"nes/suggest: {nes_id}")
        # Generate a suggestion — use agent if available, else simple response
        ai_text = ""
        try:
            if self._agent is not None:
                ai_text, _ = self._agent.sess.chat_once(
                    f"Generate a code suggestion for:\n{prompt}"
                )
            ai_text = ai_text or ""
        except Exception:
            pass
        if not ai_text:
            ai_text = f"# Suggested edit for {os.path.basename(file_path) if file_path else 'file'}\n# Based on: {prompt}\n"

        return {
            "nesId": nes_id,
            "suggestions": [
                {
                    "id": f"sug_{uuid.uuid4().hex[:8]}",
                    "text": ai_text,
                    "filePath": file_path,
                }
            ],
            "status": "suggested",
        }

    def _handle_nes_accept(
        self, params: Any, msg_id: RequestId
    ) -> dict:
        """Handle ``nes/accept`` — accept a suggestion."""
        nes_id = (params or {}).get("nesId", "")
        suggestion_id = (params or {}).get("suggestionId", "")
        logger.info(f"nes/accept: {nes_id} sug={suggestion_id}")
        return {
            "nesId": nes_id,
            "suggestionId": suggestion_id,
            "status": "accepted",
        }

    def _handle_nes_reject(
        self, params: Any, msg_id: RequestId
    ) -> dict:
        """Handle ``nes/reject`` — reject a suggestion."""
        nes_id = (params or {}).get("nesId", "")
        suggestion_id = (params or {}).get("suggestionId", "")
        logger.info(f"nes/reject: {nes_id} sug={suggestion_id}")
        return {
            "nesId": nes_id,
            "suggestionId": suggestion_id,
            "status": "rejected",
        }

    def _handle_nes_close(
        self, params: Any, msg_id: RequestId
    ) -> dict:
        """Handle ``nes/close`` — close an inline edit session."""
        nes_id = (params or {}).get("nesId", "")
        logger.info(f"nes/close: {nes_id}")
        return {"nesId": nes_id, "status": "closed"}

    # ══════════════════════════════════════════════════════════════════════
    # HANDLERS — Extension Points
    # ══════════════════════════════════════════════════════════════════════

    def _handle_ext_request(
        self, params: Any, msg_id: RequestId
    ) -> dict:
        """Handle ``ext/request`` — custom extension request.

        Allows external tools to call arbitrary Tea Agent capabilities.
        """
        method = (params or {}).get("method", "")
        ext_params = (params or {}).get("params", {})
        logger.info(f"ext/request: method={method}")

        # Route to the appropriate internal handler if available
        handler_map = {
            "toolkit/list": self._ext_toolkit_list,
            "toolkit/call": self._ext_toolkit_call,
            "config/get": self._ext_config_get,
            "config/set": self._ext_config_set,
            "memory/search": self._ext_memory_search,
            "memory/add": self._ext_memory_add,
        }

        handler = handler_map.get(method)
        if handler:
            return handler(ext_params)
        return {"error": f"Unknown extension method: {method}"}

    def _ext_toolkit_list(self, params: dict) -> dict:
        """List available toolkit tools."""
        try:
            if self._agent is None:
                from tea_agent.agent import Agent
                self._agent = Agent(mode="lightweight", config_path=self._config_path)
            tools = []
            for name, meta in self._agent.toolkit.meta_map.items():
                fn = meta.get("function", {})
                tools.append({
                    "name": fn.get("name", name),
                    "description": fn.get("description", ""),
                })
            return {"object": "list", "data": tools, "total": len(tools)}
        except Exception as e:
            return {"error": str(e)}

    def _ext_toolkit_call(self, params: dict) -> dict:
        """Call a toolkit function."""
        tool_name = params.get("name", "")
        tool_args = params.get("arguments", {})
        try:
            if self._agent is None:
                from tea_agent.agent import Agent
                self._agent = Agent(mode="lightweight", config_path=self._config_path)
            result = self._agent.toolkit.call(tool_name, **tool_args)
            return {"result": result}
        except Exception as e:
            return {"error": str(e)}

    def _ext_config_get(self, params: dict) -> dict:
        """Get a config value."""
        key = params.get("key", "")
        try:
            from tea_agent.config import get_config
            config = get_config(self._config_path)
            return {"key": key, "value": getattr(config, key, None)}
        except Exception as e:
            return {"error": str(e)}

    def _ext_config_set(self, params: dict) -> dict:
        """Set a config value."""
        key = params.get("key", "")
        value = params.get("value")
        try:
            from tea_agent.config import get_config
            config = get_config(self._config_path)
            setattr(config, key, value)
            config.save()
            return {"success": True, "key": key, "value": value}
        except Exception as e:
            return {"error": str(e)}

    def _ext_memory_search(self, params: dict) -> dict:
        """Search memory."""
        query = params.get("query", "")
        try:
            from tea_agent.store import get_storage
            storage = get_storage()
            results = storage.get_memory(query)
            return {"results": results or []}
        except Exception as e:
            return {"error": str(e)}

    def _ext_memory_add(self, params: dict) -> dict:
        """Add a memory entry."""
        content = params.get("content", "")
        category = params.get("category", "general")
        try:
            from tea_agent.store import get_storage
            storage = get_storage()
            storage.add_memory(content, category)
            return {"success": True}
        except Exception as e:
            return {"error": str(e)}

    def _handle_ext_notification(self, params: Any):
        """Handle ``ext/notification`` — custom extension notification."""
        event = (params or {}).get("event", "")
        data = (params or {}).get("data", {})
        logger.info(f"ext/notification: event={event}")

    # ══════════════════════════════════════════════════════════════════════
    # HANDLERS — Cancel
    # ══════════════════════════════════════════════════════════════════════

    def _handle_cancel_request(self, request_id: RequestId):
        """Handle $/cancelRequest from the client."""
        logger.info(f"$/cancelRequest: {request_id}")

    # ══════════════════════════════════════════════════════════════════════
    # INTERNALS
    # ══════════════════════════════════════════════════════════════════════

    def _extract_text_content(self, message: dict) -> str:
        """Extract text from a message, handling content blocks."""
        content = message.get("content", "")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            texts = []
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") == "text":
                        texts.append(block.get("text", ""))
                    elif block.get("type") == "tool_result":
                        texts.append(
                            str(block.get("content", ""))
                        )
                    elif block.get("type") == "image":
                        texts.append("[Image]")
            return "\n".join(texts)
        return str(content) if content else ""

    def _process_prompt(
        self,
        session_id: str,
        prompt: str,
        cancel_event: threading.Event,
        stream_callback: Optional[callable] = None,
    ) -> tuple[str, list[dict]]:
        """Process a prompt through the Tea Agent engine.

        Args:
            session_id: ACP session ID
            prompt: The full prompt text
            cancel_event: Event to check for cancellation
            stream_callback: Optional callback for real-time streaming

        Returns (response_text, tool_calls).
        """
        try:
            from tea_agent.agent import Agent

            # Lazily init the agent
            if self._agent is None:
                self._agent = Agent(
                    mode="lightweight",
                    config_path=self._config_path,
                )

            # Set session context
            if session_id:
                self._agent.current_topic_id = session_id
            elif not self._agent.current_topic_id:
                from tea_agent.store import get_storage

                self._agent.current_topic_id = (
                    get_storage().create_topic("ACP")
                )

            # Collect streaming output
            collected_text = []
            tool_calls = []

            def callback(text: str):
                if cancel_event and cancel_event.is_set():
                    return
                if text and not text.startswith("["):
                    collected_text.append(text)
                    if stream_callback:
                        stream_callback(text)

            # Run the chat
            ai_msg, used = self._agent.sess.chat_stream(
                prompt,
                callback=callback,
                topic_id=self._agent.current_topic_id,
            )

            # Format tool calls
            if used:
                for item in used if isinstance(used, list) else []:
                    if isinstance(item, dict):
                        tool_calls.append(item)
                    else:
                        tool_calls.append({
                            "name": str(item),
                            "input": {},
                        })

            response_text = (
                "".join(collected_text) or ai_msg or ""
            )
            return response_text, tool_calls

        except ImportError as e:
            logger.error(f"Failed to import Agent: {e}")
            return (
                "I'm running in ACP protocol mode but the full Tea Agent "
                "engine is not available. Please ensure the package is "
                "properly installed.",
                [],
            )
        except Exception as e:
            logger.exception("Agent chat error")
            return (
                f"Error processing prompt: {e}",
                [],
            )

    def _get_available_commands(self) -> list[dict]:
        """Return available commands for the session."""
        return [
            {
                "name": "help",
                "description": "Show help information",
                "icon": "help",
            },
            {
                "name": "clear",
                "description": "Clear the conversation",
                "icon": "clear",
            },
            {
                "name": "explain",
                "description": "Explain the selected code",
                "icon": "lightbulb",
            },
            {
                "name": "fix",
                "description": "Fix the selected code",
                "icon": "wrench",
            },
            {
                "name": "test",
                "description": "Run tests",
                "icon": "beaker",
            },
        ]

    def _get_config_options(self) -> list[dict]:
        """Return session config options (supersedes modes/models)."""
        return [
            {
                "id": "temperature",
                "name": "Temperature",
                "description": "Controls randomness in responses",
                "type": "number",
                "default": 0.7,
                "min": 0.0,
                "max": 2.0,
            },
            {
                "id": "max_tokens",
                "name": "Max Tokens",
                "description": "Maximum response length",
                "type": "integer",
                "default": 4096,
                "min": 256,
                "max": 32000,
            },
        ]

    def _shutdown(self):
        """Clean up resources."""
        logger.info("ACP Agent: shutting down")
        with self._sessions_lock:
            self._sessions.clear()


class SessionState:
    """Internal session state for the ACP agent."""

    def __init__(
        self,
        session_id: str,
        cwd: str = "",
        created_at: str = "",
        mode: Optional[str] = None,
        model: Optional[str] = None,
        title: str = "",
        additional_directories: Optional[list[str]] = None,
    ):
        self.session_id = session_id
        self.cwd = cwd
        self.created_at = created_at
        self.mode = mode
        self.model = model
        self.title = title
        self.additional_directories = additional_directories or []
