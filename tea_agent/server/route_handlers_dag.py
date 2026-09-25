"""DAG 可视化与服务重启、文件树与文件读取。

由 route_handlers.py 拆分而来（逐字搬运，函数体未改写）。
"""

import asyncio
import json
import time

from starlette.responses import HTMLResponse, JSONResponse, Response, StreamingResponse

from tea_agent.multi_agent.workflow_viz import DagVizRegistry, get_viz_html


async def handle_dag_viz(request):
    """GET /dag/{viz_id} — 返回 DAG 可视化 HTML 页面。"""
    viz_id = request.path_params.get("viz_id", "")
    if not viz_id:
        return JSONResponse({"error": "viz_id required"}, status_code=400)

    viz = DagVizRegistry.get(viz_id)
    if viz:
        dag_structure = viz._build_dag_structure()
        html = get_viz_html(dag_structure, viz.title, viz_id=viz_id)
        return HTMLResponse(html)

    # 回退到 SimpleDagRegistry
    from tea_agent.workflow.dag_registry import SimpleDagRegistry
    simple = SimpleDagRegistry._instances.get(viz_id)
    if simple:
        html = get_viz_html(simple, simple.get("title", "DAG"), viz_id=viz_id)
        return HTMLResponse(html)

    return HTMLResponse(
        f"<html><body style='background:#0d1117;color:#c9d1d9;"
        f"font-family:sans-serif;display:flex;align-items:center;"
        f"justify-content:center;height:100vh'>"
        f"<div style='text-align:center'><h2>🔌 DAG 已结束或不存在</h2>"
        f"<p>viz_id: {viz_id}</p></div></body></html>",
        status_code=404,
    )


async def handle_dag_sse(request):
    """GET /dag/{viz_id}/events — SSE 事件流。"""
    viz_id = request.path_params.get("viz_id", "")
    if not viz_id:
        return JSONResponse({"error": "viz_id required"}, status_code=400)

    viz = DagVizRegistry.get(viz_id)
    if not viz:
        return JSONResponse({"error": "viz not found"}, status_code=404)

    q = viz.emitter.subscribe()

    async def event_stream():
        try:
            # 先推送全量状态
            if viz._exec:
                for nid, nr in viz._exec.results.items():
                    node = viz.dag.get_node(nid)
                    yield (
                        "data: "
                        + json.dumps({
                            "type": "node_state",
                            "data": {
                                "node_id": nid,
                                "state": nr.state.value,
                                "label": node.label if node else nid,
                                "duration": nr.duration,
                                "error": nr.error,
                                "started_at": nr.started_at,
                            },
                            "timestamp": time.time(),
                        }, ensure_ascii=False)
                        + "\n\n"
                    )

            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(q.get(), timeout=1.0)
                    yield "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"
                except asyncio.TimeoutError:
                    # 心跳
                    yield ": heartbeat\n\n"
        finally:
            viz.emitter.unsubscribe(q)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
async def handle_dag_status(request):
    """GET /dag/{viz_id}/status — 返回 JSON DAG 状态快照（供轮询）。"""
    viz_id = request.path_params.get("viz_id", "")
    if not viz_id:
        return JSONResponse({"error": "viz_id required"}, status_code=400)

    snapshot = DagVizRegistry.get_status_snapshot(viz_id)
    if snapshot:
        return JSONResponse(snapshot)

    # 回退到 SimpleDagRegistry
    from tea_agent.workflow.dag_registry import SimpleDagRegistry
    simple = SimpleDagRegistry._instances.get(viz_id)
    if simple:
        return JSONResponse(simple)
    return JSONResponse({"error": "viz not found"}, status_code=404)


