
"""
Tea Agent HTTP API Server -- REST API for external integration.

Provides OpenAI-compatible chat completions (+ streaming),
tool execution, session management, and configuration API.

Quick start:
    python -m tea_agent.server
"""

import asyncio
import json
import logging
import os
import threading
import time
import uuid
from typing import Optional, List, Dict, Any
from pathlib import Path

logger = logging.getLogger("api_server")

try:
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse, StreamingResponse, HTMLResponse
    from starlette.routing import Route, Mount
    from starlette.requests import Request
    from starlette.staticfiles import StaticFiles
except ImportError:
    raise ImportError("pip install starlette uvicorn")

from tea_agent.agent import Agent
from tea_agent.store import Storage, get_storage

__version__ = "0.1.0"

def get_server_version() -> str:
    return __version__


class APIServer:
    """HTTP API Server for Tea Agent -- REST API + OpenAI compatible."""

    def __init__(self, api_key: Optional[str] = None,
                 config_path: Optional[str] = None):
        self._api_key = (api_key or os.environ.get("TEA_API_KEY", "")).strip()
        self._config_path = config_path
        self._agent: Optional[Agent] = None
        self._start_time = time.time()
        self._lock = threading.Lock()
        self._storage: Optional[Storage] = None

    def _get_storage(self) -> Storage:
        """Get Storage directly (lightweight, no Agent dependency)."""
        if self._storage is None:
            self._storage = get_storage()
        return self._storage
        self._start_time = time.time()

    def get_agent(self) -> Agent:
        if self._agent is None:
            self._agent = Agent(mode="lightweight",
                                config_path=self._config_path)
            logger.info(f"Agent initialized")
        return self._agent

    def reset_agent(self):
        with self._lock:
            if self._agent:
                try: self._agent.sess.close()
                except Exception: pass
            self._agent = None
            logger.info("Agent reset")

    def health(self) -> dict:
        return {"status": "ok", "version": __version__,
                "uptime_seconds": round(time.time() - self._start_time, 1),
                "agent_initialized": self._agent is not None}

    def chat_completion(self, model: str, messages: List[dict],
                        stream: bool = False, temperature: float = 0.7,
                        max_tokens: Optional[int] = None,
                        topic_id: str = "") -> dict:
        """Non-streaming chat completion. Returns OpenAI-compatible dict."""
        agent = self.get_agent()
        user_msg = self._extract_user_message(messages)
        with self._lock:
            if topic_id:
                agent.current_topic_id = topic_id
                agent.load_topic_history(topic_id)
            elif not agent.current_topic_id:
                agent.current_topic_id = agent.db.create_topic("API 会话")
            collected = []
            def cb(text: str):
                if text and not text.startswith("["): collected.append(text)
            ai_msg, used_tools = agent.sess.chat_stream(
                user_msg, callback=cb,
                topic_id=topic_id or agent.current_topic_id)
            full = "".join(collected) or ai_msg
        return {"id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
                "object": "chat.completion",
                "created": int(time.time()), "model": model,
                "choices": [{"index": 0,
                    "message": {"role": "assistant", "content": full},
                    "finish_reason": "stop"}],
                "usage": {"total_tokens": 0, "prompt_tokens": 0,
                          "completion_tokens": 0},
                "tools_used": used_tools or []}


    async def chat_completion_stream(self, model, messages,
                                      temperature=0.7,
                                      max_tokens=None, topic_id=""):
        """Streaming chat completion. Returns async generator for SSE."""
        agent = self.get_agent()
        user_msg = self._extract_user_message(messages)
        queue = asyncio.Queue()
        event_loop = asyncio.get_running_loop()
        def _put(event):
            try: event_loop.call_soon_threadsafe(
                lambda: queue.put_nowait(event))
            except Exception: pass
        def stream_cb(text):
            if text.startswith("["): return
            _put({"type": "content", "text": text})
        thread = threading.Thread(
            target=self._run_stream,
            args=(agent, user_msg, topic_id, stream_cb, _put),
            daemon=True)
        thread.start()
        async for event in self._generate_sse(queue, model):
            yield event

    def _run_stream(self, agent, user_msg, topic_id, stream_cb, put):
        try:
            with self._lock:
                if topic_id:
                    agent.current_topic_id = topic_id
                    agent.load_topic_history(topic_id)
                elif not agent.current_topic_id:
                    agent.current_topic_id = agent.db.create_topic(
                        "API 流式会话")
                ai_msg, used_tools = agent.sess.chat_stream(
                    user_msg, callback=stream_cb,
                    topic_id=topic_id or agent.current_topic_id)
                put({"type": "done", "ai_msg": ai_msg,
                     "tools_used": used_tools or []})
        except Exception as e:
            put({"type": "error", "error": str(e)})

    async def _generate_sse(self, queue, model):
        cid = f"chatcmpl-{uuid.uuid4().hex[:12]}"
        now = int(time.time())
        yield f"data: {json.dumps(dict(id=cid, object='chat.completion.chunk', created=now, model=model, choices=[dict(index=0, delta=dict(role='assistant'), finish_reason=None)]), ensure_ascii)}\n\n"
        while True:
            event = await queue.get()
            if event["type"] == "content":
                yield f"data: {json.dumps(dict(id=cid, object='chat.completion.chunk', created=now, model=model, choices=[dict(index=0, delta=dict(content=event['text']), finish_reason=None)]), ensure_ascii)}\n\n"
            elif event["type"] == "done":
                yield f"data: {json.dumps(dict(id=cid, object='chat.completion.chunk', created=now, model=model, choices=[dict(index=0, delta={{}}, finish_reason='stop')]), ensure_ascii)}\n\n"
                yield "data: [DONE]\n\n"
                break
            elif event["type"] == "error":
                yield f"data: {json.dumps(dict(error=event['error']), ensure_ascii)}\n\n"
                yield "data: [DONE]\n\n"
                break


    @staticmethod
    def _extract_user_message(messages):
        for msg in reversed(messages):
            if msg.get("role") == "user":
                content = msg.get("content", "")
                if isinstance(content, list):
                    texts = [p.get("text","") for p in content
                             if p.get("type") == "text"]
                    return "\n".join(texts)
                return content
        return ""

    def list_tools(self):
        agent = self.get_agent()
        tools = []
        for name, meta in agent.toolkit.meta_map.items():
            fn = meta.get("function", {})
            tools.append({"name": fn.get("name", name),
                          "description": fn.get("description", ""),
                          "parameters": fn.get("parameters", {})})
        return tools

    def run_tool(self, tool_name, arguments):
        agent = self.get_agent()
        func = agent.toolkit.func_map.get(tool_name)
        if not func:
            func = agent.toolkit.func_map.get(f"toolkit_{tool_name}")
        if not func:
            return {"ok": False, "error": f"Tool '{tool_name}' not found"}
        try:
            result = func(**arguments)
            return {"ok": True, "tool": tool_name, "result": str(result)}
        except Exception as e:
            return {"ok": False, "error": str(e), "tool": tool_name}

    def list_sessions(self, limit=20):
        # Use storage directly, avoid heavy Agent init if possible
        topics = self._get_storage().list_topics()
        result = []
        for t in topics[:limit]:
            tid = t["topic_id"]
            tokens = self._get_storage().get_topic_tokens(tid)
            result.append({"id": tid, "title": t.get("title","") or tid[:8],
                           "created": str(t.get("create_stamp",""))[:19],
                           "updated": str(t.get("last_update_stamp",""))[:19],
                           "total_tokens": (tokens or {}).get("total_tokens",0)})
        return result

    def create_session(self, title="API 会话"):
        tid = self._get_storage().create_topic(title)
        # Also try to set it on agent if agent is already initialized
        if self._agent is not None:
            self._agent.current_topic_id = tid
        return {"id": tid, "title": title}

    def get_session(self, topic_id):
        s = self._get_storage()
        topic = s.get_topic(topic_id)
        if not topic: return None
        tokens = s.get_topic_tokens(topic_id)
        convs = s.get_conversations(topic_id, limit=0, include_rounds=True)
        return {"id": topic["topic_id"], "title": topic.get("title",""),
                "created": str(topic.get("create_stamp","")),
                "updated": str(topic.get("last_update_stamp","")),
                "total_tokens": (tokens or {}).get("total_tokens",0),
                "conversations": [{"id": c["id"], "user": c["user_msg"],
                    "assistant": c["ai_msg"], "stamp": c["stamp"]}
                    for c in convs]}

    def delete_session(self, topic_id):
        try:
            self._get_storage().delete_topic(topic_id)
            return True
        except Exception:
            return False


    def get_session_messages(self, topic_id: str, limit: int = 50) -> list:
        convs = self._get_storage().get_conversations(topic_id, limit=limit, include_rounds=True)
        result = []
        for c in convs:
            result.append({"id": c["id"], "role": "user", "content": c["user_msg"],
                           "stamp": str(c.get("stamp",""))[:26]})
            result.append({"id": c["id"], "role": "assistant", "content": c["ai_msg"],
                           "stamp": str(c.get("stamp",""))[:26]})
        return result

    @staticmethod
    def _sanitize(obj):
        "Remove non-JSON-serializable fields (e.g. bytes)."
        if isinstance(obj, dict):
            return {k: APIServer._sanitize(v) for k, v in obj.items()
                    if not isinstance(v, (bytes, bytearray))}
        if isinstance(obj, list):
            return [APIServer._sanitize(item) for item in obj]
        return obj

    def list_memories(self, limit=50):
        mems = self._get_storage().get_active_memories(limit=limit)
        return self._sanitize(mems)

    def create_memory(self, content: str, category: str = "general", priority: int = 2):
        mem_id = self._get_storage().add_memory(content, category=category, priority=priority, tags="", importance=3)
        return {"id": mem_id, "content": content, "category": category}

    def delete_memory(self, mem_id):
        # Soft delete via storage
        try:
            from tea_agent.memory import MemoryManager
            mm = MemoryManager()
            mm.delete(mem_id)
            return True
        except Exception:
            return False

    def list_tasks(self):
        return self._get_storage().list_tasks()

    def create_task(self, name: str, command: str, schedule: str):
        task_id = self._get_storage().add_task(name, command, schedule)
        return {"id": task_id, "name": name, "command": command, "schedule": schedule}

    def delete_task(self, task_id: str):
        return self._get_storage().delete_task(task_id)

    def search(self, query: str, limit: int = 20) -> dict:
        s = self._get_storage()
        convs = self._sanitize(s.search_conversations(query, limit=limit))
        mems = self._sanitize(s.search_memories(query, limit=limit))
        return {"conversations": convs, "memories": mems}

    def get_config(self):
        agent = self.get_agent()
        cfg = agent.config
        key = cfg.main_model.api_key
        masked = (key[:6] + "..." + key[-4:]) if len(key) > 12 else "***"
        return {"model": cfg.main_model.model_name,
                "api_url": cfg.main_model.api_url,
                "api_key_masked": masked,
                "keep_turns": cfg.keep_turns,
                "max_iterations": cfg.max_iterations,
                "enable_thinking": cfg.enable_thinking,
                "tools_count": len(agent.toolkit.func_map),
                "server_version": __version__}

    def switch_config(self, config_path):
        if not os.path.exists(config_path):
            return {"ok": False, "error": f"Config not found: {config_path}"}
        self._config_path = config_path
        self.reset_agent()
        return {"ok": True, "config_path": config_path}


