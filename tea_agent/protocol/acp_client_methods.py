"""ACP Client-side method helpers for the Agent.

When the Agent needs to read/write files, ask for permissions, or send
streaming updates, it calls these client-side methods via JSON-RPC.

All methods use the transport's ``send_request`` / ``send_notification``
to communicate with the client (VS Code).
"""
import logging
from typing import Any, Optional

from tea_agent.protocol.acp_jsonrpc import JsonRpcTransport

logger = logging.getLogger("acp.client_methods")


class AcpClientMethods:
    """Client-side ACP method callers.

    These methods are called BY the agent TO the client (VS Code).
    Each method sends a JSON-RPC request/notification and returns the result.
    """

    def __init__(self, transport: JsonRpcTransport):
        self._transport = transport
        self._timeout = 30  # Default timeout for client calls

    # ── File System ───────────────────────────────────────────────────────

    def read_text_file(self, path: str) -> str:
        """Ask the client to read a text file.

        This reads the file via VS Code's filesystem API, which includes
        unsaved editor buffer content.
        """
        logger.info(f"fs/read_text_file: {path}")
        result = self._transport.send_request(
            "fs/read_text_file",
            {"path": path},
            timeout=self._timeout,
        )
        return result.get("content", "") if result else ""

    def write_text_file(self, path: str, content: str) -> bool:
        """Ask the client to write a text file.

        VS Code will write the file and open it in the editor so the
        user can see the change.
        """
        logger.info(f"fs/write_text_file: {path} ({len(content)} chars)")
        result = self._transport.send_request(
            "fs/write_text_file",
            {"path": path, "content": content},
            timeout=self._timeout,
        )
        return result is not None

    # ── Permissions ──────────────────────────────────────────────────────

    def request_permission(
        self,
        title: str,
        options: list[dict],
        tool_call: Optional[dict] = None,
    ) -> dict:
        """Ask the client to show a permission request to the user.

        Args:
            title: Title of the permission request
            options: List of option dicts with 'kind', 'description', 'optionId'
            tool_call: Optional tool call info for context

        Returns:
            Response with outcome ('selected'/'cancelled') and optionId if selected
        """
        logger.info(f"session/request_permission: {title}")
        params = {
            "title": title,
            "options": options,
        }
        if tool_call:
            params["toolCall"] = tool_call

        try:
            result = self._transport.send_request(
                "session/request_permission",
                params,
                timeout=self._timeout,
            )
            return result or {"outcome": {"outcome": "cancelled"}}
        except Exception as e:
            logger.error(f"Permission request failed: {e}")
            return {"outcome": {"outcome": "cancelled", "error": str(e)}}

    # ── Streaming Updates ────────────────────────────────────────────────

    def send_update(
        self,
        session_id: str,
        update_type: str,
        content_blocks: Optional[list[dict]] = None,
        status: Optional[str] = None,
        metadata: Optional[dict] = None,
    ):
        """Send a session/update notification to the client.

        Args:
            session_id: The active session ID
            update_type: Type of update (e.g., 'content_block', 'status', 'error')
            content_blocks: Content blocks for streaming
            status: Status message
            metadata: Additional metadata
        """
        params: dict[str, Any] = {
            "sessionId": session_id,
            "update": {
                "sessionUpdate": update_type,
            },
        }
        if content_blocks:
            params["contentBlocks"] = content_blocks
        if status:
            params["status"] = status
        if metadata:
            params["_meta"] = metadata

        self._transport.send_notification("session/update", params)

    def update_config(
        self,
        session_id: str,
        config_options: list[dict],
    ):
        """Send session/update_config to update available config options."""
        self._transport.send_notification("session/update_config", {
            "sessionId": session_id,
            "configOptions": config_options,
        })

    def update_commands(
        self,
        session_id: str,
        commands: list[dict],
    ):
        """Send session/update_commands to update available commands."""
        self._transport.send_notification("session/update_commands", {
            "sessionId": session_id,
            "availableCommands": commands,
        })

    def info_update(
        self,
        session_id: str,
        title: Optional[str] = None,
        metadata: Optional[dict] = None,
    ):
        """Send session/info_update to update session info."""
        params: dict[str, Any] = {"sessionId": session_id}
        if title:
            params["title"] = title
        if metadata:
            params["metadata"] = metadata
        self._transport.send_notification("session/info_update", params)

    # ── Terminal ─────────────────────────────────────────────────────────

    def create_terminal(
        self,
        command: str,
        args: Optional[list[str]] = None,
        cwd: Optional[str] = None,
        env: Optional[dict] = None,
    ) -> dict:
        """Ask the client to create a terminal."""
        params: dict[str, Any] = {"command": command}
        if args:
            params["args"] = args
        if cwd:
            params["cwd"] = cwd
        if env:
            params["env"] = env

        result = self._transport.send_request(
            "terminal/create",
            params,
            timeout=self._timeout,
        )
        return result or {}

    def terminal_output(
        self, terminal_id: str
    ) -> str:
        """Read terminal output."""
        result = self._transport.send_request(
            "terminal/output",
            {"terminalId": terminal_id},
            timeout=self._timeout,
        )
        return result.get("output", "") if result else ""

    def wait_for_terminal_exit(
        self, terminal_id: str, timeout: float = 60
    ) -> dict:
        """Wait for terminal to exit and return exit status."""
        result = self._transport.send_request(
            "terminal/wait_for_exit",
            {"terminalId": terminal_id},
            timeout=timeout,
        )
        return result or {}

    def kill_terminal(self, terminal_id: str) -> bool:
        """Kill a terminal."""
        result = self._transport.send_request(
            "terminal/kill",
            {"terminalId": terminal_id},
            timeout=self._timeout,
        )
        return result is not None

    def release_terminal(self, terminal_id: str) -> bool:
        """Release a terminal."""
        result = self._transport.send_request(
            "terminal/release",
            {"terminalId": terminal_id},
            timeout=self._timeout,
        )
        return result is not None
