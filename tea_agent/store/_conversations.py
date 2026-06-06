"""
"""
import json
import base64
import os
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

    # ── 自动嵌入 ──

    def _auto_embed_async(self, conv_id: str, text: str):
        """后台线程自动生成并存储文本向量。"""

        def _run():
            """Internal: run."""
            try:
                from tea_agent.embedding_util import get_embedding_engine
                engine = get_embedding_engine()
                vec = engine.embed(text)
                if vec:
                    self._store_embedding_inline(conv_id, vec, engine.model_name, len(vec))
            except Exception as e:
                logging.getLogger("store").warning(f"自动嵌入失败 (conv_id={conv_id}): {e}")

        t = threading.Thread(target=_run, daemon=True, name=f"auto-embed-{conv_id}")
        t.start()

    def _store_embedding_inline(self, conversation_id: str, embedding: list,
                                 model_name: str = "", dimension: int = 0):
        """内联存储向量（避免循环导入，由 _auto_embed_async 调用）。"""
        import numpy as np
        arr = np.array(embedding, dtype=np.float32)
        blob = arr.tobytes()
        c = self.conn.cursor()
        c.execute(
            "INSERT OR REPLACE INTO msg_vectors (conversation_id, embedding, dimension, model_name, created_at) "
            "VALUES (?, ?, ?, ?, datetime('now', 'localtime'))",
            (conversation_id, blob, dimension or len(embedding), model_name),
        )
        self.conn.commit()
        c.close()
