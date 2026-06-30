
"""
Tea Agent HTTP API Server -- unified REST API + Web UI.

Provides:
  - OpenAI-compatible chat completions (+ streaming) at /v1/*
  - Web chat UI at / (server/static/index.html)
  - Swagger API docs at /docs
  - SSE streaming chat at /api/chat
  - Model hot-switch, config management
  - Session/topic/memory/task management

Quick start:
    python -m tea_agent.server
    tea-agent-api
    tea-agent-web  (compat)
"""

import asyncio
import json
import logging
import os
import threading
import time
import uuid
from typing import Optional, List
from pathlib import Path

logger = logging.getLogger("api_server")

try:
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse, StreamingResponse, HTMLResponse, FileResponse
    from starlette.routing import Route, Mount
    from starlette.requests import Request
    from starlette.staticfiles import StaticFiles
except ImportError:
    raise ImportError("pip install starlette uvicorn")

from tea_agent.agent import Agent
from tea_agent.store import Storage, get_storage

__version__ = "0.2.0"

# 全局：max_iter 确认请求存储（confirm_id -> {session, timestamp}）
# 当工具轮达到上限时，后端等待前端用户确认后继续或终止
_max_iter_pending = {}  # type: dict[str, dict]

def get_server_version() -> str:
    return __version__