async def handle_dag_image(request):
    """GET /dag/{viz_id}/image — 返回 dot 渲染的 SVG/PNG DAG 状态图。

    支持三个数据源（按优先级）：
      1. DagVizRegistry（WorkflowVisualizer 完整实例）
      2. SimpleDagRegistry（轻量注册表，工具推送的简易 DAG）
    """
    viz_id = request.path_params.get("viz_id", "")
    if not viz_id:
        return JSONResponse({"error": "viz_id required"}, status_code=400)

    fmt = request.query_params.get("format", "svg")

    from tea_agent.multi_agent.dag_dot_renderer import (
        render_dag_dict_to_png,
        render_dag_dict_to_svg,
    )

    # ── 数据源 1：DagVizRegistry ──
    viz = DagVizRegistry.get(viz_id)
    if viz:
        # 转换为 dict 格式，使用通用渲染函数
        dag_data = DagVizRegistry.get_status_snapshot(viz_id)
        if dag_data:
            if fmt == "png":
                png_data = render_dag_dict_to_png(dag_data)
                if png_data:
                    return Response(content=png_data, media_type="image/png",
                                    headers={"Cache-Control": "no-cache"})
            svg_data = render_dag_dict_to_svg(dag_data)
            if svg_data:
                return Response(content=svg_data, media_type="image/svg+xml",
                                headers={"Cache-Control": "no-cache"})
            return Response(content=str(dag_data), media_type="text/plain",
                            status_code=500)

    # ── 数据源 2：SimpleDagRegistry ──
    try:
        from tea_agent.workflow.dag_registry import SimpleDagRegistry
        entry = SimpleDagRegistry._instances.get(viz_id) if hasattr(SimpleDagRegistry, '_instances') else None
        if entry:
            dag_dict = {
                "title": entry.get("title", "DAG"),
                "nodes": entry.get("nodes", []),
                "edges": entry.get("edges", []),
            }
            if fmt == "png":
                png_data = render_dag_dict_to_png(dag_dict)
                if png_data:
                    return Response(content=png_data, media_type="image/png",
                                    headers={"Cache-Control": "no-cache"})
            svg_data = render_dag_dict_to_svg(dag_dict)
            if svg_data:
                return Response(content=svg_data, media_type="image/svg+xml",
                                headers={"Cache-Control": "no-cache"})
            return Response(content=str(dag_dict), media_type="text/plain",
                            status_code=500)
    except ImportError:
        pass

    # 未找到
    return JSONResponse({"error": "viz not found", "viz_id": viz_id},
                        status_code=404)


# ═══════════════════════════════════════════════
# DAG 列表端点 — /api/dags
# ═══════════════════════════════════════════════

async def handle_list_dags(request):
    """GET /api/dags — 返回所有活跃 DAG 的摘要列表。

    合并 DagVizRegistry + SimpleDagRegistry，供任务面板轮询。
    """
    result = []

    # 1) DagVizRegistry
    try:
        from tea_agent.multi_agent.workflow_viz import DagVizRegistry
        for viz_id in DagVizRegistry.list_ids():
            snap = DagVizRegistry.get_status_snapshot(viz_id)
            if snap:
                result.append({
                    "viz_id": viz_id,
                    "title": snap.get("title", viz_id),
                    "state": snap.get("state", "unknown"),
                    "progress": snap.get("progress", {}),
                    "node_count": len(snap.get("nodes", [])),
                    "edge_count": len(snap.get("edges", [])),
                    "source": "DagVizRegistry",
                })
    except ImportError:
        pass

    # 2) SimpleDagRegistry
    try:
        from tea_agent.workflow.dag_registry import SimpleDagRegistry
        for entry in SimpleDagRegistry.list_all():
            result.append({
                "viz_id": entry.get("viz_id", ""),
                "title": entry.get("title", "DAG"),
                "state": entry.get("state", "unknown"),
                "progress": entry.get("progress", {}),
                "node_count": len(entry.get("nodes", [])),
                "edge_count": len(entry.get("edges", [])),
                "source": "SimpleDagRegistry",
            })
    except ImportError:
        pass

    return JSONResponse({"dags": result, "count": len(result)})


async def handle_restart(request):
    """POST /api/restart — 重启 server（默认 graceful，不切断在途回合）。

    Query:
        mode: graceful(默认) | immediate
        wait: graceful 等待在途回合的上限秒数（默认 120）

    用于 server 自我更新后重启，无需人工介入。
    """
    from .server import restart_server

    mode = (request.query_params.get("mode") or "graceful").strip().lower()
    if mode not in ("graceful", "immediate"):
        return JSONResponse({"ok": False, "error": "mode 仅支持 graceful|immediate"},
                            status_code=400)
    try:
        wait = float(request.query_params.get("wait", "120") or 120)
    except (TypeError, ValueError):
        wait = 120.0
    result = restart_server(graceful=(mode == "graceful"), wait_seconds=wait)
    status = 200 if result.get("ok") else 500
    return JSONResponse(result, status_code=status)


