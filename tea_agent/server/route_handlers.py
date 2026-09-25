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
import tempfile
import threading
import time
import urllib.parse
from datetime import datetime
from pathlib import Path

from starlette.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse

from tea_agent.model_manager import ProviderError
from tea_agent.multi_agent.workflow_viz import DagVizRegistry, get_viz_html
from tea_agent.toolkit.toolkit_export_last_pdf import export_topic_markdown, export_topic_pdf

from . import turn_snapshot as _snapshot
from ._compat import (
    __version__,
    _active_sessions,
    _active_sessions_lock,
    _background_buffer_reader,
    _background_sessions,
    _background_sessions_lock,
    _chat_stream_sse_wrapper,
    _is_draining,
    _is_topic_busy,
    _max_iter_pending,
    _question_pending,
    _queue_add,
    _queue_list,
    _queue_remove,
    _read_buffer_since,
    get_server,
    logger,
)

# ── 从同级模块重导出（保持 route_handlers.X 对既有调用方与测试可用）──
from .route_handlers_basic import (
    OPENAPI_SPEC,
    handle_chat_completions,
    handle_create_memory,
    handle_create_session,
    handle_create_task,
    handle_delete_memory,
    handle_delete_session,
    handle_delete_task,
    handle_docs,
    handle_get_config,
    handle_get_session,
    handle_get_session_messages,
    handle_health,
    handle_list_memory,
    handle_list_models,
    handle_list_sessions,
    handle_list_tasks,
    handle_list_tools,
    handle_openapi,
    handle_run_tool,
    handle_search,
    handle_switch_config,
)
from .route_handlers_dag import (
    handle_dag_image,
    handle_dag_sse,
    handle_dag_status,
    handle_dag_viz,
    handle_file_read,
    handle_file_tree,
    handle_list_dags,
    handle_restart,
)
from .route_handlers_exports import (
    exports_dir,
    handle_export_md,
    handle_export_pdf,
    handle_file_download,
    handle_file_preview,
    handle_screenshot_full,
    handle_screenshot_interactive,
    handle_screenshot_region,
    handle_upload,
    is_previewable_image,
)
from .route_handlers_models import (
    _ensure_selected_option,
    _mc_error_response,
    _model_store,
    _provider_option_list,
    _provider_store,
    _pstore_error_response,
    _role_selection,
    handle_model_config_get,
    handle_model_config_model_add,
    handle_model_config_model_del,
    handle_model_config_model_put,
    handle_model_config_switch,
    handle_model_config_sync,
    handle_model_options,
    handle_model_select,
    handle_provider_store_apply,
    handle_provider_store_delete,
    handle_provider_store_get,
    handle_provider_store_list,
    handle_provider_store_model_delete,
    handle_provider_store_model_put,
    handle_provider_store_query_models,
    handle_provider_store_sync_models,
    handle_provider_store_upsert,
)
from .route_handlers_providers import (
    _model_service,
    _provider_error_response,
    handle_get_module,
    handle_list_modules,
    handle_model_test,
    handle_provider_apply,
    handle_provider_create,
    handle_provider_delete,
    handle_provider_models,
    handle_provider_update,
    handle_providers_list,
    handle_reload_all_modules,
    handle_reload_module,
    handle_reload_routes,
    handle_start_watcher,
    handle_stop_watcher,
)
from .route_handlers_topics import (
    handle_web_fork_topic,
    handle_web_interruptions,
    handle_web_new_topic,
    handle_web_sessions,
    handle_web_tools,
    handle_web_topic_conversations,
    handle_web_topic_info,
    handle_web_topic_plans,
    handle_web_topic_status,
    handle_web_topic_stream_buffer,
    handle_web_topic_todo_update,
    handle_web_topic_todos,
    handle_web_topic_trajectory,
)
from .route_handlers_webconfig import (
    _writeback_provider_yaml,
    handle_web_config,
    handle_web_create_config,
    handle_web_list_configs,
    handle_web_model_config,
    handle_web_model_info,
    handle_web_model_switch,
    handle_web_root,
    handle_web_update_config,
    handle_web_upload_config,
)


