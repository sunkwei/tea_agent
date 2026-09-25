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
import logging
import os
import re
import sqlite3
import threading
import time
from typing import Any

logger = logging.getLogger("server.turn_snapshot")

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

# 不参与窗口淘汰的事件类型（回合开头写入、对「切回后可见性」至关重要）。
# user_message 由 /api/chat 在 begin_turn 后立即以 index 0 记入：回合进行中
# 该提问尚未写库，它是切回主题时唯一的来源。
_PINNED_EVENT_TYPES = ("user_message",)

_lock = threading.RLock()
_last_write: dict[str, float] = {}
# ── 节流期间的内存累积（**关键**：节流=少写盘，不是丢数据）──────────────
# 本模块的状态原本只活在 sqlite 里，而 record_event 的节流分支在读写之前
# 就 return —— 于是 0.5s 窗口内的 token 事件被**整条丢弃**。实测 40 条快速
# 事件只落盘 1 条（丢 97.5%），而 partial_text 的用途恰是「重启后不让用户
# 丢内容」，等于该功能在最需要它的流式场景下形同虚设。
# 因此改为：事件先进内存（无 I/O，代价可忽略），到点再合并落盘。
#   _pending[topic]     尚未写盘的事件（按到达顺序）
#   _next_index[topic]  自增序号游标：前台 SSE 与后台接管共享 → 单调不倒退
#   _begun             本进程已知存在的 topic（避免每条事件都回读一次 DB）
_pending: dict[str, list] = {}
_next_index: dict[str, int] = {}
_begun: set[str] = set()
# partial_text 上限（字符）：只保尾部，避免长回合把快照撑爆
_MAX_PARTIAL_CHARS = 200000
# 极端场景（长时间不 flush）下 pending 的内存上限
_MAX_PENDING_EVENTS = 4000


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
            _drop_turn_caches(topic_id)
    except (sqlite3.Error, OSError, ValueError):
        logger.debug("begin_turn: 快照落盘失败（fail-open，不影响对话）", exc_info=True)


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
            _drop_turn_caches(topic_id)
    except (sqlite3.Error, OSError, ValueError):
        logger.debug("ensure_turn: 快照落盘失败（fail-open，不影响对话）", exc_info=True)


def _drop_turn_caches(topic_id: str) -> None:
    """清掉某个 topic 的全部进程内缓存（**必须在持有 _lock 时调用**）。"""
    for _c in (_pending, _next_index, _last_write):
        _c.pop(topic_id, None)
    _begun.discard(topic_id)


def _merge_events(existing: list, incoming: list, max_events: int) -> list:
    """按 index 归并去重，保留最近 max_events 条（回合开头的关键事件不挤出）。

    落盘时与 DB 现状归并（而非整体覆盖）：多进程同时写同一 topic 时，
    各自的 pending 互不可见，覆盖式写入会让后落盘的一方抹掉先落盘的一方。

    **保头**：``user_message``（回合开头，index 0）不参与淘汰。长回合的事件数
    可达数千（实测 1296 条），而窗口上限 300 —— 只留尾部会把提问挤出，于是
    「回合进行中切走再切回」时用户看不到自己的问题（正是该事件存在的理由）。
    """
    merged: dict[int, dict] = {}
    for item in list(existing) + list(incoming):
        if not isinstance(item, dict):
            continue
        try:
            idx = int(item.get("index"))
        except (TypeError, ValueError):
            continue
        merged[idx] = item
    if not merged:
        return []
    ordered = [merged[k] for k in sorted(merged)]
    if max_events <= 0 or len(ordered) <= max_events:
        return ordered
    tail = ordered[-max_events:]
    # 只从「将被淘汰的部分」里捞保头事件，天然不会与 tail 重复
    pinned = [
        e for e in ordered[:-max_events]
        if isinstance(e.get("event"), dict)
        and e["event"].get("type") in _PINNED_EVENT_TYPES
    ]
    return pinned + tail


def _flush_locked(topic_id: str, conn, status: str, when: float,
                  max_events: int, max_field: int) -> None:
    """把内存累积落盘（**必须在持有 _lock 时调用**）。"""
    pending = _pending.get(topic_id) or []
    row = conn.execute(
        "SELECT partial_text, events_json, seen, last_event_index, conv_id"
        " FROM turn_snapshots WHERE topic_id=?", (topic_id,)
    ).fetchone()
    if row is None:
        _pending[topic_id] = []
        return
    db_partial, db_events_json, db_seen, db_idx, conv_id = row
    try:
        db_events = json.loads(db_events_json or "[]")
        if not isinstance(db_events, list):
            db_events = []
    except (ValueError, TypeError):
        db_events = []

    incoming = [{"index": i, "event": _shrink(e, max_field)} for i, e in pending]
    events = _merge_events(db_events, incoming, max_events)

    # partial_text 只追加**本次新增**内容：DB 里已有的部分不重复累加，
    # 且按 _MAX_PARTIAL_CHARS 截尾，避免长回合把快照撑爆。
    new_text = "".join(_extract_text(e) for i, e in pending
                       if _is_text_event(e))
    partial = ((db_partial or "") + new_text)
    if len(partial) > _MAX_PARTIAL_CHARS:
        partial = partial[-_MAX_PARTIAL_CHARS:]

    max_index = max([i for i, _ in pending] + [int(db_idx if db_idx is not None else -1)])
    conn.execute(
        "UPDATE turn_snapshots SET partial_text=?, events_json=?,"
        " seen=?, last_event_index=?, status=?, updated_at=?"
        " WHERE topic_id=?",
        (partial, json.dumps(events, ensure_ascii=False),
         max(int(db_seen or 0), max_index + 1), max_index, status, when, topic_id),
    )
    conn.commit()
    _pending[topic_id] = []


