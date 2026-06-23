import asyncio
import json
import logging
import threading
from pathlib import Path
from typing import Optional

logger = logging.getLogger("web")

try:
    from starlette.applications import Starlette
    from starlette.responses import HTMLResponse, JSONResponse, StreamingResponse, FileResponse
    from starlette.routing import Route, Mount
    from starlette.staticfiles import StaticFiles
except ImportError:
    raise ImportError(
        "需要安装 web 依赖: pip install starlette uvicorn"
    )

from tea_agent.agent import Agent


class WebAgent:
    """Wrapper for Agent class providing thread-safe streaming chat via SSE."""

    def __init__(self, config_path: Optional[str] = None):
        self.agent = Agent(
            mode="full",
            config_path=config_path,
        )
        self._lock = threading.Lock()

    @property
    def db(self):
        return self.agent.db

    @property
    def toolkit(self):
        return self.agent.toolkit

    @property
    def config(self):
        return self.agent.config

    def chat_stream_sse(self, msg: str, queue: asyncio.Queue, topic_id: str = "",
                         event_loop=None):
        """Run chat in a thread, pushing SSE events to an asyncio queue."""
        sess = self.agent.sess

        def _put(event: dict):
            if event_loop is None:
                return
            try:
                event_loop.call_soon_threadsafe(lambda: queue.put_nowait(event))
            except Exception:
                logger.warning("Failed to push SSE event")

        _thinking_active = False

        def stream_cb(text: str):
            nonlocal _thinking_active
            if text == "[THINK_DONE]":
                _put({"type": "think_done"})
                _thinking_active = False
            elif text.startswith("[THINK]"):
                if not _thinking_active:
                    _put({"type": "think_start"})
                    _thinking_active = True
                _put({"type": "think", "text": text[7:]})
            else:
                _put({"type": "token", "text": text})

        def status_cb(status_msg: str):
            if status_msg.startswith("!MAX_ITER:"):
                remaining = status_msg.split(":", 2)[1] if ":" in status_msg else "?"
                _put({"type": "status", "text": f"已达最大轮次，自动续命...（剩余 {remaining} 轮）"})
            elif status_msg.startswith("⏳"):
                pass
            else:
                _put({"type": "status", "text": status_msg})

        try:
            with self._lock:
                if not self.agent.current_topic_id:
                    topics = self.db.list_topics()
                    if topics:
                        tid = topics[0]["topic_id"]
                    else:
                        tid = self.db.create_topic("Web 会话")
                    self.agent.current_topic_id = tid
                    self.agent.load_topic_history(tid)

                ai_msg, used_tools = sess.chat_stream(
                    msg,
                    callback=stream_cb,
                    topic_id=topic_id or self.agent.current_topic_id,
                    on_status=status_cb,
                )

                usage = sess._last_usage or {}
                _put({
                    "type": "done",
                    "ai_msg": ai_msg,
                    "used_tools": used_tools,
                    "usage": {
                        "total_tokens": usage.get("total_tokens", 0),
                        "prompt_tokens": usage.get("prompt_tokens", 0),
                        "completion_tokens": usage.get("completion_tokens", 0),
                    },
                })
        except Exception as e:
            logger.exception("Chat stream error")
            _put({"type": "error", "error": str(e)})

    def get_sessions(self, limit: int = 20):
        topics = self.db.list_topics()
        result = []
        for t in topics[:limit]:
            tid = t["topic_id"]
            tokens = self.db.get_topic_tokens(tid)
            result.append({
                "id": tid,
                "title": t.get("title", "") or tid[:8],
                "created": str(t.get("create_stamp", ""))[:19],
                "updated": str(t.get("last_update_stamp", ""))[:19],
                "total_tokens": (tokens or {}).get("total_tokens", 0),
            })
        return result

    def get_tools(self):
        tools = []
        for name, meta in self.toolkit.meta_map.items():
            fn = meta.get("function", {})
            tools.append({
                "name": fn.get("name", name),
                "description": fn.get("description", ""),
                "parameters": fn.get("parameters", {}),
            })
        return tools

    def get_config_info(self):
        cfg = self.config
        key = cfg.main_model.api_key
        masked_key = (key[:6] + "..." + key[-4:]) if len(key) > 12 else "***"
        return {
            "model": cfg.main_model.model_name,
            "api_url": cfg.main_model.api_url,
            "api_key_masked": masked_key,
            "keep_turns": cfg.keep_turns,
            "max_iterations": cfg.max_iterations,
            "enable_thinking": cfg.enable_thinking,
            "tools_count": len(self.toolkit.func_map),
        }

    def switch_model(self, api_key: str, api_url: str, model_name: str):
        """Hot-switch the main model at runtime. Preserves current topic."""
        topic_id = self.agent.current_topic_id

        with self._lock:
            if self.agent.sess:
                self.agent.sess.close()

            cfg = self.agent._cfg
            cfg.main_model.api_key = api_key
            cfg.main_model.api_url = api_url
            cfg.main_model.model_name = model_name

            self.agent._init_session()

            if topic_id:
                self.agent.current_topic_id = topic_id
                self.agent.load_topic_history(topic_id)

        logger.info(
            f"模型切换: {model_name} @ {api_url}"
        )

    def switch_config(self, config_path: str):
        """Load model info from a config file and switch."""
        from tea_agent.config import load_config
        new_cfg = load_config(config_path)
        if not new_cfg.main_model.is_configured:
            raise ValueError(f"配置文件 {config_path} 的 main_model 配置不完整")
        cm = new_cfg.main_model
        self.switch_model(cm.api_key, cm.api_url, cm.model_name)


