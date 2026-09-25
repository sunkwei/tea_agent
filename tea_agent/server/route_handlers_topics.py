"""Web 主题与回合数据：新建/分叉/列表、待办、计划、状态、流缓冲、对话、轨迹、工具、打断。

由 route_handlers.py 拆分而来（逐字搬运，函数体未改写）。
"""

import json
import os

from starlette.responses import JSONResponse

from ._compat import (
    _active_sessions,
    _active_sessions_lock,
    _background_sessions,
    _read_buffer_since,
    get_server,
    logger,
)


async def handle_web_new_topic(request):
    """POST /api/new_topic"""
    body = await request.json()
    title = body.get("title", "Web Session")
    title = title.strip() or "Web Session"
    server = get_server()
    tid = server._get_storage().create_topic(title)
    return JSONResponse({"topic_id": tid, "title": title})


async def handle_web_fork_topic(request):
    """POST /api/topic/{topic_id}/fork — 从指定历史消息处分叉出新主题。

    body:
        boundary_conv_id: 分叉点会话 ID（**包含**该条）；空则复制全部历史
        title: 分支描述（可选；默认取边界消息的用户文本摘要）

    新主题标题为 ``#分叉: <描述>`` —— 该前缀受 ``store._topics.is_title_protected``
    保护，**不会被自动摘要覆盖**（用户显式命名的分支不应被改写）。

    实现复用 ``session_fork.fork_session``（与 toolkit_fork_session 同一事实源）。
    """
    topic_id = request.path_params.get("topic_id", "")
    if not topic_id:
        return JSONResponse({"ok": False, "error": "topic_id required"}, status_code=400)
    try:
        body = await request.json()
    except Exception:
        body = {}
    boundary = str(body.get("boundary_conv_id") or "").strip()
    label = str(body.get("title") or "").strip()

    storage = get_server()._get_storage()

    # 未给描述 → 用边界消息的用户文本作摘要，避免一堆同名的「#分叉: 分支」
    if not label and boundary:
        try:
            convs = storage.get_conversations(topic_id, limit=-1, include_rounds=False)
            for c in convs:
                if str(c.get("id")) == boundary:
                    label = (c.get("user_msg") or "").replace("\n", " ").strip()[:30]
                    break
        except Exception:
            logger.debug("fork: 取边界消息摘要失败", exc_info=True)
    if not label:
        label = "分支"

    from tea_agent.session_fork import fork_session

    result = fork_session(
        storage,
        source_topic_id=topic_id,
        title=f"#分叉: {label}",
        boundary_conv_id=boundary,
    )
    if not result.get("ok"):
        return JSONResponse(result, status_code=400)
    logger.info("web fork: %s -> %s (boundary=%s)", topic_id,
                result.get("target_topic_id"), boundary or "-")
    return JSONResponse(result)


async def handle_web_sessions(request):
    """GET /api/sessions — 返回话题列表，包含每个话题的活跃状态。

    返回扩展字段：
      - is_active: 是否正在前台对话中
      - is_background: 是否在后台处理中（客户端断连后）
    """
    limit = int(request.query_params.get("limit", 20))
    sessions = get_server().list_sessions(limit)

    with _active_sessions_lock:
        active_set = set(_active_sessions.keys())
    bg_set = set(_background_sessions.keys())

    for s in sessions:
        tid = s["id"]
        s["is_active"] = tid in active_set
        s["is_background"] = tid in bg_set

    return JSONResponse({"sessions": sessions})


async def handle_web_topic_todos(request):
    """GET /api/topic/{topic_id}/todos — 获取当前话题的 TODO 清单"""
    topic_id = request.path_params.get("topic_id", "")
    if not topic_id:
        return JSONResponse({"error": "topic_id required"}, status_code=400)
    try:
        from tea_agent.toolkit.toolkit_todo import _restore_from_db, _restored, _todos
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
            from tea_agent.toolkit.toolkit_todo import _sync_item, _todos
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
    """GET /api/topic/{topic_id}/plans — 获取当前话题的执行计划
    Query params:
      status=active (默认): running/paused/created
      status=all: 全部计划
      status=done: 仅已完成
      status=failed: 仅失败
    """
    topic_id = request.path_params.get("topic_id", "")
    status_filter = (request.query_params.get("status", "active") or "active").strip().lower()
    plans_dir = ".tea_agent_run/plans"
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
                    plan_status = (p.get("status") or "").lower()
                    if status_filter == "all" or status_filter == "done" and plan_status == "done" or status_filter == "failed" and plan_status == "failed" or status_filter == "active" and plan_status not in ("done", "failed"):
                        plans.append(p)
    except Exception as e:
        logger.warning(f"handle_web_topic_plans failed: {e}")
    return JSONResponse({"data": plans, "total": len(plans)})


