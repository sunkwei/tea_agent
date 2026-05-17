"""
@2026-05-16 gen by tea_agent, SummaryStore — 对话摘要 & 三级历史管理
"""
import json
import logging
from typing import Dict, List, Optional
from ._base import StoreComponent

logger = logging.getLogger("Storage.Summaries")


class SummaryStore(StoreComponent):
    """摘要管理：话题摘要、三级历史（Level1/2/3）、语义摘要、工具链摘要。"""

    # ── 话题摘要 (t_conv_summary) ──

    def get_topic_summary(self, topic_id: str) -> Optional[str]:
        c = self.conn.cursor()
        c.execute("SELECT summary FROM t_conv_summary WHERE topic_id = ?", (topic_id,))
        row = c.fetchone()
        c.close()
        return row["summary"] if row else None

    def update_topic_summary(self, topic_id: str, summary: str,
                              last_summarized_id: Optional[int] = None):
        c = self.conn.cursor()
        if last_summarized_id is not None:
            c.execute('''
                INSERT INTO t_conv_summary (topic_id, summary, last_summarized_id, last_update)
                VALUES (?, ?, ?, datetime('now', 'localtime'))
                ON CONFLICT(topic_id) DO UPDATE SET
                    summary = excluded.summary,
                    last_summarized_id = excluded.last_summarized_id,
                    last_update = datetime('now', 'localtime')
            ''', (topic_id, summary, last_summarized_id))
        else:
            c.execute('''
                INSERT INTO t_conv_summary (topic_id, summary, last_update)
                VALUES (?, ?, datetime('now', 'localtime'))
                ON CONFLICT(topic_id) DO UPDATE SET
                    summary = excluded.summary,
                    last_update = datetime('now', 'localtime')
            ''', (topic_id, summary))
        self.conn.commit()
        c.close()

    # ── 三级历史 Level 2 ──

    def get_level2(self, topic_id: str) -> list:
        c = self.conn.cursor()
        c.execute("SELECT level2_json FROM topics WHERE topic_id = ?", (topic_id,))
        row = c.fetchone()
        c.close()
        if row and row[0]:
            try:
                return json.loads(row[0])
            except json.JSONDecodeError:
                return []
        return []

    def set_level2(self, topic_id: str, level2: list):
        c = self.conn.cursor()
        c.execute(
            "UPDATE topics SET level2_json = ? WHERE topic_id = ?",
            (json.dumps(level2, ensure_ascii=False), topic_id),
        )
        self.conn.commit()
        c.close()

    # ── 三级历史 Level 3: 语义摘要 ──

    def get_semantic_summary(self, topic_id: str) -> str:
        c = self.conn.cursor()
        c.execute("SELECT semantic_summary FROM topics WHERE topic_id = ?", (topic_id,))
        row = c.fetchone()
        c.close()
        return row[0] if row and row[0] else ""

    def set_semantic_summary(self, topic_id: str, summary: str):
        c = self.conn.cursor()
        c.execute(
            "UPDATE topics SET semantic_summary = ? WHERE topic_id = ?",
            (summary, topic_id),
        )
        self.conn.commit()
        c.close()

    def get_tool_chain_summary(self, topic_id: str) -> str:
        c = self.conn.cursor()
        c.execute("SELECT tool_chain_summary FROM topics WHERE topic_id = ?", (topic_id,))
        row = c.fetchone()
        c.close()
        return row[0] if row and row[0] else ""

    def set_tool_chain_summary(self, topic_id: str, summary: str):
        c = self.conn.cursor()
        c.execute(
            "UPDATE topics SET tool_chain_summary = ? WHERE topic_id = ?",
            (summary, topic_id),
        )
        self.conn.commit()
        c.close()

    def push_to_level2(self, topic_id: str, user_msg: str, ai_msg: str,
                        files: list = None) -> list:
        """将一轮对话推入 Level 2，最多保留 5 轮，返回溢出条目。"""
        level2 = self.get_level2(topic_id)
        entry = {"user": user_msg, "assistant": ai_msg}
        if files:
            entry["files"] = files
        level2.append(entry)
        overflow = level2[:-5] if len(level2) > 5 else []
        level2 = level2[-5:]
        self.set_level2(topic_id, level2)
        return overflow

    # ── 摘要标记 ──

    def mark_as_summarized(self, conversation_id: str):
        c = self.conn.cursor()
        c.execute(
            "UPDATE conversations SET is_summarized = 1 WHERE id = ?",
            (conversation_id,),
        )
        self.conn.commit()
        c.close()

    def get_unsummarized_conversations(self, topic_id: str, limit: int = 50) -> List[Dict]:
        c = self.conn.cursor()
        if limit < 0:
            c.execute(
                "SELECT * FROM conversations WHERE topic_id = ? AND is_summarized = 0 "
                "ORDER BY stamp ASC",
                (topic_id,),
            )
        else:
            c.execute(
                "SELECT * FROM conversations WHERE topic_id = ? AND is_summarized = 0 "
                "ORDER BY stamp ASC LIMIT ?",
                (topic_id, limit),
            )
        rows = c.fetchall()
        c.close()
        result = []
        for r in rows:
            d = dict(r)
            if d.get("rounds_json"):
                try:
                    d["rounds_json_parsed"] = json.loads(d["rounds_json"])
                except (json.JSONDecodeError, TypeError):
                    d["rounds_json_parsed"] = None
            else:
                d["rounds_json_parsed"] = None
            result.append(d)
        return result