_server_instance: Optional[APIServer] = None

def get_server() -> APIServer:
    global _server_instance
    if _server_instance is None:
        _server_instance = APIServer()
    return _server_instance


# ── Route Handlers ──

async def handle_health(request):
    return JSONResponse(get_server().health())

async def handle_chat_completions(request):
    body = await request.json()
    model = body.get("model", "default")
    messages = body.get("messages", [])
    stream = body.get("stream", False)
    temperature = body.get("temperature", 0.7)
    max_tokens = body.get("max_tokens")
    topic_id = body.get("topic_id", "")
    if not messages:
        return JSONResponse({"error": "messages required"}, status_code=400)
    server = get_server()
    if stream:
        gen = server.chat_completion_stream(
            model, messages, temperature, max_tokens, topic_id)
        return StreamingResponse(gen, media_type="text/event-stream")
    result = server.chat_completion(
        model, messages, False, temperature, max_tokens, topic_id)
    return JSONResponse(result)

async def handle_list_models(request):
    try:
        cfg = get_server().get_config()
        models = [{"id": cfg["model"], "object": "model",
                   "created": int(time.time()), "owned_by": "tea-agent"}]
        return JSONResponse({"object": "list", "data": models})
    except Exception as e:
        return JSONResponse({"object": "list", "data": [{"id": "unknown",
            "object": "model", "created": int(time.time()),
            "owned_by": "tea-agent"}],
            "warning": f"Agent not configured: {e}"})

