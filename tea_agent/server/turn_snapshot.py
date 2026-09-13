"""在途回合快照 — 让 server 重启后仍能恢复「已产出的流式事件」。

背景（实测）：server 的模块级状态（active_sessions / background_sessions /
background_buffers / message_queue）全部只存在内存里（见 modules/state.py 自述
"All global mutable state ... lives here"）。前端靠
``GET /api/topic/{id}/stream-buffer?since=N`` 续读，而缓冲区一重启就没了 ——
于是重启必然表现为「对话中断」。

本模块把**在途回合**的最小可恢复状态落盘（sqlite）：

- ``partial_text``       已产出的助手文本（供重启后补齐 UI，不让用户丢内容）
- ``events``             最近若干条流式事件（有界 + 字段截断，供重启后续读）
- ``last_event_index``   最后事件序号（前端 ``since`` 游标的基准）
- ``seen``               已消费到的游标（下一个可读位置）

写盘按**节流**进行（默认 0.5s 一次），避免每个 token 都落一次盘；
所有对外函数都 fail-open（异常不外抛），快照失效不得影响正常对话。
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from typing import Any

# ── 默认参数 ───────────────────────────────────────────────────
DEFAULT_DB_NAME = "server_state.db"
DEFAULT_MAX_EVENTS = 300          # 每回合保留的最近事件数
DEFAULT_MAX_FIELD = 2000          # 单字段最大字符数（超出截断）
DEFAULT_MIN_INTERVAL = 0.5        # 写盘节流间隔（秒）
DEFAULT_TTL = 6 * 3600.0          # 超过此时长未更新的 active 视为 abandoned

_STATUS_ACTIVE = "active"
_STATUS_DONE = "done"
_STATUS_ERROR = "error"
_STATUS_ABANDONED = "abandoned"

# 计入 partial_text 的事件类型（仅助手可见正文，不含 reasoning）
_TEXT_EVENT_TYPES = ("content", "token")

_lock = threading.RLock()
_last_write: dict[str, float] = {}


def db_path() -> str:
    """快照数据库路径（可用 TEA_SERVER_STATE_DB 覆盖，便于测试隔离）。"""
    override = os.environ.get("TEA_SERVER_STATE_DB", "").strip()
    if override:
        return override
    return os.path.join(os.path.expanduser("~"), ".tea_agent", DEFAULT_DB_NAME)


def _connect(path: str | None = None) -> sqlite3.Connection:
    p = path or db_path()
    parent = os.path.dirname(p)
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(p, timeout=5.0)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS turn_snapshots (
            topic_id         TEXT PRIMARY KEY,
            conv_id          TEXT DEFAULT '',
            status           TEXT NOT NULL,
            last_event_index INTEGER DEFAULT -1,
            seen             INTEGER DEFAULT 0,
            partial_text     TEXT DEFAULT '',
            events_json      TEXT DEFAULT '[]',
            created_at       REAL,
            updated_at       REAL
        )
        """
    )
    return conn


def _shrink(obj: Any, limit: int) -> Any:
    """递归截断超长字符串，避免单条事件撑爆快照。"""
    if isinstance(obj, str):
        return obj if len(obj) <= limit else obj[:limit] + "…[truncated]"
    if isinstance(obj, dict):
        return {k: _shrink(v, limit) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_shrink(v, limit) for v in obj]
    return obj


def _extract_text(event: Any) -> str:
    """从事件中提取助手可见正文（用于 partial_text 累积）。"""
    if not isinstance(event, dict):
        return ""
    if event.get("type") not in _TEXT_EVENT_TYPES:
        return ""
    for key in ("text", "delta", "content"):
        val = event.get(key)
        if isinstance(val, str) and val:
            return val
    return ""


# ── 生命周期 ───────────────────────────────────────────────────


def begin_turn(topic_id: str, conv_id: str = "", path: str | None = None) -> None:
    """标记一个回合开始（覆盖同 topic 的旧快照）。fail-open。"""
    if not topic_id:
        return
    now = time.time()
    try:
        with _lock:
            conn = _connect(path)
            try:
                conn.execute(
                    "INSERT OR REPLACE INTO turn_snapshots"
                    " (topic_id, conv_id, status, last_event_index, seen,"
                    "  partial_text, events_json, created_at, updated_at)"
                    " VALUES (?,?,?,?,?,?,?,?,?)",
                    (topic_id, conv_id or "", _STATUS_ACTIVE, -1, 0, "", "[]", now, now),
                )
                conn.commit()
            finally:
                conn.close()
            _last_write.pop(topic_id, None)
    except (sqlite3.Error, OSError, ValueError):
        pass


