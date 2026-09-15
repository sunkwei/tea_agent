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
# 用 RLock：队列辅助函数会在持锁期间调用同样取锁的 _persist_queues，
# 非重入锁会自死锁（曾导致插话消费把整个回合卡死）。RLock 作为兜底，
# 但正确做法仍是"锁内只改内存、锁外落盘"。
message_queue_lock = threading.RLock()

# ⚠️ "锁内取快照、锁外写文件"带来另一类缺陷：两个并发 persist 的**完成顺序
# 可能与快照顺序相反** —— 旧快照后落盘会把已删除/已消费的消息复活到磁盘
# （内存是干净的，只有磁盘错，于是重启后消息死灰复燃）。
# 因此每次队列变更递增 _queue_version；落盘时带上快照对应的版本，
# 版本不比已落盘的新就直接跳过写入。
_queue_version = 0
_persisted_version = -1
_persisted_path: str | None = None
# 只序列化文件写入本身（不保护内存，内存由 message_queue_lock 负责）
_queue_write_lock = threading.Lock()

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


def _bump_queue_version() -> None:
    """标记队列已变更。**必须在持有 message_queue_lock 时调用**。"""
    global _queue_version
    _queue_version += 1


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
        _bump_queue_version()
    _persist_queues()
    return item_id


def queue_list(topic_id: str) -> list[dict]:
    with message_queue_lock:
        return list(message_queue.get(topic_id, []))


def queue_remove(topic_id: str, item_id: str) -> bool:
    removed = False
    with message_queue_lock:
        items = message_queue.get(topic_id, [])
        for i, item in enumerate(items):
            if item["id"] == item_id:
                items.pop(i)
                if not items:
                    message_queue.pop(topic_id, None)
                removed = True
                break
        if removed:
            _bump_queue_version()
    # 落盘必须在锁外：_persist_queues 自己会获取同一把锁，锁内调用会自死锁
    if removed:
        _persist_queues()
    return removed


def queue_pop(topic_id: str) -> dict | None:
    item = None
    with message_queue_lock:
        items = message_queue.get(topic_id, [])
        if items:
            item = items.pop(0)
            if not items:
                message_queue.pop(topic_id, None)
        if item is not None:
            _bump_queue_version()
    # 落盘必须在锁外（同上）：否则插话消费会让整个回合卡死并锁住全部队列操作
    if item is not None:
        _persist_queues()
    return item


# ── 消息队列持久化（重启后排队消息不丢）─────────────────────────
# 队列原本只在内存里，重启即丢 —— 用户「已排队但未开始」的消息会静默消失。
# 这里落一份快照（原子写），启动时由 restore_queues() 还原。

def _queue_store_path() -> str:
    override = os.environ.get("TEA_SERVER_STATE_DB", "").strip()
    base = override or os.path.join(os.path.expanduser("~"), ".tea_agent",
                                    "server_state.db")
    return base + "_queues.json"


def _persist_queues() -> int:
    """把当前排队消息落盘（原子写）。返回条数；失败返回 -1（fail-open）。

    版本守卫：快照在 message_queue_lock 内取（连同当时的 _queue_version），
    写文件在 _queue_write_lock 内做。若一个**更晚的快照**已经落过盘，本次这个
    过期快照就直接跳过写入 —— 否则会出现「删除已落盘 → 旧快照把它写回磁盘」，
    重启后已撤回/已消费的插话复活。
    """
    global _persisted_version, _persisted_path
    try:
        with message_queue_lock:
            version = _queue_version
            data = {tid: list(items) for tid, items in message_queue.items() if items}
        path = _queue_store_path()
        with _queue_write_lock:
            if version <= _persisted_version and path == _persisted_path:
                # 已有同版本或更新的快照落盘，本次为过期写入
                return sum(len(v) for v in data.values())
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            os.replace(tmp, path)
            _persisted_version = version
            _persisted_path = path
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
            if restored:
                # 内存已变，必须推进版本：否则后续 _persist_queues 可能因
                # 版本未超过 _persisted_version 而跳过落盘，恢复结果再度丢失。
                _bump_queue_version()
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