def _persist_turn_images(storage, images: list, label: str = "Image") -> list:
    """把回合图片**立即入库**，返回 ``img:<id>`` 引用列表（输入不丢失）。

    为什么必须在回合**开始**入库，而不是等回合结束的 ``save_msg``：

    1. **切回可见**：回合进行中用户切走主题再切回时，该提问尚未写库，
       图片若只活在内存里就无从恢复（实测表现为「切回后看不到刚发的图」）。
    2. **快照可承载**：data URL 动辄数万字符，会被快照的 ``_shrink`` 截断成
       ``...A…[truncated]`` —— 前端 ``<img src>`` 拿到损坏值。短引用无此问题。

    归属由回合结束的 ``save_msg`` 补上（见 ``Storage._adopt_image``）。

    Args:
        storage: Storage 实例；为空时原样返回（fail-open，不阻断对话）。
        images: data URL 列表（``_images_to_data_urls`` 的产物）。
        label: 日志前缀。

    Returns:
        引用列表；非 data URL 项（外链等）原样保留。
    """
    from tea_agent.image_ref import make_image_ref, parse_data_url

    if not images or storage is None:
        return list(images or [])
    refs: list[str] = []
    for item in images:
        if not isinstance(item, str) or not item.startswith("data:"):
            refs.append(item)
            continue
        try:
            mime, blob = parse_data_url(item)
            if not blob:
                refs.append(item)  # 解析失败：保留原值，不丢输入
                continue
            refs.append(make_image_ref(storage.add_pending_image(blob, mime)))
        except Exception as e:
            logger.warning(f"{label} persist failed: {e}")
            refs.append(item)      # 入库失败：退回原值，绝不静默丢图
    return refs


def _images_to_data_urls(images_b64: list, label: str = "Image") -> list:
    """把请求里的图片归一化为 data URL 列表（**不落盘**）。

    图片二进制由 ``Storage.save_msg`` 直接写入 ``images`` 表；此前先写
    ``uploads/`` 再存库，会在文件系统留下无清理策略的副本，且工作目录变更
    即导致历史图片永久丢失。

    接受的入参：``data:`` URL（原样透传）或裸 base64（补 ``image/png`` 前缀）。
    解码失败的项跳过并告警（与旧行为一致，不阻断整轮对话）。

    Args:
        images_b64: 请求体 ``images`` 字段。
        label: 日志前缀（区分主对话/插话）。

    Returns:
        data URL 字符串列表。
    """
    import base64 as b64mod

    out: list[str] = []
    for img in images_b64 or []:
        if not isinstance(img, str) or not img:
            continue
        if img.startswith("data:"):
            out.append(img)
            continue
        try:
            b64mod.b64decode(img, validate=False)
        except Exception as e:
            logger.warning(f"{label} base64 decode failed: {e}")
            continue
        out.append(f"data:image/png;base64,{img}")
    return out
