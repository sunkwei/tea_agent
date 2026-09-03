"""
AgentModule — 热重载 Agent 模块。

管理 Agent 生命周期、会话创建、对话引擎。
热重载时创建新的 Agent 实例，替换旧的。
依赖：toolkit, storage
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from ..module import HotReloadModule, ModuleRegistry, _module_path_for
from .state import (
    active_sessions,
    background_sessions,
    config_cache,
    max_iter_pending,
    question_pending,
)
from .state import (
    clear_all as clear_all_state,
)
from .state import (
    queue_pop,
)

logger = logging.getLogger("hot_reload.agent")


def _server_round_summary(model: str, user_msg, tool_names: list, ai_msg: str) -> None:
    """server 每轮对话的摘要信息（DEBUG 级别，默认不输出到终端）。

    Args:
        model: 使用的模型名称
        user_msg: 用户输入（str 或 {"text": ..., "images": [...]}）
        tool_names: 本轮调用的工具函数名列表
        ai_msg: AI 最终回复
    """
    try:
        _user = user_msg if isinstance(user_msg, str) else (
            (user_msg or {}).get("text", "") if isinstance(user_msg, dict) else str(user_msg)
        )
        _user = (_user or "").replace("\n", " ")[:64]
        _tools = ",".join(tool_names or [])
        _ai = (ai_msg or "").replace("\n", " ")[:64]
        # 终端仅保留启动 banner（见 server.py run_server）；每轮对话摘要降为
        # DEBUG 级别，需要时可用 set_debug(True) 临时打开。
        logger.debug(f"[chat] model={model} | user={_user} | tools=[{_tools}] | ai={_ai}")
    except Exception:
        pass


def _context_usage_estimate(context: Any) -> int | None:
    """估算当前上下文字符→token 用量；估算失败返回 None。

    复用 context_fragments 的 _estimate_context_tokens，其覆盖消息本体、
    tools 定义 JSON Schema 与 system 富化注入（与真实请求口径接近）。
    """
    try:
        from tea_agent.context_fragments import _estimate_context_tokens

        used = _estimate_context_tokens(context)
        return int(used) if used else 0
    except Exception:
        return None


def _compute_context_usage(context: Any, prompt_tokens: int) -> dict:
    """计算"当前上下文已用 xx%"信息，供后端 usage_data / 前端展示。

    组合两个口径：
    - 实际用量：优先用最近一次请求的真实 prompt_tokens（单次值 = 当前上下文大小，
      含前缀缓存命中）。注意：调用方传入的 prompt_tokens 参数来自
      session._last_usage，是会话累计值（所有请求之和），不能作为"当前上下文大小"，
      故优先取 context._last_request_prompt_tokens（S3 记录的单次值）；
      缺失时回退到 context_fragments 的启发式估算，最后才用累计值兜底。
    - 窗口上限：get_max_context_tokens（显式配置 > 模型名推断 > 128K 兜底）。

    Returns:
        {"context_used_tokens", "context_max_tokens", "context_pct", "context_used"}
        （max 未知时 context_pct=None、context_used 显示估算值字样）
    """
    from tea_agent.auto_compact import get_max_context_tokens

    used = 0
    # 单次值优先：_last_request_prompt_tokens 是最近一次主模型请求的
    # prompt_tokens（= 当前上下文大小）。prompt_tokens 参数是累计值，
    # 仅作最后兜底（避免显示 0）。
    last_real = getattr(context, "_last_request_prompt_tokens", 0) or 0
    if last_real and last_real > 0:
        used = int(last_real)
    else:
        est = _context_usage_estimate(context)
        if est is not None:
            used = est
        elif prompt_tokens and prompt_tokens > 0:
            used = int(prompt_tokens)

    max_tokens = 0
    try:
        max_tokens = int(get_max_context_tokens(context) or 0)
    except Exception:
        max_tokens = 0

    pct = None
    if max_tokens > 0:
        pct = round(min(100.0, used / max_tokens * 100.0), 1)

    if max_tokens > 0:
        text = f"上下文已用 {pct}% ({used:,}/{max_tokens:,} tok)"
    else:
        text = f"上下文已用 {used:,} tok"
    return {
        "context_used_tokens": used,
        "context_max_tokens": max_tokens,
        "context_pct": pct,
        "context_used": text,
    }


class AgentModule(HotReloadModule):
    """Agent 热重载模块。"""

    name: str = "agent"
    dependencies: list[str] = ["toolkit", "storage"]

    _instance: Any = None
    _config_path: str = ""
    _start_time: float = 0.0
    _server_version: str = ""

    @classmethod
    def _load(cls, registry: ModuleRegistry) -> bool:
        """加载 Agent 模块（热重载时深度 reload 核心依赖）。"""
        import importlib
        import sys as _sys

        # ── 深度 reload 核心依赖模块（按依赖顺序） ──
        # 当 basesession.py / session/context.py 等文件变更时，
        # FileWatcher 触发 AgentModule.reload → 此处按依赖链深度 reload
        # 确保所有 import 拿到最新代码。
        _core_modules = [
            'tea_agent.session.context',
            'tea_agent.session.history_builder',
            'tea_agent.session.os_info_injector',
            'tea_agent.session.params',
            'tea_agent.session.prompts',
            'tea_agent.session.tool_loop_runner',
            'tea_agent.basesession',
            'tea_agent.session_pipeline',
            'tea_agent.onlinesession',
            'tea_agent.agent',
            'tea_agent.agent_pipeline',
        ]
        for mod_name in _core_modules:
            mod = _sys.modules.get(mod_name)
            if mod is not None:
                try:
                    importlib.reload(mod)
                except Exception as e:
                    logger.warning(f"⚠️ Deep reload {mod_name} failed (non-fatal): {e}")

        from tea_agent.agent import Agent
        cls._start_time = time.time()
        cfg_path = cls._config_path or os.environ.get("TEA_CONFIG", "")
        cls._instance = Agent(mode="full", config_path=cfg_path or None)
        cls._config_path = cfg_path or getattr(cls._instance, '_config_path', '')
        logger.info(f"Agent loaded | model={cls._get_model_name()}")
        return True

    @classmethod
    def _unload(cls) -> None:
        """卸载 Agent 模块。"""
        if cls._instance:
            with contextlib.suppress(Exception):
                cls._instance.sess.close()
            cls._instance = None
        clear_all_state()

    @classmethod
    def get_agent(cls) -> Any:
        return cls._instance

    @classmethod
    def _get_model_name(cls) -> str:
        try:
            return cls._instance.config.main_model.model_name if cls._instance else ""
        except Exception:
            return ""

    @classmethod
    def set_config_path(cls, config_path: str) -> None:
        cls._config_path = config_path

    @classmethod
    def _load_config_cached(cls, config_path: str | None = None):
        key = config_path or "__default__"
        if key not in config_cache:
            from tea_agent.config import load_config
            config_cache[key] = load_config(config_path)
        return config_cache[key]

    @classmethod
    def invalidate_config_cache(cls, config_path: str | None = None):
        """使会话配置缓存失效（模型 apply/switch 后调用）。

        配置被外部修改（如 /api/providers/{name}/apply 落盘新模型）后，
        必须清除 config_cache 才能让 create_session 读到最新配置；
        否则缓存永久命中启动时的旧配置，聊天会话始终使用老模型。
        """
        if config_path:
            config_cache.pop(config_path, None)
        config_cache.pop("__default__", None)
        if getattr(cls, "_config_path", None):
            config_cache.pop(cls._config_path, None)

    # ── 会话创建 ──

    @classmethod
    def create_session(cls, config_path: str | None = None):
        """为流式请求创建独立 Session。"""
        from tea_agent import tlk
        from tea_agent.onlinesession import OnlineToolSession

        cfg = cls._load_config_cached(config_path or cls._config_path)
        tk = tlk.toolkit
        main_m = cfg.main_model
        cheap_m = cfg.cheap_model
        vision_m = cfg.vision_model
        _options = getattr(main_m, 'options', {}) or {}
        main_supports_vision = _options.get('supports_vision', False) if isinstance(_options, dict) else False
        # 主模型或已配置视觉模型任一支持即可（会话含图片时自动切换 vision_model）
        supports_vision = main_supports_vision or vision_m.is_configured
        supports_reasoning = _options.get('supports_reasoning', True) if isinstance(_options, dict) else True

        from tea_agent.store import get_storage as _get_storage
        _storage = _get_storage()
        sess = OnlineToolSession(
            toolkit=tk,
            api_key=main_m.api_key, api_url=main_m.api_url, model=main_m.model_name,
            max_history=cfg.max_history, max_iterations=cfg.max_iterations,
            keep_turns=cfg.keep_turns, max_tool_output=cfg.max_tool_output,
            max_assistant_content=cfg.max_assistant_content,
            max_context_tokens=main_m.max_context_tokens,
            extra_iterations_on_continue=cfg.extra_iterations_on_continue,
            memory_extraction_threshold=cfg.memory_extraction_threshold,
            storage=_storage,
            cheap_api_key=cheap_m.api_key, cheap_api_url=cheap_m.api_url,
            cheap_model=cheap_m.model_name,
            vision_api_key=vision_m.api_key, vision_api_url=vision_m.api_url,
            vision_model=vision_m.model_name,
            enable_thinking=cfg.enable_thinking,
            thinking_strength=cfg.thinking_strength,
            reasoning_effort=cfg.reasoning_effort,
            supports_vision=supports_vision, supports_reasoning=supports_reasoning,
        )
        sess.context.interface_type = "web"
        return sess, _storage

    @classmethod
    def chat_completion(cls, model: str, messages: list[dict],
                         stream: bool = False, temperature: float = 0.7,
                         max_tokens: int | None = None,
                         topic_id: str = "") -> dict:
        """非流式对话完成。"""
        agent = cls._instance
        if agent is None:
            return {"error": "Agent not loaded"}
        user_msg = cls._extract_user_message(messages)
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
        _server_round_summary(
            getattr(agent.sess.context, "model", ""),
            user_msg,
            getattr(agent.sess, "_last_tool_names", []) or [],
            ai_msg,
        )
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

    @classmethod
    async def chat_completion_stream(cls, model, messages,
                                      temperature=0.7,
                                      max_tokens=None, topic_id="",
                                      config_path=None):
        """流式对话完成。每请求创建独立 Session。"""
        session, _storage = cls.create_session(config_path)
        user_msg = cls._extract_user_message(messages)
        queue = asyncio.Queue()
        event_loop = asyncio.get_running_loop()
        def _put(event):
            with contextlib.suppress(Exception):
                event_loop.call_soon_threadsafe(
                    lambda: queue.put_nowait(event))
        def stream_cb(text):
            if text.startswith("["):
                return
            _put({"type": "content", "text": text})
        thread = threading.Thread(
            target=cls._run_stream,
            args=(session, user_msg, topic_id, stream_cb, _put),
            daemon=True)
        thread.start()
        try:
            async for event in cls._generate_sse(queue, model):
                yield event
        except asyncio.CancelledError:
            session.interrupt()

    @classmethod
    def _run_stream(cls, session, user_msg, topic_id, stream_cb, put):
        """后台线程运行流式对话。"""
        from tea_agent.store import get_storage
        storage = get_storage()
        _streamed_text_parts: list[str] = []
        def _wrapped_cb(text):
            _streamed_text_parts.append(text)
            stream_cb(text)
        try:
            if topic_id:
                cls._load_topic_history(storage, session, topic_id)
            else:
                topic_id = storage.create_topic("API 流式会话")
            from tea_agent.session_ref import get_agent
            _ga = get_agent() or cls._instance
            if _ga:
                _ga.current_topic_id = topic_id
            ai_msg, used_tools = session.chat_stream(
                user_msg, callback=_wrapped_cb, topic_id=topic_id)
            _effective_ai_msg = ai_msg if ai_msg else "".join(_streamed_text_parts)
            _server_round_summary(
                getattr(session.context, "model", ""),
                user_msg,
                getattr(session, "_last_tool_names", []) or [],
                _effective_ai_msg,
            )
            cls._save_chat_result(storage, session, topic_id, user_msg, _effective_ai_msg, used_tools)
            _usage = getattr(session, '_last_usage', None) or {}
            _model = getattr(session.context, 'model', '')
            _cheap_model = getattr(session.context, 'cheap_model', '')
            put({"type": "done", "ai_msg": _effective_ai_msg,
                 "tools_used": used_tools or [],
                 "usage": {
                     "total_tokens": _usage.get("total_tokens", 0),
                     "prompt_tokens": _usage.get("prompt_tokens", 0),
                     "completion_tokens": _usage.get("completion_tokens", 0),
                     "model": _model,
                     "cheap_model": _cheap_model,
                 }})
        except Exception as e:
            logger.exception(f"Stream chat error: {e}")
            with contextlib.suppress(Exception):
                put({"type": "error", "error": f"{type(e).__name__}: {e}"})

    @classmethod
    async def _generate_sse(cls, queue, model):
        cid = "chatcmpl-" + uuid.uuid4().hex[:12]
        now = int(time.time())
        nl2 = "\n\n"
        init_data = {"id": cid, "object": "chat.completion.chunk",
                     "created": now, "model": model,
                     "choices": [{"index": 0, "delta": {"role": "assistant"},
                                  "finish_reason": None}]}
        yield "data: " + json.dumps(init_data) + nl2
        while True:
            event = await queue.get()
            t = event["type"]
            if t == "content":
                data = {"id": cid, "object": "chat.completion.chunk",
                        "created": now, "model": model,
                        "choices": [{"index": 0,
                                     "delta": {"content": event["text"]},
                                     "finish_reason": None}]}
                yield "data: " + json.dumps(data) + NL2
            elif t == "done":
                done_data = {"id": cid, "object": "chat.completion.chunk",
                            "created": now, "model": model,
                            "choices": [{"index": 0, "delta": {},
                                         "finish_reason": "stop"}],
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

    @staticmethod
    def _load_topic_history(storage, session, topic_id):
        if not storage:
            return
        try:
            all_light = storage.get_conversations(topic_id, limit=-1, include_rounds=False)
            if all_light:
                history_turns = getattr(session.context, 'keep_turns', 3)
                recent_n = storage.get_conversations(topic_id, limit=history_turns, include_rounds=True)
                if recent_n:
                    for i, conv in enumerate(recent_n):
                        all_light[-(len(recent_n) - i)] = conv
                level2 = storage.get_level2(topic_id)
                semantic = storage.get_semantic_summary(topic_id)
                tool_chain = storage.get_tool_chain_summary(topic_id)
                old_summary = storage.get_topic_summary(topic_id) or ""
                session.load_history(all_light, summary=old_summary,
                                    level2=level2, semantic_summary=semantic,
                                    tool_chain_summary=tool_chain,
                                    history_turns=history_turns)
                return
        except Exception:
            logger.exception(f"_load_topic_history failed for topic={topic_id}")
        session.messages = [{"role": "system", "content": session.system_prompt}]
        session._history_summary = ""
        session._semantic_summary = ""
        session._tool_chain_summary = ""
        session.context._level2 = []

    @staticmethod
    def _save_chat_result(storage, session, topic_id, user_msg, ai_msg, used_tools):
        if not storage:
            return
        user_text = user_msg if isinstance(user_msg, str) else (
            user_msg.get("text", "") if isinstance(user_msg, dict) else str(user_msg)
        )
        try:
            conv_id = storage.save_msg(topic_id, user_text, "", False)
        except Exception:
            logger.exception("save_msg failed")
            return
        rounds = session._rounds_collector
        try:
            storage.update_msg_rounds(conversation_id=conv_id, ai_msg=ai_msg,
                                       is_func_calling=used_tools,
                                       rounds=rounds if rounds else None)
        except Exception:
            logger.exception("update_msg_rounds failed")
        try:
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
        except Exception:
            logger.exception("add_topic_tokens failed")
        try:
            l2_count, overflow_items, should_summarize = storage.push_to_level2(
                topic_id, user_text, ai_msg,
                rounds=rounds if rounds else None,
            )
        except Exception:
            logger.exception("push_to_level2 failed")
            return
        if overflow_items or should_summarize:
            from tea_agent.agent_pipeline import do_async_summaries
            proxy = _ChatAgentProxy(storage, session)
            threading.Thread(
                target=do_async_summaries,
                args=(proxy, topic_id, overflow_items, should_summarize),
                daemon=True,
            ).start()

    @classmethod
    def chat_stream_sse(cls, session, storage, msg,
                         queue: asyncio.Queue, topic_id: str = "",
                         event_loop=None):
        """在后台线程运行 SSE 流式对话。"""
        def _put(event: dict):
            if event_loop is None:
                return
            with contextlib.suppress(Exception):
                event_loop.call_soon_threadsafe(
                    lambda: queue.put_nowait(event))

        _thinking_active = False
        _tool_active = False
        _streamed_text_parts: list[str] = []

        def stream_cb(text: str):
            nonlocal _thinking_active, _tool_active, _streamed_text_parts
            if text.startswith("[PARALLEL:"):
                # 并行工具批次标记：转为事件，避免作为 token 泄漏到聊天区
                _names = text[len("[PARALLEL:"):-1]
                _put({"type": "tool_parallel", "names": _names})
            elif text.startswith("[TOOL_START:"):
                _tool_name = text[len("[TOOL_START:"):-1]
                _put({"type": "tool_start", "name": _tool_name})
                _tool_active = True
            elif text.startswith("[TOOL_RESULT:"):
                _res = text[len("[TOOL_RESULT:"):-1]
                _put({"type": "tool_result", "result": _res})
            elif text.startswith("[DAG_VIZ:"):
                _viz_id = text[len("[DAG_VIZ:"):-1]
                if _viz_id:
                    _put({"type": "dag_viz", "viz_id": _viz_id})
            elif text.startswith("[TOOL_ARG:"):
                _args = text[len("[TOOL_ARG:"):-1]
                _put({"type": "tool_args", "args": _args})
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
                _streamed_text_parts.append(text)

        def status_cb(status_msg: str):
            if status_msg.startswith("!MAX_ITER:"):
                confirm_id = uuid.uuid4().hex[:12]
                max_iter_pending[confirm_id] = {
                    "session": session, "timestamp": time.time(),
                }
                _put({"type": "max_iter_confirm", "confirm_id": confirm_id,
                      "text": status_msg})
            elif not status_msg.startswith("\u23f3"):
                _put({"type": "status", "text": status_msg})

        try:
            from tea_agent import session_ref as _sess_ref
            _saved_session = _sess_ref._current_session
            _sess_ref._current_session = session

            if not topic_id:
                _ts = datetime.now().strftime('%m-%d %H:%M')
                topic_id = storage.create_topic(f"Web Session ({_ts})")
            # ⭐ 尽早通知前端主题 ID（首次对话时前端尚未持有 topic_id，
            # 拿到后才能正确投递插话消息 /api/chat/steering）
            _put({"type": "topic_ready", "topic_id": topic_id})

            from tea_agent.session_ref import get_agent as _get_agent
            _ga = _get_agent() or cls._instance
            if _ga:
                _ga.current_topic_id = topic_id

            cls._load_topic_history(storage, session, topic_id)

            from tea_agent import tlk
            tlk.toolkit._question_web_handler = lambda t, q, o, d, to: cls._server_question_handler(
                t, q, o, d, to, _put, event_loop,
            )

            # ⭐ 插话（steering）接线：
            #   - _steering_provider: 按 topic 消费服务端排队队列（state.message_queue）
            #   - _steering_notify:   注入后通过 SSE 通知前端（steering_injected），
            #                         前端据此从本地排队列表移除该项
            def _steering_provider():
                _tid = getattr(session, "current_topic_id", "") or topic_id
                if not _tid:
                    return []
                _items = []
                while True:
                    _item = queue_pop(_tid)
                    if _item is None:
                        break
                    _items.append(_item)
                return _items

            def _steering_notify(item):
                _put({
                    "type": "steering_injected",
                    "item_id": (item or {}).get("id", ""),
                    "text": (item or {}).get("message", ""),
                })

            session._steering_provider = _steering_provider
            session._steering_notify = _steering_notify

            ai_msg = None
            used_tools = None
            try:
                ai_msg, used_tools = session.chat_stream(
                    msg, callback=stream_cb, topic_id=topic_id,
                    on_status=status_cb,
                )
            finally:
                tlk.toolkit._question_web_handler = None

            _effective_ai_msg = ai_msg if ai_msg else "".join(_streamed_text_parts)
            _server_round_summary(
                getattr(session.context, "model", ""),
                msg,
                getattr(session, "_last_tool_names", []) or [],
                _effective_ai_msg,
            )
            if _effective_ai_msg is not None:
                try:
                    cls._save_chat_result(storage, session, topic_id, msg,
                                           _effective_ai_msg, used_tools)
                except Exception as save_err:
                    logger.exception(f"Save chat failed: {save_err}")

            try:
                _tp = storage.get_topic(topic_id)
                if _tp:
                    _cur_title = (_tp.get("title") or "")
                    if _cur_title and not _cur_title.startswith("\u203b"):
                        _user_text = msg if isinstance(msg, str) else (
                            msg.get("text", "") if isinstance(msg, dict) else str(msg)
                        )
                        if _user_text:
                            _short = _user_text.strip().replace("\n", " ")[:28]
                            if _short:
                                _suffix = "\u2026" if len(_user_text.strip()) > 28 else ""
                                _new_title = f"Web: {_short}{_suffix}"
                                storage.update_topic_title(topic_id, _new_title)
            except Exception:
                pass

            usage = session._last_usage or {}
            cheap_usage = getattr(session, '_last_cheap_usage', None) or {}
            model_name = getattr(session.context, 'model', '')
            cheap_model_name = getattr(session.context, 'cheap_model', '')
            usage_data = {
                "total_tokens": usage.get("total_tokens", 0),
                "prompt_tokens": usage.get("prompt_tokens", 0),
                "completion_tokens": usage.get("completion_tokens", 0),
                "prompt_cache_hit_tokens": usage.get("prompt_cache_hit_tokens", 0),
                "prompt_cache_miss_tokens": usage.get("prompt_cache_miss_tokens", 0),
                "model": model_name,
                "cheap_model": cheap_model_name,
            }
            if cheap_usage.get("total_tokens", 0) > 0:
                usage_data["cheap_tokens"] = cheap_usage.get("total_tokens", 0)
                usage_data["cheap_prompt_tokens"] = cheap_usage.get("prompt_tokens", 0)
                usage_data["cheap_completion_tokens"] = cheap_usage.get("completion_tokens", 0)
                usage_data["cheap_prompt_cache_hit_tokens"] = cheap_usage.get("prompt_cache_hit_tokens", 0)
                usage_data["cheap_prompt_cache_miss_tokens"] = cheap_usage.get("prompt_cache_miss_tokens", 0)
            # 缓存命中率描述（供前端直接展示）
            try:
                from tea_agent.session.cache_report import format_cache_hit_rate
                _rate = format_cache_hit_rate(usage)
                if _rate:
                    usage_data["cache_hit_rate"] = _rate
                _cheap_rate = format_cache_hit_rate(cheap_usage)
                if _cheap_rate:
                    usage_data["cheap_cache_hit_rate"] = _cheap_rate
            except Exception:
                pass
            # 当前上下文已用 xx%（供前端展示；优先用真实 prompt_tokens 口径）
            try:
                _ctx_usage = _compute_context_usage(
                    getattr(session, "context", None),
                    usage.get("prompt_tokens", 0) or 0,
                )
                usage_data["context_used_tokens"] = _ctx_usage["context_used_tokens"]
                usage_data["context_max_tokens"] = _ctx_usage["context_max_tokens"]
                usage_data["context_pct"] = _ctx_usage["context_pct"]
                usage_data["context_used"] = _ctx_usage["context_used"]
            except Exception:
                logger.exception("context usage compute failed")
            _put({
                "type": "done",
                "ai_msg": _effective_ai_msg,
                "used_tools": used_tools,
                "topic_id": topic_id,
                "usage": usage_data,
            })
        except Exception as e:
            logger.exception("Chat stream error")
            _put({"type": "error", "error": str(e)})
        finally:
            _sess_ref._current_session = _saved_session

    @classmethod
    def _server_question_handler(cls, title, question, options, default, timeout,
                                  put_fn, event_loop):
        """Server 模式下处理 toolkit_question()。"""
        import uuid as _uuid_mod
        question_id = _uuid_mod.uuid4().hex[:12]
        event = threading.Event()
        entry = {"event": event, "answer": None, "timestamp": time.time()}
        question_pending[question_id] = entry
        try:
            if event_loop is not None:
                event_loop.call_soon_threadsafe(lambda: put_fn({
                    "type": "question",
                    "question_id": question_id,
                    "title": title,
                    "question": question,
                    "options": options or [],
                    "default": default,
                }))
        except Exception:
            pass
        if timeout > 0:
            event.wait(timeout=timeout)
        else:
            event.wait()
        answer = entry.get("answer")
        question_pending.pop(question_id, None)
        return answer if answer is not None else (default or "")

    # ── 模型切换 ──

    @classmethod
    def switch_model(cls, api_key: str, api_url: str, model_name: str,
                     **kwargs) -> None:
        """热切换模型。"""
        agent = cls._instance
        if agent is None:
            return
        topic_id = agent.current_topic_id or ""
        has_active_streams = bool(active_sessions)
        if agent.sess:
            agent.sess.close()
        cfg = agent._cfg
        cfg.main_model.api_key = api_key
        cfg.main_model.api_url = api_url
        cfg.main_model.model_name = model_name
        if kwargs.get("temperature") is not None:
            cfg.main_model.temperature = kwargs["temperature"]
        if kwargs.get("max_tokens") is not None:
            cfg.main_model.max_tokens = kwargs["max_tokens"]
        if kwargs.get("top_p") is not None:
            cfg.main_model.top_p = kwargs["top_p"]
        if kwargs.get("max_context_tokens") is not None:
            cfg.main_model.max_context_tokens = kwargs["max_context_tokens"]
        if kwargs.get("options") is not None:
            cfg.main_model.options = kwargs["options"]

        cheap_api_url = kwargs.get("cheap_api_url", "")
        cheap_model_name = kwargs.get("cheap_model_name", "")
        if cheap_api_url and cheap_model_name:
            cfg.cheap_model.api_key = kwargs.get("cheap_api_key", api_key)
            cfg.cheap_model.api_url = cheap_api_url
            cfg.cheap_model.model_name = cheap_model_name
            for attr in ["temperature", "max_tokens", "top_p",
                         "max_context_tokens", "options"]:
                val = kwargs.get(f"cheap_{attr}")
                if val is not None:
                    setattr(cfg.cheap_model, attr, val)

        agent._init_session(update_ref=not has_active_streams)
        if topic_id:
            agent.current_topic_id = topic_id
            agent.load_topic_history(topic_id)

    # ── 会话续用切换（当前轮不中断，结束后自动应用新模型） ──

    _pending_switch: dict | None = None
    _switch_lock = threading.Lock()

    @classmethod
    def request_model_switch(cls, api_key: str, api_url: str, model_name: str,
                             **kwargs) -> dict:
        """请求切换模型并继续当前会话（统一模型面板「应用并继续会话」入口）。

        语义（配置须已由调用方落盘，如 ProviderService.apply_provider）：
          - 对话进行中（active/background）→ 仅挂起，本轮结束后由
            try_apply_pending_switch 自动应用，绝不打断正在流式输出的回复；
          - 空闲且长驻 Agent 存在 → 立即热切换（重建会话并恢复当前主题历史）；
          - 无长驻 Agent（纯 Web/API 模式）→ 下一条消息 create_session 读盘，
            自动以新模型继续同一 topic。
        """
        busy = bool(active_sessions) or bool(background_sessions)
        if busy:
            with cls._switch_lock:
                cls._pending_switch = {"api_key": api_key, "api_url": api_url,
                                       "model_name": model_name, "kwargs": dict(kwargs),
                                       "at": time.time()}
            logger.info("model switch queued (turn in progress): %s", model_name)
            return {"mode": "pending_next_turn", "model": model_name}
        if cls._instance is None:
            return {"mode": "next_message", "model": model_name}
        cls.switch_model(api_key, api_url, model_name, **kwargs)
        return {"mode": "applied", "model": model_name}

    @classmethod
    def try_apply_pending_switch(cls) -> dict | None:
        """回合结束钩子（chat finally / 后台缓冲读取 finally 调用）：

        有挂起的模型切换且已无进行中对话 → 应用之；当前主题历史无缝续接。
        """
        with cls._switch_lock:
            pending = cls._pending_switch
            if not pending:
                return None
            if bool(active_sessions) or bool(background_sessions):
                return None  # 仍有其他会话进行中，等它的回合结束再应用
            cls._pending_switch = None
        if cls._instance is None:
            # 纯 Web 模式：落盘配置已生效，下一条消息自然使用新模型
            return {"mode": "next_message", "model": pending["model_name"]}
        try:
            cls.switch_model(pending["api_key"], pending["api_url"],
                             pending["model_name"], **pending["kwargs"])
            logger.info("pending model switch applied: %s (session continues)",
                        pending["model_name"])
            return {"mode": "applied_after_turn", "model": pending["model_name"]}
        except Exception as e:
            logger.warning("apply pending model switch failed: %s", e)
            return None

    @classmethod
    def get_pending_switch(cls) -> dict | None:
        """查询挂起中的模型切换（面板展示“待本轮结束后生效”状态）。"""
        with cls._switch_lock:
            p = cls._pending_switch
            if not p:
                return None
            return {"model_name": p["model_name"], "api_url": p["api_url"], "at": p["at"]}

    @classmethod
    def switch_config(cls, config_path: str) -> dict:
        if not os.path.exists(config_path):
            return {"ok": False, "error": f"Config not found: {config_path}"}
        from tea_agent.config import AgentConfig, load_config
        new_cfg = load_config(config_path)
        if not new_cfg.main_model.is_configured:
            return {"ok": False, "error": "main_model not complete"}
        cm = new_cfg.main_model
        cc = new_cfg.cheap_model
        cls.switch_model(
            cm.api_key, cm.api_url, cm.model_name,
            cheap_api_key=(cc.api_key or "") if cc else "",
            cheap_api_url=(cc.api_url or "") if cc else "",
            cheap_model_name=(cc.model_name or "") if cc else "",
            temperature=cm.temperature,
            max_tokens=cm.max_tokens,
            top_p=cm.top_p,
            max_context_tokens=cm.max_context_tokens,
            options=cm.options,
        )
        agent = cls._instance
        if agent and hasattr(agent, '_cfg'):
            cfg = agent._cfg
            for key in AgentConfig._RUNTIME_CONFIG_KEYS:
                setattr(cfg, key, getattr(new_cfg, key))
            cfg.embedding = new_cfg.embedding
            cfg.mode_params = new_cfg.mode_params
        cls._config_path = config_path
        if agent and hasattr(agent, '_config_path'):
            agent._config_path = config_path
        return {"ok": True, "config_path": config_path}

    # ── 配置信息 ──

    @classmethod
    def get_config_info(cls) -> dict:
        agent = cls._instance
        if agent is None:
            return {"error": "Agent not loaded"}
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
            "interruption": cfg.interruption,
            "tools_count": len(agent.toolkit.func_map),
            "server_version": cls._server_version,
        }

    @classmethod
    def update_config(cls, updates: dict) -> dict:
        from tea_agent.config import AgentConfig
        agent = cls._instance
        if agent is None:
            return {"ok": False, "errors": ["Agent not loaded"]}
        cfg = agent._cfg
        whitelist = AgentConfig._RUNTIME_CONFIG_KEYS
        type_map = getattr(AgentConfig, '_CONFIG_TYPES', {})
        updated, errors = [], []
        for key, value in updates.items():
            if key not in whitelist:
                errors.append(f"{key}: not runtime-configurable")
                continue
            try:
                expected_type = type_map.get(key, str)
                value = bool(value) if expected_type == bool else expected_type(value)
                setattr(cfg, key, value)
                updated.append(key)
            except (ValueError, TypeError) as e:
                errors.append(f"{key}: {e}")
        return {"ok": len(errors) == 0, "updated": updated, "errors": errors}

    # ── 配置管理 ──

    @classmethod
    def _get_configs_dir(cls):
        return Path.home() / ".tea_agent"

    @classmethod
    def list_config_files(cls, check_valid: bool = False):
        """Scan ~/.tea_agent/*.yaml and return parsed config summaries."""
        from tea_agent.config import load_config
        configs_dir = cls._get_configs_dir()
        if not configs_dir.exists():
            return {"configs": [], "any_valid": False} if check_valid else []
        results = []
        any_valid = False
        for fpath in sorted(configs_dir.glob("*.yaml")):
            try:
                cfg = load_config(str(fpath))
                main_m = cfg.main_model
                cheap_m = cfg.cheap_model
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

    @classmethod
    def create_config_file(cls, filename: str,
                           main_model_name: str, main_api_url: str, main_api_key: str,
                           cheap_model_name: str = "", cheap_api_url: str = "",
                           cheap_api_key: str = ""):
        """Create a new config file in ~/.tea_agent/."""
        configs_dir = cls._get_configs_dir()
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


class _ChatAgentProxy:
    """轻量级 Agent 代理，供后处理流水线使用。"""
    def __init__(self, storage, session):
        self._db = storage
        self._sess = session
        self._pending_cheap_tokens = {}


_module_path_for(AgentModule)
