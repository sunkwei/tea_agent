"""
P2 事件溯源存储 — Append-only Session Event Log（借鉴 DeepSeek Harness）。

核心设计：
- session_events 表是**只追加**的事件日志（append-only），是会话的审计事实源
- 事件类型: turn/start, user/message, assistant/chunk, assistant/message,
           tool/call, tool/result, turn/end, session/fork
- seq 在 topic 内严格递增（UNIQUE(topic_id, seq)），保证重放顺序
- 派生视图（derive）从事件流 fold 出消息历史，可随时重放
- 不替代 conversations 表（渐进式改造），事件日志作为审计层叠加

审计语义（用户关注点）：
- 事件不可变：无 UPDATE/DELETE 接口，只有 append
- "发生了什么"是唯一真相，"当前状态"只是投影
"""

import json
import logging

from ._component import StoreComponent

logger = logging.getLogger("Storage.Events")

# 合法事件类型（扩展点：插件可追加，但核心类型固定）
EVENT_TYPES = {
    "turn/start", "user/message", "assistant/chunk", "assistant/message",
    "tool/call", "tool/result", "turn/end", "session/fork",
}


class SessionEventStore(StoreComponent):
    """会话事件日志 — append-only + 派生/重放。"""

    # ── 写入（append-only，无修改/删除） ──

    def append_event(self, topic_id: str, event_type: str, payload: dict,
                     conversation_id: str = "") -> int:
        """追加一条事件日志（append-only）。

        Args:
            topic_id: 主题 ID
            event_type: 事件类型（见 EVENT_TYPES）
            payload: 事件负载（JSON 可序列化）
            conversation_id: 关联的会话 ID（可选）

        Returns:
            该事件的 seq 号（topic 内递增）
        """
        if event_type not in EVENT_TYPES:
            logger.warning(f"未知事件类型 {event_type!r}，仍将记录")
        ev_id = None  # id 为 AUTOINCREMENT 自增主键，无需显式提供
        payload_json = json.dumps(payload, ensure_ascii=False, default=str)
        with self._get_connection() as conn:
            c = conn.cursor()
            # 计算下一个 seq（topic 内）
            row = c.execute(
                "SELECT COALESCE(MAX(seq), 0) + 1 AS nxt FROM session_events WHERE topic_id = ?",
                (topic_id,),
            ).fetchone()
            seq = row["nxt"] if row else 1
            c.execute(
                "INSERT INTO session_events "
                "(topic_id, conversation_id, event_type, payload_json, seq, created_at) "
                "VALUES (?, ?, ?, ?, ?, datetime('now', 'localtime'))",
                (topic_id, conversation_id or None, event_type,
                 payload_json, seq),
            )
        return seq

    # ── 查询 / 重放（派生） ──

    def query_events(self, topic_id: str, event_type: str = "",
                     start_seq: int = 0, limit: int = 0) -> list[dict]:
        """按序查询事件流（重放基础）。

        Args:
            topic_id: 主题
            event_type: 过滤事件类型（空=全部）
            start_seq: 起始 seq（0=从头）
            limit: 上限（0=不限）

        Returns:
            事件 dict 列表（含 seq, event_type, payload, created_at）
        """
        c = self.conn.cursor()
        if event_type:
            c.execute(
                "SELECT * FROM session_events WHERE topic_id = ? AND event_type = ? "
                "AND seq > ? ORDER BY seq ASC" + (" LIMIT ?" if limit > 0 else ""),
                (topic_id, event_type, start_seq) + ((limit,) if limit > 0 else ()),
            )
        else:
            c.execute(
                "SELECT * FROM session_events WHERE topic_id = ? AND seq > ? "
                "ORDER BY seq ASC" + (" LIMIT ?" if limit > 0 else ""),
                (topic_id, start_seq) + ((limit,) if limit > 0 else ()),
            )
        rows = c.fetchall()
        c.close()
        result = []
        for r in rows:
            d = dict(r)
            try:
                d["payload"] = json.loads(d.pop("payload_json") or "{}")
            except (json.JSONDecodeError, TypeError):
                d["payload"] = {}
            result.append(d)
        return result

    def replay(self, topic_id: str) -> list[dict]:
        """完整重放事件流（按 seq 顺序，审计视图）。

        Returns:
            [{seq, event_type, payload, created_at, conversation_id}, ...]
        """
        return self.query_events(topic_id, limit=0)

    def derive_messages(self, topic_id: str) -> list[dict]:
        """从事件流 fold 出模型可见消息历史（派生视图，核心审计能力）。

        将 user/message 和 assistant/message 事件投影为消息列表，
        验证"模型看到的必须能从日志重建"（Model-visible means logged）。

        Returns:
            [{"role": "user"|"assistant", "content": str, "seq": int}, ...]
        """
        events = self.query_events(topic_id, limit=0)
        messages: list[dict] = []
        for ev in events:
            et = ev["event_type"]
            payload = ev["payload"]
            if et == "user/message":
                messages.append({"role": "user", "content": payload.get("content", ""),
                                 "seq": ev["seq"]})
            elif et == "assistant/message":
                messages.append({"role": "assistant", "content": payload.get("content", ""),
                                 "seq": ev["seq"]})
        return messages

    def stats(self, topic_id: str = "") -> dict:
        """事件统计（审计概览）。"""
        c = self.conn.cursor()
        if topic_id:
            c.execute("SELECT COUNT(*) n FROM session_events WHERE topic_id = ?", (topic_id,))
        else:
            c.execute("SELECT COUNT(*) n FROM session_events")
        total = c.fetchone()["n"]
        c.execute(
            "SELECT event_type, COUNT(*) n FROM session_events "
            + ("WHERE topic_id = ? " if topic_id else "")
            + "GROUP BY event_type ORDER BY n DESC",
            (topic_id,) if topic_id else (),
        )
        by_type = {r["event_type"]: r["n"] for r in c.fetchall()}
        c.close()
        return {"total": total, "by_type": by_type}

    def fork_events(self, source_topic_id: str, target_topic_id: str) -> int:
        """fork 时复制事件流到目标 topic（保留审计血统）。

        复制后目标 topic 的事件 seq 从 1 重新计数，payload 中记录
        source_topic_id + source_seq，保证血统可追溯。

        Returns:
            复制的事件数
        """
        events = self.query_events(source_topic_id, limit=0)
        if not events:
            return 0
        copied = 0
        with self._get_connection() as conn:
            c = conn.cursor()
            for i, ev in enumerate(events, start=1):
                payload = dict(ev["payload"])
                payload["_fork_source"] = {
                    "topic_id": source_topic_id,
                    "seq": ev["seq"],
                }
                c.execute(
                    "INSERT INTO session_events "
                    "(topic_id, conversation_id, event_type, payload_json, seq, created_at) "
                    "VALUES (?, ?, ?, ?, ?, datetime('now', 'localtime'))",
                    (target_topic_id, ev.get("conversation_id"),
                     ev["event_type"], json.dumps(payload, ensure_ascii=False, default=str),
                     i),
                )
                copied += 1
        return copied