async def handle_web_chat(request):
    """POST /api/chat - SSE streaming chat for Web UI.

    如果 topic 正在对话中，消息将被加入排队队列而非启动新对话。
    前端收到 queued 响应后显示排队状态。
    """
    body = await request.json()
    message = body.get("message", "").strip()
    topic_id = body.get("topic_id", "")
    config_path = body.get("config_path") or None
    images_b64 = body.get("images", [])

    if not message and not images_b64:
        return JSONResponse({"error": "message required"}, status_code=400)

    if _is_draining() and not topic_id:
        # 重启排空期且无 topic_id（无法排队）：提示客户端稍后重试，
        # 避免刚启动的回合随即被 should_exit 切断
        return JSONResponse({"error": "server restarting, please retry",
                             "retry_after": 2}, status_code=503)
    if not topic_id:
        # 新主题直接进入 SSE 流
        pass
    elif _is_topic_busy(topic_id) or _is_draining():
        # ⭐ 主题正忙 → 加入排队队列，返回 SSE 事件而非普通 JSON
        # 让前端 SSE 解析器能正常接收并处理，避免卡死
        # 图片统一转 data URL（该队列项会被工具循环作为插话消费注入，
        # to_multimodal 对 data: 前缀直接透传）
        _steer_images = []
        for _img in images_b64:
            if isinstance(_img, str) and _img.startswith("data:"):
                _steer_images.append(_img)
            else:
                _steer_images.append(f"data:image/png;base64,{_img}")
        item_id = _queue_add(topic_id, message, _steer_images)
        position = len(_queue_list(topic_id))
        logger.info(f"Topic busy, queued message: topic={topic_id} item={item_id} position={position}")
        async def _queued_sse():
            yield f"data: {json.dumps({'type': 'queued', 'item_id': item_id, 'topic_id': topic_id, 'position': position})}\n\n"
        return StreamingResponse(_queued_sse(), media_type="text/event-stream")

    # 图片归一化为 data URL（不落盘）；随后在回合开始时入库为 img:<id> 引用
    image_paths = _images_to_data_urls(images_b64, label="Image")

    server = get_server()
    session, storage = server.create_session(config_path)
    queue: asyncio.Queue = asyncio.Queue()

    async def event_stream():
        loop = asyncio.get_running_loop()

        nonlocal topic_id
        if not topic_id:
            topic_id = storage.create_topic(f"Web Session ({datetime.now().strftime('%m-%d %H:%M')})")

        # 在途快照：登记本回合，使 server 意外重启后可恢复已产出内容
        _snapshot.begin_turn(topic_id)
        # 图片在回合**开始**即入库，全程改用 img:<id> 短引用：
        #   1) data URL 数万字符会被快照 _shrink 截断成损坏值（切回后图片打不开）；
        #   2) 图片只活在内存时，回合进行中切走再切回无从恢复（输入丢失）。
        _img_refs = _persist_turn_images(storage, image_paths, label="Image")
        _turn_payload = ({"text": message, "images": _img_refs}
                         if _img_refs else message)
        # 回合**开始**即建 conversation 行（status=pending）：
        #   1) 回合中的工具/增量事件据此归属 —— 此前 conversation_id 恒为 NULL
        #      （实测 404 条 tool/call 全部无归属），轮次级审计无法进行；
        #   2) 切回主题时该轮已在库可查，不必等回合结束才写；
        #   3) 图片在 create_turn 内获得归属（_store_images → _adopt_image）。
        # 失败时降级为旧行为（回合结束的 save_msg 兜底建行），不阻断对话。
        try:
            _conv_id = storage.create_turn(topic_id, _turn_payload)
            _ctx = getattr(session, "context", None)
            if _ctx is not None:
                _ctx.conversation_id = _conv_id
        except Exception:
            logger.exception("create_turn failed (turn continues, will save at end)")
        # 把用户提问记为快照事件（序号 0）：回合进行中切走再切回时，
        # 该提问尚未定稿（finalize_turn 在回合结束时才调用），若不记入事件流，
        # 前端既读不到 DB 也读不到缓冲区 —— 用户连自己刚问过什么都看不到。
        _snapshot.record_event(
            topic_id,
            {"type": "user_message", "text": message, "images": _img_refs},
            0, force=True,
        )

        try:
            with _active_sessions_lock:
                _active_sessions[topic_id] = session

            thread = threading.Thread(
                target=_chat_stream_sse_wrapper,
                args=(session, storage, _turn_payload, queue, topic_id, loop),
                daemon=True,
            )
            thread.start()

            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                    # 在途快照：节流落盘（终态强制），server 重启后据此续读
                    _terminal = event.get("type") in ("done", "error")
                    _snapshot.record_event(topic_id, event, force=_terminal)
                    if _terminal:
                        _snapshot.finish_turn(topic_id, status=event["type"])
                    yield "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"
                    if _terminal:
                        break
                except asyncio.TimeoutError:
                    # 线程已死但没发 done/error → 强制终结（防止按钮卡红）
                    if not thread.is_alive():
                        yield "data: " + json.dumps({
                            "type": "error",
                            "error": "服务器处理意外终止"
                        }) + "\n\n"
                        break
                    # 线程还活着 → 发送 SSE 心跳保活，防止中间代理/浏览器断开连接
                    yield ":keepalive\n\n"
        except asyncio.CancelledError:
            # 客户端断连 → 不中断 session（留给 /api/chat/abort 处理）
            # 后台线程会继续完成对话并自动保存到数据库
            logger.info("Web SSE client disconnected, session continues in background")
            # ⭐ 移入后台会话追踪，防止用户切回时启动重复会话
            # _chat_stream_sse_wrapper 的 finally 会在线程结束时清理
            with _background_sessions_lock:
                _background_sessions[topic_id] = session
            # ⭐ 启动后台缓冲区读取器：消费 queue 中的后续 SSE 事件并缓存
            # 供前端轮询获取实时流式内容
            asyncio.create_task(
                _background_buffer_reader(topic_id, queue, loop),
            )
            # Don't call session.interrupt() — 让后台线程自然完成并保存结果
            raise
        except Exception:
            # 其他 SSE 异常 → 同样中断后台线程
            logger.exception("SSE stream error, interrupting session")
            session.interrupt()
            raise
        finally:
            # 仅清理活跃会话中的条目（后台会话由 _chat_stream_sse_wrapper 清理）
            with _active_sessions_lock:
                if _active_sessions.get(topic_id) is session:
                    _active_sessions.pop(topic_id, None)
            # ⭐ 当前对话结束（后续排队消息由前端驱动自动发送）；
            # 尝试应用挂起的模型切换 —— 会话续用：不中断本轮，结束后自动以新模型继续
            try:
                from .modules.agent_module import AgentModule
                AgentModule.try_apply_pending_switch()
            except Exception as e:
                logger.debug("apply queued model switch skipped: %s", e)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