async def handle_web_topic_status(request):
    """GET /api/topic/{topic_id}/status — 查看 topic 后台处理状态

    Returns:
        background: bool — 是否正在后台处理中
        active: bool — 是否正在前台活跃
    """
    topic_id = request.path_params.get("topic_id", "")
    if not topic_id:
        return JSONResponse({"error": "topic_id required"}, status_code=400)
    return JSONResponse({
        "topic_id": topic_id,
        "background": topic_id in _background_sessions,
        "active": topic_id in _active_sessions,
    })


async def handle_web_topic_stream_buffer(request):
    """GET /api/topic/{topic_id}/stream-buffer — 获取后台缓冲区中的流式事件

    Query params:
        since: int — **尚未看过的最小事件序号**（含），首次传 -1。
            前端把上次响应的 next_index 原样传回，二者语义严格对齐。
    Returns:
        events: list[dict] — 序号 >= since 的事件列表
        done: bool — 流是否已结束
        next_index: int — 下次应传的 since（= 本次最后一条 + 1）
    """
    topic_id = request.path_params.get("topic_id", "")
    if not topic_id:
        return JSONResponse({"error": "topic_id required"}, status_code=400)
    try:
        since = int(request.query_params.get("since", "-1"))
    except (ValueError, TypeError):
        since = -1
    result = _read_buffer_since(topic_id, since)
    return JSONResponse(result)


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
        # 同时返回 topic 标题（可能已通过 toolkit_set_topic_title 更新）
        topic_info = get_server().get_topic_info(topic_id)
        title = (topic_info or {}).get("title", "") or topic_id[:8]
        return JSONResponse({"conversations": convs, "count": len(convs), "title": title})
    except Exception as e:
        logger.exception("get_topic_conversations failed")
        return JSONResponse({"error": str(e)}, status_code=500)




async def handle_web_topic_trajectory(request):
    """GET /api/topic/{topic_id}/trajectory — 轨迹时间线（Agent 工作过程可视化）。

    借鉴 DeepSeek Harness Trajectory：按事件流重建 Agent 的执行轨迹，
    含 用户输入 / 思考链 / 工具调用(参数) / 工具结果 / AI 回复。
    """
    topic_id = request.path_params.get("topic_id", "")
    if not topic_id:
        return JSONResponse({"error": "topic_id required"}, status_code=400)
    limit = int(request.query_params.get("limit", 0))
    try:
        data = get_server().get_topic_trajectory(topic_id, limit=limit)
        topic_info = get_server().get_topic_info(topic_id)
        data["title"] = (topic_info or {}).get("title", "") or topic_id[:8]
        return JSONResponse(data)
    except Exception as e:
        logger.exception("get_topic_trajectory failed")
        return JSONResponse({"error": str(e)}, status_code=500)


async def handle_web_tools(request):
    """GET /api/tools"""
    tools = get_server().list_tools()
    return JSONResponse({"tools": tools, "count": len(tools)})


async def handle_web_interruptions(request):
    """GET /api/interruptions — 打断知识闭环统计查询。

    Query params:
        since: ISO 时间戳，仅统计该时间之后的事件（默认近 7 天）
        limit: 最近事件返回条数（默认 20）

    Returns:
        {stats: [{tool_name, count, last_ts}], recent: [...], total}
    """
    try:
        query = request.query_params
        since = query.get("since", "")
        limit = int(query.get("limit", 20))
        try:
            from tea_agent.store import get_storage

            storage = get_storage()
        except Exception:
            return JSONResponse({"stats": [], "recent": [], "total": 0})
        stats = storage.stats_interruptions(since or None)
        recent = storage.query_interruptions(since=since or None, limit=limit)
        return JSONResponse({
            "stats": stats,
            "recent": recent,
            "total": len(recent),
            "count": sum(int(s.get("count", 0)) for s in stats),
        })
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=503)