async def handle_list_tools(request):
    try:
        tools = get_server().list_tools()
        return JSONResponse({"object": "list", "data": tools, "total": len(tools)})
    except Exception as e:
        return JSONResponse({"object": "list", "data": [], "total": 0,
                             "warning": f"Agent not configured: {e}"})

async def handle_run_tool(request):
    tool_name = request.path_params.get("name", "")
    body = await request.json() if request.headers.get("content-length") else {}
    arguments = (body or {}).get("arguments", {})
    result = get_server().run_tool(tool_name, arguments)
    return JSONResponse(result)

async def handle_list_sessions(request):
    limit = int(request.query_params.get("limit", 20))
    try:
        return JSONResponse({"object": "list",
                             "data": get_server().list_sessions(limit)})
    except Exception as e:
        return JSONResponse({"object": "list", "data": [],
                             "warning": str(e)})

async def handle_create_session(request):
    body = await request.json() if request.headers.get("content-length") else {}
    title = (body.get("title") or "API 会话").strip()
    try:
        return JSONResponse(get_server().create_session(title), status_code=201)
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=503)

async def handle_get_session(request):
    tid = request.path_params.get("topic_id", "")
    session = get_server().get_session(tid)
    if not session:
        return JSONResponse({"error": "Session not found"}, status_code=404)
    return JSONResponse(session)