def ensure_turn(topic_id: str, conv_id: str = "", path: str | None = None) -> None:
    """确保存在 active 快照；已存在且未结束则**保留**（不重置已累积内容）。

    用于「接管写入」的场景：前台 SSE 断连后由后台缓冲区读取器接手，此时不能
    调用 ``begin_turn``（会清空前台已累积的 partial_text / events）。
    """
    if not topic_id:
        return
    now = time.time()
    try:
        with _lock:
            conn = _connect(path)
            try:
                row = conn.execute(
                    "SELECT status FROM turn_snapshots WHERE topic_id=?", (topic_id,)
                ).fetchone()
                if row is not None and row[0] == _STATUS_ACTIVE:
                    return
                conn.execute(
                    "INSERT OR REPLACE INTO turn_snapshots"
                    " (topic_id, conv_id, status, last_event_index, seen,"
                    "  partial_text, events_json, created_at, updated_at)"
                    " VALUES (?,?,?,?,?,?,?,?,?)",
                    (topic_id, conv_id or "", _STATUS_ACTIVE, -1, 0, "", "[]", now, now),
                )
                conn.commit()
            finally:
                conn.close()
            _last_write.pop(topic_id, None)
    except (sqlite3.Error, OSError, ValueError):
        pass


def record_event(topic_id: str, event: Any, index: int | None = None,
                 path: str | None = None,
                 min_interval: float = DEFAULT_MIN_INTERVAL,
                 force: bool = False,
                 max_events: int = DEFAULT_MAX_EVENTS,
                 max_field: int = DEFAULT_MAX_FIELD,
                 now: float | None = None) -> bool:
    """记录一条流式事件（节流写盘）。返回是否真正落盘。fail-open。

    Args:
        index: 事件序号；``None`` 时自动取 ``last_event_index + 1``，保证
            前台 SSE 与后台接管两条写入路径的序号单调（互不倒退）。
    """
    if not topic_id:
        return False
    ts = time.time() if now is None else now
    try:
        with _lock:
            if not force and ts - _last_write.get(topic_id, 0.0) < min_interval:
                return False
            conn = _connect(path)
            try:
                row = conn.execute(
                    "SELECT partial_text, events_json, seen, last_event_index, conv_id"
                    " FROM turn_snapshots WHERE topic_id=?", (topic_id,)
                ).fetchone()
                if row is None:
                    # 未 begin 过的回合（如无 topic 的临时对话）：静默跳过
                    return False
                partial, events_json, seen, last_idx, conv_id = row
                if index is None:
                    index = int(last_idx if last_idx is not None else -1) + 1
                try:
                    events = json.loads(events_json or "[]")
                    if not isinstance(events, list):
                        events = []
                except (ValueError, TypeError):
                    events = []
                events.append({"index": index, "event": _shrink(event, max_field)})
                if len(events) > max_events:
                    events = events[-max_events:]
                partial = (partial or "") + _extract_text(event)
                conn.execute(
                    "UPDATE turn_snapshots SET partial_text=?, events_json=?,"
                    " seen=?, last_event_index=?, status=?, updated_at=?"
                    " WHERE topic_id=?",
                    (partial, json.dumps(events, ensure_ascii=False),
                     max(int(seen or 0), index + 1), index, _STATUS_ACTIVE, ts,
                     topic_id),
                )
                conn.commit()
            finally:
                conn.close()
            _last_write[topic_id] = ts
        return True
    except (sqlite3.Error, OSError, ValueError, TypeError):
        return False


def finish_turn(topic_id: str, status: str = _STATUS_DONE,
                path: str | None = None) -> None:
    """标记回合结束（done/error/abandoned）。fail-open。"""
    if not topic_id:
        return
    try:
        with _lock:
            conn = _connect(path)
            try:
                conn.execute(
                    "UPDATE turn_snapshots SET status=?, updated_at=? WHERE topic_id=?",
                    (status, time.time(), topic_id),
                )
                conn.commit()
            finally:
                conn.close()
            _last_write.pop(topic_id, None)
    except (sqlite3.Error, OSError, ValueError):
        pass


# ── 读取 / 恢复 ────────────────────────────────────────────────


