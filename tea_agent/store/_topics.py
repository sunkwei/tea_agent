"""
"""
import logging

from ._component import StoreComponent

logger = logging.getLogger("Storage.Topics")

class TopicStore(StoreComponent):
    """主题管理：创建、更新、删除、列表，以及 Token 消耗统计。"""

    # ── 主题 CRUD ──

    def create_topic(self, title: str, topic_id: str = None) -> str:
        """Create topic.

        Args:
            title: Description.
            topic_id: Description.
        """
        # 使用临时连接
        with self._get_connection() as conn:
            conn.row_factory = __import__('sqlite3').Row
            c = conn.cursor()
            tid = topic_id or self._new_id()
            c.execute("INSERT INTO topics (topic_id, title, create_stamp, last_update_stamp) VALUES (?, ?, datetime('now', 'localtime'), datetime('now', 'localtime'))", (tid, title))
            conn.commit()
            return tid

    def update_topic_title(self, topic_id: str, new_title: str):
        """Update topic title. ※ 前缀的主题标题不可被自动摘要覆盖。

        Args:
            topic_id: Description.
            new_title: Description.
        """
        old = self.get_topic(topic_id)
        if old:
            old_title = old.get("title") or ""
            if old_title.startswith("chat_room_"):
                logger.debug(f"拒绝修改 chat_room 主题标题: {old_title}")
                return
            # ※ 前缀表示手动设置的标题，禁止自动摘要覆盖（竞态安全）
            if old_title.startswith("※") and not new_title.startswith("※"):
                logger.debug(f"拒绝覆盖 ※ 手动标题: {old_title}")
                return
        c = self.conn.cursor()
        c.execute(
            "UPDATE topics SET title = ? WHERE topic_id = ?",
            (new_title, topic_id),
        )
        self.conn.commit()
        c.close()

    def update_topic_active(self, topic_id: str, active: int = 1):
        """设置主题活跃状态。active=1 活跃，active=0 停用。

        Args:
            topic_id: 主题ID
            active: 1=活跃, 0=停用
        """
        c = self.conn.cursor()
        c.execute(
            "UPDATE topics SET is_active = ?, last_update_stamp = datetime('now', 'localtime') WHERE topic_id = ?",
            (active, topic_id),
        )
        self.conn.commit()
        c.close()

    def get_drift_count(self, topic_id: str) -> int:
        """获取主题漂移计数"""
        c = self.conn.cursor()
        c.execute("SELECT drift_count FROM topics WHERE topic_id = ?", (topic_id,))
        row = c.fetchone()
        c.close()
        return row["drift_count"] if row and row["drift_count"] is not None else 0

    def increment_drift_count(self, topic_id: str) -> int:
        """递增并返回主题漂移计数"""
        c = self.conn.cursor()
        c.execute(
            "UPDATE topics SET drift_count = COALESCE(drift_count, 0) + 1 WHERE topic_id = ?",
            (topic_id,),
        )
        self.conn.commit()
        c.close()
        return self.get_drift_count(topic_id)

    def delete_topic(self, topic_id: str):
        """Hard delete a topic and all associated data (cascade).

        Deletes agent_rounds, images, conversations,
        topic_token_stats, t_conv_summary, memories, and the topic itself.

        Args:
            topic_id: The UUID of the topic to delete.
        """
        c = self.conn.cursor()
        try:
            # 级联删除：先删孙表，再删子表，最后删主表
            c.execute(
                "DELETE FROM agent_rounds WHERE conversation_id IN "
                "(SELECT id FROM conversations WHERE topic_id = ?)",
                (topic_id,))
            c.execute(
                "DELETE FROM images WHERE conversation_id IN "
                "(SELECT id FROM conversations WHERE topic_id = ?)",
                (topic_id,))
            c.execute("DELETE FROM conversations WHERE topic_id = ?", (topic_id,))
            c.execute("DELETE FROM topic_token_stats WHERE topic_id = ?", (topic_id,))
            c.execute("DELETE FROM t_conv_summary WHERE topic_id = ?", (topic_id,))
            c.execute("DELETE FROM memories WHERE source_topic_id = ?", (topic_id,))
            c.execute("DELETE FROM topics WHERE topic_id = ?", (topic_id,))
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        finally:
            c.close()

    def get_topic(self, topic_id: str) -> dict | None:
        """Get the topic.

        Args:
            topic_id: Description.
        """
        c = self.conn.cursor()
        c.execute("SELECT * FROM topics WHERE topic_id = ?", (topic_id,))
        r = c.fetchone()
        c.close()
        return dict(r) if r else None

    def get_topic_system_prompt(self, topic_id: str) -> str | None:
        """获取主题的自定义系统提示词。

        Args:
            topic_id: 主题ID

        Returns:
            自定义 system_prompt 文本，若无则返回 None
        """
        c = self.conn.cursor()
        c.execute("SELECT system_prompt FROM topics WHERE topic_id = ?", (topic_id,))
        row = c.fetchone()
        c.close()
        if row:
            return row["system_prompt"] if row["system_prompt"] else None
        return None

    def set_topic_system_prompt(self, topic_id: str, system_prompt: str | None):
        """设置主题的自定义系统提示词。

        Args:
            topic_id: 主题ID
            system_prompt: 系统提示词，传 None 或空字符串可清除自定义设置
        """
        c = self.conn.cursor()
        val = system_prompt if system_prompt else None
        c.execute(
            "UPDATE topics SET system_prompt = ?, last_update_stamp = datetime('now', 'localtime') WHERE topic_id = ?",
            (val, topic_id),
        )
        self.conn.commit()
        c.close()

    def list_topics(self) -> list[dict]:
        """List topics (only active ones)."""
        c = self.conn.cursor()
        c.execute('''
            SELECT t.*,
                   COALESCE(s.total_tokens, 0) as total_tokens,
                   COALESCE(s.conversation_count, 0) as conversation_count
            FROM topics t
            LEFT JOIN topic_token_stats s ON t.topic_id = s.topic_id
            WHERE t.is_active = 1
            ORDER BY t.last_update_stamp DESC
        ''')
        rows = c.fetchall()
        c.close()
        return [dict(r) for r in rows]

    # ── Token 统计 ──

    def add_topic_tokens(
        self, topic_id: str,
        total_tokens: int = 0, prompt_tokens: int = 0, completion_tokens: int = 0,
        cheap_tokens: int = 0, cheap_prompt_tokens: int = 0, cheap_completion_tokens: int = 0,
        embedding_tokens: int = 0, embedding_prompt_tokens: int = 0,
    ):
        """Add topic tokens.

        Args:
            topic_id: Description.
            total_tokens: Description.
            prompt_tokens: Description.
            completion_tokens: Description.
            cheap_tokens: Description.
            cheap_prompt_tokens: Description.
            cheap_completion_tokens: Description.
            embedding_tokens: Description.
            embedding_prompt_tokens: Description.
        """
        has_main = total_tokens > 0 or prompt_tokens > 0 or completion_tokens > 0
        has_cheap = cheap_tokens > 0 or cheap_prompt_tokens > 0 or cheap_completion_tokens > 0
        has_embedding = embedding_tokens > 0 or embedding_prompt_tokens > 0
        if not has_main and not has_cheap and not has_embedding:
            return
        c = self.conn.cursor()
        c.execute('''
            INSERT INTO topic_token_stats (
                topic_id, total_tokens, total_prompt_tokens, total_completion_tokens,
                total_cheap_tokens, total_cheap_prompt_tokens, total_cheap_completion_tokens,
                total_embedding_tokens, total_embedding_prompt_tokens,
                conversation_count, last_update
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, datetime('now', 'localtime'))
            ON CONFLICT(topic_id) DO UPDATE SET
                total_tokens = total_tokens + excluded.total_tokens,
                total_prompt_tokens = total_prompt_tokens + excluded.total_prompt_tokens,
                total_completion_tokens = total_completion_tokens + excluded.total_completion_tokens,
                total_cheap_tokens = total_cheap_tokens + excluded.total_cheap_tokens,
                total_cheap_prompt_tokens = total_cheap_prompt_tokens + excluded.total_cheap_prompt_tokens,
                total_cheap_completion_tokens = total_cheap_completion_tokens + excluded.total_cheap_completion_tokens,
                total_embedding_tokens = total_embedding_tokens + excluded.total_embedding_tokens,
                total_embedding_prompt_tokens = total_embedding_prompt_tokens + excluded.total_embedding_prompt_tokens,
                conversation_count = conversation_count + 1,
                last_update = datetime('now', 'localtime')
        ''', (topic_id, total_tokens, prompt_tokens, completion_tokens,
              cheap_tokens, cheap_prompt_tokens, cheap_completion_tokens,
              embedding_tokens, embedding_prompt_tokens))
        self.conn.commit()
        c.close()

    def accumulate_pending_cheap_tokens(self, topic_id: str, usage: dict):
        """累加待显示的便宜模型 token（异步摘要完成后调用，下一轮显示的轮合并）。"""
        import json as _json_pt
        if not usage or usage.get("total_tokens", 0) <= 0:
            return
        # 读取已有 pending
        existing = self.get_topic_tokens(topic_id).get("pending_cheap_tokens_json", "")
        prev = {}
        if existing:
            try:
                prev = _json_pt.loads(existing)
            except Exception:
                logger.exception('op_failed')

        # 合并
        for k in ("total_tokens", "prompt_tokens", "completion_tokens"):
            prev[k] = prev.get(k, 0) + usage.get(k, 0)
        c = self.conn.cursor()
        c.execute(
            "INSERT INTO topic_token_stats (topic_id, pending_cheap_tokens_json) "
            "VALUES (?, ?) ON CONFLICT(topic_id) DO UPDATE SET "
            "pending_cheap_tokens_json = excluded.pending_cheap_tokens_json",
            (topic_id, _json_pt.dumps(prev)),
        )
        self.conn.commit()
        c.close()

    def get_and_clear_pending_cheap_tokens(self, topic_id: str) -> dict:
        """读取并清零待显示的便宜模型 token。返回 {'total_tokens': N, ...}。"""
        import json as _json_pt
        row = self.get_topic_tokens(topic_id)
        existing = row.get("pending_cheap_tokens_json", "")
        result = {}
        if existing:
            try:
                result = _json_pt.loads(existing)
            except Exception:
                logger.exception('op_failed')

        # 清零
        c = self.conn.cursor()
        c.execute(
            "INSERT INTO topic_token_stats (topic_id, pending_cheap_tokens_json) "
            "VALUES (?, '') ON CONFLICT(topic_id) DO UPDATE SET "
            "pending_cheap_tokens_json = ''",
            (topic_id,),
        )
        self.conn.commit()
        c.close()
        return result

    def get_topic_tokens(self, topic_id: str) -> dict:
        """Get the topic tokens.

        Args:
            topic_id: Description.
        """
        c = self.conn.cursor()
        c.execute("SELECT * FROM topic_token_stats WHERE topic_id = ?", (topic_id,))
        row = c.fetchone()
        c.close()
        if row:
            return dict(row)
        return {
            "topic_id": topic_id,
            "total_tokens": 0, "total_prompt_tokens": 0, "total_completion_tokens": 0,
            "total_cheap_tokens": 0, "total_cheap_prompt_tokens": 0, "total_cheap_completion_tokens": 0,
            "total_embedding_tokens": 0, "total_embedding_prompt_tokens": 0,
            "conversation_count": 0,
        }
