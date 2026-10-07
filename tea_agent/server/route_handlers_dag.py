"""DAG 可视化与服务重启、文件树与文件读取。

由 route_handlers.py 拆分而来（逐字搬运，函数体未改写）。
"""

import asyncio
import json
import time
import urllib.parse

from starlette.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse

from tea_agent.multi_agent.workflow_viz import DagVizRegistry, get_viz_html

# 图片 MIME 白名单与 /v1/preview 共用同一事实源：文件树预览与文档预览
# 对"什么算图片"必须一致，否则同一文件在一处能预览、另一处不能。
from tea_agent.server.route_handlers_exports import _IMAGE_MIME

#: 可作为文本读取并格式化的扩展名（白名单；未列出者按二进制处理）
_TEXT_EXTS: frozenset = frozenset(
    {
        ".py",
        ".pyi",
        ".pyw",
        ".js",
        ".mjs",
        ".cjs",
        ".ts",
        ".tsx",
        ".jsx",
        ".vue",
        ".svelte",
        ".html",
        ".htm",
        ".css",
        ".scss",
        ".less",
        ".json",
        ".jsonl",
        ".ndjson",
        ".yaml",
        ".yml",
        ".toml",
        ".ini",
        ".cfg",
        ".conf",
        ".properties",
        ".md",
        ".markdown",
        ".rst",
        ".txt",
        ".log",
        ".csv",
        ".tsv",
        ".sh",
        ".bash",
        ".zsh",
        ".fish",
        ".bat",
        ".cmd",
        ".ps1",
        ".sql",
        ".c",
        ".h",
        ".cc",
        ".cpp",
        ".hpp",
        ".cs",
        ".java",
        ".kt",
        ".rs",
        ".go",
        ".rb",
        ".php",
        ".pl",
        ".lua",
        ".r",
        ".m",
        ".swift",
        ".dart",
        ".scala",
        ".gradle",
        ".dockerfile",
        ".editorconfig",
        ".gitignore",
        ".dockerignore",
        ".env",
        ".lock",
        ".patch",
        ".diff",
    }
)

#: 文本读取上限（超出即截断并提示；避免把巨型日志塞进弹窗）
_TEXT_READ_MAX = 2 * 1024 * 1024


def classify_file(name: str) -> tuple:
    """按扩展名判定文件预览类型。

    Returns:
        ``(kind, mime)``；kind ∈ {``image``, ``text``, ``binary``}。
        ``binary`` 的 mime 恒为 ``application/octet-stream``。
    """
    from pathlib import Path as _Path

    ext = _Path(name).suffix.lower()
    if ext in _IMAGE_MIME:
        return "image", _IMAGE_MIME[ext]
    # 无扩展名的常见文本文件（Dockerfile / Makefile / LICENSE …）
    if ext in _TEXT_EXTS or (not ext and _Path(name).name.lower() in {"dockerfile", "makefile", "license", "readme"}):
        return "text", "text/plain"
    return "binary", "application/octet-stream"


