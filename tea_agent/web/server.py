import asyncio
import json
import logging
import threading
from pathlib import Path
from typing import Optional

logger = logging.getLogger("web")

# 全局：max_iter 确认请求存储
_max_iter_pending = {}  # type: dict[str, dict]

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

    def chat_stream_sse(self, msg, queue: asyncio.Queue, topic_id: str = "",
                         event_loop=None):
        """Run chat in a thread, pushing SSE events to an asyncio queue.

        Args:
            msg: 纯文本字符串，或包含 text/images 的字典
        """
        sess = self.agent.sess

        def _put(event: dict):
            if event_loop is None:
                return
            try:
                event_loop.call_soon_threadsafe(lambda: queue.put_nowait(event))
            except Exception:
                logger.warning("Failed to push SSE event")

        _thinking_active = False
        _tool_active = False

        def stream_cb(text: str):
            nonlocal _thinking_active, _tool_active
            # 工具调用标记
            if text.startswith("[TOOL_START:"):
                # [TOOL_START:toolkit_exec]
                tool_name = text[len("[TOOL_START:"):-1] if text.endswith("]") else text[len("[TOOL_START:"):]
                _put({"type": "tool_start", "name": tool_name})
                _tool_active = True
            elif text.startswith("[TOOL_ARG:"):
                _arg = text[len("[TOOL_ARG:"):-1] if text.endswith("]") else text[len("[TOOL_ARG:"):]
                _put({"type": "tool_args", "args": _arg})
            elif text.startswith("[TOOL_RESULT:"):
                _res = text[len("[TOOL_RESULT:"):-1] if text.endswith("]") else text[len("[TOOL_RESULT:"):]
                _put({"type": "tool_result", "result": _res})
            elif text == "[TOOL_DONE]":
                if _tool_active:
                    _put({"type": "tool_done"})
                    _tool_active = False
            elif text == "[THINK_DONE]":
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
                # 生成唯一确认ID，存储session引用，供前端确认后继续/终止
                import uuid as _uuid_mod
                confirm_id = _uuid_mod.uuid4().hex[:12]
                _max_iter_pending[confirm_id] = {
                    "session": sess,
                    "timestamp": time.time(),
                }
                _put({"type": "max_iter_confirm", "confirm_id": confirm_id, "text": status_msg})
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
                # 保存对话到数据库
                self.agent._post_chat_pipeline(ai_msg, used_tools, msg,
                                                topic_id or self.agent.current_topic_id)

                usage = sess._last_usage or {}
                _put({                    "type": "done",
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

    def get_topic_conversations(self, topic_id: str, limit: int = 0) -> list:
        """获取指定主题下的所有历史对话轮次。"""
        convs = self.db.get_conversations(topic_id, limit=limit, include_rounds=True)
        result = []
        for c in convs:
            result.append({
                "id": c["id"],
                "topic_id": c["topic_id"],
                "user_msg": c["user_msg"],
                "ai_msg": c["ai_msg"],
                "is_func_calling": c["is_func_calling"],
                "stamp": c["stamp"],
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
        cheap = cfg.cheap_model
        cheap_info = None
        if cheap and cheap.model_name:
            cheap_key = cheap.api_key or ""
            cheap_masked = (cheap_key[:6] + "..." + cheap_key[-4:]) if len(cheap_key) > 12 else "***"
            cheap_info = {
                "model": cheap.model_name,
                "api_url": cheap.api_url or "",
                "api_key_masked": cheap_masked,
            }
        return {
            "model": cfg.main_model.model_name,
            "api_url": cfg.main_model.api_url,
            "api_key_masked": masked_key,
            "cheap_model": cheap_info,
            "keep_turns": cfg.keep_turns,
            "max_iterations": cfg.max_iterations,
            "enable_thinking": cfg.enable_thinking,
            "tools_count": len(self.toolkit.func_map),
        }

    def switch_model(self, api_key: str, api_url: str, model_name: str,
                     cheap_api_key: str = "", cheap_api_url: str = "",
                     cheap_model_name: str = ""):
        """Hot-switch models (main + optional cheap) at runtime. Preserves current topic."""
        topic_id = self.agent.current_topic_id

        with self._lock:
            if self.agent.sess:
                self.agent.sess.close()

            cfg = self.agent._cfg
            cfg.main_model.api_key = api_key
            cfg.main_model.api_url = api_url
            cfg.main_model.model_name = model_name

            if cheap_api_url and cheap_model_name:
                cfg.cheap_model.api_key = cheap_api_key or api_key
                cfg.cheap_model.api_url = cheap_api_url
                cfg.cheap_model.model_name = cheap_model_name

            self.agent._init_session()

            if topic_id:
                self.agent.current_topic_id = topic_id
                self.agent.load_topic_history(topic_id)

        logger.info(
            f"模型切换: main={model_name} @ {api_url}"
            + (f", cheap={cheap_model_name}" if cheap_model_name else "")
        )

    def switch_config(self, config_path: str):
        """Load a full config file and switch all configuration items.

        Previously only updated main_model and cheap_model API params,
        missing temperature, max_tokens, top_p, embedding, paths,
        max_history, max_iterations, keep_turns, etc.
        Now replaces the entire _cfg object and re-initializes the session.
        """
        from tea_agent.config import load_config, set_active_config_path
        new_cfg = load_config(config_path)
        if not new_cfg.main_model.is_configured:
            raise ValueError(f"配置文件 {config_path} 的 main_model 配置不完整")

        topic_id = self.agent.current_topic_id

        with self._lock:
            if self.agent.sess:
                self.agent.sess.close()

            # Replace entire config object (not just model params)
            self.agent._cfg = new_cfg
            self.agent._config_path = config_path
            set_active_config_path(config_path)

            # Re-initialize session with new config
            self.agent._init_session()

            if topic_id:
                self.agent.current_topic_id = topic_id
                self.agent.load_topic_history(topic_id)

        logger.info(
            f"配置切换: {Path(config_path).name} | "
            f"主模型: {new_cfg.main_model.model_name}"
            + (f" | 摘要: {new_cfg.cheap_model.model_name}" if new_cfg.cheap_model.model_name else "")
        )

    # ── 配置文件管理 ──

    @staticmethod
    def _get_configs_dir():
        """Get the ~/.tea_agent/ directory path."""
        return Path.home() / ".tea_agent"

    def list_config_files(self):
        """Scan ~/.tea_agent/*.yaml and return parsed config summaries."""
        configs_dir = self._get_configs_dir()
        if not configs_dir.exists():
            return []
        from tea_agent.config import load_config
        results = []
        for fpath in sorted(configs_dir.glob("*.yaml")):
            try:
                cfg = load_config(str(fpath))
                main_m = cfg.main_model
                cheap_m = cfg.cheap_model
                results.append({
                    "filename": fpath.name,
                    "path": str(fpath),
                    "main_model": {
                        "model_name": main_m.model_name or "",
                        "api_url": main_m.api_url or "",
                        "api_key_masked": (
                            (main_m.api_key[:6] + "..." + main_m.api_key[-4:])
                            if len(main_m.api_key) > 12 else "***"
                        ) if main_m.api_key else "",
                    },
                    "cheap_model": {
                        "model_name": cheap_m.model_name or "",
                        "api_url": cheap_m.api_url or "",
                        "api_key_masked": (
                            (cheap_m.api_key[:6] + "..." + cheap_m.api_key[-4:])
                            if len(cheap_m.api_key) > 12 else "***"
                        ) if cheap_m and cheap_m.api_key else "",
                    } if cheap_m and cheap_m.model_name else None,
                })
            except Exception as e:
                results.append({
                    "filename": fpath.name,
                    "path": str(fpath),
                    "error": str(e),
                })
        return results

    def create_config_file(self, filename: str,
                           main_model_name: str, main_api_url: str, main_api_key: str,
                           cheap_model_name: str = "", cheap_api_url: str = "",
                           cheap_api_key: str = ""):
        """Create a new config file in ~/.tea_agent/."""
        configs_dir = self._get_configs_dir()
        configs_dir.mkdir(parents=True, exist_ok=True)

        if not filename.endswith(".yaml"):
            filename += ".yaml"
        fpath = configs_dir / filename

        lines = []
        lines.append("main_model:")
        lines.append(f"  api_key: {main_api_key}")
        lines.append(f"  api_url: {main_api_url}")
        lines.append(f"  model_name: \"{main_model_name}\"")
        lines.append("  temperature: 0.65")
        lines.append("  max_tokens: 131072")
        lines.append("  options:")
        lines.append("    supports_vision: false")
        lines.append("    supports_reasoning: true")
        lines.append("")

        if cheap_model_name and cheap_api_url:
            lines.append("cheap_model:")
            lines.append(f"  api_key: {cheap_api_key or main_api_key}")
            lines.append(f"  api_url: {cheap_api_url}")
            lines.append(f"  model_name: \"{cheap_model_name}\"")
            lines.append("  max_tokens: 8192")
            lines.append("  options:")
            lines.append("    supports_vision: false")
            lines.append("    supports_reasoning: true")
            lines.append("")

        lines.append("embedding_model:")
        lines.append("  api_url: https://api.siliconflow.cn")
        lines.append("  model_name: Qwen/Qwen3-Embedding-4B")
        lines.append(f"  api_key: {main_api_key}")
        lines.append("  dimension: 2560")
        lines.append("")

        lines.append("max_history: 10")
        lines.append("max_iterations: 100")
        lines.append("enable_thinking: true")
        lines.append("keep_turns: 5")
        lines.append("max_tool_output: 128000")
        lines.append("max_assistant_content: 128000")
        lines.append("extra_iterations_on_continue: 25")
        lines.append("memory_extraction_threshold: 2")
        lines.append("memory_dedup_threshold: 0.3")
        lines.append("chat_page_size: 50")
        lines.append("history_l2_max: 30")
        lines.append("history_l3_batch: 10")

        content = "\n".join(lines) + "\n"
        fpath.write_text(content, encoding="utf-8")
        logger.info(f"创建配置文件: {fpath}")
        return str(fpath)


_web_agent: Optional[WebAgent] = None


def get_agent() -> WebAgent:
    global _web_agent
    if _web_agent is None:
        _web_agent = WebAgent()
    return _web_agent


# ── Route Handlers ──


async def handle_chat(request):
    """POST /api/chat - SSE streaming chat for Web UI.

    支持纯文本和图片输入：
    - 纯文本: {"message": "hello", "topic_id": "..."}
    - 图片+文本: {"message": "hello", "images": ["data:image/png;base64,..."], "topic_id": "..."}
    """
    body = await request.json()
    message = body.get("message", "").strip()
    topic_id = body.get("topic_id", "")
    images_b64 = body.get("images", [])

    if not message and not images_b64:
        return JSONResponse({"error": "消息不能为空"}, status_code=400)

    # 将 base64 图片保存到临时文件
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
                import uuid as uuid_mod
                img_bytes = b64mod.b64decode(data)
                fname = f"upload_{uuid_mod.uuid4().hex[:8]}_{idx}{ext}"
                fpath = upload_dir / fname
                fpath.write_bytes(img_bytes)
                image_paths.append(str(fpath))
            except Exception as e:
                logger.warning(f"图片 base64 解码失败: {e}")

    # 构建消息：如果有图片则用字典格式，否则纯文本
    if image_paths:
        msg_payload = {"text": message, "images": image_paths}
    else:
        msg_payload = message

    agent = get_agent()
    queue: asyncio.Queue = asyncio.Queue()

    async def event_stream():
        loop = asyncio.get_running_loop()

        thread = threading.Thread(
            target=agent.chat_stream_sse,
            args=(msg_payload, queue, topic_id, loop),
            daemon=True,
        )
        thread.start()

        while True:
            event = await queue.get()
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            if event.get("type") in ("done", "error"):
                break

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
        logger.info(f"用户确认 max_iter: continue={decision}")
        return JSONResponse({"ok": True, "continue": decision})
    except Exception as e:
        logger.exception(f"处理 max_iter 确认失败: {e}")
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


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


async def handle_topic_conversations(request):
    """获取指定主题下的所有历史对话轮次。
    GET /api/topic/{topic_id}/conversations
    """
    agent = get_agent()
    topic_id = request.path_params.get("topic_id", "")
    if not topic_id:
        return JSONResponse({"error": "topic_id 不能为空"}, status_code=400)
    limit = int(request.query_params.get("limit", 0))
    try:
        convs = agent.get_topic_conversations(topic_id, limit=limit)
        return JSONResponse({"conversations": convs, "count": len(convs)})
    except Exception as e:
        logger.exception("获取主题对话失败")
        return JSONResponse({"error": str(e)}, status_code=500)


async def handle_topic_info(request):
    """获取指定主题的详细信息。
    GET /api/topic/{topic_id}
    """
    agent = get_agent()
    topic_id = request.path_params.get("topic_id", "")
    if not topic_id:
        return JSONResponse({"error": "topic_id 不能为空"}, status_code=400)
    try:
        topic = agent.agent.db.get_topic(topic_id)
        if not topic:
            return JSONResponse({"error": "主题不存在"}, status_code=404)
        tokens = agent.agent.db.get_topic_tokens(topic_id)
        return JSONResponse({
            "topic": {
                "id": topic["topic_id"],
                "title": topic.get("title", ""),
                "created": str(topic.get("create_stamp", "")),
                "updated": str(topic.get("last_update_stamp", "")),
                "total_tokens": tokens.get("total_tokens", 0),
                "conversation_count": tokens.get("conversation_count", 0),
            }
        })
    except Exception as e:
        logger.exception("获取主题信息失败")
        return JSONResponse({"error": str(e)}, status_code=500)


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

    # Cheap model (optional)
    cheap_api_key = (body.get("cheap_api_key") or "").strip()
    cheap_api_url = (body.get("cheap_api_url") or "").strip()
    cheap_model_name = (body.get("cheap_model_name") or "").strip()

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
        agent.switch_model(
            api_key, api_url, model_name,
            cheap_api_key=cheap_api_key,
            cheap_api_url=cheap_api_url,
            cheap_model_name=cheap_model_name,
        )
        masked_key = (api_key[:6] + "..." + api_key[-4:]) if len(api_key) > 12 else "***"
        result = {
            "ok": True, "model": model_name, "api_url": api_url,
            "api_key_masked": masked_key,
        }
        if cheap_model_name:
            cheap_masked = (cheap_api_key[:6] + "..." + cheap_api_key[-4:]) if len(cheap_api_key) > 12 else "***"
            result["cheap_model"] = {
                "model": cheap_model_name,
                "api_url": cheap_api_url,
                "api_key_masked": cheap_masked,
            }
        return JSONResponse(result)
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


async def handle_list_configs(request):
    """列出 ~/.tea_agent/ 下所有配置文件的模型信息"""
    agent = get_agent()
    configs = agent.list_config_files()
    active_config_path = agent.agent._config_path or ""
    # 如果活跃配置路径存在，提取文件名
    active_config_filename = ""
    if active_config_path:
        try:
            active_config_filename = Path(active_config_path).name
        except Exception:
            pass
    return JSONResponse({
        "configs": configs,
        "count": len(configs),
        "active_config_path": active_config_path,
        "active_config_filename": active_config_filename,
    })


async def handle_create_config(request):
    """创建新的配置文件"""
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
        errors.append("文件名不能为空")
    if not main_model_name:
        errors.append("主模型名称不能为空")
    if not main_api_url:
        errors.append("主模型 API URL 不能为空")
    if not main_api_key:
        errors.append("主模型 API Key 不能为空")
    if errors:
        return JSONResponse({"ok": False, "errors": errors}, status_code=400)

    if not filename.endswith(".yaml"):
        filename += ".yaml"

    agent = get_agent()
    try:
        fpath = agent.create_config_file(
            filename=filename,
            main_model_name=main_model_name,
            main_api_url=main_api_url,
            main_api_key=main_api_key,
            cheap_model_name=cheap_model_name,
            cheap_api_url=cheap_api_url,
            cheap_api_key=cheap_api_key,
        )
        # 自动切换到新配置
        agent.switch_config(fpath)
        return JSONResponse({
            "ok": True,
            "config_path": fpath,
            "filename": filename,
        })
    except Exception as e:
        logger.exception("创建配置文件失败")
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


# ── App Factory ──


def create_app(config_path: Optional[str] = None):
    """Create the Starlette application."""
    global _web_agent
    _web_agent = WebAgent(config_path)

    static_dir = str(Path(__file__).parent / "static")

    routes = [
        Route("/", endpoint=handle_root),
        Route("/api/chat", endpoint=handle_chat, methods=["POST"]),
        Route("/api/chat/continue", endpoint=handle_chat_continue, methods=["POST"]),
        Route("/api/new_topic", endpoint=handle_new_topic, methods=["POST"]),
        Route("/api/sessions", endpoint=handle_sessions),
        Route("/api/topic/{topic_id:str}/conversations", endpoint=handle_topic_conversations),
        Route("/api/topic/{topic_id:str}", endpoint=handle_topic_info),
        Route("/api/config", endpoint=handle_config),
        Route("/api/configs", endpoint=handle_list_configs),
        Route("/api/config/create", endpoint=handle_create_config, methods=["POST"]),
        Route("/api/tools", endpoint=handle_tools),
        Route("/api/model", endpoint=handle_model_info),
        Route("/api/model", endpoint=handle_model_switch, methods=["POST"]),
        Route("/api/model/config", endpoint=handle_model_config, methods=["POST"]),
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