class APIServer:
    """HTTP API Server for Tea Agent -- REST API + Web UI + OpenAI compatible."""

    def __init__(self, api_key: Optional[str] = None,
                 config_path: Optional[str] = None):
        self._api_key = (api_key or os.environ.get("TEA_API_KEY", "")).strip()
        self._config_path = config_path
        self._agent: Optional[Agent] = None
        self._start_time = time.time()
        self._lock = threading.Lock()
        self._storage: Optional[Storage] = None

    def _get_storage(self) -> Storage:
        """Get Storage directly (lightweight, no Agent dependency)."""
        if self._storage is None:
            self._storage = get_storage()
        return self._storage
        self._start_time = time.time()

    def get_agent(self) -> Agent:
        if self._agent is None:
            self._agent = Agent(mode="full",
                                config_path=self._config_path)
            logger.info(f"Agent initialized")
        return self._agent

    def reset_agent(self):
        with self._lock:
            if self._agent:
                try: self._agent.sess.close()
                except Exception: logger.exception("operation failed")
            self._agent = None
            logger.info("Agent reset")

    def health(self) -> dict:
        return {"status": "ok", "version": __version__,
                "uptime_seconds": round(time.time() - self._start_time, 1),
                "agent_initialized": self._agent is not None}

    def chat_completion(self, model: str, messages: List[dict],
                        stream: bool = False, temperature: float = 0.7,
                        max_tokens: Optional[int] = None,
                        topic_id: str = "") -> dict:
        """Non-streaming chat completion. Returns OpenAI-compatible dict."""
        agent = self.get_agent()
        user_msg = self._extract_user_message(messages)
        with self._lock:
            if topic_id:
                agent.current_topic_id = topic_id
                agent.load_topic_history(topic_id)
            elif not agent.current_topic_id:
                agent.current_topic_id = agent.db.create_topic("API 会话")
            collected = []
            def cb(text: str):
                if text and not text.startswith("["): collected.append(text)
            ai_msg, used_tools = agent.sess.chat_stream(
                user_msg, callback=cb,
                topic_id=topic_id or agent.current_topic_id)
            # 保存对话到数据库
            agent._post_chat_pipeline(ai_msg, used_tools, user_msg,
                                       topic_id or agent.current_topic_id)
            full = "".join(collected) or ai_msg
        return {
            "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model,
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": full},
                "finish_reason": "stop"
            }],
            "usage": {"total_tokens": 0, "prompt_tokens": 0, "completion_tokens": 0},
            "tools_used": used_tools or []
        }


    async def chat_completion_stream(self, model, messages,
                                      temperature=0.7,
                                      max_tokens=None, topic_id=""):
        """Streaming chat completion. Returns async generator for SSE."""
        agent = self.get_agent()
        user_msg = self._extract_user_message(messages)
        queue = asyncio.Queue()
        event_loop = asyncio.get_running_loop()
        def _put(event):
            try: event_loop.call_soon_threadsafe(
                lambda: queue.put_nowait(event))
            except Exception: logger.exception("operation failed")
        def stream_cb(text):
            if text.startswith("["): return
            _put({"type": "content", "text": text})
        thread = threading.Thread(
            target=self._run_stream,
            args=(agent, user_msg, topic_id, stream_cb, _put),
            daemon=True)
        thread.start()
        async for event in self._generate_sse(queue, model):
            yield event

    def _run_stream(self, agent, user_msg, topic_id, stream_cb, put):
        try:
            with self._lock:
                if topic_id:
                    agent.current_topic_id = topic_id
                    agent.load_topic_history(topic_id)
                elif not agent.current_topic_id:
                    agent.current_topic_id = agent.db.create_topic(
                        "API 流式会话")
                ai_msg, used_tools = agent.sess.chat_stream(
                    user_msg, callback=stream_cb,
                    topic_id=topic_id or agent.current_topic_id)
                # 保存对话到数据库
                agent._post_chat_pipeline(ai_msg, used_tools, user_msg,
                                           topic_id or agent.current_topic_id)
                put({"type": "done", "ai_msg": ai_msg,
                     "tools_used": used_tools or []})
        except Exception as e:
            put({"type": "error", "error": str(e)})
    async def _generate_sse(self, queue, model):
        cid = "chatcmpl-" + uuid.uuid4().hex[:12]
        now = int(time.time())
        init_data = {"id": cid, "object": "chat.completion.chunk", "created": now, "model": model,
                     "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]}
        NL2 = "\n\n"
        yield "data: " + json.dumps(init_data) + NL2
        while True:
            event = await queue.get()
            t = event["type"]
            if t == "content":
                data = {"id": cid, "object": "chat.completion.chunk", "created": now, "model": model,
                        "choices": [{"index": 0, "delta": {"content": event["text"]}, "finish_reason": None}]}
                yield "data: " + json.dumps(data) + NL2
            elif t == "tool_call":
                yield "data: " + json.dumps({"type": "tool_call", "tool_calls": event["tool_calls"]}) + NL2
            elif t == "reasoning":
                yield "data: " + json.dumps({"type": "reasoning", "content": event["text"]}) + NL2
            elif t == "done":
                done_data = {"id": cid, "object": "chat.completion.chunk", "created": now, "model": model,
                            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                            "tools_used": event.get("tools_used", [])}
                yield "data: " + json.dumps(done_data) + NL2
                yield "data: [DONE]" + NL2
                break
            elif t == "error":
                yield "data: " + json.dumps({"error": event["error"]}) + NL2
                yield "data: [DONE]" + NL2
                break

    @staticmethod
    def _extract_user_message(messages):
        """提取用户消息，支持纯文本和多模态内容（包含图片）。
        
        返回格式：
        - 纯文本消息：返回字符串
        - 多模态消息：返回字典 {"text": str, "images": list}
        """
        for msg in reversed(messages):
            if msg.get("role") == "user":
                content = msg.get("content", "")
                if isinstance(content, list):
                    texts = []
                    images = []
                    for part in content:
                        if isinstance(part, dict):
                            if part.get("type") == "text":
                                texts.append(part.get("text", ""))
                            elif part.get("type") == "image_url":
                                # 提取图片URL或base64数据
                                image_url = part.get("image_url", {})
                                if isinstance(image_url, dict):
                                    url = image_url.get("url", "")
                                    if url:
                                        images.append(url)
                                elif isinstance(image_url, str):
                                    images.append(image_url)
                    text = "\n".join(texts)
                    if images:
                        return {"text": text, "images": images}
                    return text
                return content
        return ""


    # ═══════════════════════════════════════════════════════════════
    #  Web UI SSE Chat (rich events: think/tool/status/done)
    # ═══════════════════════════════════════════════════════════════

    def chat_stream_sse(self, msg, queue: "asyncio.Queue", topic_id: str = "",
                         event_loop=None):
        """Run chat in a thread, pushing SSE events to an asyncio queue.

        Args:
            msg: 纯文本字符串，或包含 text/images 的字典
        """
        agent = self.get_agent()

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
            if text.startswith("[TOOL_START:"):
                tool_name = text[len("[TOOL_START:"):-1] if text.endswith("]") else text[len("[TOOL_START:"):]
                _put({"type": "tool_start", "name": tool_name})
                _tool_active = True
            elif text.startswith("[TOOL_ARG:"):
                _arg_raw = text[len("[TOOL_ARG:"):-1] if text.endswith("]") else text[len("[TOOL_ARG:"):]
                _put({"type": "tool_args", "args": _arg_raw})
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
                    "session": agent.sess,
                    "timestamp": time.time(),
                }
                _put({"type": "max_iter_confirm", "confirm_id": confirm_id, "text": status_msg})
            elif status_msg.startswith("\u23f3"):
                pass
            else:
                _put({"type": "status", "text": status_msg})

        try:
            with self._lock:
                # If no topic_id is provided, always create a new topic
                if not topic_id:
                    tid = agent.db.create_topic("Web Session")
                    agent.current_topic_id = tid
                    agent.load_topic_history(tid)
                elif not agent.current_topic_id:
                    # topic_id provided but agent has no active topic
                    agent.current_topic_id = topic_id
                    agent.load_topic_history(topic_id)

                ai_msg, used_tools = agent.sess.chat_stream(
                    msg,
                    callback=stream_cb,
                    topic_id=topic_id or agent.current_topic_id,
                    on_status=status_cb,
                )
                # 保存对话到数据库
                agent._post_chat_pipeline(ai_msg, used_tools, msg,
                                           topic_id or agent.current_topic_id)

                usage = agent.sess._last_usage or {}
                _put({
                    "type": "done",
                    "ai_msg": ai_msg,
                    "used_tools": used_tools,
                    "topic_id": topic_id or agent.current_topic_id,
                    "usage": {
                        "total_tokens": usage.get("total_tokens", 0),
                        "prompt_tokens": usage.get("prompt_tokens", 0),
                        "completion_tokens": usage.get("completion_tokens", 0),
                    },
                })
        except Exception as e:
            logger.exception("Chat stream error")
            _put({"type": "error", "error": str(e)})
    # ── Topic conversations (Web UI format) ──

    def get_topic_conversations(self, topic_id: str, limit: int = 0) -> list:
        """Get all conversation rounds for a topic (Web UI format)."""
        convs = self._get_storage().get_conversations(topic_id, limit=limit, include_rounds=True)
        result = []
        for c in convs:
            result.append({
                "id": c["id"],
                "topic_id": c["topic_id"],
                "user_msg": c["user_msg"],
                "ai_msg": c["ai_msg"],
                "is_func_calling": c.get("is_func_calling", 0),
                "stamp": str(c.get("stamp", "")),
            })
        return result

    def get_topic_info(self, topic_id: str):
        """Get topic detail (Web UI format)."""
        s = self._get_storage()
        topic = s.get_topic(topic_id)
        if not topic:
            return None
        tokens = s.get_topic_tokens(topic_id)
        return {
            "id": topic["topic_id"],
            "title": topic.get("title", ""),
            "created": str(topic.get("create_stamp", "")),
            "updated": str(topic.get("last_update_stamp", "")),
            "total_tokens": (tokens or {}).get("total_tokens", 0),
            "conversation_count": (tokens or {}).get("conversation_count", 0),
        }


    def list_tools(self):
        agent = self.get_agent()
        tools = []
        for name, meta in agent.toolkit.meta_map.items():
            fn = meta.get("function", {})
            tools.append({"name": fn.get("name", name),
                          "description": fn.get("description", ""),
                          "parameters": fn.get("parameters", {})})
        return tools

    def run_tool(self, tool_name, arguments):
        agent = self.get_agent()
        func = agent.toolkit.func_map.get(tool_name)
        if not func:
            func = agent.toolkit.func_map.get(f"toolkit_{tool_name}")
        if not func:
            return {"ok": False, "error": f"Tool '{tool_name}' not found"}
        try:
            result = func(**arguments)
            return {"ok": True, "tool": tool_name, "result": str(result)}
        except Exception as e:
            return {"ok": False, "error": str(e), "tool": tool_name}

    def list_sessions(self, limit=20):
        # Use storage directly, avoid heavy Agent init if possible
        topics = self._get_storage().list_topics()
        result = []
        for t in topics[:limit]:
            tid = t["topic_id"]
            tokens = self._get_storage().get_topic_tokens(tid)
            result.append({"id": tid, "title": t.get("title","") or tid[:8],
                           "created": str(t.get("create_stamp",""))[:19],
                           "updated": str(t.get("last_update_stamp",""))[:19],
                           "total_tokens": (tokens or {}).get("total_tokens",0)})
        return result

    def create_session(self, title="API 会话"):
        tid = self._get_storage().create_topic(title)
        # Also try to set it on agent if agent is already initialized
        if self._agent is not None:
            self._agent.current_topic_id = tid
        return {"id": tid, "title": title}

    def get_session(self, topic_id):
        s = self._get_storage()
        topic = s.get_topic(topic_id)
        if not topic: return None
        tokens = s.get_topic_tokens(topic_id)
        convs = s.get_conversations(topic_id, limit=0, include_rounds=True)
        return {"id": topic["topic_id"], "title": topic.get("title",""),
                "created": str(topic.get("create_stamp","")),
                "updated": str(topic.get("last_update_stamp","")),
                "total_tokens": (tokens or {}).get("total_tokens",0),
                "conversations": [{"id": c["id"], "user": c["user_msg"],
                    "assistant": c["ai_msg"], "stamp": c["stamp"]}
                    for c in convs]}

    def delete_session(self, topic_id):
        try:
            self._get_storage().delete_topic(topic_id)
            return True
        except Exception:
            return False


    def get_session_messages(self, topic_id: str, limit: int = 50) -> list:
        convs = self._get_storage().get_conversations(topic_id, limit=limit, include_rounds=True)
        result = []
        for c in convs:
            result.append({"id": c["id"], "role": "user", "content": c["user_msg"],
                           "stamp": str(c.get("stamp",""))[:26]})
            result.append({"id": c["id"], "role": "assistant", "content": c["ai_msg"],
                           "stamp": str(c.get("stamp",""))[:26]})
        return result

    @staticmethod
    def _sanitize(obj):
        "Remove non-JSON-serializable fields (e.g. bytes)."
        if isinstance(obj, dict):
            return {k: APIServer._sanitize(v) for k, v in obj.items()
                    if not isinstance(v, (bytes, bytearray))}
        if isinstance(obj, list):
            return [APIServer._sanitize(item) for item in obj]
        return obj

    def list_memories(self, limit=50):
        mems = self._get_storage().get_active_memories(limit=limit)
        return self._sanitize(mems)

    def create_memory(self, content: str, category: str = "general", priority: int = 2):
        mem_id = self._get_storage().add_memory(content, category=category, priority=priority, tags="", importance=3)
        return {"id": mem_id, "content": content, "category": category}

    def delete_memory(self, mem_id):
        # Soft delete via storage
        try:
            from tea_agent.memory import MemoryManager
            mm = MemoryManager()
            mm.delete(mem_id)
            return True
        except Exception:
            return False

    def list_tasks(self):
        return self._get_storage().list_tasks()

    def create_task(self, name: str, command: str, schedule: str):
        task_id = self._get_storage().add_task(name, command, schedule)
        return {"id": task_id, "name": name, "command": command, "schedule": schedule}

    def delete_task(self, task_id: str):
        return self._get_storage().delete_task(task_id)

    def search(self, query: str, limit: int = 20) -> dict:
        s = self._get_storage()
        convs = self._sanitize(s.search_conversations(query, limit=limit))
        mems = self._sanitize(s.search_memories(query, limit=limit))
        return {"conversations": convs, "memories": mems}

    def screenshot_region(self, x: int, y: int, w: int, h: int) -> dict:
        """Capture a screen region and return base64 image data.

        Args:
            x: Left coordinate
            y: Top coordinate
            w: Width
            h: Height
        Returns:
            dict: {ok: bool, image_base64?: str, error?: str}
        """
        from tea_agent.toolkit.toolkit_screenshot import toolkit_screenshot
        import base64
        import tempfile
        import os

        try:
            # 截取区域截图
            tmp_path = os.path.join(tempfile.gettempdir(), "screenshot_region.png")
            result = toolkit_screenshot(action="region", region=f"{x},{y},{w},{h}", output=tmp_path)

            if not result.get("success"):
                return {"ok": False, "error": result.get("error", "截图失败")}

            # 读取图片并转为 base64
            with open(result["path"], "rb") as f:
                img_data = f.read()
            b64_str = base64.b64encode(img_data).decode("utf-8")
            data_url = f"data:image/png;base64,{b64_str}"

            return {
                "ok": True,
                "image_base64": data_url,
                "path": result["path"],
                "size": result.get("size", 0),
                "method": result.get("method", ""),
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # ═══════════════════════════════════════════════════════════════
    #  Model Hot-Switch & Config Management
    # ═══════════════════════════════════════════════════════════════

    def switch_model(self, api_key: str, api_url: str, model_name: str,
                     cheap_api_key: str = "", cheap_api_url: str = "",
                     cheap_model_name: str = "",
                     temperature: float = None, max_tokens: int = None,
                     top_p: float = None, max_context_tokens: int = None,
                     options: dict = None,
                     cheap_temperature: float = None, cheap_max_tokens: int = None,
                     cheap_top_p: float = None, cheap_max_context_tokens: int = None,
                     cheap_options: dict = None):
        """Hot-switch models (main + optional cheap) at runtime. Preserves current topic."""
        topic_id = self._agent.current_topic_id if self._agent else ""

        with self._lock:
            if self._agent and self._agent.sess:
                self._agent.sess.close()

            agent = self.get_agent()
            cfg = agent._cfg
            cfg.main_model.api_key = api_key
            cfg.main_model.api_url = api_url
            cfg.main_model.model_name = model_name
            if temperature is not None:
                cfg.main_model.temperature = temperature
            if max_tokens is not None:
                cfg.main_model.max_tokens = max_tokens
            if top_p is not None:
                cfg.main_model.top_p = top_p
            if max_context_tokens is not None:
                cfg.main_model.max_context_tokens = max_context_tokens
            if options is not None:
                cfg.main_model.options = options

            if cheap_api_url and cheap_model_name:
                cfg.cheap_model.api_key = cheap_api_key or api_key
                cfg.cheap_model.api_url = cheap_api_url
                cfg.cheap_model.model_name = cheap_model_name
                if cheap_temperature is not None:
                    cfg.cheap_model.temperature = cheap_temperature
                if cheap_max_tokens is not None:
                    cfg.cheap_model.max_tokens = cheap_max_tokens
                if cheap_top_p is not None:
                    cfg.cheap_model.top_p = cheap_top_p
                if cheap_max_context_tokens is not None:
                    cfg.cheap_model.max_context_tokens = cheap_max_context_tokens
                if cheap_options is not None:
                    cfg.cheap_model.options = cheap_options

            agent._init_session()

            if topic_id:
                agent.current_topic_id = topic_id
                agent.load_topic_history(topic_id)

        logger.info(
            "Model switch: main=" + model_name + " @ " + api_url
            + (", cheap=" + cheap_model_name if cheap_model_name else "")
        )

    def switch_config(self, config_path):
        """Load a full config file and switch both main and cheap models."""
        if not os.path.exists(config_path):
            return {"ok": False, "error": "Config not found: " + config_path}
        from tea_agent.config import load_config, AgentConfig
        new_cfg = load_config(config_path)
        if not new_cfg.main_model.is_configured:
            return {"ok": False, "error": "config main_model not complete: " + config_path}
        cm = new_cfg.main_model
        cc = new_cfg.cheap_model
        self.switch_model(
            cm.api_key, cm.api_url, cm.model_name,
            cheap_api_key=(cc.api_key or "") if cc else "",
            cheap_api_url=(cc.api_url or "") if cc else "",
            cheap_model_name=(cc.model_name or "") if cc else "",
            temperature=cm.temperature,
            max_tokens=cm.max_tokens,
            top_p=cm.top_p,
            max_context_tokens=cm.max_context_tokens,
            options=cm.options,
            cheap_temperature=cc.temperature if cc else None,
            cheap_max_tokens=cc.max_tokens if cc else None,
            cheap_top_p=cc.top_p if cc else None,
            cheap_max_context_tokens=cc.max_context_tokens if cc else None,
            cheap_options=cc.options if cc else None,
        )
        # 同步运行时参数到运行中的 agent
        agent = self._agent
        if agent and hasattr(agent, '_cfg'):
            cfg = agent._cfg
            for key in AgentConfig._RUNTIME_CONFIG_KEYS:
                setattr(cfg, key, getattr(new_cfg, key))
            cfg.embedding = new_cfg.embedding
            cfg.mode_params = new_cfg.mode_params
        self._config_path = config_path
        return {"ok": True, "config_path": config_path}

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
        lines.append("  api_key: " + main_api_key)
        lines.append("  api_url: " + main_api_url)
        lines.append('  model_name: "' + main_model_name + '"')
        lines.append("  temperature: 0.65")
        lines.append("  max_tokens: 131072")
        lines.append("  options:")
        lines.append("    supports_vision: false")
        lines.append("    supports_reasoning: true")
        lines.append("")

        if cheap_model_name and cheap_api_url:
            lines.append("cheap_model:")
            lines.append("  api_key: " + (cheap_api_key or main_api_key))
            lines.append("  api_url: " + cheap_api_url)
            lines.append('  model_name: "' + cheap_model_name + '"')
            lines.append("  max_tokens: 8192")
            lines.append("  options:")
            lines.append("    supports_vision: false")
            lines.append("    supports_reasoning: true")
            lines.append("")

        lines.append("embedding_model:")
        lines.append("  api_url: https://api.siliconflow.cn")
        lines.append("  model_name: Qwen/Qwen3-Embedding-4B")
        lines.append("  api_key: " + main_api_key)
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
        logger.info("Created config: " + str(fpath))
        return str(fpath)

    # ── Enhanced config info (with cheap model) ──

    def get_config_info(self):
        """Get config with cheap model info (Web UI format)."""
        agent = self.get_agent()
        cfg = agent.config
        main = cfg.main_model
        key = main.api_key
        masked_key = (key[:6] + "..." + key[-4:]) if len(key) > 12 else "***"
        main_info = {
            "model": main.model_name,
            "api_url": main.api_url,
            "api_key_masked": masked_key,
            "temperature": main.temperature,
            "max_tokens": main.max_tokens,
            "top_p": main.top_p,
            "max_context_tokens": main.max_context_tokens,
            "options": main.options or {},
        }
        cheap = cfg.cheap_model
        cheap_info = None
        if cheap and cheap.model_name:
            cheap_key = cheap.api_key or ""
            cheap_masked = (cheap_key[:6] + "..." + cheap_key[-4:]) if len(cheap_key) > 12 else "***"
            cheap_info = {
                "model": cheap.model_name,
                "api_url": cheap.api_url or "",
                "api_key_masked": cheap_masked,
                "temperature": cheap.temperature,
                "max_tokens": cheap.max_tokens,
                "top_p": cheap.top_p,
                "max_context_tokens": cheap.max_context_tokens,
                "options": cheap.options or {},
            }
        return {
            "model": main_info["model"],
            "api_url": main_info["api_url"],
            "api_key_masked": main_info["api_key_masked"],
            "temperature": main_info["temperature"],
            "max_tokens": main_info["max_tokens"],
            "top_p": main_info["top_p"],
            "max_context_tokens": main_info["max_context_tokens"],
            "options": main_info["options"],
            "cheap_model": cheap_info,
            "keep_turns": cfg.keep_turns,
            "max_iterations": cfg.max_iterations,
            "max_history": cfg.max_history,
            "enable_thinking": cfg.enable_thinking,
            "max_tool_output": cfg.max_tool_output,
            "max_assistant_content": cfg.max_assistant_content,
            "extra_iterations_on_continue": cfg.extra_iterations_on_continue,
            "memory_extraction_threshold": cfg.memory_extraction_threshold,
            "memory_dedup_threshold": cfg.memory_dedup_threshold,
            "chat_page_size": cfg.chat_page_size,
            "history_l2_max": cfg.history_l2_max,
            "history_l3_batch": cfg.history_l3_batch,
            "tools_count": len(agent.toolkit.func_map),
            "server_version": __version__,
        }


    def get_config(self):
        return self.get_config_info()

    def update_config(self, updates: dict):
        """Update runtime config fields on the fly. Only whitelisted keys are accepted.
        
        Args:
            updates: dict of config key → value pairs (e.g. {"max_iterations": 100})
        
        Returns:
            dict: {ok: bool, updated: list, errors: list}
        """
        from tea_agent.config import AgentConfig
        agent = self.get_agent()
        cfg = agent._cfg
        whitelist = AgentConfig._RUNTIME_CONFIG_KEYS
        type_map = getattr(AgentConfig, '_CONFIG_TYPES', {})
        updated = []
        errors = []
        for key, value in updates.items():
            if key not in whitelist:
                errors.append(f"{key}: not a runtime-configurable key")
                continue
            try:
                expected_type = type_map.get(key, str)
                if expected_type == bool:
                    value = bool(value)
                else:
                    value = expected_type(value)
                setattr(cfg, key, value)
                updated.append(key)
                logger.info(f"Config updated: {key} = {value}")
            except (ValueError, TypeError) as e:
                errors.append(f"{key}: {e}")
        return {"ok": len(errors) == 0, "updated": updated, "errors": errors}



_server_instance: Optional[APIServer] = None

def get_server() -> APIServer:
    global _server_instance
    if _server_instance is None:
        _server_instance = APIServer()
    return _server_instance


# ── Route Handlers ──

async def handle_health(request):
    return JSONResponse(get_server().health())

async def handle_chat_completions(request):
    body = await request.json()
    model = body.get("model", "default")
    messages = body.get("messages", [])
    stream = body.get("stream", False)
    temperature = body.get("temperature", 0.7)
    max_tokens = body.get("max_tokens")
    topic_id = body.get("topic_id", "")
    if not messages:
        return JSONResponse({"error": "messages required"}, status_code=400)
    server = get_server()
    if stream:
        gen = server.chat_completion_stream(
            model, messages, temperature, max_tokens, topic_id)
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
        return JSONResponse(get_server().create_session(title), status_code=201)
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
                        "topic_id": {"type": "string"}},
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