def flush_pending(topic_id: str, path: str | None = None,
                  max_events: int = DEFAULT_MAX_EVENTS,
                  max_field: int = DEFAULT_MAX_FIELD) -> bool:
    """立即把该回合节流窗口内积压的事件落盘。返回是否执行了写入。fail-open。

    供「读之前先对齐磁盘」与测试使用；正常路径由 record_event 的节流判定
    与 finish_turn 负责刷盘。
    """
    if not topic_id:
        return False
    try:
        with _lock:
            if not _pending.get(topic_id):
                return False
            conn = _connect(path)
            try:
                _flush_locked(topic_id, conn, _STATUS_ACTIVE, time.time(),
                              max_events, max_field)
            finally:
                conn.close()
            _last_write[topic_id] = time.time()
        return True
    except (sqlite3.Error, OSError, ValueError, TypeError):
        return False


def _is_text_event(event: Any) -> bool:
    """是否计入助手正文（content/token，不含 reasoning/tool）。"""
    return isinstance(event, dict) and event.get("type") in _TEXT_EVENT_TYPES


def record_event(topic_id: str, event: Any, index: int | None = None,
                 path: str | None = None,
                 min_interval: float = DEFAULT_MIN_INTERVAL,
                 force: bool = False,
                 max_events: int = DEFAULT_MAX_EVENTS,
                 max_field: int = DEFAULT_MAX_FIELD,
                 now: float | None = None) -> bool:
    """记录一条流式事件。返回是否**已接收**（不是"是否已写盘"）。fail-open。

    节流只作用于**磁盘写入**，事件本身一律先入内存：0.5s 窗口内的 token 若
    直接丢弃，恢复出来的 partial_text 与 events 就会缺一大段 —— 而本模块的
    存在理由正是"重启后不让用户丢内容"。

    Args:
        index: 事件序号；``None`` 时自动取上一个序号 +1，保证前台 SSE 与
            后台接管两条写入路径的序号单调（互不倒退）。
        force: 跳过节流立即落盘（终止事件用）。
    """
    if not topic_id:
        return False
    ts_now = time.time() if now is None else now
    try:
        with _lock:
            if topic_id not in _begun and not _adopt_locked(topic_id, path):
                # 未 begin 过的回合（如无 topic 的临时对话）：静默跳过
                return False
            if index is None:
                index = _next_index.get(topic_id, 0)
            try:
                index = int(index)
            except (TypeError, ValueError):
                return False
            _pending.setdefault(topic_id, []).append((index, event))
            # 序号游标前进（显式传入更大 index 时接管后续自增值）
            _next_index[topic_id] = max(_next_index.get(topic_id, index + 1), index + 1)
            # 极端场景（长时间不 flush，如客户端挂住）下限制内存占用
            _cap = min(max(max_events * 2, 1), _MAX_PENDING_EVENTS)
            if len(_pending[topic_id]) > _cap:
                _pending[topic_id] = _pending[topic_id][-_cap:]

            if force or (ts_now - _last_write.get(topic_id, 0.0)) >= min_interval:
                conn = _connect(path)
                try:
                    _flush_locked(topic_id, conn, _STATUS_ACTIVE, ts_now,
                                  max_events, max_field)
                finally:
                    conn.close()
                _last_write[topic_id] = ts_now
        return True
    except (sqlite3.Error, OSError, ValueError, TypeError):
        return False


