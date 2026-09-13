"""
Shared state for hot-reload modules.

All global mutable state (active sessions, queues, buffers, pending confirmations)
lives here rather than in module classes, so route handlers can access them
without depending on module internals.

This module is NOT hot-reloadable (it's pure state).
"""

from __future__ import annotations

import json
import os
import threading
import time
from typing import Any

# 活跃会话（topic_id -> session）
active_sessions: dict[str, Any] = {}
active_sessions_lock = threading.Lock()

# 后台运行会话（topic_id -> session）
background_sessions: dict[str, Any] = {}
background_sessions_lock = threading.Lock()

# 消息排队队列（topic_id -> list[dict]）
message_queue: dict[str, list[dict]] = {}
message_queue_lock = threading.Lock()

# 后台 SSE 事件缓冲区（topic_id -> buffer_dict）
background_buffers: dict[str, dict] = {}
background_buffers_lock = threading.Lock()

# 重启排空标志：graceful restart 置位后，新回合不再启动（改为排队），
# 等待在途回合自然结束，避免 should_exit 直接切断在途 SSE 流。
draining = False
draining_lock = threading.Lock()

# max_iter 确认请求（confirm_id -> {session, timestamp}）
max_iter_pending: dict[str, dict] = {}

# question 待答存储（question_id -> {event, answer, timestamp}）
question_pending: dict[str, dict] = {}

# 配置缓存
config_cache: dict = {}


# ── Helper functions ──

def register_active(topic_id: str, session) -> None:
    with active_sessions_lock:
        active_sessions[topic_id] = session


def unregister_active(topic_id: str) -> None:
    with active_sessions_lock:
        active_sessions.pop(topic_id, None)


def register_background(topic_id: str, session) -> None:
    with background_sessions_lock:
        background_sessions[topic_id] = session


def unregister_background(topic_id: str) -> None:
    with background_sessions_lock:
        background_sessions.pop(topic_id, None)


def is_topic_busy(topic_id: str) -> bool:
    with active_sessions_lock:
        in_active = topic_id in active_sessions
    with background_sessions_lock:
        in_bg = topic_id in background_sessions
    return in_active or in_bg


def set_draining(flag: bool) -> None:
    """置位/清除重启排空标志。"""
    global draining
    with draining_lock:
        draining = bool(flag)


def is_draining() -> bool:
    """是否处于重启排空期（新回合应排队而非启动）。"""
    with draining_lock:
        return draining


def queue_add(topic_id: str, message: str, images: list | None = None) -> str:
    import uuid
    item_id = uuid.uuid4().hex[:12]
    with message_queue_lock:
        if topic_id not in message_queue:
            message_queue[topic_id] = []
        message_queue[topic_id].append({
            "id": item_id, "message": message,
            "images": images or [], "timestamp": time.time(),
        })
    _persist_queues()
    return item_id


def queue_list(topic_id: str) -> list[dict]:
    with message_queue_lock:
        return list(message_queue.get(topic_id, []))


def queue_remove(topic_id: str, item_id: str) -> bool:
    with message_queue_lock:
        items = message_queue.get(topic_id, [])
        for i, item in enumerate(items):
            if item["id"] == item_id:
                items.pop(i)
                if not items:
                    message_queue.pop(topic_id, None)
                _persist_queues()
                return True
    return False


def queue_pop(topic_id: str) -> dict | None:
    with message_queue_lock:
        items = message_queue.get(topic_id, [])
        if items:
            item = items.pop(0)
            if not items:
                message_queue.pop(topic_id, None)
            _persist_queues()
            return item
    return None


# ── 消息队列持久化（重启后排队消息不丢）─────────────────────────
# 队列原本只在内存里，重启即丢 —— 用户「已排队但未开始」的消息会静默消失。
# 这里落一份快照（原子写），启动时由 restore_queues() 还原。

def _queue_store_path() -> str:
    override = os.environ.get("TEA_SERVER_STATE_DB", "").strip()
    base = override or os.path.join(os.path.expanduser("~"), ".tea_agent",
                                    "server_state.db")
    return base + "_queues.json"


def _persist_queues() -> int:
    """把当前排队消息落盘（原子写）。返回条数；失败返回 -1（fail-open）。"""
    try:
        with message_queue_lock:
            data = {tid: list(items) for tid, items in message_queue.items() if items}
        path = _queue_store_path()
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, path)
        return sum(len(v) for v in data.values())
    except (OSError, ValueError, TypeError):
        return -1


def restore_queues() -> int:
    """启动时恢复上次未消费的排队消息。返回恢复条数（fail-open 返回 0）。"""
    try:
        path = _queue_store_path()
        if not os.path.isfile(path):
            return 0
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return 0
        restored = 0
        with message_queue_lock:
            for tid, items in data.items():
                if not isinstance(tid, str) or not isinstance(items, list) or not items:
                    continue
                kept = [it for it in items
                        if isinstance(it, dict) and it.get("message")]
                if kept:
                    message_queue.setdefault(tid, []).extend(kept)
                    restored += len(kept)
        return restored
    except (OSError, ValueError, TypeError):
        return 0


def create_background_buffer(topic_id: str) -> dict:
    buf = {"events": [], "done": False, "created": time.time()}
    with background_buffers_lock:
        background_buffers[topic_id] = buf
    return buf


def append_to_buffer(topic_id: str, event: dict, index: int) -> None:
    with background_buffers_lock:
        buf = background_buffers.get(topic_id)
        if buf is not None and not buf["done"]:
            buf["events"].append({"index": index, "event": event})


def mark_buffer_done(topic_id: str) -> None:
    with background_buffers_lock:
        buf = background_buffers.get(topic_id)
        if buf is not None:
            buf["done"] = True


def read_buffer_since(topic_id: str, since: int) -> dict:
    with background_buffers_lock:
        buf = background_buffers.get(topic_id)
        if buf is None:
            return {"events": [], "done": True, "next_index": 0}
        events_since = [e for e in buf["events"] if e["index"] > since]
        next_index = (buf["events"][-1]["index"] + 1) if buf["events"] else 0
        return {"events": events_since, "done": buf["done"],
                "next_index": next_index}


def cleanup_buffer(topic_id: str) -> None:
    with background_buffers_lock:
        background_buffers.pop(topic_id, None)


def clear_all() -> None:
    """Clear all state (used during module unload)."""
    max_iter_pending.clear()
    question_pending.clear()
    with active_sessions_lock:
        active_sessions.clear()
    with background_sessions_lock:
        background_sessions.clear()
    with background_buffers_lock:
        background_buffers.clear()
    with message_queue_lock:
        message_queue.clear()
    config_cache.clear()