async def handle_get_session_messages(request):
    server = get_server()
    topic_id = request.path_params.get("topic_id", "")
    limit = int(request.query_params.get("limit", 50))
    msgs = server.get_session_messages(topic_id, limit=limit)
    return JSONResponse({"data": msgs, "total": len(msgs)})

async def _safe_handle(handler, request):
    """Wrapper to catch agent initialization errors."""
    try:
        return await handler(request)
    except ValueError as e:
        if "配置不完整" in str(e):
            return JSONResponse(
                {"error": "Agent not configured", "detail": str(e),
                 "hint": "Run 'tea-agent --setup' or configure ~/.tea_agent/config.yaml"},
                status_code=503)
        return JSONResponse({"error": str(e)}, status_code=500)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

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

async def handle_search(request):
    server = get_server()
    query = request.query_params.get("q", "")
    limit = int(request.query_params.get("limit", 20))
    if not query:
        return JSONResponse({"error": "query required"}, status_code=400)
    results = server.search(query, limit=limit)
    return JSONResponse(results)

async def handle_export_pdf(request):
    from tea_agent.toolkit.toolkit_export_last_pdf import export_topic_pdf
    body = await request.json()
    topic_id = body.get("topic_id", "")
    if not topic_id:
        return JSONResponse({"error": "topic_id required"}, status_code=400)
    output = body.get("output")
    try:
        result = await asyncio.to_thread(export_topic_pdf, topic_id, output or None)
        return JSONResponse({"success": True, "path": result or output})
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


