"""
InterruptionStore — 打断事件持久化（打断知识闭环 M2）。

记录「用户打断」的结构化事件：打断发生在哪一轮、执行什么工具、
已生成内容、后续用户消息与分类结果（corrected/abandoned/silent）。

设计要点：
- 短连接 + 线程安全（继承 StoreComponent）
- 事件表独立于 conversations，conversation_id 允许 NULL（打断发生在入库前）
- 写入失败仅记日志不抛异常（不阻塞打断返回路径）
"""

from __future__ import annotations

import logging

from ._component import StoreComponent

logger = logging.getLogger("InterruptionStore")


class InterruptionStore(StoreComponent):
    """打断事件 CRUD 与统计。"""

    _TABLE = "interruption_events"

    def insert_interruption_event(self, ev: dict) -> str:
        """插入一条打断事件。返回事件 id。

        Args:
            ev: 事件字典，键：topic_id/timestamp/iteration/tool_name/
                tool_args_summary/partial_reply/phase/status/conversation_id

        Returns:
            str: 新事件 id（失败返回空串，不抛出）
        """
        event_id = ev.get("id") or self._new_id()
        try:
            c = self.conn.cursor()
            c.execute(
                f"INSERT INTO {self._TABLE} "
                "(id, topic_id, conversation_id, timestamp, iteration, tool_name, "
                " tool_args_summary, partial_reply, phase, status, classification, "
                " similarity, followup_user_msg, followup_ts) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    event_id,
                    ev.get("topic_id"),
                    ev.get("conversation_id"),
                    ev.get("timestamp"),
                    ev.get("iteration"),
                    ev.get("tool_name"),
                    ev.get("tool_args_summary"),
                    ev.get("partial_reply"),
                    ev.get("phase", "tool_loop"),
                    ev.get("status", "pending"),
                    ev.get("classification"),
                    ev.get("similarity"),
                    ev.get("followup_user_msg"),
                    ev.get("followup_ts"),
                ),
            )
            c.connection.commit()
            c.close()
        except Exception:
            logger.exception("insert_interruption_event failed")
            return ""
        return event_id

    def update_interruption_classification(
        self,
        event_id: str,
        classification: str,
        similarity: float | None,
        followup_msg: str | None,
        followup_ts: str | None,
    ) -> bool:
        """打断事件分类后回写（下一条消息进入时调用）。"""
        try:
            c = self.conn.cursor()
            c.execute(
                f"UPDATE {self._TABLE} SET status='classified', classification=?, "
                "similarity=?, followup_user_msg=?, followup_ts=? WHERE id=?",
                (classification, similarity, followup_msg, followup_ts, event_id),
            )
            c.connection.commit()
            c.close()
            return True
        except Exception:
            logger.exception("update_interruption_classification failed")
            return False

    def get_interruption_event(self, event_id: str) -> dict | None:
        """按 id 查询事件。"""
        try:
            c = self.conn.cursor()
            c.execute(
                f"SELECT * FROM {self._TABLE} WHERE id=?", (event_id,)
            )
            row = c.fetchone()
            c.close()
            return dict(row) if row else None
        except Exception:
            logger.exception("get_interruption_event failed")
            return None

    def query_interruptions(
        self,
        topic_id: str | None = None,
        status: str | None = None,
        since: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """查询打断事件，按时间倒序。

        Args:
            topic_id: 按主题过滤
            status: pending / classified
            since: ISO 时间戳下限（>=）
            limit: 返回上限
        """
        sql = f"SELECT * FROM {self._TABLE} WHERE 1=1"
        params: list = []
        if topic_id:
            sql += " AND topic_id=?"
            params.append(topic_id)
        if status:
            sql += " AND status=?"
            params.append(status)
        if since:
            sql += " AND timestamp>=?"
            params.append(since)
        sql += " ORDER BY timestamp DESC LIMIT ?"
        params.append(int(limit))
        try:
            c = self.conn.cursor()
            c.execute(sql, params)
            rows = c.fetchall()
            c.close()
            return [dict(r) for r in rows]
        except Exception:
            logger.exception("query_interruptions failed")
            return []

    def stats_interruptions(self, since: str | None = None) -> list[dict]:
        """按 tool_name 聚合打断统计。

        Returns:
            [{tool_name, count, last_ts}]
        """
        sql = (
            f"SELECT tool_name, COUNT(*) AS count, MAX(timestamp) AS last_ts "
            f"FROM {self._TABLE} WHERE tool_name IS NOT NULL AND tool_name != ''"
        )
        params: list = []
        if since:
            sql += " AND timestamp>=?"
            params.append(since)
        sql += " GROUP BY tool_name ORDER BY count DESC"
        try:
            c = self.conn.cursor()
            c.execute(sql, params)
            rows = c.fetchall()
            c.close()
            return [dict(r) for r in rows]
        except Exception:
            logger.exception("stats_interruptions failed")
            return []

    def cleanup_old_events(self, keep_days: int = 30) -> int:
        """清理超过保留期的旧事件（幂等，供 M4 定时任务调用）。"""
        try:
            c = self.conn.cursor()
            c.execute(
                f"DELETE FROM {self._TABLE} WHERE timestamp < "
                "datetime('now', 'localtime', ?)",
                (f"-{int(keep_days)} days",),
            )
            deleted = c.rowcount
            c.connection.commit()
            c.close()
            return deleted
        except Exception:
            logger.exception("cleanup_old_events failed")
            return 0
