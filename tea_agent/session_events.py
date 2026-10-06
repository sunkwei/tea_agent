"""session_events — append-only 会话事件日志 + 纯函数投影（借鉴 dsh SessionEvent）。

事实与视图分离：
- **事实**：`SessionEvent` 追加写（append-only），永不改写/删除
- **视图**：L1/L2/L3、turn_snapshot 等一律由 `project_*` 纯函数从事件重放得出，
  同一事件序列必得同一视图 —— 历史可审计、可重放、可重建

生命周期事件（借鉴 dsh 生命周期契约）：
- `turn_start` / `turn_end`：用户回合边界
- `step_request`：一次模型请求（含 starts_request_series=前缀缓存重置点）
- `tool_call` / `tool_result`：工具调用与结果
- `summary` / `memory`：后处理产物

不变式：seq 严格递增且连续；事件只追加。
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field

logger = logging.getLogger("session_events")

EVENT_TYPES = frozenset(
    {
        "turn_start",
        "turn_end",
        "step_request",
        "tool_call",
        "tool_result",
        "summary",
        "memory",
    }
)


@dataclass(frozen=True)
class SessionEvent:
    """一条不可变会话事件。"""

    seq: int
    topic_id: str
    type: str
    turn: int
    step: int = 0
    data: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> SessionEvent:
        return cls(
            seq=int(d["seq"]),
            topic_id=str(d["topic_id"]),
            type=str(d["type"]),
            turn=int(d.get("turn", 0)),
            step=int(d.get("step", 0)),
            data=dict(d.get("data") or {}),
        )


def append_event(log: list[SessionEvent], *, topic_id: str, type: str, turn: int, step: int = 0, data: dict | None = None) -> SessionEvent:
    """追加事件（append-only）：seq 自增，类型/连续性违例抛 ValueError。

    Args:
        log: 现有事件日志（原地追加）
        topic_id: 主题 ID
        type: 事件类型（须在 EVENT_TYPES）
        turn/step: 生命周期坐标
        data: 事件负载

    Returns:
        新追加的事件
    """
    if type not in EVENT_TYPES:
        raise ValueError(f"未知事件类型: {type}")
    expected = (log[-1].seq + 1) if log else 1
    ev = SessionEvent(seq=expected, topic_id=topic_id, type=type, turn=turn, step=step, data=dict(data or {}))
    log.append(ev)
    return ev


def replay(rows: list[dict]) -> list[SessionEvent]:
    """从行记录重放事件序列（校验 seq 连续，坏行跳过并告警）。"""
    out: list[SessionEvent] = []
    for r in rows:
        try:
            ev = SessionEvent.from_dict(r)
        except Exception as e:  # noqa: BLE001
            logger.warning("坏事件行跳过: %s", e)
            continue
        expected = (out[-1].seq + 1) if out else 1
        if ev.seq != expected:
            logger.warning("事件序列断裂: got %s expect %s（跳过）", ev.seq, expected)
            continue
        out.append(ev)
    return out


# ═══ 纯函数投影 ══════════════════════════════════════════


def persist_step_request(storage, topic_id: str, turn: int, step: int, data: dict | None = None) -> None:
    """把 step_request 事件持久化到 storage.events（旁路 fail-open，永不抛出）。"""
    try:
        evs = getattr(storage, "events", None)
        if evs is None or not hasattr(evs, "append_event"):
            return
        evs.append_event(topic_id or "unknown", "step/request", data or {}, "")
    except Exception as e:  # noqa: BLE001 — 旁路观测不得影响请求
        logger.debug("session_events 持久化跳过: %s", e)


def project_l1(events: list[SessionEvent]) -> list[dict]:
    """L1 视图投影：事件流 → 回合明细消息序列（step/工具调用链）。

    纯函数：同一事件序列必得同一视图。
    """
    msgs: list[dict] = []
    for ev in events:
        if ev.type == "step_request":
            msgs.append({"role": "step", "turn": ev.turn, "starts_request_series": ev.data.get("starts_request_series")})
        elif ev.type == "tool_call":
            msgs.append({"role": "tool_call", "turn": ev.turn, "name": ev.data.get("name", "")})
        elif ev.type == "tool_result":
            msgs.append({"role": "tool_result", "turn": ev.turn, "status": ev.data.get("status", "")})
    return msgs


def project_l2(events: list[SessionEvent], window: int = 10) -> list[dict]:
    """L2 视图投影：最近 window 个 turn 的滚动窗口条目（统计型，纯函数）。"""
    turns = project_turns(events)
    return turns[-window:] if window and window > 0 else turns


def project_l3(events: list[SessionEvent]) -> dict:
    """L3 视图投影：全事件聚合摘要（统计型，纯函数）。"""
    turns = project_turns(events)
    steps = project_steps(events)
    return {
        "topic_summary": (f"{len(turns)} turns / {len(steps)} steps / {sum(t['tool_calls'] for t in turns)} tool_calls"),
        "series_resets": sum(1 for s in steps if s["series_reset"]),
    }


def project_turns(events: list[SessionEvent]) -> list[dict]:
    """投影：每个 turn 的边界与步进统计（turn_snapshot 事实源）。"""
    turns: dict[int, dict] = {}
    for ev in events:
        t = turns.setdefault(
            ev.turn,
            {
                "turn": ev.turn,
                "started": False,
                "ended": False,
                "steps": 0,
                "series_resets": 0,
                "tool_calls": 0,
            },
        )
        if ev.type == "turn_start":
            t["started"] = True
        elif ev.type == "turn_end":
            t["ended"] = True
        elif ev.type == "step_request":
            t["steps"] += 1
            if ev.data.get("starts_request_series"):
                t["series_resets"] += 1
        elif ev.type == "tool_call":
            t["tool_calls"] += 1
    return [turns[k] for k in sorted(turns)]


def project_steps(events: list[SessionEvent]) -> list[dict]:
    """投影：step 序列（step 请求 + 工具调用，L1 视图的骨架）。"""
    out = []
    for ev in events:
        if ev.type == "step_request":
            out.append({"turn": ev.turn, "step": ev.step, "series_reset": bool(ev.data.get("starts_request_series")), "tools": []})
        elif ev.type == "tool_call" and out:
            out[-1]["tools"].append(ev.data.get("name", ""))
    return out