async def handle_screenshot_region(request):
    """POST /api/screenshot/region — capture a screen region and return base64.

    Body: {"x": int, "y": int, "w": int, "h": int}
    """
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


# ================================================================
#  Web UI API Route Handlers (SSE chat, model switch, etc.)
# ================================================================

async def handle_web_chat(request):
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
        return JSONResponse({"error": "message required"}, status_code=400)

    # 将 base64 图片保存到临时文件
    image_paths = []
    if images_b64:
        import base64 as b64mod
        upload_dir = Path("uploads")
        upload_dir.mkdir(exist_ok=True)
        for idx, img_b64 in enumerate(images_b64):
            try:
                # 支持 "data:image/png;base64,XXXX" 和纯 base64 两种格式
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
                logger.warning(f"图片 base64 解码失败: {e}")

    # 构建消息：如果有图片则用字典格式，否则纯文本
    if image_paths:
        msg_payload = {"text": message, "images": image_paths}
    else:
        msg_payload = message

    server = get_server()
    queue: asyncio.Queue = asyncio.Queue()

    async def event_stream():
        loop = asyncio.get_running_loop()

        thread = threading.Thread(
            target=server.chat_stream_sse,
            args=(msg_payload, queue, topic_id, loop),
            daemon=True,
        )
        thread.start()

        while True:
            event = await queue.get()
            yield "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"
            if event.get("type") in ("done", "error"):
                break

    return StreamingResponse(event_stream(), media_type="text/event-stream")