def _resolve_in_root(rel_path: str):
    """把请求路径解析到**启动目录**内（防路径遍历）。

    Returns:
        ``(Path, None)`` 成功；``(None, JSONResponse)`` 失败（400/403）。
    """
    import os as _os
    from pathlib import Path as _Path

    root = _Path(_os.getcwd()).resolve()
    try:
        target = (_Path(root) / rel_path).resolve()
    except (ValueError, OSError):
        return None, JSONResponse({"ok": False, "error": "无效路径"}, status_code=400)
    # 用 relative_to 判定包含关系：纯 startswith 会把 /root2 误判为 /root 的子路径
    try:
        target.relative_to(root)
    except ValueError:
        return None, JSONResponse({"ok": False, "error": "路径超出项目目录"}, status_code=403)
    return target, None


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
                        + json.dumps(
                            {
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
                            },
                            ensure_ascii=False,
                        )
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
                    return Response(content=png_data, media_type="image/png", headers={"Cache-Control": "no-cache"})
            svg_data = render_dag_dict_to_svg(dag_data)
            if svg_data:
                return Response(content=svg_data, media_type="image/svg+xml", headers={"Cache-Control": "no-cache"})
            return Response(content=str(dag_data), media_type="text/plain", status_code=500)

    # ── 数据源 2：SimpleDagRegistry ──
    try:
        from tea_agent.workflow.dag_registry import SimpleDagRegistry

        entry = SimpleDagRegistry._instances.get(viz_id) if hasattr(SimpleDagRegistry, "_instances") else None
        if entry:
            dag_dict = {
                "title": entry.get("title", "DAG"),
                "nodes": entry.get("nodes", []),
                "edges": entry.get("edges", []),
            }
            if fmt == "png":
                png_data = render_dag_dict_to_png(dag_dict)
                if png_data:
                    return Response(content=png_data, media_type="image/png", headers={"Cache-Control": "no-cache"})
            svg_data = render_dag_dict_to_svg(dag_dict)
            if svg_data:
                return Response(content=svg_data, media_type="image/svg+xml", headers={"Cache-Control": "no-cache"})
            return Response(content=str(dag_dict), media_type="text/plain", status_code=500)
    except ImportError:
        pass

    # 未找到
    return JSONResponse({"error": "viz not found", "viz_id": viz_id}, status_code=404)


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
                result.append(
                    {
                        "viz_id": viz_id,
                        "title": snap.get("title", viz_id),
                        "state": snap.get("state", "unknown"),
                        "progress": snap.get("progress", {}),
                        "node_count": len(snap.get("nodes", [])),
                        "edge_count": len(snap.get("edges", [])),
                        "source": "DagVizRegistry",
                    }
                )
    except ImportError:
        pass

    # 2) SimpleDagRegistry
    try:
        from tea_agent.workflow.dag_registry import SimpleDagRegistry

        for entry in SimpleDagRegistry.list_all():
            result.append(
                {
                    "viz_id": entry.get("viz_id", ""),
                    "title": entry.get("title", "DAG"),
                    "state": entry.get("state", "unknown"),
                    "progress": entry.get("progress", {}),
                    "node_count": len(entry.get("nodes", [])),
                    "edge_count": len(entry.get("edges", [])),
                    "source": "SimpleDagRegistry",
                }
            )
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
        return JSONResponse({"ok": False, "error": "mode 仅支持 graceful|immediate"}, status_code=400)
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
        ".git",
        "node_modules",
        "__pycache__",
        ".venv",
        "venv",
        ".tea_agent_run",
        ".svn",
        ".hg",
        ".idea",
        ".vscode",
        "dist",
        "build",
        "build_mini_dist",
        "build_nuitka_dist",
        ".egg-info",
        ".mypy_cache",
        ".pytest_cache",
    }
    # 仅过滤"体积大且无法文本预览"的类型；图片**不再**过滤——它们可内联预览
    # （此前 .png/.jpg 被排除，导致文件树里根本看不到图片，自然无从预览）。
    ignored_exts = {
        ".pyc",
        ".pyo",
        ".egg",
        ".whl",
        ".mp4",
        ".mp3",
        ".wav",
        ".ogg",
        ".flac",
        ".avi",
        ".mov",
        ".pdf",
        ".zip",
        ".tar",
        ".gz",
        ".tar.gz",
        ".7z",
        ".rar",
        ".exe",
        ".dll",
        ".so",
        ".dylib",
        ".bin",
        ".woff",
        ".woff2",
        ".ttf",
        ".otf",
    }

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
                # 预览类型：前端据此决定「可点击预览」与图标（image/text/binary）
                item["kind"] = classify_file(name)[0]
                try:
                    item["size"] = entry.stat().st_size
                except OSError:
                    item["size"] = 0
                if ext in ignored_exts:
                    continue
            items.append(item)
    except PermissionError:
        return JSONResponse({"ok": False, "error": "无权限访问"}, status_code=403)

    return JSONResponse(
        {
            "ok": True,
            "path": req_path or "/",
            "abs_path": str(target.resolve()),
            "items": items,
            "parent": str(_Path(req_path).parent) if req_path else None,
        }
    )


