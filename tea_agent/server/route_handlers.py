"""Route handlers for Tea Agent HTTP API Server.

Extracted from server.py to reduce file size. All handle_* functions
and OPENAPI_SPEC live here.

Imports:
    from .server import get_server, _max_iter_pending, _active_sessions, logger
"""

import asyncio
import contextlib
import json
import os
import threading
import time
import uuid
from pathlib import Path

from starlette.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse

from tea_agent.toolkit.toolkit_export_last_pdf import export_topic_pdf

from .server import (
    __version__,
    _active_sessions,
    _max_iter_pending,
    _question_pending,
    get_server,
    logger,
)

# ================================================================
#  System / Health
# ================================================================

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


async def handle_export_pdf(request):
    """GET /v1/export/pdf/{topic_id} — export topic as PDF and download

    Query params:
        mode: 'latest' (default) = last conversation only, 'full_topic' = all conversations.
    """
    topic_id = request.path_params.get("topic_id", "")
    if not topic_id:
        return JSONResponse({"error": "topic_id required"}, status_code=400)
    mode = request.query_params.get("mode", "latest")
    if mode not in ("latest", "full_topic"):
        mode = "latest"
    try:
        server = get_server()
        db_path = server._get_storage().db_path
        result = await asyncio.to_thread(export_topic_pdf, topic_id, None, db_path, mode=mode)
        # Get topic title for filename
        import sqlite3
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT title FROM topics WHERE topic_id = ?", (topic_id,))
        row = cur.fetchone()
        conn.close()
        title = row["title"] if row else "Untitled"
        safe_title = "".join(c if c.isalnum() or c in ' -_()[]' else '_' for c in title)
        safe_title = safe_title.strip()[:80] or "export"
        filename = safe_title + ".pdf"
        # RFC 5987: use filename* for non-ASCII, fallback ASCII for latin-1 clients
        import urllib.parse
        ascii_name = "".join(c if ord(c) < 128 else '_' for c in filename) or "export.pdf"
        disposition = f'attachment; filename="{ascii_name}"; filename*=UTF-8''{urllib.parse.quote(filename)}'
        return FileResponse(result, media_type="application/pdf",
            headers={"Content-Disposition": disposition})
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


# ================================================================
#  Screenshots
# ================================================================

async def handle_screenshot_region(request):
    """POST /api/screenshot/region — capture a screen region and return base64."""
    body = await request.json()
    for key in ("x", "y", "w", "h"):
        if key not in body:
            return JSONResponse({"ok": False, "error": f"缺少参数: {key}"}, status_code=400)
    try:
        x, y, w, h = int(body["x"]), int(body["y"]), int(body["w"]), int(body["h"])
    except (ValueError, TypeError):
        return JSONResponse({"ok": False, "error": "参数必须为整数"}, status_code=400)
    if w <= 0 or h <= 0:
        return JSONResponse({"ok": False, "error": "宽高必须大于0"}, status_code=400)
    result = get_server().screenshot_region(x, y, w, h)
    if result.get("ok"):
        return JSONResponse(result)
    return JSONResponse(result, status_code=500)


async def handle_screenshot_full(request):
    """GET /api/screenshot/full — capture full screen and return base64."""
    result = get_server().screenshot_full()
    if result.get("ok"):
        return JSONResponse(result)
    return JSONResponse(result, status_code=500)


