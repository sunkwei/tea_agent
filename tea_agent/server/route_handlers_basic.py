"""基础 API：健康检查/文档/模型与工具列表/会话/配置/记忆/任务/搜索，以及 OPENAPI_SPEC。

由 route_handlers.py 拆分而来（逐字搬运，函数体未改写）。
"""

import time

from starlette.responses import HTMLResponse, JSONResponse, StreamingResponse

from ._compat import (
    __version__,
    get_server,
)


async def handle_health(request):
    return JSONResponse(get_server().health())


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


# ================================================================
#  OpenAI-compatible Chat Completions
# ================================================================

async def handle_chat_completions(request):
    body = await request.json()
    model = body.get("model", "default")
    messages = body.get("messages", [])
    stream = body.get("stream", False)
    temperature = body.get("temperature", 0.7)
    max_tokens = body.get("max_tokens")
    topic_id = body.get("topic_id", "")
    config_path = body.get("config_path") or None
    if not messages:
        return JSONResponse({"error": "messages required"}, status_code=400)
    server = get_server()
    if stream:
        gen = server.chat_completion_stream(
            model, messages, temperature, max_tokens, topic_id, config_path)
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


# ================================================================
#  Tools
# ================================================================

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


# ================================================================
#  Sessions / Topics
# ================================================================

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
        return JSONResponse(get_server().create_topic_session(title), status_code=201)
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


async def handle_get_session_messages(request):
    server = get_server()
    topic_id = request.path_params.get("topic_id", "")
    limit = int(request.query_params.get("limit", 50))
    msgs = server.get_session_messages(topic_id, limit=limit)
    return JSONResponse({"data": msgs, "total": len(msgs)})


# ================================================================
#  Config
# ================================================================

async def handle_get_config(request):
    try:
        return JSONResponse(get_server().get_config_info())
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


# ================================================================
#  Memory
# ================================================================

async def handle_list_memory(request):
    server = get_server()
    memories = server.list_memories()
    return JSONResponse({"data": memories, "total": len(memories)})


async def handle_create_memory(request):
    """创建记忆。

    响应**必须**含 ``ok`` 字段：前端 app.js 以 ``if (d.ok)`` 判定成败（与
    deleteMemory 一致）。原先只返回裸对象 ``{"id","content","category"}``，
    ``d.ok`` 恒为 undefined → 记忆**已成功入库却报「添加失败」**（静默假失败；
    又因未走成功分支，列表也不刷新，用户无从察觉其实已写入）。

    失败路径一律非 2xx：``StorageModule.create_memory`` 在存储未就绪时返回
    ``{"error": ...}``，旧代码仍以 **201** 送出 —— 任何按状态码判定的调用方
    都会反过来「假成功」，与本 bug 恰成镜像。
    """
    server = get_server()
    body = await request.json()
    content = (body.get("content") or "").strip()
    if not content:
        return JSONResponse({"ok": False, "error": "content required"}, status_code=400)
    mem = server.create_memory(content,
        category=body.get("category", "general"),
        priority=body.get("priority", 2))
    if mem.get("error"):
        return JSONResponse({"ok": False, "error": mem["error"]}, status_code=503)
    return JSONResponse({"ok": True, **mem}, status_code=201)


async def handle_delete_memory(request):
    server = get_server()
    mem_id = request.path_params.get("mem_id", "")
    ok = server.delete_memory(mem_id)
    return JSONResponse({"ok": ok, "deleted": ok})


# ================================================================
#  Tasks
# ================================================================

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


# ================================================================
#  Search / Export / Upload
# ================================================================