def _adopt_locked(topic_id: str, path: str | None) -> bool:
    """进程重启/接管时把 DB 中已存在的回合载入内存缓存；返回该 topic 是否存在。

    **必须在持有 _lock 时调用**。只在首次遇到未知 topic 时走一次 SELECT，
    稳态路径不额外读盘。
    """
    conn = _connect(path)
    try:
        row = conn.execute(
            "SELECT events_json, last_event_index, partial_text"
            " FROM turn_snapshots WHERE topic_id=?", (topic_id,)
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return False
    try:
        events = json.loads(row[0] or "[]")
        if not isinstance(events, list):
            events = []
    except (ValueError, TypeError):
        events = []
    _pending.setdefault(topic_id, [])
    last_idx = int(row[1] if row[1] is not None else -1)
    _next_index[topic_id] = last_idx + 1
    _begun.add(topic_id)
    return True


def finish_turn(topic_id: str, status: str = _STATUS_DONE,
                path: str | None = None,
                max_events: int = DEFAULT_MAX_EVENTS,
                max_field: int = DEFAULT_MAX_FIELD) -> None:
    """标记回合结束（done/error/abandoned），并把节流窗口内残留的事件**先落盘**。

    不 flush 就结束，会让回合尾部的 token 永久丢失 —— 而那正是用户最关心的
    最后一段内容。fail-open。
    """
    if not topic_id:
        return
    try:
        with _lock:
            if topic_id in _begun:
                conn = _connect(path)
                try:
                    _flush_locked(topic_id, conn, status, time.time(),
                                  max_events, max_field)
                    conn.execute(
                        "UPDATE turn_snapshots SET status=?, updated_at=?"
                        " WHERE topic_id=?", (status, time.time(), topic_id))
                    conn.commit()
                finally:
                    conn.close()
                _drop_turn_caches(topic_id)
                return
            conn = _connect(path)
            try:
                conn.execute(
                    "UPDATE turn_snapshots SET status=?, updated_at=? WHERE topic_id=?",
                    (status, time.time(), topic_id),
                )
                conn.commit()
            finally:
                conn.close()
            _drop_turn_caches(topic_id)
    except (sqlite3.Error, OSError, ValueError):
        logger.debug("finish_turn: 快照落盘失败（fail-open，不影响对话）", exc_info=True)


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
    if not isinstance(events, list):
        events = []

    # 合并尚未落盘的事件（节流窗口内的 token 只在内存里）。不合并的话，
    # 「记录了但读不到」会被误读成丢数据，且重启续读拿到的是残缺内容。
    with _lock:
        pending = list(_pending.get(topic_id) or [])
    if pending:
        events = _merge_events(
            events, [{"index": i, "event": e} for i, e in pending], DEFAULT_MAX_EVENTS)
    last_idx = int(row[3] if row[3] is not None else -1)
    if pending:
        last_idx = max(last_idx, max(i for i, _ in pending))
    seen = int(row[4] or 0)
    if pending:
        seen = max(seen, last_idx + 1)

    # partial_text 同样要合并 pending 正文：只补事件不补文本，等于换个地方丢内容
    partial = row[5] or ""
    if pending:
        extra = "".join(_extract_text(e) for i, e in pending
                        if _is_text_event(e))
        if extra:
            partial = (partial + extra)
            if len(partial) > _MAX_PARTIAL_CHARS:
                partial = partial[-_MAX_PARTIAL_CHARS:]

    return {
        "topic_id": row[0], "conv_id": row[1], "status": row[2],
        "last_event_index": last_idx, "seen": seen, "partial_text": partial,
        "events": events,
        "created_at": row[7], "updated_at": row[8],
    }


def snapshot_image_ids(path: str | None = None) -> set[int] | None:
    """收集快照事件里引用的图片 id（``img:<n>``），供孤儿图片清理排除。

    未归属（``conversation_id=''``）的图片有两种来源：崩溃遗留的孤儿，以及
    **正在恢复中的回合**要显示的内容。后者绝不能删 —— 判据就是「是否被快照引用」。

    Returns:
        图片 id 集合；**读取失败返回 None**（表示"未知"，调用方应跳过清理）。
        这里刻意不返回空集：空集会被当成"无引用"，从而把待恢复回合的图片一并删掉。
    """
    try:
        with _lock:
            conn = _connect(path)
            try:
                rows = conn.execute("SELECT events_json FROM turn_snapshots").fetchall()
            finally:
                conn.close()
    except (sqlite3.Error, OSError, ValueError):
        return None
    ids: set[int] = set()
    for row in rows:
        raw = row[0] if row else None
        if not raw:
            continue
        for m in re.finditer(r"img:(\d+)", raw):
            ids.add(int(m.group(1)))
    return ids


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
                n = int(cur.rowcount or 0)
            finally:
                conn.close()
            # 进程内缓存必须同步清空：否则被清掉的回合仍会从 _pending 里把旧事件
            # 合并进后续读取（DB 已空却仍读得到内容），跨回合/跨测试成串。
            _pending.clear()
            _next_index.clear()
            _begun.clear()
            _last_write.clear()
        return n
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
            # partial_text 是由 content/token 事件累积出来的 —— 若恢复的事件里
            # 已含 content，再补一条会造成**文本重复渲染**（端到端实测踩中：
            # 事件流为 甲 / 乙 / 甲乙，用户会看到内容出现两遍）。
            # 仅当事件被裁剪或缺失、partial_text 是唯一残留文本时才用它兜底。
            _has_content = any(
                isinstance(item.get("event"), dict)
                and item["event"].get("type") == "content"
                for item in snap["events"]
            )
            if snap.get("partial_text") and not _has_content:
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