_web_agent: Optional[WebAgent] = None


def get_agent() -> WebAgent:
    global _web_agent
    if _web_agent is None:
        _web_agent = WebAgent()
    return _web_agent


PROVIDER_PRESETS = {
    "OpenAI": {"url": "https://api.openai.com/v1", "model": "gpt-4o"},
    "DeepSeek": {"url": "https://api.deepseek.com/v1", "model": "deepseek-chat"},
    "Anthropic": {"url": "https://api.anthropic.com/v1", "model": "claude-sonnet-4-20250514"},
    "GLM (智谱)": {"url": "https://open.bigmodel.cn/api/paas/v4", "model": "glm-5"},
    "Qwen (阿里)": {"url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "model": "qwen-plus"},
    "DeepSeek V4": {"url": "https://api.deepseek.com/v1", "model": "deepseek-v4"},
    "Kimi (月之暗面)": {"url": "https://api.moonshot.cn/v1", "model": "kimi-latest"},
    "Ollama (本地)": {"url": "http://localhost:11434/v1", "model": "qwen3.6"},
    "vLLM (本地)": {"url": "http://localhost:8000/v1", "model": "Qwen/Qwen2.5-14B"},
    "OpenRouter": {"url": "https://openrouter.ai/api/v1", "model": "openai/gpt-4o"},
}

# ── Route Handlers ──


async def handle_chat(request):
    body = await request.json()
    message = body.get("message", "").strip()
    topic_id = body.get("topic_id", "")

    if not message:
        return JSONResponse({"error": "消息不能为空"}, status_code=400)

    agent = get_agent()
    queue: asyncio.Queue = asyncio.Queue()

    async def event_stream():
        loop = asyncio.get_running_loop()

        thread = threading.Thread(
            target=agent.chat_stream_sse,
            args=(message, queue, topic_id, loop),
            daemon=True,
        )
        thread.start()

        while True:
            event = await queue.get()
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            if event.get("type") in ("done", "error"):
                break

    return StreamingResponse(event_stream(), media_type="text/event-stream")


async def handle_new_topic(request):
    body = await request.json()
    title = body.get("title", "Web 会话")
    title = title.strip() or "Web 会话"
    agent = get_agent()
    tid = agent.db.create_topic(title)
    return JSONResponse({"topic_id": tid, "title": title})


async def handle_sessions(request):
    agent = get_agent()
    limit = int(request.query_params.get("limit", 20))
    sessions = agent.get_sessions(limit)
    return JSONResponse({"sessions": sessions})


async def handle_config(request):
    agent = get_agent()
    return JSONResponse(agent.get_config_info())


async def handle_tools(request):
    agent = get_agent()
    tools = agent.get_tools()
    return JSONResponse({"tools": tools, "count": len(tools)})


async def handle_root(request):
    static_dir = Path(__file__).parent / "static"
    index_path = static_dir / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path), media_type="text/html")
    return HTMLResponse("<h1>Tea Agent Web</h1><p>前端页面未找到</p>")