async def handle_web_chat_steering(request):
    """POST /api/chat/steering — 会话进行期间插话入队（steering）。

    当前会话的工具循环在下一轮边界消费该队列并注入模型请求，使使用者的
    新输入无需等待会话结束即可生效（软插话，不打断执行中的工具批次）。

    Returns:
        JSONResponse: {ok, item_id, topic_id, position}
        item_id 用于前端在收到 steering_injected SSE 事件时，从本地排队
        列表移除对应项，避免流结束后重复发送。
    """
    body = await request.json()
    message = body.get("message", "").strip()
    topic_id = body.get("topic_id", "").strip()
    images_b64 = body.get("images", [])

    if not message and not images_b64:
        return JSONResponse({"error": "message required"}, status_code=400)

    if not topic_id:
        # 首次对话时前端可能尚未拿到 topic_id：活跃会话唯一则按主题解析
        with _active_sessions_lock:
            _keys = list(_active_sessions.keys())
        if len(_keys) == 1:
            topic_id = _keys[0]
        else:
            return JSONResponse(
                {"error": "topic_id 不能为空（无法唯一确定当前会话）"},
                status_code=400,
            )

    # 插话图片同样不落盘：归一化为 data URL，由 save_msg 写入 images 表
    image_paths = _images_to_data_urls(images_b64, label="Steering image")

    item_id = _queue_add(topic_id, message, image_paths)
    position = len(_queue_list(topic_id))
    logger.info(
        f"Steering queued: topic={topic_id} item={item_id} "
        f"position={position} images={len(image_paths)}"
    )
    return JSONResponse({
        "ok": True,
        "item_id": item_id,
        "topic_id": topic_id,
        "position": position,
    })


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
        # 用户输入的续命轮数（弹框输入，默认 10；钳位 1..1000 防误填爆轮）
        try:
            extra = int(body.get("extra", 10))
        except (TypeError, ValueError):
            extra = 10
        extra = max(1, min(1000, extra))
        session._continue_after_max = decision
        if decision:
            session._max_iter_extra_pending = extra
        session._max_iter_wait.set()
        logger.info(f"User confirmed max_iter: continue={decision} extra={extra}")
        return JSONResponse({"ok": True, "continue": decision, "extra": extra})
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

    with _active_sessions_lock:
        session = _active_sessions.get(topic_id)
    if not session:
        # 也可能在后台会话中
        session = _background_sessions.get(topic_id)
    if not session:
        logger.warning(f"Abort failed: no active session for topic_id={topic_id}")
        return JSONResponse({"ok": False, "error": "未找到活跃会话（可能已结束）"}, status_code=404)

    try:
        session.interrupt()
        logger.info(f"User aborted session topic_id={topic_id}")
    except Exception as e:
        logger.exception(f"Abort session failed topic_id={topic_id}")
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

    # ⭐ 立即清理会话追踪，避免中断后发送新消息时 is_topic_busy 仍返回 True
    with _active_sessions_lock:
        if _active_sessions.get(topic_id) is session:
            _active_sessions.pop(topic_id, None)
    with _background_sessions_lock:
        if _background_sessions.get(topic_id) is session:
            _background_sessions.pop(topic_id, None)
    # 清理后台缓冲区（如果有）
    try:
        from .modules.state import cleanup_buffer, mark_buffer_done
        cleanup_buffer(topic_id)
        mark_buffer_done(topic_id)
    except Exception:
        pass

    return JSONResponse({"ok": True, "message": "已发送中断信号并清理会话"})