async def handle_screenshot_interactive(request):
    """POST /api/screenshot/interactive — 系统级截图选区"""
    import base64
    import subprocess
    import sys as _sys

    try:
        _self_path = os.path.dirname(os.path.abspath(__file__))
        _probe = os.path.dirname(_self_path)  # tea_agent/
        for _ in range(6):
            if os.path.isdir(os.path.join(_probe, "toolkit")):
                break
            _probe = os.path.dirname(_probe)
        agent_root = _probe
        script_code = (
            "import sys, json, tempfile, os\n"
            f"sys.path.insert(0, {agent_root!r})\n"
            "from tea_agent.toolkit.toolkit_screenshot_picker import toolkit_screenshot_picker\n"
            "result = toolkit_screenshot_picker()\n"
            "print(json.dumps(result))\n"
            "sys.stdout.flush()\n"
        )

        proc = await asyncio.create_subprocess_exec(
            _sys.executable, "-c", script_code,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)

        if proc.returncode != 0:
            err_msg = stderr.decode()[:300] if stderr else "未知错误"
            return JSONResponse({"ok": False, "error": f"选区工具异常: {err_msg}"},
                                status_code=500)

        result = json.loads(stdout.decode().strip())
        if not result.get("success"):
            return JSONResponse({"ok": False, "error": result.get("error", "用户取消")},
                                status_code=400)

        img_path = result["path"]
        if not os.path.isfile(img_path):
            return JSONResponse({"ok": False, "error": "结果文件不存在"}, status_code=500)

        with open(img_path, "rb") as f:
            b64_str = base64.b64encode(f.read()).decode("utf-8")

        with contextlib.suppress(OSError):
            os.remove(img_path)

        return JSONResponse({
            "ok": True,
            "image_base64": b64_str,
            "width": result["width"],
            "height": result["height"],
            "x": result["x"],
            "y": result["y"],
            "w": result["w"],
            "h": result["h"],
        })

    except asyncio.TimeoutError:
        return JSONResponse({"ok": False, "error": "选区超时（120秒）"}, status_code=504)
    except Exception as e:
        logger.exception("handle_screenshot_interactive error")
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


# ================================================================
#  Web UI API — SSE Chat
# ================================================================

async def handle_web_chat(request):
    """POST /api/chat - SSE streaming chat for Web UI."""
    body = await request.json()
    message = body.get("message", "").strip()
    topic_id = body.get("topic_id", "")
    config_path = body.get("config_path") or None
    images_b64 = body.get("images", [])

    if not message and not images_b64:
        return JSONResponse({"error": "message required"}, status_code=400)

    image_paths = []
    if images_b64:
        import base64 as b64mod
        upload_dir = Path("uploads")
        upload_dir.mkdir(exist_ok=True)
        for idx, img_b64 in enumerate(images_b64):
            try:
                if img_b64.startswith("data:"):
                    header, data = img_b64.split(",", 1)
                    ext_map = {
                        "image/png": ".png",
                        "image/jpeg": ".jpg",
                        "image/gif": ".gif",
                        "image/webp": ".webp",
                        "image/bmp": ".bmp",
                    }
                    mime = header.split(";")[0].replace("data:", "")
                    ext = ext_map.get(mime, ".png")
                else:
                    data = img_b64
                    ext = ".png"
                img_bytes = b64mod.b64decode(data)
                fname = f"upload_{uuid.uuid4().hex[:8]}_{idx}{ext}"
                fpath = upload_dir / fname
                fpath.write_bytes(img_bytes)
                image_paths.append(str(fpath))
            except Exception as e:
                logger.warning(f"Image base64 decode failed: {e}")

    msg_payload = {"text": message, "images": image_paths} if image_paths else message

    server = get_server()
    session, storage = server.create_session(config_path)
    queue: asyncio.Queue = asyncio.Queue()

    async def event_stream():
        loop = asyncio.get_running_loop()

        nonlocal topic_id
        if not topic_id:
            topic_id = storage.create_topic("Web Session (进行中)")

        _active_sessions[topic_id] = session

        try:
            thread = threading.Thread(
                target=server.chat_stream_sse,
                args=(session, storage, msg_payload, queue, topic_id, loop),
                daemon=True,
            )
            thread.start()

            while True:
                event = await queue.get()
                yield "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"
                if event.get("type") in ("done", "error"):
                    break
        finally:
            _active_sessions.pop(topic_id, None)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


async def handle_chat_continue(request):
    """POST /api/chat/continue — 用户确认 max_iter 后继续或终止"""
    body = await request.json()
    confirm_id = body.get("confirm_id", "")
    decision = body.get("continue", True)

    if not confirm_id:
        return JSONResponse({"ok": False, "error": "confirm_id 不能为空"}, status_code=400)

    pending = _max_iter_pending.pop(confirm_id, None)
    if not pending:
        return JSONResponse({"ok": False, "error": "确认请求已过期或不存在"}, status_code=404)

    session = pending["session"]
    try:
        session._continue_after_max = decision
        session._max_iter_wait.set()
        logger.info(f"User confirmed max_iter: continue={decision}")
        return JSONResponse({"ok": True, "continue": decision})
    except Exception as e:
        logger.exception(f"Handle max_iter confirm failed: {e}")
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


