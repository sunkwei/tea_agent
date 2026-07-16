"""ACP JSON-RPC 2.0 Transport Layer.

Provides the wire-level JSON-RPC 2.0 implementation over stdio,
including request/response/notification dispatching, cancellation,
and streaming support.
"""
import json
import logging
import sys
import threading
import time
import traceback
from collections.abc import Callable
from typing import Any

logger = logging.getLogger("acp.jsonrpc")

RequestId = str | int | float | None

# Heartbeat: send a ping every N seconds; exit if no write success after M failures
_HEARTBEAT_INTERVAL = 15.0
_HEARTBEAT_MAX_FAILURES = 3


class JsonRpcError(Exception):
    """JSON-RPC 2.0 error with code, message, and optional data."""

    PARSE_ERROR = -32700
    INVALID_REQUEST = -32600
    METHOD_NOT_FOUND = -32601
    INVALID_PARAMS = -32602
    INTERNAL_ERROR = -32603

    def __init__(self, code: int, message: str, data: Any = None):
        self.code = code
        self.message = message
        self.data = data
        super().__init__(f"[{code}] {message}")

    def to_dict(self) -> dict:
        d = {"code": self.code, "message": self.message}
        if self.data is not None:
            d["data"] = self.data
        return d


class JsonRpcMessage:
    """Helper to build JSON-RPC 2.0 messages."""

    @staticmethod
    def request(method: str, params: Any = None, id: RequestId = None) -> dict:
        msg = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        if id is not None:
            msg["id"] = id
        return msg

    @staticmethod
    def response(result: Any, id: RequestId) -> dict:
        return {"jsonrpc": "2.0", "result": result, "id": id}

    @staticmethod
    def error(error: JsonRpcError, id: RequestId) -> dict:
        return {"jsonrpc": "2.0", "error": error.to_dict(), "id": id}

    @staticmethod
    def notification(method: str, params: Any = None) -> dict:
        msg = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        return msg