async def handle_delete_session(request):
    tid = request.path_params.get("topic_id", "")
    ok = get_server().delete_session(tid)
    return JSONResponse({"ok": ok})

async def handle_get_config(request):
    try:
        return JSONResponse(get_server().get_config())
    except Exception as e:
        return JSONResponse({"error": "Agent not configured", "detail": str(e)}, status_code=503)

async def handle_switch_config(request):
    body = await request.json()
    config_path = (body.get("config_path") or "").strip()
    if not config_path:
        return JSONResponse({"error": "config_path required"}, status_code=400)
    result = get_server().switch_config(config_path)
    if not result.get("ok"):
        return JSONResponse(result, status_code=400)
    return JSONResponse(result)

async def handle_docs(request):
    html = """<!DOCTYPE html>
<html><head><title>Tea Agent API</title>
<meta charset="utf-8"/>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css">
</head><body>
<div id="swagger-ui"></div>
<script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js">
</script>
<script>
SwaggerUIBundle({ url: '/openapi.json', dom_id: '#swagger-ui' })
</script>
</body></html>"""
    return HTMLResponse(html)

async def handle_openapi(request):
    return JSONResponse(OPENAPI_SPEC)


OPENAPI_SPEC = {
    "openapi": "3.0.3",
    "info": {"title": "Tea Agent API", "version": __version__,
             "description": "REST API for Tea Agent"},
    "servers": [{"url": "http://127.0.0.1:8081", "description": "Local"}],
    "paths": {
        "/health": {"get": {"summary": "Health check", "tags": ["System"],
            "responses": {"200": {"description": "OK"}}}},
        "/v1/chat/completions": {"post": {"summary": "Chat completion",
            "tags": ["Chat"],
            "requestBody": {"required": True, "content": {
                "application/json": {"schema": {"type": "object",
                    "properties": {
                        "model": {"type": "string", "example": "gpt-4o"},
                        "messages": {"type": "array", "items": {"type": "object"}},
                        "stream": {"type": "boolean", "default": False},
                        "temperature": {"type": "number", "default": 0.7},
                        "topic_id": {"type": "string"}},
                    "required": ["messages"]}}}},
            "responses": {"200": {"description": "OK"}}}},
        "/v1/models": {"get": {"summary": "List models", "tags": ["Models"],
            "responses": {"200": {"description": "OK"}}}},
        "/v1/tools": {"get": {"summary": "List tools", "tags": ["Tools"],
            "responses": {"200": {"description": "OK"}}}},
        "/v1/tools/{name}/run": {"post": {
            "summary": "Execute a tool", "tags": ["Tools"],
            "parameters": [{"name": "name", "in": "path",
                "required": True, "schema": {"type": "string"}}],
            "responses": {"200": {"description": "OK"}}}},
        "/v1/sessions": {"get": {"summary": "List sessions", "tags": ["Sessions"],
            "responses": {"200": {"description": "OK"}}},
            "post": {"summary": "Create session", "tags": ["Sessions"],
            "responses": {"201": {"description": "Created"}}}},
        "/v1/sessions/{topic_id}": {"get": {
            "summary": "Get session", "tags": ["Sessions"],
            "parameters": [{"name": "topic_id", "in": "path",
                "required": True, "schema": {"type": "string"}}],
            "responses": {"200": {"description": "OK"}}},
            "delete": {"summary": "Delete session", "tags": ["Sessions"],
            "parameters": [{"name": "topic_id", "in": "path",
                "required": True, "schema": {"type": "string"}}],
            "responses": {"200": {"description": "OK"}}}},
        "/v1/config": {"get": {"summary": "Get config", "tags": ["Config"],
            "responses": {"200": {"description": "OK"}}}},
        "/v1/config/switch": {"post": {
            "summary": "Switch config", "tags": ["Config"],
            "responses": {"200": {"description": "OK"}}}},
    }
}