async def handle_file_read(request):
    """GET /api/file?path=... — 读取单个文件内容（按类型分流）。

    返回体始终含 ``kind``（``image``/``text``/``binary``）与 ``mime``，
    前端据此选渲染方式：

    - ``text``：返回 ``content`` 文本（超 :data:`_TEXT_READ_MAX` 截断）
    - ``image``：**不**当文本读（二进制读出来是乱码），只回 ``raw_url``
      指向 :func:`handle_file_raw` 做内联渲染
    - ``binary``：只回元信息与提示，不返回内容

    ``format_hint`` 给出建议的格式化方式（json/markdown/code/none），
    由前端决定是否套用——服务端不猜用户的展示偏好。
    """

    file_path = request.query_params.get("path", "")
    if not file_path:
        return JSONResponse({"ok": False, "error": "需要 path 参数"}, status_code=400)

    target, err = _resolve_in_root(file_path)
    if err is not None:
        return err
    if not target.is_file():
        return JSONResponse({"ok": False, "error": "文件不存在"}, status_code=404)

    try:
        size = target.stat().st_size
    except OSError:
        size = 0

    kind, mime = classify_file(target.name)
    ext = target.suffix.lower()
    base = {"ok": True, "path": file_path, "name": target.name, "ext": ext, "size": size, "kind": kind, "mime": mime}

    if kind == "image":
        # 图片不做文本读取：交给 /api/file/raw 内联（正确 MIME，浏览器直接渲染）
        base["raw_url"] = "/api/file/raw?path=" + urllib.parse.quote(file_path)
        base["format_hint"] = "none"
        return JSONResponse(base)

    if kind == "binary":
        base["format_hint"] = "none"
        base["message"] = f"二进制文件（{ext or '无扩展名'}），不支持预览"
        return JSONResponse(base)

    # 文本：限流读取（超大文件截断而非拒绝——用户仍想看一眼开头）
    truncated = size > _TEXT_READ_MAX
    try:
        with open(target, encoding="utf-8", errors="replace") as fh:
            content = fh.read(_TEXT_READ_MAX)
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

    base["content"] = content
    base["truncated"] = truncated
    if truncated:
        base["message"] = f"文件较大（{size} 字节），仅显示前 {_TEXT_READ_MAX} 字节"
    base["format_hint"] = "json" if ext in (".json", ".jsonl", ".ndjson") else ("markdown" if ext in (".md", ".markdown") else "code")
    return JSONResponse(base)


async def handle_file_raw(request):
    """GET /api/file/raw?path=... — 原样字节返回（图片内联预览用）。

    与 ``/api/file`` 的区别同 ``/v1/preview`` vs ``/v1/download``：这里给
    **正确 MIME + inline**，可直接作 ``<img src>``；``/api/file`` 是 JSON
    文本接口，拿来当 img 源只会得到一坨 JSON。

    安全：复用 :func:`_resolve_in_root`（防遍历，限定启动目录内）；
    SVG 额外加 sandbox CSP —— SVG 可内嵌 ``<script>``，同源内联即存储型 XSS。
    """

    file_path = request.query_params.get("path", "")
    if not file_path:
        return JSONResponse({"ok": False, "error": "需要 path 参数"}, status_code=400)

    target, err = _resolve_in_root(file_path)
    if err is not None:
        return err
    if not target.is_file():
        return JSONResponse({"ok": False, "error": "文件不存在"}, status_code=404)

    ext = target.suffix.lower()
    media = _IMAGE_MIME.get(ext)
    if not media:
        return JSONResponse(
            {"ok": False, "error": f"不是可内联预览的类型: {ext or '(无扩展名)'}", "previewable": sorted(_IMAGE_MIME)},
            status_code=415,
        )

    headers = {
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "private, max-age=60",
    }
    if ext == ".svg":
        headers["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'; sandbox"
    return FileResponse(str(target), media_type=media, headers=headers)
