"""
"""
import json
import base64
import os
import queue
import sqlite3
import threading
import logging
from typing import Dict, List, Optional
from ._component import StoreComponent

logger = logging.getLogger("Storage.Conversations")

class ConversationStore(StoreComponent):
    """对话管理：保存消息、更新轮次、查询对话历史、Agent 轮次记录。"""

    def save_msg(self, topic_id: str, user_msg, ai_msg: str, is_func: bool,
                 update_active_cb=None, auto_embed_cb=None) -> str:
        """
        新增一条对话，返回 conversation_id。
        若 user_msg 含图片，自动读取文件存入 images 表并转为 Base64。
        """
        conv_id = self._new_id()

        # 处理图片：存入 images 表 + 转换为 Base64
        if isinstance(user_msg, dict) and "images" in user_msg:
            raw_imgs = user_msg["images"]
            processed_imgs = []
            c_img = self.conn.cursor()
            for img_item in raw_imgs:
                if os.path.isfile(img_item):
                    try:
                        with open(img_item, "rb") as f:
                            blob = f.read()
                        ext = os.path.splitext(img_item)[1].lower()
                        mime_map = {
                            ".png": "image/png", ".jpg": "image/jpeg",
                            ".jpeg": "image/jpeg", ".gif": "image/gif",
                            ".webp": "image/webp",
                        }
                        mime = mime_map.get(ext, "image/png")
                        c_img.execute(
                            "INSERT INTO images (conversation_id, image_blob, mime_type) VALUES (?, ?, ?)",
                            (conv_id, blob, mime),
                        )
                        b64 = base64.b64encode(blob).decode("utf-8")
                        processed_imgs.append(f"data:{mime};base64,{b64}")
                    except Exception as e:
                        logger.error(f"Failed to process image {img_item}: {e}")
                        processed_imgs.append(img_item)
                else:
                    processed_imgs.append(img_item)
            user_msg["images"] = processed_imgs
            c_img.close()

        if isinstance(user_msg, dict):
            user_msg_json = json.dumps(user_msg, ensure_ascii=False)
            user_msg_text = user_msg.get("text", "")
        else:
            user_msg_json = str(user_msg)
            user_msg_text = str(user_msg)

        c = self.conn.cursor()
        c.execute(
            "INSERT INTO conversations (id, topic_id, user_msg, ai_msg, is_func_calling, stamp) "
            "VALUES (?, ?, ?, ?, ?, datetime('now', 'localtime'))",
            (conv_id, topic_id, user_msg_json, ai_msg, 1 if is_func else 0),
        )
        self.conn.commit()
        c.close()

        if update_active_cb:
            update_active_cb(topic_id)

        if user_msg_text and user_msg_text.strip():
            if auto_embed_cb:
                auto_embed_cb(conv_id, user_msg_text.strip())
            else:
                self._auto_embed_async(conv_id, user_msg_text.strip())

        return conv_id

    def update_msg_rounds(
        self, conversation_id: int, ai_msg: str, is_func_calling: bool,
        rounds: Optional[List[Dict]] = None,
    ):
        """Update msg rounds.
        
        Args:
            conversation_id: Description.
            ai_msg: Description.
            is_func_calling: Description.
            rounds: Description.
        """
        rounds_json = json.dumps(rounds, ensure_ascii=False) if rounds else None
        c = self.conn.cursor()
        c.execute(
            "UPDATE conversations SET ai_msg = ?, is_func_calling = ?, rounds_json = ? WHERE id = ?",
            (ai_msg, 1 if is_func_calling else 0, rounds_json, conversation_id),
        )
        self.conn.commit()
        c.close()

    def save_agent_round(
        self, conversation_id: int, round_num: int, role: str, content: str,
        tool_calls: Optional[List[Dict]] = None, tool_call_id: Optional[str] = None,
    ):
        """Save agent round.
        
        Args:
            conversation_id: Description.
            round_num: Description.
            role: Description.
            content: Description.
            tool_calls: Description.
            tool_call_id: Description.
        """
        tc_json = json.dumps(tool_calls, ensure_ascii=False) if tool_calls else None
        c = self.conn.cursor()
        c.execute(
            "INSERT INTO agent_rounds (conversation_id, round_num, role, content, tool_calls, tool_call_id, stamp) "
            "VALUES (?, ?, ?, ?, ?, ?, datetime('now', 'localtime'))",
            (conversation_id, round_num, role, content, tc_json, tool_call_id),
        )
        self.conn.commit()
        c.close()

    def get_conversations(self, topic_id: str, limit: int = 5, include_rounds: bool = True) -> List[Dict]:
        """Get the conversations.
        
        Args:
            topic_id: Description.
            limit: Description.
            include_rounds: Description.
        """
        c = self.conn.cursor()
        if include_rounds:
            c.execute(
                "SELECT * FROM conversations WHERE topic_id = ? ORDER BY stamp ASC", (topic_id,)
            )
        else:
            c.execute(
                "SELECT id, topic_id, user_msg, ai_msg, is_func_calling, is_summarized, stamp "
                "FROM conversations WHERE topic_id = ? ORDER BY stamp ASC", (topic_id,)
            )
        rows = c.fetchall()
        c.close()

        if limit == 0:
            return []
        if limit > 0 and len(rows) > limit:
            rows = rows[-limit:]

        result = []
        for r in rows:
            d = dict(r)
            if include_rounds:
                if d.get("rounds_json"):
                    try:
                        d["rounds_json_parsed"] = json.loads(d["rounds_json"])
                    except (json.JSONDecodeError, TypeError):
                        d["rounds_json_parsed"] = None
                else:
                    d["rounds_json_parsed"] = None
            result.append(d)
        return result

    def get_recent_conversations(self, topic_id: str, limit: int = 3) -> List[Dict]:
        """Get the recent conversations.
        
        Args:
            topic_id: Description.
            limit: Description.
        """
        c = self.conn.cursor()
        c.execute(
            "SELECT * FROM conversations WHERE topic_id = ? ORDER BY stamp DESC LIMIT ?",
            (topic_id, limit),
        )
        rows = c.fetchall()
        c.close()
        return [dict(r) for r in reversed(rows)]

    def get_agent_rounds(self, conversation_id: str) -> List[Dict]:
        """Get the agent rounds.
        
        Args:
            conversation_id: Description.
        """
        c = self.conn.cursor()
        c.execute(
            "SELECT * FROM agent_rounds WHERE conversation_id = ? ORDER BY id ASC",
            (conversation_id,),
        )
        rows = c.fetchall()
        c.close()
        result = []
        for r in rows:
            d = dict(r)
            if d.get("tool_calls"):
                d["tool_calls"] = json.loads(d["tool_calls"])
            result.append(d)
        return result

    # ── 全文搜索（FTS5 fallback LIKE）──

    def search_conversations(self, query: str, limit: int = 30,
                              include_ai: bool = True, include_rounds: bool = True,
                              date_from: str = "", date_to: str = "") -> List[Dict]:
        """跨主题全文搜索对话内容。

        同时搜索 user_msg、ai_msg 和 agent_rounds.content，
        结果按相关度排序，附带主题标题和上下文片段。

        Args:
            query: 搜索关键词。
            limit: 返回结果上限。
            include_ai: 是否搜索 ai_msg 字段。
            include_rounds: 是否搜索 agent_rounds 内容。
            date_from: 起始日期 YYYY-MM-DD（可选）。
            date_to: 结束日期 YYYY-MM-DD（可选）。

        Returns:
            搜索结果列表：conversation_id, topic_id, topic_title,
            user_msg, ai_msg, snippet, rank_score, stamp
        """
        if not query or not query.strip():
            return []

        q = query.strip()
        like_pat = f"%{q}%"
        conditions = ["c.user_msg LIKE ?"]
        params = [like_pat]

        if include_ai:
            conditions.append("c.ai_msg LIKE ?")
            params.append(like_pat)

        if date_from:
            conditions.append("c.stamp >= ?")
            params.append(f"{date_from} 00:00:00")
        if date_to:
            conditions.append("c.stamp <= ?")
            params.append(f"{date_to} 23:59:59")

        where = " OR ".join(f"({cond})" for cond in conditions)

        sql = f'''
            SELECT c.id as conversation_id, c.topic_id, t.title as topic_title,
                   c.user_msg, c.ai_msg, c.stamp
            FROM conversations c
            JOIN topics t ON c.topic_id = t.topic_id
            WHERE ({where})
            ORDER BY c.stamp DESC
            LIMIT ?
        '''
        params.append(limit)

        c = self.conn.cursor()
        c.execute(sql, params)
        rows = c.fetchall()
        conv_results = [dict(r) for r in rows]

        # 如果也搜索 agent_rounds，补充查询
        if include_rounds:
            rc = self.conn.cursor()
            rc.execute('''
                SELECT DISTINCT r.conversation_id
                FROM agent_rounds r
                WHERE r.content LIKE ?
            ''', (like_pat,))
            round_conv_ids = {row["conversation_id"] for row in rc.fetchall()}
            rc.close()

            if round_conv_ids:
                existing_ids = {r["conversation_id"] for r in conv_results}
                missing_ids = round_conv_ids - existing_ids
                if missing_ids:
                    placeholders = ",".join("?" for _ in missing_ids)
                    rc2 = self.conn.cursor()
                    rc2.execute(f'''
                        SELECT c.id as conversation_id, c.topic_id, t.title as topic_title,
                               c.user_msg, c.ai_msg, c.stamp
                        FROM conversations c
                        JOIN topics t ON c.topic_id = t.topic_id
                        WHERE c.id IN ({placeholders})
                    ''', list(missing_ids))
                    conv_results.extend(dict(r) for r in rc2.fetchall())
                    rc2.close()

        c.close()

        # 计算排序分数
        q_lower = q.lower()
        for r in conv_results:
            score = 0
            user_msg = r.get("user_msg", "") or ""
            ai_msg = r.get("ai_msg", "") or ""
            for field in [user_msg, ai_msg]:
                field_lower = field.lower()
                count = field_lower.count(q_lower)
                score += count * 10
                if field_lower.startswith(q_lower):
                    score += 50
                if field_lower == q_lower:
                    score += 200
            r["rank_score"] = score
            r["snippet"] = self._make_snippet(user_msg + " " + ai_msg, q)

        conv_results.sort(key=lambda x: x["rank_score"], reverse=True)
        return conv_results

    @staticmethod
    def _make_snippet(text: str, query: str, context_chars: int = 60) -> str:
        """从文本中提取包含关键词的上下文片段。"""
        if not text:
            return ""
        q_lower = query.lower()
        text_lower = text.lower()
        idx = text_lower.find(q_lower)
        if idx < 0:
            return text[:context_chars * 2] + ("..." if len(text) > context_chars * 2 else "")
        start = max(0, idx - context_chars)
        end = min(len(text), idx + len(query) + context_chars)
        snippet = text[start:end]
        if start > 0:
            snippet = "..." + snippet
        if end < len(text):
            snippet = snippet + "..."
        snippet = snippet.replace("\n", " ").replace("\r", " ").strip()
        return snippet

    # ── 自动嵌入（队列 + 单后台线程，独立连接）──

    _embed_queue = queue.Queue()
    _embed_worker_started = False

    @classmethod
    def _ensure_embed_worker(cls, conn):
        """Ensure a single background worker thread is running."""
        if cls._embed_worker_started:
            return
        cls._embed_worker_started = True

        def _worker():
            """Background worker with its own connection."""
            db_path = None
            try:
                db_path = conn.execute("PRAGMA database_list").fetchone()[2]
            except Exception:
                return
            if not db_path:
                return
            try:
                worker_conn = sqlite3.connect(db_path, check_same_thread=False)
                worker_conn.row_factory = sqlite3.Row
                import numpy as np
                from tea_agent.embedding_util import get_embedding_engine
                engine = get_embedding_engine()
                while True:
                    try:
                        conv_id, text = cls._embed_queue.get(timeout=1)
                    except queue.Empty:
                        continue
                    if conv_id is None:
                        break
                    try:
                        vec = engine.embed(text)
                        if vec:
                            arr = np.array(vec, dtype=np.float32)
                            blob = arr.tobytes()
                            c = worker_conn.cursor()
                            c.execute(
                                "INSERT OR REPLACE INTO msg_vectors "
                                "(conversation_id, embedding, dimension, model_name, created_at) "
                                "VALUES (?, ?, ?, ?, datetime('now', 'localtime'))",
                                (conv_id, blob, len(vec), engine.model_name),
                            )
                            worker_conn.commit()
                            c.close()
                    except Exception as e:
                        logging.getLogger("store").warning(
                            f"自动嵌入失败 (conv_id={conv_id}): {e}"
                        )
                worker_conn.close()
            except Exception:
                logging.getLogger("store").exception("嵌入工作线程异常退出")

        t = threading.Thread(target=_worker, daemon=True, name="auto-embed-worker")
        t.start()

    def _auto_embed_async(self, conv_id: str, text: str):
        """Enqueue embedding request for async processing.

        Uses a single daemon worker thread with its own connection,
        avoiding thread-safety issues.
        """
        self._ensure_embed_worker(self.conn)
        self._embed_queue.put((conv_id, text))
