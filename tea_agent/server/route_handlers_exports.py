"""文件导出与截图：导出目录、图片持久化、PDF/Markdown 导出、上传、截图（区域/全屏/交互选区）。

由 route_handlers.py 拆分而来（逐字搬运，函数体未改写）。
"""

import asyncio
import contextlib
import json
import os
import tempfile
import time
import urllib.parse
from pathlib import Path

from starlette.responses import FileResponse, JSONResponse

from tea_agent.toolkit.toolkit_export_last_pdf import export_topic_markdown, export_topic_pdf

from ._compat import (
    get_server,
    logger,
)


def exports_dir() -> str:
    """文档发布目录（~/.tea_agent/exports/），供 /v1/download 服务。"""
    d = os.path.join(os.path.expanduser("~"), ".tea_agent", "exports")
    os.makedirs(d, exist_ok=True)
    return d


async def handle_file_download(request):
    """GET /v1/download/{filename} — 下载发布的文档（工具/接口文档等）。

    文件名必须为纯文件名（拒绝路径分隔符 / ../ 绝对路径），
    解析后必须位于 exports_dir 内。返回 Content-Disposition: attachment
    强制浏览器下载（而非预览）。
    """
    filename = request.path_params.get("filename", "")
    if not filename:
        return JSONResponse({"error": "filename required"}, status_code=400)
    # 安全校验：仅允许纯文件名（防路径遍历）
    if "/" in filename or "\\" in filename or ".." in filename or filename.startswith((".", "~")):
        return JSONResponse({"error": "非法文件名"}, status_code=400)
    try:
        target = (Path(exports_dir()) / filename).resolve()
        if not str(target).startswith(str(Path(exports_dir()).resolve())):
            return JSONResponse({"error": "非法路径"}, status_code=403)
        if not target.is_file():
            return JSONResponse({"error": "文件不存在"}, status_code=404)
        # RFC 5987：中文文件名用 filename*，ASCII 回退
        ascii_name = "".join(c if ord(c) < 128 else "_" for c in filename) or "download"
        disposition = f'attachment; filename="{ascii_name}"; filename*=UTF-8\'\'{urllib.parse.quote(filename)}'
        return FileResponse(str(target), media_type="application/octet-stream",
                            headers={"Content-Disposition": disposition})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def handle_export_pdf(request):
    """GET /v1/export/pdf/{topic_id} — export topic as PDF and download

    Query params:
        mode: 'latest' (default) = last conversation only, 'full_topic' = all conversations.
        filter: 'final' (default) = user + AI final only, 'full' = with reasoning.
    """
    topic_id = request.path_params.get("topic_id", "")
    if not topic_id:
        return JSONResponse({"error": "topic_id required"}, status_code=400)
    mode = request.query_params.get("mode", "latest")
    if mode not in ("latest", "full_topic"):
        mode = "latest"
    filter_mode = request.query_params.get("filter", "final")
    if filter_mode not in ("final", "full"):
        filter_mode = "final"
    try:
        server = get_server()
        db_path = server._get_storage().db_path
        # 导出文件缓冲到系统临时目录（Windows=%TEMP%，Linux/macOS=/tmp 或 /dev/shm），
        # 避免 server 以服务方式运行时 CWD 无写权限导致导出失败。
        # FileResponse 完成响应后会自动清理临时文件。
        _tmp_out = os.path.join(tempfile.gettempdir(), f"tea_export_{topic_id[:8]}_{int(time.time())}.pdf")
        result = await asyncio.to_thread(export_topic_pdf, topic_id,
            _tmp_out, db_path, mode=mode, filter_mode=filter_mode)
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
        ascii_name = "".join(c if ord(c) < 128 else '_' for c in filename) or "export.pdf"
        disposition = f'attachment; filename="{ascii_name}"; filename*=UTF-8''{urllib.parse.quote(filename)}'
        return FileResponse(result, media_type="application/pdf",
            headers={"Content-Disposition": disposition})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def handle_export_md(request):
    """GET /v1/export/md/{topic_id} — export topic as Markdown and download

    Query params:
        mode: 'latest' (default) = last conversation only, 'full_topic' = all conversations.
        filter: 'final' (default) = user + AI final only, 'full' = with reasoning.
    """
    topic_id = request.path_params.get("topic_id", "")
    if not topic_id:
        return JSONResponse({"error": "topic_id required"}, status_code=400)
    mode = request.query_params.get("mode", "latest")
    if mode not in ("latest", "full_topic"):
        mode = "latest"
    filter_mode = request.query_params.get("filter", "final")
    if filter_mode not in ("final", "full"):
        filter_mode = "final"
    try:
        server = get_server()
        db_path = server._get_storage().db_path
        # 导出文件缓冲到系统临时目录，避免 CWD 无写权限导致失败
        _tmp_out = os.path.join(tempfile.gettempdir(), f"tea_export_{topic_id[:8]}_{int(time.time())}.md")
        result = await asyncio.to_thread(
            export_topic_markdown, topic_id,
            _tmp_out, db_path, mode=mode, filter_mode=filter_mode)
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
        filename = safe_title + ".md"
        # RFC 5987: use filename* for non-ASCII, fallback ASCII for latin-1 clients
        ascii_name = "".join(c if ord(c) < 128 else '_' for c in filename) or "export.md"
        disposition = f'attachment; filename="{ascii_name}"; filename*=UTF-8''{urllib.parse.quote(filename)}'
        return FileResponse(result, media_type="text/markdown; charset=utf-8",
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
