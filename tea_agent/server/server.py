
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
"""

import asyncio
import json
import logging
import os
import threading
import time
import uuid
from pathlib import Path

logger = logging.getLogger("api_server")

try:
    from starlette.applications import Starlette
    from starlette.requests import Request
    from starlette.responses import JSONResponse, StreamingResponse
    from starlette.routing import Mount, Route
    from starlette.staticfiles import StaticFiles
except ImportError:
    raise ImportError("pip install starlette uvicorn")

import contextlib

from tea_agent.agent import Agent
from tea_agent.store import Storage, get_storage

__version__ = "0.2.0"

# 全局：max_iter 确认请求存储（confirm_id -> {session, timestamp}）
# 当工具轮达到上限时，后端等待前端用户确认后继续或终止
_max_iter_pending = {}  # type: dict[str, dict]

# 全局：活跃会话存储（topic_id -> session）
# 用于中断请求通过 topic_id 找到对应 session 并调用 interrupt()
_active_sessions: dict = {}

# ── 配置缓存（按路径缓存，减少重复 IO） ──
_config_cache: dict = {}

def _load_config_cached(config_path: str | None = None):
    """加载配置（带缓存）。"""
    key = config_path or "__default__"
    if key not in _config_cache:
        from tea_agent.config import load_config
        _config_cache[key] = load_config(config_path)
    return _config_cache[key]


def _create_session_from_cfg(cfg, toolkit, storage=None):
    """从配置对象创建 OnlineToolSession（不依赖 Agent）。"""
    from tea_agent.onlinesession import OnlineToolSession
    main_m = cfg.main_model
    cheap_m = cfg.cheap_model
    _options = getattr(main_m, 'options', {}) or {}
    supports_vision = _options.get('supports_vision', False) if isinstance(_options, dict) else False
    supports_reasoning = _options.get('supports_reasoning', True) if isinstance(_options, dict) else True

    return OnlineToolSession(
        toolkit=toolkit,
        api_key=main_m.api_key, api_url=main_m.api_url, model=main_m.model_name,
        max_history=cfg.max_history, max_iterations=cfg.max_iterations,
        keep_turns=cfg.keep_turns, max_tool_output=cfg.max_tool_output,
        max_assistant_content=cfg.max_assistant_content,
        max_context_tokens=main_m.max_context_tokens,
        extra_iterations_on_continue=cfg.extra_iterations_on_continue,
        memory_extraction_threshold=cfg.memory_extraction_threshold,
        storage=storage,
        cheap_api_key=cheap_m.api_key, cheap_api_url=cheap_m.api_url,
        cheap_model=cheap_m.model_name,
        enable_thinking=True,
        supports_vision=supports_vision, supports_reasoning=supports_reasoning,
    )


class _ChatAgentProxy:
    """轻量级 Agent 代理，供后处理流水线（do_async_summaries 等）使用。

    提供 _db 和 _sess 属性，让 agent_pipeline 函数无需依赖完整 Agent。
    """
    def __init__(self, storage, session):
        self._db = storage
        self._sess = session
        self._pending_cheap_tokens = {}


def _load_topic_history(storage, session, topic_id):
    """加载主题历史到会话（Agent.load_topic_history 的独立版本）。

    不依赖 Agent 实例，只需要 storage 和 session。
    """
    if not storage:
        return
    all_light = storage.get_conversations(topic_id, limit=-1, include_rounds=False)
    if all_light:
        recent = storage.get_conversations(topic_id, limit=1, include_rounds=True)
        if recent:
            all_light[-1] = recent[-1]
        level2 = storage.get_level2(topic_id)
        semantic = storage.get_semantic_summary(topic_id)
        tool_chain = storage.get_tool_chain_summary(topic_id)
        old_summary = storage.get_topic_summary(topic_id) or ""
        session.load_history(all_light, summary=old_summary,
                            level2=level2, semantic_summary=semantic,
                            tool_chain_summary=tool_chain)
    else:
        session.messages = [{"role": "system", "content": session.system_prompt}]
        session._history_summary = ""
        session._semantic_summary = ""
        session._tool_chain_summary = ""
        session._level2 = []


def _save_chat_result(storage, session, topic_id, user_msg, ai_msg, used_tools):
    """保存对话结果（Agent._post_chat_pipeline 的独立版本）。

    直接操作 storage 和 session，不依赖 Agent 实例。
    """
    if not storage:
        return
    user_text = user_msg if isinstance(user_msg, str) else (
        user_msg.get("text", "") if isinstance(user_msg, dict) else str(user_msg)
    )
    conv_id = storage.save_msg(topic_id, user_text, "", False)
    rounds = session._rounds_collector
    storage.update_msg_rounds(conversation_id=conv_id, ai_msg=ai_msg,
                               is_func_calling=used_tools,
                               rounds=rounds if rounds else None)
    # Token 统计
    usage = session._last_usage
    cheap_usage = session._last_cheap_usage
    if usage and usage.get("total_tokens", 0) > 0:
        kwargs = {"total_tokens": usage["total_tokens"],
                  "prompt_tokens": usage["prompt_tokens"],
                  "completion_tokens": usage["completion_tokens"]}
        if cheap_usage and cheap_usage.get("total_tokens", 0) > 0:
            kwargs["cheap_tokens"] = cheap_usage["total_tokens"]
            kwargs["cheap_prompt_tokens"] = cheap_usage["prompt_tokens"]
            kwargs["cheap_completion_tokens"] = cheap_usage["completion_tokens"]
        storage.add_topic_tokens(topic_id, **kwargs)
    # L2 推送
    l2_count, overflow_items, should_summarize = storage.push_to_level2(
        topic_id, user_text, ai_msg,
        rounds=rounds if rounds else None,
    )
    # 异步摘要（fire-and-forget）
    if overflow_items or should_summarize:
        from tea_agent.agent_pipeline import do_async_summaries
        proxy = _ChatAgentProxy(storage, session)
        threading.Thread(
            target=do_async_summaries,
            args=(proxy, topic_id, overflow_items, should_summarize),
            daemon=True,
        ).start()


def get_server_version() -> str:
    return __version__


class APIServer:
    """HTTP API Server for Tea Agent -- REST API + Web UI + OpenAI compatible.

    架构说明（v2.0 并发改造）：
    - 非流式操作（admin/config/tool-list）使用共享 Agent
    - 流式操作（SSE chat / streaming completions）使用每请求独立 Session
    - 共享 Toolkit + Storage 跨请求复用，Session 隔离
    - 支持不同 Web 实例通过 config_path 使用不同配置
    """

    def __init__(self, api_key: str | None = None,
                 config_path: str | None = None):
        self._api_key = (api_key or os.environ.get("TEA_API_KEY", "")).strip()
        self._config_path = config_path
        self._agent: Agent | None = None
        self._start_time = time.time()
        self._lock = threading.Lock()
        self._storage: Storage | None = None
        # 共享 Toolkit（跨请求复用，只读）
        self._toolkit: object | None = None

    # ═══════════════════════════════════════════════
    # 共享资源（Toolkit + Storage）
    # ═══════════════════════════════════════════════

    def _get_storage(self) -> Storage:
        """Get Storage directly (lightweight, no Agent dependency)."""
        if self._storage is None:
            self._storage = get_storage()
        return self._storage

    def _get_toolkit(self):
        """获取共享 Toolkit 实例（延迟初始化，只需一次）。"""
        if self._toolkit is None:
            from tea_agent import tlk
            cfg = _load_config_cached(self._config_path)
            tool_dir = str(Path(cfg.paths.toolkit_dir_abs))
            Path(tool_dir).mkdir(parents=True, exist_ok=True)
            self._toolkit = tlk.Toolkit(tool_dir)
            tlk.toolkit = self._toolkit
            logger.debug(f"Toolkit initialized | tools: {len(self._toolkit.func_map)} | dir: {tool_dir}")
        return self._toolkit

    # ═══════════════════════════════════════════════
    # 共享 Agent（非流式操作：admin/config/tool-list）
    # ═══════════════════════════════════════════════

    def get_agent(self) -> Agent:
        if self._agent is None:
            self._agent = Agent(mode="full",
                                config_path=self._config_path)
            logger.info("Agent initialized")
        return self._agent

    def reset_agent(self):
        with self._lock:
            if self._agent:
                try: self._agent.sess.close()
                except Exception:
                    logger.exception("operation failed")
            self._agent = None
            logger.debug("Agent reset")

    # ═══════════════════════════════════════════════
    # 每请求 Session 工厂（流式操作）
    # ═══════════════════════════════════════════════

    def create_session(self, config_path: str | None = None):
        """为流式请求创建独立的 OnlineToolSession。

        每个请求获得独立 Session，互不干扰，无需全局锁。
        支持指定 config_path 实现不同 Web 实例使用不同配置。

        Returns:
            (OnlineToolSession, Storage) 元组
        """
        cfg = _load_config_cached(config_path or self._config_path)
        storage = self._get_storage()
        toolkit = self._get_toolkit()
        session = _create_session_from_cfg(cfg, toolkit, storage)
        logger.debug(f"Session created | model={cfg.main_model.model_name} | config={config_path or '(default)'}")
        return session, storage

    def health(self) -> dict:
        return {"status": "ok", "version": __version__,
                "uptime_seconds": round(time.time() - self._start_time, 1),
                "agent_initialized": self._agent is not None}

    def chat_completion(self, model: str, messages: list[dict],
                        stream: bool = False, temperature: float = 0.7,
                        max_tokens: int | None = None,
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
                if text and not text.startswith("["):
                    collected.append(text)
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
                                      max_tokens=None, topic_id="",
                                      config_path=None):
        """Streaming chat completion. 每请求创建独立 Session，支持并发。

        Args:
            config_path: 可选，指定使用的配置文件路径
        """
        session, storage = self.create_session(config_path)
        user_msg = self._extract_user_message(messages)
        queue = asyncio.Queue()
        event_loop = asyncio.get_running_loop()
        def _put(event):
            try: event_loop.call_soon_threadsafe(
                lambda: queue.put_nowait(event))
            except Exception:
                logger.exception("operation failed")
        def stream_cb(text):
            if text.startswith("["):
                return
            _put({"type": "content", "text": text})
        thread = threading.Thread(
            target=self._run_stream,
            args=(session, storage, user_msg, topic_id, stream_cb, _put),
            daemon=True)
        thread.start()
        async for event in self._generate_sse(queue, model):
            yield event

    def _run_stream(self, session, storage, user_msg, topic_id, stream_cb, put):
        """在后台线程运行流式对话。使用独立 Session，无需全局锁。"""
        try:
            if topic_id:
                _load_topic_history(storage, session, topic_id)
            else:
                topic_id = storage.create_topic("API 流式会话")
            ai_msg, used_tools = session.chat_stream(
                user_msg, callback=stream_cb, topic_id=topic_id)
            _save_chat_result(storage, session, topic_id, user_msg, ai_msg, used_tools)
            put({"type": "done", "ai_msg": ai_msg,
                 "tools_used": used_tools or []})
        except Exception as e:
            logger.exception(f"Stream chat error: {e}")
            with contextlib.suppress(Exception):
                put({"type": "error", "error": f"{type(e).__name__}: {e}"})
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

    def chat_stream_sse(self, session, storage, msg,
                         queue: "asyncio.Queue", topic_id: str = "",
                         event_loop=None):
        """Run chat in a thread, pushing SSE events to an asyncio queue.

        使用独立 Session + Storage，无需全局锁，支持并发。

        Args:
            session: OnlineToolSession 实例（每请求独立）
            storage: Storage 实例（共享）
            msg: 纯文本字符串，或包含 text/images 的字典
        """
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
                import uuid as _uuid_mod
                confirm_id = _uuid_mod.uuid4().hex[:12]
                _max_iter_pending[confirm_id] = {
                    "session": session,
                    "timestamp": time.time(),
                }
                _put({"type": "max_iter_confirm", "confirm_id": confirm_id, "text": status_msg})
            elif status_msg.startswith("\u23f3"):
                pass
            else:
                _put({"type": "status", "text": status_msg})

        try:
            # 新主题或已有主题
            if not topic_id:
                topic_id = storage.create_topic("Web Session")
            _load_topic_history(storage, session, topic_id)

            ai_msg, used_tools = session.chat_stream(
                msg,
                callback=stream_cb,
                topic_id=topic_id,
                on_status=status_cb,
            )
            # 保存对话到数据库（异常时不阻断 done 事件）
            try:
                _save_chat_result(storage, session, topic_id, msg, ai_msg, used_tools)
            except Exception as save_err:
                logger.exception(f"Save chat failed topic={topic_id}: {save_err}")

            usage = session._last_usage or {}
            _put({
                "type": "done",
                "ai_msg": ai_msg,
                "used_tools": used_tools,
                "topic_id": topic_id,
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

    def create_topic_session(self, title="API 会话"):
        """Create a new topic (dialogue session) in storage."""
        tid = self._get_storage().create_topic(title)
        # Also try to set it on agent if agent is already initialized
        if self._agent is not None:
            self._agent.current_topic_id = tid
        return {"id": tid, "title": title}

    def get_session(self, topic_id):
        s = self._get_storage()
        topic = s.get_topic(topic_id)
        if not topic:
            return None
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

    def rename_topic(self, topic_id: str, new_title: str):
        """Rename a topic."""
        try:
            self._get_storage().update_topic_title(topic_id, new_title)
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
            x: Left coordinate (physical pixels)
            y: Top coordinate (physical pixels)
            w: Width (physical pixels)
            h: Height (physical pixels)
        Returns:
            dict: {ok: bool, image_base64?: str, error?: str}
        """
        import base64
        import os
        import tempfile

        from tea_agent.toolkit.toolkit_screenshot import toolkit_screenshot

        try:
            # 截取区域截图
            tmp_path = os.path.join(tempfile.gettempdir(), "screenshot_region.png")
            result = toolkit_screenshot(action="region", region=f"{x},{y},{w},{h}", output=tmp_path)

            if not result.get("success"):
                return {"ok": False, "error": result.get("error", "Screenshot failed")}

            # 容错：确保 path 是有效的文件路径
            img_path = result.get("path", "")
            if not img_path or not isinstance(img_path, str) or not os.path.isfile(img_path):
                if os.path.isfile(tmp_path):
                    img_path = tmp_path
                else:
                    return {"ok": False, "error": f"Invalid screenshot file: path={img_path!r}"}

            # 读取图片并转为 base64
            with open(img_path, "rb") as f:
                img_data = f.read()
            if len(img_data) < 100:
                return {"ok": False, "error": f"截图文件过小: {len(img_data)} bytes"}
            b64_str = base64.b64encode(img_data).decode("utf-8")
            data_url = f"data:image/png;base64,{b64_str}"

            return {
                "ok": True,
                "image_base64": data_url,
                "path": img_path,
                "size": len(img_data),
                "method": result.get("method", ""),
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def screenshot_full(self) -> dict:
        """Capture full screen and return base64 image data.

        Returns:
            dict: {ok: bool, image_base64?: str, error?: str, size?: int}
        """
        import base64
        import os
        import tempfile

        from tea_agent.toolkit.toolkit_screenshot import toolkit_screenshot

        try:
            tmp_path = os.path.join(tempfile.gettempdir(), "screenshot_full.png")
            result = toolkit_screenshot(action="full", output=tmp_path)

            if not result.get("success"):
                return {"ok": False, "error": result.get("error", "Screenshot failed")}

            img_path = result.get("path", "")
            if not img_path or not isinstance(img_path, str) or not os.path.isfile(img_path):
                if os.path.isfile(tmp_path):
                    img_path = tmp_path
                else:
                    return {"ok": False, "error": f"Invalid screenshot file: path={img_path!r}"}

            with open(img_path, "rb") as f:
                img_data = f.read()
            if len(img_data) < 100:
                return {"ok": False, "error": f"截图文件过小: {len(img_data)} bytes"}
            b64_str = base64.b64encode(img_data).decode("utf-8")
            data_url = f"data:image/png;base64,{b64_str}"

            return {
                "ok": True,
                "image_base64": data_url,
                "path": img_path,
                "size": len(img_data),
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

        logger.debug(
            "Model switch: main=" + model_name + " @ " + api_url
            + (", cheap=" + cheap_model_name if cheap_model_name else "")
        )

    def switch_config(self, config_path):
        """Load a full config file and switch both main and cheap models."""
        if not os.path.exists(config_path):
            return {"ok": False, "error": "Config not found: " + config_path}
        from tea_agent.config import AgentConfig, load_config
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
        # 同步更新 agent._config_path，确保后续 API 查询返回正确路径
        self._config_path = config_path
        agent = self._agent
        if agent and hasattr(agent, '_config_path'):
            agent._config_path = config_path
        return {"ok": True, "config_path": config_path}

    @staticmethod
    def _get_configs_dir():
        """Get the ~/.tea_agent/ directory path."""
        return Path.home() / ".tea_agent"

    def list_config_files(self, check_valid: bool = False):
        """Scan ~/.tea_agent/*.yaml and return parsed config summaries.

        Args:
            check_valid: 如果 True，额外返回 any_valid 字段
        """
        configs_dir = self._get_configs_dir()
        if not configs_dir.exists():
            return {"configs": [], "any_valid": False} if check_valid else []
        from tea_agent.config import load_config
        results = []
        any_valid = False
        for fpath in sorted(configs_dir.glob("*.yaml")):
            try:
                cfg = load_config(str(fpath))
                main_m = cfg.main_model
                cheap_m = cfg.cheap_model
                # 判断配置是否有效：必须有 api_url、api_key 和 model_name
                is_valid = main_m.is_configured
                if is_valid:
                    any_valid = True
                results.append({
                    "filename": fpath.name,
                    "path": str(fpath),
                    "is_valid": is_valid,
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
                    "is_valid": False,
                    "error": str(e),
                })
        if check_valid:
            return {"configs": results, "any_valid": any_valid}
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
                value = bool(value) if expected_type == bool else expected_type(value)
                setattr(cfg, key, value)
                updated.append(key)
                logger.info(f"Config updated: {key} = {value}")
            except (ValueError, TypeError) as e:
                errors.append(f"{key}: {e}")
        return {"ok": len(errors) == 0, "updated": updated, "errors": errors}



_server_instance: APIServer | None = None

def get_server() -> APIServer:
    global _server_instance
    if _server_instance is None:
        _server_instance = APIServer()
    return _server_instance


def create_app(api_key: str | None = None,
               config_path: str | None = None):
    """Create the Starlette application for the unified server."""
    # Import route handlers here to avoid circular imports
    from .route_handlers import (
        handle_chat_abort,
        handle_chat_completions,
        handle_chat_continue,
        handle_create_memory,
        handle_create_session,
        handle_create_task,
        handle_delete_memory,
        handle_delete_session,
        handle_delete_task,
        handle_docs,
        handle_export_pdf,
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
        handle_screenshot_full,
        handle_screenshot_interactive,
        handle_screenshot_region,
        handle_search,
        handle_switch_config,
        handle_upload,
        handle_web_chat,
        handle_web_config,
        handle_web_create_config,
        handle_web_list_configs,
        handle_web_model_config,
        handle_web_model_info,
        handle_web_model_switch,
        handle_web_new_topic,
        handle_web_root,
        handle_web_sessions,
        handle_web_tools,
        handle_web_topic_conversations,
        handle_web_topic_info,
        handle_web_topic_todos,
        handle_web_topic_todo_update,
        handle_web_topic_plans,
        handle_web_update_config,
        handle_web_upload_config,
    )

    global _server_instance
    _server_instance = APIServer(api_key=api_key, config_path=config_path)

    static_dir = str(Path(__file__).parent / "static")

    routes = [
        Route("/", endpoint=handle_web_root),
        Route("/api/chat", endpoint=handle_web_chat, methods=["POST"]),
        Route("/api/chat/continue", endpoint=handle_chat_continue, methods=["POST"]),
        Route("/api/chat/abort", endpoint=handle_chat_abort, methods=["POST"]),
        Route("/api/screenshot/region", endpoint=handle_screenshot_region, methods=["POST"]),
        Route("/api/screenshot/full", endpoint=handle_screenshot_full),
        Route("/api/screenshot/interactive", endpoint=handle_screenshot_interactive, methods=["POST"]),
        Route("/api/new_topic", endpoint=handle_web_new_topic, methods=["POST"]),
        Route("/api/sessions", endpoint=handle_web_sessions),
        Route("/api/topic/{topic_id:str}", endpoint=handle_web_topic_info, methods=["GET", "PUT", "DELETE"]),
        Route("/api/topic/{topic_id:str}/conversations", endpoint=handle_web_topic_conversations),
        Route("/api/topic/{topic_id:str}/todos", endpoint=handle_web_topic_todos),
        Route("/api/topic/{topic_id:str}/todos/{idx:int}", endpoint=handle_web_topic_todo_update, methods=["PUT"]),
        Route("/api/topic/{topic_id:str}/plans", endpoint=handle_web_topic_plans),
        Route("/api/tools", endpoint=handle_web_tools),
        Route("/api/config", endpoint=handle_web_config),
        Route("/api/config", endpoint=handle_web_update_config, methods=["PUT"]),
        Route("/api/configs", endpoint=handle_web_list_configs),
        Route("/api/config/create", endpoint=handle_web_create_config, methods=["POST"]),
        Route("/api/model", endpoint=handle_web_model_info),
        Route("/api/model", endpoint=handle_web_model_switch, methods=["POST"]),
        Route("/api/model/config", endpoint=handle_web_model_config, methods=["POST"]),
        Route("/api/config/upload", endpoint=handle_web_upload_config, methods=["POST"]),
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
        Route("/docs", endpoint=handle_docs),
        Route("/openapi.json", endpoint=handle_openapi),
        Mount("/static", app=StaticFiles(directory=static_dir), name="static"),
    ]

    logger.info(f"API Server initialized | v{__version__}")
    app = Starlette(debug=False, routes=routes)

    frontend_dir = Path(__file__).parent.parent / "gui2" / "frontend"
    if frontend_dir.exists():
        logger.info(f"Frontend (gui2): {frontend_dir}")

    return app


def run_server(host: str = "127.0.0.1", port: int = 8080,
               api_key: str | None = None,
               config_path: str | None = None):
    """Run the API server."""
    try:
        import uvicorn
    except ImportError:
        raise ImportError("pip install starlette uvicorn")

    # Suppress noisy loggers: only show WARNING+ on terminal for runtime logs
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.error").setLevel(logging.WARNING)
    logging.getLogger("uvicorn").setLevel(logging.WARNING)
    logging.getLogger("api_server").setLevel(logging.INFO)

    app = create_app(api_key=api_key, config_path=config_path)
    print(f"\n  Tea Agent Server v{__version__}")
    if api_key:
        logger.info("API Key auth enabled")
    logger.info(f"API Server starting: http://{host}:{port}")
    logger.info(f"API Docs: http://{host}:{port}/docs")
    uvicorn.run(app, host=host, port=port, log_level="info")


# ── CLI Entry ──

def main():
    """CLI entry: tea-agent-api (unified)"""
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