async def handle_chat_question(request):
    """POST /api/chat/question — 用户回答 toolkit_question 的提问"""
    body = await request.json()
    question_id = body.get("question_id", "")
    answer = body.get("answer", "")

    if not question_id:
        return JSONResponse({"ok": False, "error": "question_id 不能为空"}, status_code=400)

    pending = _question_pending.get(question_id)
    if not pending:
        return JSONResponse({"ok": False, "error": "问题已过期或不存在"}, status_code=404)

    pending["answer"] = answer
    pending["event"].set()
    logger.info(f"User answered question {question_id}: {answer!r}")
    return JSONResponse({"ok": True, "answer": answer})


async def handle_chat_abort(request):
    """POST /api/chat/abort — 中断当前正在进行的对话"""
    body = await request.json()
    topic_id = body.get("topic_id", "")
    if not topic_id:
        return JSONResponse({"ok": False, "error": "topic_id 不能为空"}, status_code=400)

    session = _active_sessions.get(topic_id)
    if not session:
        logger.warning(f"Abort failed: no active session for topic_id={topic_id}")
        return JSONResponse({"ok": False, "error": "未找到活跃会话（可能已结束）"}, status_code=404)

    try:
        session.interrupt()
        logger.info(f"User aborted session topic_id={topic_id}")
        return JSONResponse({"ok": True, "message": "已发送中断信号"})
    except Exception as e:
        logger.exception(f"Abort session failed topic_id={topic_id}")
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


# ================================================================
#  Web UI API — Topics / Sessions / Config
# ================================================================

async def handle_web_new_topic(request):
    """POST /api/new_topic"""
    body = await request.json()
    title = body.get("title", "Web Session")
    title = title.strip() or "Web Session"
    server = get_server()
    tid = server._get_storage().create_topic(title)
    return JSONResponse({"topic_id": tid, "title": title})


async def handle_web_sessions(request):
    """GET /api/sessions"""
    limit = int(request.query_params.get("limit", 20))
    sessions = get_server().list_sessions(limit)
    return JSONResponse({"sessions": sessions})


async def handle_web_topic_todos(request):
    """GET /api/topic/{topic_id}/todos — 获取当前话题的 TODO 清单"""
    topic_id = request.path_params.get("topic_id", "")
    if not topic_id:
        return JSONResponse({"error": "topic_id required"}, status_code=400)
    try:
        from tea_agent.toolkit.toolkit_todo import _todos, _restore_from_db, _restored
        # 确保从 DB 恢复
        if not _restored:
            _restore_from_db()
        # 从 DB 直接读取
        server = get_server()
        storage = server._get_storage()
        if storage and hasattr(storage, 'conn'):
            c = storage.conn.cursor()
            c.execute(
                "SELECT idx, desc, done FROM todo_items WHERE topic_id=? ORDER BY idx ASC",
                (topic_id,),
            )
            rows = c.fetchall()
            c.close()
            items = [{"idx": r[0], "desc": r[1], "done": bool(r[2])} for r in rows]
        else:
            items = [{"idx": t["idx"], "desc": t["desc"], "done": t["done"]} for t in _todos]
        done = sum(1 for it in items if it["done"])
        return JSONResponse({"items": items, "total": len(items), "done": done})
    except Exception as e:
        logger.warning(f"handle_web_topic_todos failed: {e}")
        return JSONResponse({"items": [], "total": 0, "done": 0})