# ================================================================
#  File Tree API
# ================================================================

async def handle_file_tree(request):
    """GET /api/files?path=... — 列出指定目录的文件树。

    返回目录结构，支持懒加载（只返回当前层级）。
    自动过滤 .git/ node_modules/ __pycache__/ 等目录。
    """
    import os as _os
    from pathlib import Path as _Path

    req_path = request.query_params.get("path", "")
    root = _os.getcwd()

    if req_path:
        target = _Path(root) / req_path
        # 安全检查：不能超出项目根目录
        try:
            target = target.resolve()
            _Path(root).resolve()
            # 简化安全校验：确保目标在项目目录下
            target_str = str(target).lower()
            root_str = str(_Path(root).resolve()).lower()
            if not target_str.startswith(root_str):
                return JSONResponse({"ok": False, "error": "路径超出项目目录"}, status_code=403)
        except (ValueError, OSError):
            return JSONResponse({"ok": False, "error": "无效路径"}, status_code=400)
    else:
        target = _Path(root)

    if not target.is_dir():
        return JSONResponse({"ok": False, "error": "不是目录"}, status_code=400)

    # 忽略的目录模式
    ignored_dirs = {
        ".git", "node_modules", "__pycache__", ".venv", "venv",
        ".tea_agent_run", ".svn", ".hg", ".idea", ".vscode",
        "dist", "build", "build_mini_dist", "build_nuitka_dist",
        ".egg-info", ".mypy_cache", ".pytest_cache",
    }
    ignored_exts = {".pyc", ".pyo", ".egg", ".whl", ".jpg", ".jpeg",
                    ".png", ".gif", ".ico", ".svg", ".webp", ".mp4",
                    ".mp3", ".wav", ".ogg", ".pdf", ".zip", ".tar.gz"}

    items = []
    try:
        for entry in sorted(target.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower())):
            name = entry.name
            if name.startswith(".") and name not in (".env", ".gitignore", ".dockerignore"):
                continue
            if entry.is_dir() and name in ignored_dirs:
                continue

            item = {
                "name": name,
                "path": str(_Path(req_path) / name) if req_path else name,
                "type": "dir" if entry.is_dir() else "file",
            }
            if entry.is_file():
                ext = entry.suffix.lower()
                item["ext"] = ext
                try:
                    item["size"] = entry.stat().st_size
                except OSError:
                    item["size"] = 0
                if ext in ignored_exts:
                    continue
            items.append(item)
    except PermissionError:
        return JSONResponse({"ok": False, "error": "无权限访问"}, status_code=403)

    return JSONResponse({
        "ok": True,
        "path": req_path or "/",
        "abs_path": str(target.resolve()),
        "items": items,
        "parent": str(_Path(req_path).parent) if req_path else None,
    })


async def handle_file_read(request):
    """GET /api/file?path=... — 读取单个文件内容。"""
    import os as _os
    from pathlib import Path as _Path

    file_path = request.query_params.get("path", "")
    if not file_path:
        return JSONResponse({"ok": False, "error": "需要 path 参数"}, status_code=400)

    root = _os.getcwd()
    target = (_Path(root) / file_path).resolve()
    root_resolved = _Path(root).resolve()

    # 安全检查
    if not str(target).lower().startswith(str(root_resolved).lower()):
        return JSONResponse({"ok": False, "error": "路径超出项目目录"}, status_code=403)

    if not target.is_file():
        return JSONResponse({"ok": False, "error": "文件不存在"}, status_code=404)

    # 限制文件大小（5MB）
    max_size = 5 * 1024 * 1024
    if target.stat().st_size > max_size:
        return JSONResponse({"ok": False, "error": "文件过大，无法预览"}, status_code=413)

    try:
        content = target.read_text(encoding="utf-8", errors="replace")
        return JSONResponse({
            "ok": True,
            "path": file_path,
            "content": content,
            "size": target.stat().st_size,
        })
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)