class JsonRpcTransport:
    """JSON-RPC 2.0 transport over a read/write stream (stdin/stdout).

    This is the lowest-level layer. It reads JSON-RPC messages from the
    input stream, dispatches them to registered handlers, and writes
    responses to the output stream.

    Features:
    - Thread-safe write (lock-protected)
    - Graceful shutdown via stop()
    - In-flight request tracking for $/cancelRequest support
    - Response handler per request-id (thread-safe)
    - Heartbeat / client-disconnect detection
    - Newline-delimited JSON (NDJSON)
    """

    def __init__(
        self,
        reader: Any | None = None,
        writer: Any | None = None,
    ):
        self._reader = reader or sys.stdin
        self._writer = writer or sys.stdout
        self._write_lock = threading.Lock()
        self._running = False
        self._handlers: dict[str, Callable] = {}
        self._in_flight: dict[RequestId, threading.Event] = {}
        self._in_flight_lock = threading.Lock()
        self._cancel_handlers: list[Callable] = []
        # Response handlers keyed by request-id (thread-safe)
        self._response_handlers: dict[str, Callable] = {}
        self._response_handlers_lock = threading.Lock()
        self._heartbeat_thread: threading.Thread | None = None

    # ── handler registration ──────────────────────────────────────────────

    def on_request(self, method: str, handler: Callable):
        """Register a handler for a JSON-RPC request (expects a response).

        The handler may be sync or async (coroutine). It receives
        ``(params, id)`` and should return the result value (or raise
        JsonRpcError).
        """
        self._handlers[method] = handler

    def on_notification(self, method: str, handler: Callable):
        """Register a handler for a JSON-RPC notification (no response).

        The handler receives ``(params,)`` and its return value is ignored.
        """
        self._handlers[f"notify:{method}"] = handler

    def on_cancel(self, handler: Callable[[RequestId], None]):
        """Register a handler for $/cancelRequest notifications."""
        self._cancel_handlers.append(handler)

    # ── lifecycle ─────────────────────────────────────────────────────────

    def start(self):
        """Start reading messages from the input stream (blocking)."""
        self._running = True
        # Start heartbeat thread to detect client disconnect
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop, daemon=True
        )
        self._heartbeat_thread.start()
        logger.info("JsonRpcTransport: started reading from stdin")
        try:
            for line in self._reader:
                if not self._running:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError as e:
                    # Can't respond without an id — log and skip
                    logger.warning(f"JSON parse error: {e}")
                    continue

                self._dispatch(msg)
        except EOFError:
            logger.info("JsonRpcTransport: EOF on stdin")
        except KeyboardInterrupt:
            logger.info("JsonRpcTransport: interrupted")
        except Exception as e:
            logger.error(f"JsonRpcTransport: read error: {e}")
        finally:
            self._running = False

    def stop(self):
        """Signal the transport to stop reading."""
        self._running = False

    def _heartbeat_loop(self):
        """Background thread: periodically write a ping to detect client disconnect.

        If writing fails repeatedly, triggers self-stop so the read loop
        can exit cleanly.
        """
        failure_count = 0
        while self._running:
            time.sleep(_HEARTBEAT_INTERVAL)
            if not self._running:
                break
            try:
                ping = JsonRpcMessage.notification("$/ping", {"time": time.time()})
                with self._write_lock:
                    line = json.dumps(ping, ensure_ascii=False)
                    self._writer.write(line + "\n")
                    self._writer.flush()
                failure_count = 0
            except Exception:
                failure_count += 1
                logger.warning(
                    f"heartbeat write failed ({failure_count}/"
                    f"{_HEARTBEAT_MAX_FAILURES})"
                )
                if failure_count >= _HEARTBEAT_MAX_FAILURES:
                    logger.error(
                        "heartbeat: client appears disconnected, "
                        "stopping transport"
                    )
                    self._running = False
                    break

    def write(self, msg: dict):
        """Write a JSON-RPC message to the output stream (thread-safe)."""
        with self._write_lock:
            line = json.dumps(msg, ensure_ascii=False, default=str)
            self._writer.write(line + "\n")
            self._writer.flush()

    # ── client-side request helpers (agent → client) ──────────────────────

    def send_request(
        self, method: str, params: Any = None, timeout: float = 30
    ) -> Any:
        """Send a JSON-RPC request to the client and await the response.

        Used when the agent needs to call client-side methods like
        fs/read_text_file or session/request_permission.

        Thread-safe: each request gets its own handler registered under
        its unique request-id, so concurrent calls don't interfere.
        """
        import uuid

        req_id = str(uuid.uuid4())
        msg = JsonRpcMessage.request(method, params, id=req_id)
        done = threading.Event()
        result_container: list[Any] = [None]
        error_container: list[JsonRpcError | None] = [None]

        with self._in_flight_lock:
            self._in_flight[req_id] = done

        def _handle_response(response: dict):
            if "error" in response:
                err = response["error"]
                error_container[0] = JsonRpcError(
                    err.get("code", -1), err.get("message", "Unknown"),
                    err.get("data"),
                )
            else:
                result_container[0] = response.get("result")
            done.set()

        # Register handler under this specific request-id
        with self._response_handlers_lock:
            self._response_handlers[req_id] = _handle_response

        self.write(msg)

        if not done.wait(timeout=timeout):
            with self._in_flight_lock:
                self._in_flight.pop(req_id, None)
            with self._response_handlers_lock:
                self._response_handlers.pop(req_id, None)
            raise TimeoutError(
                f"Request {method} timed out after {timeout}s"
            )

        if error_container[0]:
            raise error_container[0]
        return result_container[0]

    def send_notification(self, method: str, params: Any = None):
        """Send a JSON-RPC notification to the client (no response expected)."""
        msg = JsonRpcMessage.notification(method, params)
        self.write(msg)

    # ── internal dispatch ─────────────────────────────────────────────────

    def _dispatch(self, msg: dict):
        """Route an incoming JSON-RPC message to the appropriate handler."""
        if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
            logger.warning(f"Invalid JSON-RPC message: {msg}")
            return

        method = msg.get("method", "")
        msg_id = msg.get("id")
        params = msg.get("params")

        # Handle $/cancelRequest
        if method == "$/cancelRequest":
            for h in self._cancel_handlers:
                try:
                    h(params.get("id") if params else None)
                except Exception:
                    logger.exception("cancel handler error")
            return

        # Handle responses to our outgoing requests
        if "id" in msg and ("result" in msg or "error" in msg):
            self._handle_incoming_response(msg)
            return

        is_notification = "id" not in msg

        if is_notification:
            handler = self._handlers.get(f"notify:{method}")
            if handler:
                try:
                    handler(params)
                except Exception:
                    logger.exception(
                        f"Notification handler error: {method}"
                    )
            else:
                logger.debug(f"Unhandled notification: {method}")
            return

        # It's a request — find handler, call it, send response
        handler = self._handlers.get(method)
        if not handler:
            self.write(
                JsonRpcMessage.error(
                    JsonRpcError(
                        JsonRpcError.METHOD_NOT_FOUND,
                        f"Method not found: {method}",
                    ),
                    msg_id,
                )
            )
            return

        try:
            result = handler(params, msg_id)
            # If a handler accidentally returns a coroutine, log a warning
            # (all ACP handlers are expected to be synchronous)
            import asyncio

            if asyncio.iscoroutine(result):
                logger.warning(
                    f"Handler '{method}' returned a coroutine but "
                    f"transport is sync-only; the coroutine will not "
                    f"be executed"
                )
                result = None

            self.write(JsonRpcMessage.response(result, msg_id))

        except JsonRpcError as e:
            logger.warning(f"Request error {method}: {e}")
            self.write(JsonRpcMessage.error(e, msg_id))
        except Exception as e:
            logger.exception(f"Unhandled handler error: {method}")
            self.write(
                JsonRpcMessage.error(
                    JsonRpcError(
                        JsonRpcError.INTERNAL_ERROR,
                        str(e),
                        {"traceback": traceback.format_exc()},
                    ),
                    msg_id,
                )
            )

    def _handle_incoming_response(self, msg: dict):
        """Handle a response to one of our outgoing requests.

        Looks up the registered handler by request-id, invokes it,
        and cleans up both the in-flight marker and the handler.
        Thread-safe by design: each request-id has its own handler.
        """
        msg_id = msg.get("id")
        if msg_id is None:
            return
        with self._in_flight_lock:
            done_event = self._in_flight.pop(msg_id, None)
        if done_event:
            # Fetch and remove the per-request handler
            with self._response_handlers_lock:
                handler = self._response_handlers.pop(msg_id, None)
            if handler:
                try:
                    handler(msg)
                except Exception:
                    logger.exception("response handler error")
            done_event.set()
