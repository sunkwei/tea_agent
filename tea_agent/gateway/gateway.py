"""Tea Agent Gateway 守护进程 — 后台常驻 + WebSocket + Canvas 宿主"""

import asyncio, json, logging, os, threading, time, uuid
from pathlib import Path
from typing import Optional, Dict

logger = logging.getLogger("gateway")

try:
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse, FileResponse, StreamingResponse
    from starlette.routing import Route, Mount, WebSocketRoute
    from starlette.websockets import WebSocket, WebSocketDisconnect
    from starlette.staticfiles import StaticFiles
    import uvicorn
except ImportError as e:
    raise ImportError("pip install starlette uvicorn") from e

from tea_agent.server.server import APIServer

DEFAULT_PORT = 18789
DEFAULT_HOST = "127.0.0.1"
CANVAS_ROOT = Path(__file__).parent.parent.parent / "gateway" / "canvas"
WEBUI_ROOT = Path(__file__).parent.parent.parent / "gateway" / "webui"

_STATUS = {"running": False, "pid": None, "port": None, "started_at": None}
class GatewayDaemon:
    """Gateway 守护进程 — 统一控制面"""

    def __init__(self, host=DEFAULT_HOST, port=DEFAULT_PORT, config_path=None):
        self.host = host
        self.port = port
        self.config_path = config_path
        self._api_server = None
        self._server = None
        self._loop = None
        self._thread = None
        self._ws_clients = {}
        self._ws_lock = threading.Lock()
        self._start_time = None

    @property
    def api_server(self):
        if self._api_server is None:
            self._api_server = APIServer(api_key="", config_path=self.config_path)
        return self._api_server

    def _build_app(self):
        """构建 Starlette 应用实例（内部使用）"""
        routes = [
            Route("/health", endpoint=self._handle_health),
            Route("/api/tools", endpoint=self._handle_list_tools),
            Route("/api/chat", endpoint=self._handle_chat, methods=["POST"]),
            Route("/api/sessions", endpoint=self._handle_list_sessions),
            Route("/api/sessions/create", endpoint=self._handle_create_session, methods=["POST"]),
            Route("/api/canvas/push", endpoint=self._handle_canvas_push, methods=["POST"]),
            Route("/api/canvas/snapshot", endpoint=self._handle_canvas_snapshot),
            Mount("/canvas", app=StaticFiles(directory=str(CANVAS_ROOT), html=True), name="canvas"),
            Mount("/css", app=StaticFiles(directory=str(WEBUI_ROOT / "css")), name="css"),
            Mount("/js", app=StaticFiles(directory=str(WEBUI_ROOT / "js")), name="js"),
            WebSocketRoute("/ws", endpoint=self._handle_ws),
            Route("/a2ui/push", endpoint=self._handle_a2ui_push, methods=["POST"]),
            Route("/", endpoint=self._handle_root),
        ]
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def lifespan(app):
            await self._on_startup()
            yield
            await self._on_shutdown()

        return Starlette(routes=routes, lifespan=lifespan)

    @property
    def starlette_app(self):
        """兼容属性 — 返回 Starlette 应用实例"""
        return self._build_app()# ── 生命周期 ──
    def start(self, daemon=True):
        """启动 Gateway"""
        if _STATUS["running"]:
            return {"ok": False, "error": "已在运行", "port": _STATUS["port"]}
        self._start_time = time.time()
        _STATUS.update({"running": True, "pid": os.getpid(), "port": self.port, "started_at": self._start_time})
        # 构建 Starlette 应用实例（属性不能传给 uvicorn，直接构建）
        app = self._build_app()
        config = uvicorn.Config(app=app, host=self.host, port=self.port, log_level="info", reload=False, workers=1, access_log=False)
        self._server = uvicorn.Server(config)
        if daemon:
            self._thread = threading.Thread(target=self._server.run, daemon=True, name="Gateway")
            self._thread.start()
            logger.info(f"Gateway 已启动 → http://{self.host}:{self.port}")
            return {"ok": True, "port": self.port, "url": f"http://{self.host}:{self.port}", "canvas": f"http://{self.host}:{self.port}/canvas"}
        else:
            logger.info(f"Gateway 前台启动 → http://{self.host}:{self.port}")
            self._server.run()
            return {"ok": True, "port": self.port}

    def stop(self):
        """停止 Gateway"""
        if not _STATUS["running"]:
            return {"ok": False, "error": "未运行"}
        if self._server:
            self._server.should_exit = True
        _STATUS["running"] = False
        _STATUS["pid"] = None
        logger.info("Gateway 已停止")
        return {"ok": True}

    @staticmethod
    def status():
        result = dict(_STATUS)
        if result["started_at"]:
            result["uptime"] = round(time.time() - result["started_at"], 1)
        return result# ── Starlette 事件 ──
    async def _on_startup(self):
        logger.info(f"Gateway 就绪 → http://{self.host}:{self.port}")
        CANVAS_ROOT.mkdir(parents=True, exist_ok=True)
        WEBUI_ROOT.mkdir(parents=True, exist_ok=True)

    async def _on_shutdown(self):
        logger.info("Gateway 关闭中...")
        for ws_id, ws in self._ws_clients.items():
            try: await ws.close(code=1001)
            except Exception: pass
        self._ws_clients.clear()

    async def _handle_root(self, request):
        """根路径 → WebUI 主界面"""
        index = WEBUI_ROOT / "index.html"
        if WEBUI_ROOT.exists() and index.exists():
            return FileResponse(str(index))
        # 降级到 Canvas
        canvas_index = CANVAS_ROOT / "index.html"
        if canvas_index.exists():
            return FileResponse(str(canvas_index))
        return JSONResponse({"service": "Tea Agent Gateway", "version": "0.1.0"})

    async def _handle_health(self, request):
        return JSONResponse({"ok": True, "service": "Tea Agent Gateway", "version": "0.1.0", "uptime": round(time.time() - self._start_time, 1) if self._start_time else 0, "ws_clients": len(self._ws_clients)})# ── REST 处理器 ──
    async def _handle_list_tools(self, request):
        tools = self.api_server.list_tools()
        return JSONResponse({"ok": True, "tools": tools, "count": len(tools)})

    async def _handle_chat(self, request):
        body = await request.json()
        messages = body.get("messages", [])
        stream = body.get("stream", False)
        topic_id = body.get("topic_id", "")
        if stream:
            return StreamingResponse(self.api_server.chat_completion_stream("tea-agent", messages, topic_id=topic_id), media_type="text/event-stream")
        result = self.api_server.chat_completion("tea-agent", messages, topic_id=topic_id)
        return JSONResponse(result)

    async def _handle_list_sessions(self, request):
        return JSONResponse({"ok": True, "sessions": self.api_server.list_sessions()})

    async def _handle_create_session(self, request):
        body = await request.json()
        title = body.get("title", "Gateway 会话")
        result = self.api_server.create_session(title)
        return JSONResponse({"ok": True, **result})# ── WebSocket ──
    async def _handle_ws(self, ws: WebSocket):
        await ws.accept()
        ws_id = uuid.uuid4().hex[:8]
        with self._ws_lock:
            self._ws_clients[ws_id] = ws
        logger.info(f"WS 客户端连接: {ws_id}")
        try:
            while True:
                data = await ws.receive_text()
                try:
                    msg = json.loads(data)
                    t = msg.get("type", "")
                    if t == "ping":
                        await ws.send_text(json.dumps({"type": "pong"}))
                    elif t == "chat":
                        result = self.api_server.chat_completion("tea-agent", msg.get("messages", []))
                        await ws.send_text(json.dumps({"type": "chat_response", **result}))
                    elif t == "canvas_push":
                        with self._ws_lock:
                            for cid, cws in self._ws_clients.items():
                                try: await cws.send_text(json.dumps({"type": "canvas_update", "path": msg.get("path","")}))
                                except Exception: pass
                except json.JSONDecodeError:
                    await ws.send_text(json.dumps({"type": "error", "error": "无效 JSON"}))
        except WebSocketDisconnect:
            logger.info(f"WS 断开: {ws_id}")
        except Exception as e:
            logger.warning(f"WS 错误 ({ws_id}): {e}")
        finally:
            with self._ws_lock:
                self._ws_clients.pop(ws_id, None)# ── Canvas API ──
    async def _handle_canvas_push(self, request):
        """推送内容到 Canvas"""
        body = await request.json()
        path = body.get("path", "index.html")
        content = body.get("content", "")
        target = CANVAS_ROOT / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        with self._ws_lock:
            for cid, ws in self._ws_clients.items():
                try: await ws.send_text(json.dumps({"type": "canvas_update", "path": path}))
                except Exception: pass
        return JSONResponse({"ok": True, "path": str(target), "url": f"/canvas/{path}"})

    async def _handle_canvas_snapshot(self, request):
        return JSONResponse({"ok": True, "note": "快照功能待实现"})

    async def _handle_a2ui_push(self, request):
        """A2UI 协议 — Agent 用 JSON 描述 UI"""
        body = await request.json()
        surface = body.get("surface", "main")
        components = body.get("components", [])
        html = self._a2ui_to_html(components)
        target = CANVAS_ROOT / f"_a2ui_{surface}.html"
        full = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8"><title>A2UI {surface}</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box;}}