async def handle_web_topic_todo_update(request):
    """PUT /api/topic/{topic_id}/todos/{idx} — 更新 TODO 状态"""
    topic_id = request.path_params.get("topic_id", "")
    idx_str = request.path_params.get("idx", "")
    if not topic_id or idx_str == "":
        return JSONResponse({"error": "topic_id and idx required"}, status_code=400)
    try:
        idx = int(idx_str)
    except ValueError:
        return JSONResponse({"error": "idx must be integer"}, status_code=400)
    try:
        body = await request.json()
        done = bool(body.get("done", True))
        server = get_server()
        storage = server._get_storage()
        if storage and hasattr(storage, 'conn'):
            c = storage.conn.cursor()
            c.execute(
                "UPDATE todo_items SET done=? WHERE topic_id=? AND idx=?",
                (1 if done else 0, topic_id, idx),
            )
            storage.conn.commit()
            c.close()
        # Also sync toolkit_todo memory cache
        try:
            from tea_agent.toolkit.toolkit_todo import _todos, _sync_item
            if 0 <= idx < len(_todos):
                _todos[idx]["done"] = done
            _sync_item(idx, done)
        except Exception:
            pass
        return JSONResponse({"ok": True, "idx": idx, "done": done})
    except Exception as e:
        logger.warning(f"handle_web_topic_todo_update failed: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


async def handle_web_topic_plans(request):
    """GET /api/topic/{topic_id}/plans — 获取当前话题的执行计划"""
    topic_id = request.path_params.get("topic_id", "")
    plans_dir = ".tea_agent_run/plans"
    import json, os
    plans = []
    try:
        if os.path.isdir(plans_dir):
            for fname in sorted(os.listdir(plans_dir), reverse=True):
                if not fname.endswith(".json"):
                    continue
                fpath = os.path.join(plans_dir, fname)
                with open(fpath, encoding="utf-8") as f:
                    p = json.load(f)
                if p.get("topic_id") == topic_id or p.get("topic_id") == "" or not topic_id:
                    plans.append(p)
    except Exception as e:
        logger.warning(f"handle_web_topic_plans failed: {e}")
    return JSONResponse({"data": plans, "total": len(plans)})


async def handle_web_topic_info(request):
    """GET/PUT/DELETE /api/topic/{topic_id}"""
    topic_id = request.path_params.get("topic_id", "")
    if not topic_id:
        return JSONResponse({"error": "topic_id required"}, status_code=400)

    if request.method == "PUT":
        body = await request.json()
        new_title = (body.get("title") or "").strip()
        if not new_title:
            return JSONResponse({"error": "title required"}, status_code=400)
        ok = get_server().rename_topic(topic_id, new_title)
        if not ok:
            return JSONResponse({"error": "Rename failed"}, status_code=500)
        return JSONResponse({"ok": True, "title": new_title})

    if request.method == "DELETE":
        ok = get_server().delete_session(topic_id)
        if not ok:
            return JSONResponse({"error": "Delete failed"}, status_code=500)
        return JSONResponse({"ok": True})

    info = get_server().get_topic_info(topic_id)
    if not info:
        return JSONResponse({"error": "Topic not found"}, status_code=404)
    return JSONResponse({"topic": info})


async def handle_web_topic_conversations(request):
    """GET /api/topic/{topic_id}/conversations"""
    topic_id = request.path_params.get("topic_id", "")
    if not topic_id:
        return JSONResponse({"error": "topic_id required"}, status_code=400)
    limit = int(request.query_params.get("limit", 0))
    try:
        convs = get_server().get_topic_conversations(topic_id, limit=limit)
        return JSONResponse({"conversations": convs, "count": len(convs)})
    except Exception as e:
        logger.exception("get_topic_conversations failed")
        return JSONResponse({"error": str(e)}, status_code=500)


async def handle_web_tools(request):
    """GET /api/tools"""
    tools = get_server().list_tools()
    return JSONResponse({"tools": tools, "count": len(tools)})


async def handle_web_config(request):
    """GET /api/config"""
    try:
        return JSONResponse(get_server().get_config_info())
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=503)


async def handle_web_update_config(request):
    """PUT /api/config — update runtime config fields."""
    body = await request.json()
    if not body:
        return JSONResponse({"ok": False, "errors": ["empty body"]}, status_code=400)
    result = get_server().update_config(body)
    status = 200 if result["ok"] else 400
    return JSONResponse(result, status_code=status)


async def handle_web_list_configs(request):
    """GET /api/configs"""
    server = get_server()
    result = server.list_config_files(check_valid=True)
    configs = result["configs"]
    any_valid = result["any_valid"]
    active_config_path = ""
    active_config_filename = ""
    try:
        agent = server.get_agent()
        if agent and agent._config_path:
            active_config_path = agent._config_path
            active_config_filename = Path(active_config_path).name
    except Exception:
        pass
    return JSONResponse({
        "configs": configs,
        "count": len(configs),
        "any_valid": any_valid,
        "active_config_path": active_config_path,
        "active_config_filename": active_config_filename,
    })