async def handle_get_session_messages(request):
    server = get_server()
    topic_id = request.path_params.get("topic_id", "")
    limit = int(request.query_params.get("limit", 50))
    msgs = server.get_session_messages(topic_id, limit=limit)
    return JSONResponse({"data": msgs, "total": len(msgs)})

async def _safe_handle(handler, request):
    """Wrapper to catch agent initialization errors."""
    try:
        return await handler(request)
    except ValueError as e:
        if "配置不完整" in str(e):
            return JSONResponse(
                {"error": "Agent not configured", "detail": str(e),
                 "hint": "Run 'tea-agent --setup' or configure ~/.tea_agent/config.yaml"},
                status_code=503)
        return JSONResponse({"error": str(e)}, status_code=500)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

async def handle_list_memory(request):
    server = get_server()
    memories = server.list_memories()
    return JSONResponse({"data": memories, "total": len(memories)})

async def handle_create_memory(request):
    server = get_server()
    body = await request.json()
    mem = server.create_memory(body.get("content",""),
        category=body.get("category","general"),
        priority=body.get("priority",2))
    return JSONResponse(mem, status_code=201)

async def handle_delete_memory(request):
    server = get_server()
    mem_id = request.path_params.get("mem_id", "")
    ok = server.delete_memory(mem_id)
    return JSONResponse({"deleted": ok})

async def handle_list_tasks(request):
    server = get_server()
    tasks = server.list_tasks()
    return JSONResponse({"data": tasks, "total": len(tasks)})

async def handle_create_task(request):
    server = get_server()
    body = await request.json()
    task = server.create_task(body.get("name",""),
        body.get("command",""), body.get("schedule",""))
    return JSONResponse(task, status_code=201)

async def handle_delete_task(request):
    server = get_server()
    task_id = request.path_params.get("task_id", "")
    ok = server.delete_task(task_id)
    return JSONResponse({"deleted": ok})

async def handle_search(request):
    server = get_server()
    query = request.query_params.get("q", "")
    limit = int(request.query_params.get("limit", 20))
    if not query:
        return JSONResponse({"error": "query required"}, status_code=400)
    results = server.search(query, limit=limit)
    return JSONResponse(results)

async def handle_export_pdf(request):
    from tea_agent.toolkit.toolkit_export_last_pdf import export_topic_pdf
    body = await request.json()
    topic_id = body.get("topic_id", "")
    if not topic_id:
        return JSONResponse({"error": "topic_id required"}, status_code=400)
    output = body.get("output")
    try:
        result = await asyncio.to_thread(export_topic_pdf, topic_id, output or None)
        return JSONResponse({"success": True, "path": result or output})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