# ================================================================
#  Queue API — 排队消息管理
# ================================================================

async def handle_web_queue_add(request):
    """POST /api/queue/{topic_id} — 添加消息到排队队列（手动入队）"""
    topic_id = request.path_params.get("topic_id", "")
    if not topic_id:
        return JSONResponse({"error": "topic_id 不能为空"}, status_code=400)
    body = await request.json()
    message = body.get("message", "").strip()
    images_b64 = body.get("images", [])
    if not message and not images_b64:
        return JSONResponse({"error": "message required"}, status_code=400)
    item_id = _queue_add(topic_id, message, images_b64)
    position = len(_queue_list(topic_id))
    return JSONResponse({"ok": True, "item_id": item_id, "topic_id": topic_id, "position": position})


async def handle_web_queue_list(request):
    """GET /api/queue/{topic_id} — 获取排队消息列表"""
    topic_id = request.path_params.get("topic_id", "")
    if not topic_id:
        return JSONResponse({"error": "topic_id 不能为空"}, status_code=400)
    items = _queue_list(topic_id)
    return JSONResponse({"ok": True, "topic_id": topic_id, "items": items, "count": len(items)})


async def handle_web_queue_remove(request):
    """DELETE /api/queue/{topic_id}/{item_id} — 取消排队消息"""
    topic_id = request.path_params.get("topic_id", "")
    item_id = request.path_params.get("item_id", "")
    if not topic_id or not item_id:
        return JSONResponse({"error": "topic_id 和 item_id 不能为空"}, status_code=400)
    ok = _queue_remove(topic_id, item_id)
    if ok:
        return JSONResponse({"ok": True, "item_id": item_id, "topic_id": topic_id})
    return JSONResponse({"ok": False, "error": "未找到该排队消息"}, status_code=404)
