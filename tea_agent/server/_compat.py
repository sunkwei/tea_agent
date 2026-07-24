"""
_compat.py — 兼容层，从热重载模块系统重新导出符号。

route_handlers.py 通过 from ._compat import ... 访问所有全局状态和函数，
不直接依赖模块内部结构。这样模块热重载时，handler 总能拿到最新引用。
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any

# ── 版本号（来自 server） ──
from .server import __version__, get_server, logger as server_logger
logger = server_logger

# ── 共享状态（来自 modules.state） ──
from .modules.state import (
    active_sessions as _active_sessions,
    active_sessions_lock as _active_sessions_lock,
    background_sessions as _background_sessions,
    background_sessions_lock as _background_sessions_lock,
    background_buffers as _background_buffers,
    background_buffers_lock as _background_buffers_lock,
    max_iter_pending as _max_iter_pending,
    question_pending as _question_pending,
    message_queue as _message_queue,
    message_queue_lock as _message_queue_lock,
    is_topic_busy,
    queue_add, queue_list, queue_remove, queue_pop,
    read_buffer_since,
    create_background_buffer, append_to_buffer,
    mark_buffer_done, cleanup_buffer,
    register_active, unregister_active,
    register_background, unregister_background,
    clear_all,
)

# ── AgentModule 方法（通过 get_registry 间接获取，确保热重载后仍有效） ──
from .module import get_registry as _get_registry


def _call_agent_module(method_name: str, *args, **kwargs):
    """动态调用 AgentModule 的方法，确保拿到热重载后的最新类。"""
    registry = _get_registry()
    agent_cls = registry.get("agent")
    if agent_cls is None:
        raise RuntimeError("Agent module not registered")
    method = getattr(agent_cls, method_name, None)
    if method is None:
        raise RuntimeError(f"AgentModule.{method_name} not found")
    return method(*args, **kwargs)


def _chat_stream_sse_wrapper(session, storage, msg,
                              queue: "asyncio.Queue", topic_id: str = "",
                              event_loop=None):
    """转发到 AgentModule.chat_stream_sse。"""
    return _call_agent_module("chat_stream_sse", session, storage, msg,
                               queue, topic_id=topic_id, event_loop=event_loop)


def _schedule_buffer_cleanup(topic_id: str, delay: float = 30.0) -> None:
    """延迟清理后台缓冲区，给前端轮询留出读取时间。"""
    try:
        loop = asyncio.get_running_loop()
        loop.call_later(delay, lambda: cleanup_buffer(topic_id))
    except RuntimeError:
        threading.Timer(delay, lambda: cleanup_buffer(topic_id)).start()


async def _background_buffer_reader(topic_id: str, queue: asyncio.Queue,
                                      event_loop=None):
    """从 queue 消费事件并写入后台缓冲区供前端轮询。"""
    buf = create_background_buffer(topic_id)
    index = 0
    try:
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=300)
                append_to_buffer(topic_id, event, index)
                index += 1
                if event.get("type") in ("done", "error"):
                    mark_buffer_done(topic_id)
                    break
            except asyncio.TimeoutError:
                with _background_sessions_lock:
                    if topic_id not in _background_sessions:
                        mark_buffer_done(topic_id)
                        break
    except asyncio.CancelledError:
        mark_buffer_done(topic_id)
    except Exception:
        logger.exception(f"Background buffer reader error for topic={topic_id}")
        mark_buffer_done(topic_id)
    finally:
        _schedule_buffer_cleanup(topic_id)
        # ⭐ 当缓冲区读取完毕（后台会话也结束了），清理 background_sessions
        # 避免后续消息因 is_topic_busy 返回 True 被错误排队
        with _background_sessions_lock:
            _background_sessions.pop(topic_id, None)


# ── 带下划前缀的别名（route_handlers.py 历史引用） ──
_read_buffer_since = read_buffer_since
_queue_add = queue_add
_queue_list = queue_list
_queue_remove = queue_remove
_queue_pop = queue_pop
_is_topic_busy = is_topic_busy

# 显式导出（与原始 route_handlers.py import 匹配）
__all__ = [
    "__version__",
    "_active_sessions",
    "_active_sessions_lock",
    "_background_sessions",
    "_background_sessions_lock",
    "_background_buffer_reader",
    "_read_buffer_since",
    "_chat_stream_sse_wrapper",
    "_max_iter_pending",
    "_question_pending",
    "_queue_add",
    "_queue_list",
    "_queue_remove",
    "_queue_pop",
    "_is_topic_busy",
    "get_server",
    "logger",
]