body{{font-family:system-ui,sans-serif;padding:2rem;background:#0d1117;color:#c9d1d9;}}
h1{{color:#58a6ff;}} h2{{color:#79c0ff;}}
.card{{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:1.5rem;margin:1rem 0;}}
.badge{{display:inline-block;padding:.2rem .8rem;border-radius:999px;font-size:.8rem;background:#1f6feb;color:#fff;}}
pre{{background:#161b22;padding:1rem;border-radius:6px;overflow-x:auto;}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:1rem;}}
</style></head><body><div id="root">{html}</div>
<script>
const ws=new WebSocket('ws://'+location.host+'/ws');
ws.onmessage=e=>{{const m=JSON.parse(e.data);if(m.type==='canvas_update')location.reload()}};
</script></body></html>'''
        target.write_text(full, encoding="utf-8")
        return JSONResponse({"ok": True, "surface": surface, "components": len(components), "url": f"/canvas/_a2ui_{surface}.html"})    @staticmethod
    def _a2ui_to_html(components):
        """A2UI 组件 → HTML"""
        parts = []
        for comp in components:
            cid = comp.get("id", "")
            ctype = comp.get("component", {})
            if not isinstance(ctype, dict): continue
            for key, val in ctype.items():
                if key == "Text":
                    text = val.get("text", {}).get("literalString", "") if isinstance(val.get("text"), dict) else val.get("text", "")
                    hint = val.get("usageHint", "body")
                    if hint == "h1": parts.append(f'<h1 id="{cid}">{text}</h1>')
                    elif hint == "h2": parts.append(f'<h2 id="{cid}">{text}</h2>')
                    else: parts.append(f'<p id="{cid}">{text}</p>')
                elif key == "Column":
                    children = val.get("children", {}).get("explicitList", [])
                    inner = "".join(f'<div class="col-item">{ch}</div>' for ch in children)
                    parts.append(f'<div id="{cid}" class="column">{inner}</div>')
                elif key == "Card":
                    parts.append(f'<div id="{cid}" class="card">{val.get("content","")}</div>')
                elif key == "Badge":
                    parts.append(f'<span id="{cid}" class="badge">{val.get("text","")}</span>')
                elif key == "Code":
                    parts.append(f'<pre id="{cid}">{val.get("code","")}</pre>')
                elif key == "Divider":
                    parts.append(f'<hr id="{cid}" style="border-color:#30363d;margin:1rem 0">')
                else:
                    parts.append(f'<div id="{cid}">{str(val)[:200]}</div>')
        return "\n".join(parts)