def read_snapshot(topic_id: str, path: str | None = None) -> dict | None:
    """读取单个回合快照（events 已反序列化）。fail-open 返回 None。"""
    if not topic_id:
        return None
    try:
        with _lock:
            conn = _connect(path)
            try:
                row = conn.execute(
                    "SELECT topic_id, conv_id, status, last_event_index, seen,"
                    " partial_text, events_json, created_at, updated_at"
                    " FROM turn_snapshots WHERE topic_id=?", (topic_id,)
                ).fetchone()
            finally:
                conn.close()
    except (sqlite3.Error, OSError, ValueError):
        return None
    if row is None:
        return None
    try:
        events = json.loads(row[6] or "[]")
    except (ValueError, TypeError):
        events = []
    return {
        "topic_id": row[0], "conv_id": row[1], "status": row[2],
        "last_event_index": row[3], "seen": row[4], "partial_text": row[5],
        "events": events if isinstance(events, list) else [],
        "created_at": row[7], "updated_at": row[8],
    }


def load_resumable(path: str | None = None, ttl: float = DEFAULT_TTL,
                   now: float | None = None) -> list[dict]:
    """返回仍在途（active 且未超时）的快照，按更新时间升序。fail-open。"""
    ts = time.time() if now is None else now
    try:
        with _lock:
            conn = _connect(path)
            try:
                rows = conn.execute(
                    "SELECT topic_id FROM turn_snapshots"
                    " WHERE status=? AND updated_at>=? ORDER BY updated_at",
                    (_STATUS_ACTIVE, ts - ttl),
                ).fetchall()
            finally:
                conn.close()
    except (sqlite3.Error, OSError, ValueError):
        return []
    return [s for s in (read_snapshot(r[0], path) for r in rows) if s]


def abandon_stale(path: str | None = None, ttl: float = DEFAULT_TTL,
                  now: float | None = None) -> int:
    """把超时未更新的 active 快照标记为 abandoned，返回处理条数。fail-open。"""
    ts = time.time() if now is None else now
    try:
        with _lock:
            conn = _connect(path)
            try:
                cur = conn.execute(
                    "UPDATE turn_snapshots SET status=?, updated_at=?"
                    " WHERE status=? AND updated_at<?",
                    (_STATUS_ABANDONED, ts, _STATUS_ACTIVE, ts - ttl),
                )
                conn.commit()
                return int(cur.rowcount or 0)
            finally:
                conn.close()
    except (sqlite3.Error, OSError, ValueError):
        return 0


def clear(path: str | None = None) -> int:
    """清空全部快照（测试/维护用）。返回删除条数。fail-open。"""
    try:
        with _lock:
            conn = _connect(path)
            try:
                cur = conn.execute("DELETE FROM turn_snapshots")
                conn.commit()
                return int(cur.rowcount or 0)
            finally:
                conn.close()
    except (sqlite3.Error, OSError, ValueError):
        return 0


def rebuild_buffers(path: str | None = None, ttl: float = DEFAULT_TTL,
                    state_module: Any = None) -> list[str]:
    """启动恢复：把在途快照重建成后台缓冲区，供前端续读。

    重建后立即补一个 ``done`` 事件并标记结束 —— 崩溃/重启时在途的回合无法
    真正继续生成（工具循环状态已随进程消失），但**已产出的内容不丢**：
    前端续读可得完整已产出事件 + partial_text，并正常收尾。

    Returns:
        被恢复的 topic_id 列表。
    """
    if state_module is None:
        try:
            from tea_agent.server.modules import state as state_module  # type: ignore
        except ImportError:
            return []
    resumed: list[str] = []
    for snap in load_resumable(path, ttl=ttl):
        topic_id = snap["topic_id"]
        try:
            state_module.create_background_buffer(topic_id)
            for item in snap["events"]:
                idx = item.get("index")
                ev = item.get("event")
                if isinstance(idx, int) and isinstance(ev, dict):
                    state_module.append_to_buffer(topic_id, ev, idx)
            next_idx = int(snap.get("seen") or 0)
            if snap.get("partial_text"):
                state_module.append_to_buffer(
                    topic_id,
                    {"type": "content", "text": snap["partial_text"], "recovered": True},
                    next_idx,
                )
                next_idx += 1
            state_module.append_to_buffer(
                topic_id,
                {"type": "done", "recovered": True,
                 "reason": "server restarted while turn was in flight"},
                next_idx,
            )
            state_module.mark_buffer_done(topic_id)
            finish_turn(topic_id, status=_STATUS_ABANDONED, path=path)
            resumed.append(topic_id)
        except (AttributeError, TypeError, ValueError):
            continue
    return resumed