async def handle_web_image(request):
    """GET /api/image/{image_id} — 回读会话图片（二进制存于 images 表）。

    前端历史渲染把 ``img:<id>`` 引用指向本路由，无需文件系统副本。
    """
    raw = request.path_params.get("image_id", "")
    try:
        image_id = int(raw)
    except (TypeError, ValueError):
        return JSONResponse({"error": "invalid image id"}, status_code=400)
    try:
        img = get_server().get_image(image_id)
    except Exception as e:
        logger.exception("get_image failed")
        return JSONResponse({"error": str(e)}, status_code=500)
    if not img or not img.get("blob"):
        return JSONResponse({"error": "image not found"}, status_code=404)
    return Response(
        content=img["blob"],
        media_type=img.get("mime_type") or "image/png",
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


__all__ = [
    "DagVizRegistry",
    "FileResponse",
    "HTMLResponse",
    "JSONResponse",
    "OPENAPI_SPEC",
    "Path",
    "ProviderError",
    "Response",
    "StreamingResponse",
    "__version__",
    "_active_sessions",
    "_active_sessions_lock",
    "_background_buffer_reader",
    "_background_sessions",
    "_background_sessions_lock",
    "_chat_stream_sse_wrapper",
    "_ensure_selected_option",
    "_images_to_data_urls",
    "_is_draining",
    "_is_topic_busy",
    "_max_iter_pending",
    "_mc_error_response",
    "_model_service",
    "_model_store",
    "_persist_turn_images",
    "_provider_error_response",
    "_provider_option_list",
    "_provider_store",
    "_pstore_error_response",
    "_question_pending",
    "_queue_add",
    "_queue_list",
    "_queue_remove",
    "_read_buffer_since",
    "_role_selection",
    "_snapshot",
    "_writeback_provider_yaml",
    "asyncio",
    "contextlib",
    "datetime",
    "export_topic_markdown",
    "export_topic_pdf",
    "exports_dir",
    "get_server",
    "get_viz_html",
    "handle_chat_abort",
    "handle_chat_completions",
    "handle_chat_continue",
    "handle_chat_question",
    "handle_create_memory",
    "handle_create_session",
    "handle_create_task",
    "handle_dag_image",
    "handle_dag_sse",
    "handle_dag_status",
    "handle_dag_viz",
    "handle_delete_memory",
    "handle_delete_session",
    "handle_delete_task",
    "handle_docs",
    "handle_export_md",
    "handle_export_pdf",
    "handle_file_download",
    "handle_file_preview",
    "handle_file_read",
    "handle_file_tree",
    "handle_get_config",
    "handle_get_module",
    "handle_get_session",
    "handle_get_session_messages",
    "handle_health",
    "handle_list_dags",
    "handle_list_memory",
    "handle_list_models",
    "handle_list_modules",
    "handle_list_sessions",
    "handle_list_tasks",
    "handle_list_tools",
    "handle_model_config_get",
    "handle_model_config_model_add",
    "handle_model_config_model_del",
    "handle_model_config_model_put",
    "handle_model_config_switch",
    "handle_model_config_sync",
    "handle_model_options",
    "handle_model_select",
    "handle_model_test",
    "handle_openapi",
    "handle_provider_apply",
    "handle_provider_create",
    "handle_provider_delete",
    "handle_provider_models",
    "handle_provider_store_apply",
    "handle_provider_store_delete",
    "handle_provider_store_get",
    "handle_provider_store_list",
    "handle_provider_store_model_delete",
    "handle_provider_store_model_put",
    "handle_provider_store_query_models",
    "handle_provider_store_sync_models",
    "handle_provider_store_upsert",
    "handle_provider_update",
    "handle_providers_list",
    "handle_reload_all_modules",
    "handle_reload_module",
    "handle_reload_routes",
    "handle_restart",
    "handle_run_tool",
    "handle_screenshot_full",
    "handle_screenshot_interactive",
    "handle_screenshot_region",
    "handle_search",
    "handle_start_watcher",
    "handle_stop_watcher",
    "handle_switch_config",
    "handle_upload",
    "handle_web_chat",
    "handle_web_chat_steering",
    "handle_web_config",
    "handle_web_create_config",
    "handle_web_fork_topic",
    "handle_web_image",
    "handle_web_interruptions",
    "handle_web_list_configs",
    "handle_web_model_config",
    "handle_web_model_info",
    "handle_web_model_switch",
    "handle_web_new_topic",
    "handle_web_queue_add",
    "handle_web_queue_list",
    "handle_web_queue_remove",
    "handle_web_root",
    "handle_web_sessions",
    "handle_web_tools",
    "handle_web_topic_conversations",
    "handle_web_topic_info",
    "handle_web_topic_plans",
    "handle_web_topic_status",
    "handle_web_topic_stream_buffer",
    "handle_web_topic_todo_update",
    "handle_web_topic_todos",
    "handle_web_topic_trajectory",
    "handle_web_update_config",
    "handle_web_upload_config",
    "is_previewable_image",
    "json",
    "logger",
    "os",
    "tempfile",
    "threading",
    "time",
    "urllib",
]