async def handle_upload(request):
    form = await request.form()
    file = form.get("file")
    if not file:
        return JSONResponse({"error": "No file"}, status_code=400)
    upload_dir = Path("uploads")
    upload_dir.mkdir(exist_ok=True)
    content = await file.read()
    dest = upload_dir / file.filename
    with open(dest, "wb") as f:
        f.write(content)
    return JSONResponse({"path": str(dest), "url": f"/uploads/{file.filename}"})

def create_app(api_key: Optional[str] = None,
               config_path: Optional[str] = None):
    """Create the Starlette application for the API server."""
    global _server_instance
    _server_instance = APIServer(api_key=api_key, config_path=config_path)

    routes = [
        Route("/health", endpoint=handle_health),
        Route("/v1/chat/completions", endpoint=handle_chat_completions,
              methods=["POST"]),
        Route("/v1/models", endpoint=handle_list_models),
        Route("/v1/tools", endpoint=handle_list_tools),
        Route("/v1/tools/{name:str}/run", endpoint=handle_run_tool,
              methods=["POST"]),
        Route("/v1/sessions", endpoint=handle_list_sessions),
        Route("/v1/sessions", endpoint=handle_create_session,
              methods=["POST"]),
        Route("/v1/sessions/{topic_id:str}",
              endpoint=handle_get_session),
        Route("/v1/sessions/{topic_id:str}",
              endpoint=handle_delete_session, methods=["DELETE"]),
        Route("/v1/config", endpoint=handle_get_config),
        Route("/v1/config/switch", endpoint=handle_switch_config,
              methods=["POST"]),
        Route("/docs", endpoint=handle_docs),
        Route("/openapi.json", endpoint=handle_openapi),
        Route("/v1/sessions/{topic_id:str}/messages",
              endpoint=handle_get_session_messages),
        Route("/v1/memory", endpoint=handle_list_memory),
        Route("/v1/memory", endpoint=handle_create_memory,
              methods=["POST"]),
        Route("/v1/memory/{mem_id:str}", endpoint=handle_delete_memory,
              methods=["DELETE"]),
        Route("/v1/tasks", endpoint=handle_list_tasks),
        Route("/v1/tasks", endpoint=handle_create_task,
              methods=["POST"]),
        Route("/v1/tasks/{task_id:str}", endpoint=handle_delete_task,
              methods=["DELETE"]),
        Route("/v1/search", endpoint=handle_search),
        Route("/v1/export/pdf", endpoint=handle_export_pdf,
              methods=["POST"]),
        Route("/v1/upload", endpoint=handle_upload,
              methods=["POST"]),
    ]

    logger.info(f"API Server initialized | v{__version__}")
    app = Starlette(debug=False, routes=routes)
    frontend_dir = Path(__file__).parent.parent / "gui2" / "frontend"
    if frontend_dir.exists():
        from starlette.staticfiles import StaticFiles
        app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")
        logger.info(f"Frontend: {frontend_dir}")
    return app


def run_server(host: str = "127.0.0.1", port: int = 8081,
               api_key: Optional[str] = None,
               config_path: Optional[str] = None):
    """Run the API server."""
    try:
        import uvicorn
    except ImportError:
        raise ImportError("pip install uvicorn")

    app = create_app(api_key=api_key, config_path=config_path)
    if api_key:
        logger.info(f"API Key auth enabled")
    logger.info(f"API Server starting: http://{host}:{port}")
    logger.info(f"API Docs: http://{host}:{port}/docs")
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    run_server()


# ── CLI Entry ──

def main():
    """CLI entry: tea-agent-api"""
    import argparse
    parser = argparse.ArgumentParser(description="Tea Agent API Server")
    parser.add_argument("--host", type=str, default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8081)
    parser.add_argument("--api-key", type=str, default="")
    parser.add_argument("--config", type=str, default=None)
    args = parser.parse_args()
    run_server(host=args.host, port=args.port,
               api_key=args.api_key or None,
               config_path=args.config)

if __name__ == "__main__":
    main()