async def handle_chat_continue(request):
    """POST /api/chat/continue — 用户确认 max_iter 后继续或终止"""
    body = await request.json()
    confirm_id = body.get("confirm_id", "")
    decision = body.get("continue", True)  # True=继续, False=终止

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


async def handle_web_topic_info(request):
    """GET /api/topic/{topic_id}"""
    topic_id = request.path_params.get("topic_id", "")
    if not topic_id:
        return JSONResponse({"error": "topic_id required"}, status_code=400)
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
    configs = server.list_config_files()
    # 获取当前活跃配置路径和文件名
    active_config_path = ""
    active_config_filename = ""
    if server._agent and server._agent._config_path:
        active_config_path = server._agent._config_path
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
    if not filename: errors.append("filename required")
    if not main_model_name: errors.append("main_model_name required")
    if not main_api_url: errors.append("main_api_url required")
    if not main_api_key: errors.append("main_api_key required")
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

    # Parse extra model parameters
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
    if not api_key: errors.append("api_key required")
    if not api_url: errors.append("api_url required")
    if not model_name: errors.append("model_name required")
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


async def handle_web_root(request):
    """GET / - serve Web UI index.html."""
    static_dir = Path(__file__).parent / "static"
    index_path = static_dir / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path), media_type="text/html")
    return HTMLResponse("<h1>Tea Agent Server</h1><p>Web UI not found. Visit <a href='/docs'>/docs</a> for API.</p>")


