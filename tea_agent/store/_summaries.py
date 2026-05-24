"""
"""
import json
import logging
from typing import Dict, List, Optional
from ._base import StoreComponent

logger = logging.getLogger("Storage.Summaries")

class SummaryStore(StoreComponent):
    """摘要管理：话题摘要、三级历史（Level1/2/3）、语义摘要、工具链摘要。"""


    def get_topic_summary(self, topic_id: str) -> Optional[str]:
        """Get the topic summary.
        
        Args:
            topic_id: Description.
        """
        c = self.conn.cursor()
        c.execute("SELECT summary FROM t_conv_summary WHERE topic_id = ?", (topic_id,))
        row = c.fetchone()
        c.close()
        return row["summary"] if row else None

    def update_topic_summary(self, topic_id: str, summary: str,
                              last_summarized_id: Optional[int] = None):
        """Update topic summary.
        
        Args:
            topic_id: Description.
            summary: Description.
            last_summarized_id: Description.
        """
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


    def get_level2(self, topic_id: str) -> list:
        """Get the level2.
        
        Args:
            topic_id: Description.
        """
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
        """Set the level2.
        
        Args:
            topic_id: Description.
            level2: Description.
        """
        c = self.conn.cursor()
        c.execute(
            "UPDATE topics SET level2_json = ? WHERE topic_id = ?",
            (json.dumps(level2, ensure_ascii=False), topic_id),
        )
        self.conn.commit()
        c.close()


    def get_semantic_summary(self, topic_id: str) -> str:
        """Get the semantic summary.
        
        Args:
            topic_id: Description.
        """
        c = self.conn.cursor()
        c.execute("SELECT semantic_summary FROM topics WHERE topic_id = ?", (topic_id,))
        row = c.fetchone()
        c.close()
        return row[0] if row and row[0] else ""

    def set_semantic_summary(self, topic_id: str, summary: str):
        """Set the semantic summary.
        
        Args:
            topic_id: Description.
            summary: Description.
        """
        c = self.conn.cursor()
        c.execute(
            "UPDATE topics SET semantic_summary = ? WHERE topic_id = ?",
            (summary, topic_id),
        )
        self.conn.commit()
        c.close()

    def get_tool_chain_summary(self, topic_id: str) -> str:
        """Get the tool chain summary.
        
        Args:
            topic_id: Description.
        """
        c = self.conn.cursor()
        c.execute("SELECT tool_chain_summary FROM topics WHERE topic_id = ?", (topic_id,))
        row = c.fetchone()
        c.close()
        return row[0] if row and row[0] else ""

    def set_tool_chain_summary(self, topic_id: str, summary: str):
        """Set the tool chain summary.
        
        Args:
            topic_id: Description.
            summary: Description.
        """
        c = self.conn.cursor()
        c.execute(
            "UPDATE topics SET tool_chain_summary = ? WHERE topic_id = ?",
            (summary, topic_id),
        )
        self.conn.commit()
        c.close()

    def push_to_level2(self, topic_id: str, user_msg: str, ai_msg: str,
                        files: list = None, max_level2: int = 30) -> list:
        """
        2026-05-20 gen by Tea Agent, L2扩容+分层压缩

        Args:
            topic_id (str): Description.
            user_msg (str): Description.
            ai_msg (str): Description.
            files (list): Description.
            max_level2 (int): Description.

        Returns:
            list: Description.
        """
        level2 = self.get_level2(topic_id)
        entry = {"user": user_msg, "assistant": ai_msg}
        if files:
            entry["files"] = files
        level2.append(entry)
        overflow = level2[:-max_level2] if len(level2) > max_level2 else []
        level2 = level2[-max_level2:]
        self.set_level2(topic_id, level2)
        return overflow


    def get_l3_pending(self, topic_id: str) -> list:
        """
        获取该 topic 的 L3 待处理缓冲。

        Args:
            topic_id (str): Description.

        Returns:
            list: Description.
        """
        c = self.conn.cursor()
        c.execute("SELECT l3_pending_json FROM topics WHERE topic_id = ?", (topic_id,))
        row = c.fetchone()
        c.close()
        if row and row[0]:
            try:
                return json.loads(row[0])
            except json.JSONDecodeError:
                return []
        return []

    def push_l3_pending(self, topic_id: str, items: list):
        """
        将溢出条目追加到 L3 待处理缓冲。

        Args:
            topic_id (str): Description.
            items (list): Description.
        """
        existing = self.get_l3_pending(topic_id)
        existing.extend(items)
        c = self.conn.cursor()
        c.execute(
            "UPDATE topics SET l3_pending_json = ? WHERE topic_id = ?",
            (json.dumps(existing, ensure_ascii=False), topic_id),
        )
        self.conn.commit()
        c.close()

    def clear_l3_pending(self, topic_id: str):
        """
        清空 L3 待处理缓冲（摘要完成后调用）。

        Args:
            topic_id (str): Description.
        """
        c = self.conn.cursor()
        c.execute("UPDATE topics SET l3_pending_json = '' WHERE topic_id = ?", (topic_id,))
        self.conn.commit()
        c.close()

    def mark_as_summarized(self, conversation_id: str):
        """Mark as summarized.
        
        Args:
            conversation_id: Description.
        """
        c = self.conn.cursor()
        c.execute(
            "UPDATE conversations SET is_summarized = 1 WHERE id = ?",
            (conversation_id,),
        )
        self.conn.commit()
        c.close()

    def get_unsummarized_conversations(self, topic_id: str, limit: int = 50) -> List[Dict]:
        """Get the unsummarized conversations.
        
        Args:
            topic_id: Description.
            limit: Description.
        """
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