async def handle_web_create_config(request):
    """POST /api/config/create"""
    body = await request.json()
    filename = (body.get("filename") or "").strip()
    main_model_name = (body.get("main_model_name") or "").strip()
    main_api_url = (body.get("main_api_url") or "").strip()
    main_api_key = (body.get("main_api_key") or "").strip()
    cheap_model_name = (body.get("cheap_model_name") or "").strip()
    cheap_api_url = (body.get("cheap_api_url") or "").strip()
    cheap_api_key = (body.get("cheap_api_key") or "").strip()

    errors = []
    if not filename:
        errors.append("filename required")
    if not main_model_name:
        errors.append("main_model_name required")
    if not main_api_url:
        errors.append("main_api_url required")
    if not main_api_key:
        errors.append("main_api_key required")
    if errors:
        return JSONResponse({"ok": False, "errors": errors}, status_code=400)

    server = get_server()
    try:
        fpath = server.create_config_file(
            filename=filename,
            main_model_name=main_model_name,
            main_api_url=main_api_url,
            main_api_key=main_api_key,
            cheap_model_name=cheap_model_name,
            cheap_api_url=cheap_api_url,
            cheap_api_key=cheap_api_key,
        )
        server.switch_config(fpath)
        return JSONResponse({"ok": True, "config_path": fpath, "filename": filename})
    except Exception as e:
        logger.exception("create_config_file failed")
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


async def handle_web_model_info(request):
    """GET /api/model"""
    try:
        return JSONResponse(get_server().get_config_info())
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=503)


async def handle_web_model_switch(request):
    """POST /api/model - hot-switch model at runtime."""
    body = await request.json()
    server = get_server()
    agent = server._agent
    current_key = agent._cfg.main_model.api_key if agent else ""

    api_key = (body.get("api_key") or current_key or "").strip()
    api_url = (body.get("api_url") or "").strip()
    model_name = (body.get("model_name") or "").strip()
    cheap_api_key = (body.get("cheap_api_key") or "").strip()
    cheap_api_url = (body.get("cheap_api_url") or "").strip()
    cheap_model_name = (body.get("cheap_model_name") or "").strip()

    def _float_or_none(key):
        v = body.get(key)
        return float(v) if v is not None and str(v).strip() else None
    def _int_or_none(key):
        v = body.get(key)
        return int(v) if v is not None and str(v).strip() else None

    temperature = _float_or_none("temperature")
    max_tokens = _int_or_none("max_tokens")
    top_p = _float_or_none("top_p")
    max_context_tokens = _int_or_none("max_context_tokens")
    options = body.get("options")

    cheap_temperature = _float_or_none("cheap_temperature")
    cheap_max_tokens = _int_or_none("cheap_max_tokens")
    cheap_top_p = _float_or_none("cheap_top_p")
    cheap_max_context_tokens = _int_or_none("cheap_max_context_tokens")
    cheap_options = body.get("cheap_options")

    errors = []
    if not api_key:
        errors.append("api_key required")
    if not api_url:
        errors.append("api_url required")
    if not model_name:
        errors.append("model_name required")
    if errors:
        return JSONResponse({"ok": False, "errors": errors}, status_code=400)

    try:
        server.switch_model(
            api_key, api_url, model_name,
            cheap_api_key, cheap_api_url, cheap_model_name,
            temperature=temperature, max_tokens=max_tokens,
            top_p=top_p, max_context_tokens=max_context_tokens,
            options=options,
            cheap_temperature=cheap_temperature, cheap_max_tokens=cheap_max_tokens,
            cheap_top_p=cheap_top_p, cheap_max_context_tokens=cheap_max_context_tokens,
            cheap_options=cheap_options,
        )
        masked_key = (api_key[:6] + "..." + api_key[-4:]) if len(api_key) > 12 else "***"
        result = {"ok": True, "model": model_name, "api_url": api_url,
                  "api_key_masked": masked_key}
        if cheap_model_name:
            cheap_masked = (cheap_api_key[:6] + "..." + cheap_api_key[-4:]) if len(cheap_api_key) > 12 else "***"
            result["cheap_model"] = {
                "model": cheap_model_name, "api_url": cheap_api_url,
                "api_key_masked": cheap_masked}
        return JSONResponse(result)
    except Exception as e:
        logger.exception("model_switch failed")
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


async def handle_web_model_config(request):
    """POST /api/model/config - switch config from file."""
    body = await request.json()
    config_path = (body.get("config_path") or "").strip()
    if not config_path:
        return JSONResponse({"error": "config_path required"}, status_code=400)
    server = get_server()
    result = server.switch_config(config_path)
    if not result.get("ok"):
        return JSONResponse(result, status_code=400)
    return JSONResponse(result)