def create_app(api_key: Optional[str] = None,
               config_path: Optional[str] = None):
    """Create the Starlette application for the unified server."""
    global _server_instance
    _server_instance = APIServer(api_key=api_key, config_path=config_path)

    static_dir = str(Path(__file__).parent / "static")

    routes = [
        # Web UI root
        Route("/", endpoint=handle_web_root),

        # Web UI API
        Route("/api/chat", endpoint=handle_web_chat, methods=["POST"]),
        Route("/api/chat/continue", endpoint=handle_chat_continue, methods=["POST"]),
        Route("/api/screenshot/region", endpoint=handle_screenshot_region, methods=["POST"]),
        Route("/api/new_topic", endpoint=handle_web_new_topic, methods=["POST"]),
        Route("/api/sessions", endpoint=handle_web_sessions),
        Route("/api/topic/{topic_id:str}", endpoint=handle_web_topic_info),
        Route("/api/topic/{topic_id:str}/conversations", endpoint=handle_web_topic_conversations),
        Route("/api/tools", endpoint=handle_web_tools),
        Route("/api/config", endpoint=handle_web_config),
        Route("/api/config", endpoint=handle_web_update_config, methods=["PUT"]),
        Route("/api/configs", endpoint=handle_web_list_configs),
        Route("/api/config/create", endpoint=handle_web_create_config, methods=["POST"]),
        Route("/api/model", endpoint=handle_web_model_info),
        Route("/api/model", endpoint=handle_web_model_switch, methods=["POST"]),
        Route("/api/model/config", endpoint=handle_web_model_config, methods=["POST"]),

        # OpenAI-compatible REST API
        Route("/health", endpoint=handle_health),
        Route("/v1/chat/completions", endpoint=handle_chat_completions, methods=["POST"]),
        Route("/v1/models", endpoint=handle_list_models),
        Route("/v1/tools", endpoint=handle_list_tools),
        Route("/v1/tools/{name:str}/run", endpoint=handle_run_tool, methods=["POST"]),
        Route("/v1/sessions", endpoint=handle_list_sessions),
        Route("/v1/sessions", endpoint=handle_create_session, methods=["POST"]),
        Route("/v1/sessions/{topic_id:str}", endpoint=handle_get_session),
        Route("/v1/sessions/{topic_id:str}", endpoint=handle_delete_session, methods=["DELETE"]),
        Route("/v1/sessions/{topic_id:str}/messages", endpoint=handle_get_session_messages),
        Route("/v1/config", endpoint=handle_get_config),
        Route("/v1/config/switch", endpoint=handle_switch_config, methods=["POST"]),
        Route("/v1/memory", endpoint=handle_list_memory),
        Route("/v1/memory", endpoint=handle_create_memory, methods=["POST"]),
        Route("/v1/memory/{mem_id:str}", endpoint=handle_delete_memory, methods=["DELETE"]),
        Route("/v1/tasks", endpoint=handle_list_tasks),
        Route("/v1/tasks", endpoint=handle_create_task, methods=["POST"]),
        Route("/v1/tasks/{task_id:str}", endpoint=handle_delete_task, methods=["DELETE"]),
        Route("/v1/search", endpoint=handle_search),
        Route("/v1/export/pdf", endpoint=handle_export_pdf, methods=["POST"]),
        Route("/v1/upload", endpoint=handle_upload, methods=["POST"]),

        # Swagger / OpenAPI
        Route("/docs", endpoint=handle_docs),
        Route("/openapi.json", endpoint=handle_openapi),

        # Static files (CSS/JS for Web UI)
        Mount("/static", app=StaticFiles(directory=static_dir), name="static"),
    ]

    logger.info(f"API Server initialized | v{__version__}")
    app = Starlette(debug=False, routes=routes)

    # Mount gui2 frontend as fallback (if exists)
    frontend_dir = Path(__file__).parent.parent / "gui2" / "frontend"
    if frontend_dir.exists():
        logger.info(f"Frontend (gui2): {frontend_dir}")

    return app


def run_server(host: str = "127.0.0.1", port: int = 8080,
               api_key: Optional[str] = None,
               config_path: Optional[str] = None):
    """Run the API server."""
    try:
        import uvicorn
    except ImportError:
        raise ImportError("pip install uvicorn")

    app = create_app(api_key=api_key, config_path=config_path)
    if api_key:
        logger.info(f"API Key auth enabled")
    logger.info(f"API Server starting: http://{host}:{port}")
    logger.info(f"API Docs: http://{host}:{port}/docs")
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    run_server()


# ── CLI Entry ──

def main():
    """CLI entry: tea-agent-api / tea-agent-web (unified)"""
    import argparse
    parser = argparse.ArgumentParser(description="Tea Agent Unified Server (API + Web UI)")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Listen address")
    parser.add_argument("--port", type=int, default=8080, help="Listen port")
    parser.add_argument("--api-key", type=str, default="", help="API key for auth")
    parser.add_argument("--config", type=str, default=None, help="Config file path")
    args = parser.parse_args()
    run_server(host=args.host, port=args.port,
               api_key=args.api_key or None,
               config_path=args.config)

if __name__ == "__main__":
    main()