async def handle_search(request):
    server = get_server()
    query = request.query_params.get("q", "")
    limit = int(request.query_params.get("limit", 20))
    if not query:
        return JSONResponse({"error": "query required"}, status_code=400)
    results = server.search(query, limit=limit)
    return JSONResponse(results)
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
                        "topic_id": {"type": "string"},
                        "config_path": {"type": "string",
                            "description": "Config file path, different instances can use different configs"}},
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
        "/api/providers": {"get": {
            "summary": "List providers (builtin + custom)", "tags": ["Model Management"],
            "responses": {"200": {"description": "Provider list with source/capabilities/active"}}},
            "post": {
                "summary": "Add custom provider", "tags": ["Model Management"],
                "requestBody": {"required": True, "content": {"application/json": {"schema": {
                    "type": "object",
                    "required": ["name", "api_url", "default_model"],
                    "properties": {
                        "name": {"type": "string", "description": "2-32 chars, [A-Za-z0-9_-]"},
                        "api_url": {"type": "string"},
                        "default_model": {"type": "string"},
                        "models": {"type": "array", "items": {
                            "oneOf": [
                                {"type": "string"},
                                {"type": "object",
                                 "properties": {
                                     "id": {"type": "string"},
                                     "context_window": {"type": "integer"},
                                     "max_output_tokens": {"type": "integer"},
                                     "supports_vision": {"type": "boolean"},
                                     "supports_thinking": {"type": "boolean"},
                                 },
                                 "required": ["id"]},
                            ],
                            "description": "string 简写或含 id/窗口/输出的富条目"},
                        },
                        "supports_thinking": {"type": "boolean"},
                        "supports_vision": {"type": "boolean"},
                        "description": {"type": "string"},
                    }}}}},
                "responses": {"200": {"description": "Created"}, "409": {"description": "Duplicate name"}}}},
        "/api/providers/{name}": {"put": {
            "summary": "Update custom provider", "tags": ["Model Management"],
            "parameters": [{"name": "name", "in": "path", "required": True,
                            "schema": {"type": "string"}}],
            "responses": {"200": {"description": "Updated"}, "403": {"description": "Builtin cannot be modified"},
                          "404": {"description": "Not found"}}},
            "delete": {
                "summary": "Delete custom provider", "tags": ["Model Management"],
                "parameters": [{"name": "name", "in": "path", "required": True,
                                "schema": {"type": "string"}}],
                "responses": {"200": {"description": "Deleted"}, "403": {"description": "Builtin cannot be deleted"}}}},
        "/api/providers/{name}/models": {"get": {
            "summary": "Query provider models (cache-first, live + static fallback)",
            "tags": ["Model Management"],
            "parameters": [
                {"name": "name", "in": "path", "required": True, "schema": {"type": "string"}},
                {"name": "refresh", "in": "query", "required": False,
                 "schema": {"type": "boolean", "default": False},
                 "description": "true=force live query"},
                {"name": "api_key", "in": "query", "required": False,
                 "schema": {"type": "string"}, "description": "for live query (custom provider)"}],
            "responses": {"200": {"description": "Models (source: live|cache|static)"}}}},
        "/api/providers/{name}/apply": {"post": {
            "summary": "Apply provider to model config (one-click)", "tags": ["Model Management"],
            "parameters": [{"name": "name", "in": "path", "required": True,
                            "schema": {"type": "string"}}],
            "requestBody": {"required": True, "content": {"application/json": {"schema": {
                "type": "object",
                "properties": {
                    "api_key": {"type": "string"},
                    "model": {"type": "string", "description": "defaults to provider default_model"},
                    "role": {"type": "string", "enum": ["main", "cheap", "vision"], "default": "main"},
                    "temperature": {"type": "number"},
                    "max_tokens": {"type": "integer"},
                    "top_p": {"type": "number"},
                }}}}},
            "responses": {"200": {"description": "Applied to config.yaml (main hot-swaps)"},
                          "404": {"description": "Provider not found"}}}},
        "/api/model/test": {"post": {
            "summary": "Test connection (endpoint + key + model)", "tags": ["Model Management"],
            "requestBody": {"required": True, "content": {"application/json": {"schema": {
                "type": "object",
                "required": ["api_url", "api_key"],
                "properties": {
                    "api_url": {"type": "string"},
                    "api_key": {"type": "string"},
                    "model": {"type": "string"},
                }}}}},
            "responses": {"200": {"description": "Connection test result (latency_ms)"},
                          "400": {"description": "Missing params"}}}},
        "/api/model-config": {"get": {
            "summary": "Unified model config panel (model_config.json single source)",
            "tags": ["Model Config Panel"],
            "responses": {"200": {"description":
                "providers→models→per-model config + roles + active + pending_switch"}}}},
        "/api/model-config/model": {
            "put": {"summary": "Update per-model config (max_context/max_output/thinking/vision/tools/note)",
                    "tags": ["Model Config Panel"],
                    "requestBody": {"required": True, "content": {"application/json": {"schema": {
                        "type": "object", "required": ["provider", "model"],
                        "properties": {"provider": {"type": "string"},
                                       "model": {"type": "string"},
                                       "config": {"type": "object"}}}}}},
                    "responses": {"200": {"description": "Updated entry"}}},
            "post": {"summary": "Add model to provider (config optional, heuristic defaults)",
                     "tags": ["Model Config Panel"],
                     "responses": {"200": {"description": "Created entry"}}},
            "delete": {"summary": "Delete model config entry",
                       "tags": ["Model Config Panel"],
                       "parameters": [
                           {"name": "provider", "in": "query", "required": True,
                            "schema": {"type": "string"}},
                           {"name": "model", "in": "query", "required": True,
                            "schema": {"type": "string"}}],
                       "responses": {"200": {"description": "Deleted"},
                                     "404": {"description": "Not found"}}}},
        "/api/model-config/sync": {"post": {
            "summary": "Sync live /v1/models into model_config.json (new only, keep user edits)",
            "tags": ["Model Config Panel"],
            "responses": {"200": {"description": "added/kept/total"}}}},
        "/api/model-config/switch": {"post": {
            "summary": "Switch model & continue current session (deferred when a turn is in progress)",
            "tags": ["Model Config Panel"],
            "requestBody": {"required": True, "content": {"application/json": {"schema": {
                "type": "object", "required": ["provider", "model"],
                "properties": {
                    "provider": {"type": "string"}, "model": {"type": "string"},
                    "role": {"type": "string", "enum": ["main", "cheap", "vision"], "default": "main"},
                    "api_key": {"type": "string"},
                    "continue_session": {"type": "boolean", "default": True},
                    "temperature": {"type": "number"}, "max_tokens": {"type": "integer"},
                    "top_p": {"type": "number"}}}}}},
            "responses": {"200": {"description":
                "apply result + switch mode: applied|pending_next_turn|next_message"}}}},
    }
}