async def handle_model_info(request):
    agent = get_agent()
    return JSONResponse(agent.get_config_info())


async def handle_model_switch(request):
    body = await request.json()
    agent = get_agent()

    current_key = agent.agent._cfg.main_model.api_key
    api_key = (body.get("api_key") or current_key or "").strip()
    api_url = (body.get("api_url") or "").strip()
    model_name = (body.get("model_name") or "").strip()

    errors = []
    if not api_key:
        errors.append("API Key 不能为空（当前未配置，请填写）")
    if not api_url:
        errors.append("API URL 不能为空")
    if not model_name:
        errors.append("模型名称不能为空")
    if errors:
        return JSONResponse({"ok": False, "errors": errors}, status_code=400)

    try:
        agent.switch_model(api_key, api_url, model_name)
        masked_key = (api_key[:6] + "..." + api_key[-4:]) if len(api_key) > 12 else "***"
        return JSONResponse({
            "ok": True, "model": model_name, "api_url": api_url,
            "api_key_masked": masked_key,
        })
    except Exception as e:
        logger.exception("模型切换失败")
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


async def handle_model_config(request):
    body = await request.json()
    config_path = (body.get("config_path") or "").strip()
    if not config_path:
        return JSONResponse({"error": "配置文件路径不能为空"}, status_code=400)

    agent = get_agent()
    try:
        agent.switch_config(config_path)
        return JSONResponse({"ok": True, "config_path": config_path})
    except Exception as e:
        logger.exception("配置文件加载失败")
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


async def handle_model_providers(request):
    return JSONResponse({"providers": PROVIDER_PRESETS})


# ── App Factory ──


def create_app(config_path: Optional[str] = None):
    """Create the Starlette application."""
    global _web_agent
    _web_agent = WebAgent(config_path)

    static_dir = str(Path(__file__).parent / "static")

    routes = [
        Route("/", endpoint=handle_root),
        Route("/api/chat", endpoint=handle_chat, methods=["POST"]),
        Route("/api/new_topic", endpoint=handle_new_topic, methods=["POST"]),
        Route("/api/sessions", endpoint=handle_sessions),
        Route("/api/config", endpoint=handle_config),
        Route("/api/tools", endpoint=handle_tools),
        Route("/api/model", endpoint=handle_model_info),
        Route("/api/model", endpoint=handle_model_switch, methods=["POST"]),
        Route("/api/model/config", endpoint=handle_model_config, methods=["POST"]),
        Route("/api/model/providers", endpoint=handle_model_providers),
        Mount("/static", app=StaticFiles(directory=static_dir), name="static"),
    ]

    cfg_info = _web_agent.get_config_info()
    logger.info(
        f"Web Agent 初始化完成 | 模型: {cfg_info['model']} | "
        f"工具: {cfg_info['tools_count']} 个"
    )

    app = Starlette(debug=True, routes=routes)
    return app


def run_server(
    config_path: Optional[str] = None,
    host: str = "127.0.0.1",
    port: int = 8080,
):
    """Run the web server."""
    try:
        import uvicorn
    except ImportError:
        raise ImportError("需要安装 uvicorn: pip install uvicorn")

    app = create_app(config_path)
    logger.info(f"启动 Web 服务: http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="info")