async def handle_web_upload_config(request):
    """POST /api/config/upload - upload a .yaml config file."""
    form = await request.form()
    file = form.get("file")
    if not file:
        return JSONResponse({"ok": False, "error": "请选择文件"}, status_code=400)

    filename = file.filename or ""
    if not filename.endswith((".yaml", ".yml")):
        return JSONResponse({"ok": False, "error": "仅支持 .yaml / .yml 文件"}, status_code=400)

    content = await file.read()
    if not content or not content.strip():
        return JSONResponse({"ok": False, "error": "文件内容为空"}, status_code=400)

    server = get_server()
    configs_dir = server._get_configs_dir()
    configs_dir.mkdir(parents=True, exist_ok=True)
    dest_path = configs_dir / filename

    if dest_path.exists():
        from datetime import datetime
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        name_stem = dest_path.stem
        dest_path = configs_dir / f"{name_stem}_{stamp}.yaml"

    try:
        if isinstance(content, bytes):
            dest_path.write_bytes(content)
        else:
            dest_path.write_text(content, encoding="utf-8")
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"保存文件失败: {e}"}, status_code=500)

    from tea_agent.config import load_config
    try:
        cfg = load_config(str(dest_path))
    except Exception as e:
        with contextlib.suppress(Exception):
            dest_path.unlink()
        return JSONResponse({"ok": False, "error": f"配置解析失败: {e}"}, status_code=400)

    main_m = cfg.main_model
    if not main_m.is_configured:
        with contextlib.suppress(Exception):
            dest_path.unlink()
        return JSONResponse({
            "ok": False,
            "error": "配置无效：必须包含 main_model 的 api_url、api_key 和 model_name",
        }, status_code=400)

    try:
        switch_result = server.switch_config(str(dest_path))
        if not switch_result.get("ok"):
            logger.warning(f"Auto-switch config after upload failed: {switch_result.get('error', '')}")
    except Exception as e:
                    logger.warning(f"Auto-switch config after upload exception: {e}")

    config_link = configs_dir / "config.yaml"
    try:
        if config_link.exists() or config_link.is_symlink():
            if config_link.is_symlink():
                config_link.unlink()
            else:
                from datetime import datetime
                stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                backup_path = configs_dir / f"config_{stamp}.yaml"
                import shutil
                shutil.move(str(config_link), str(backup_path))
                logger.info(f"Existing config.yaml backed up to {backup_path}")
        try:
            if os.name == "nt":
                try:
                    os.symlink(str(dest_path), str(config_link))
                    logger.info(f"Symlink created: {config_link} → {dest_path}")
                except (OSError, PermissionError):
                    import shutil
                    shutil.copy2(str(dest_path), str(config_link))
                    logger.info(f"Symlink failed, copied file to {config_link}")
            else:
                os.symlink(str(dest_path), str(config_link))
                logger.info(f"Symlink created: {config_link} → {dest_path}")
        except Exception as e:
            logger.warning(f"Create config.yaml symlink failed: {e}")
    except Exception as e:
        logger.warning(f"Config.yaml symlink handling error: {e}")

    return JSONResponse({
        "ok": True,
        "filename": dest_path.name,
        "path": str(dest_path),
        "is_valid": True,
    })


async def handle_web_root(request):
    """GET / - serve Web UI index.html."""
    static_dir = Path(__file__).parent / "static"
    index_path = static_dir / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path), media_type="text/html")
    return HTMLResponse("<h1>Tea Agent Server</h1><p>Web UI not found. Visit <a href='/docs'>/docs</a> for API.</p>")


# ================================================================
#  Error wrapper
# ================================================================

async def _safe_handle(handler, request):
    """Wrapper to catch agent initialization errors."""
    try:
        return await handler(request)
    except ValueError as e:
        if "incomplete config" in str(e).lower():
            return JSONResponse(
                {"error": "Agent not configured", "detail": str(e),
                 "hint": "Run 'tea-agent --setup' or configure ~/.tea_agent/config.yaml"},
                status_code=503)
        return JSONResponse({"error": str(e)}, status_code=500)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ================================================================
#  OpenAPI Specification
# ================================================================

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
    }
}
