"""
"""
import numpy as np
from typing import Dict, List, Optional
from ._base import StoreComponent

class VectorStore(StoreComponent):
    """向量管理：存储、检索、批量向量化、语义搜索（余弦相似度）。"""

    def store_embedding(self, conversation_id: str, embedding: list,
                         model_name: str = "", dimension: int = 0):
        """Store embedding.
        
        Args:
            conversation_id: Description.
            embedding: Description.
            model_name: Description.
            dimension: Description.
        """
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

    def get_msg_embedding(self, conversation_id: str) -> Optional[List[float]]:
        """Get the msg embedding.
        
        Args:
            conversation_id: Description.
        """
        c = self.conn.cursor()
        c.execute(
            "SELECT embedding, dimension FROM msg_vectors WHERE conversation_id = ?",
            (conversation_id,),
        )
        row = c.fetchone()
        c.close()
        if row and row["embedding"]:
            try:
                arr = np.frombuffer(row["embedding"], dtype=np.float32)
                return arr.tolist()
            except Exception:
                return None
        return None

    def get_all_embeddings(self) -> List[Dict]:
        """Get the all embeddings."""
        c = self.conn.cursor()
        c.execute('''
            SELECT v.conversation_id, v.embedding, c.user_msg, c.topic_id, t.title as topic_title
            FROM msg_vectors v
            JOIN conversations c ON v.conversation_id = c.id
            JOIN topics t ON c.topic_id = t.topic_id
            ORDER BY v.created_at DESC
        ''')
        rows = c.fetchall()
        c.close()
        results = []
        for row in rows:
            d = dict(row)
            blob = d.pop("embedding", None)
            if blob:
                try:
                    d["embedding"] = np.frombuffer(blob, dtype=np.float32).tolist()
                except Exception:
                    d["embedding"] = None
            else:
                d["embedding"] = None
            results.append(d)
        return results

    def search_by_vector(self, query_embedding: List[float], top_k: int = 10,
                          min_similarity: float = 0.3) -> List[Dict]:
        """Search by vector.
        
        Args:
            query_embedding: Description.
            top_k: Description.
            min_similarity: Description.
        """
        all_embs = self.get_all_embeddings()
        if not all_embs:
            return []

        query_arr = np.array(query_embedding, dtype=np.float32)
        q_norm = np.linalg.norm(query_arr)
        if q_norm == 0:
            return []

        valid_items = []
        vecs = []
        for item in all_embs:
            emb = item.get("embedding")
            if not emb or len(emb) != len(query_embedding):
                continue
            vecs.append(emb)
            valid_items.append(item)
        if not vecs:
            return []

        mat = np.array(vecs, dtype=np.float32)
        dots = mat @ query_arr
        mat_norms = np.linalg.norm(mat, axis=1)
        sims = dots / (q_norm * mat_norms)

        scored = []
        for i, sim in enumerate(sims):
            if sim >= min_similarity:
                scored.append({
                    "conversation_id": valid_items[i]["conversation_id"],
                    "similarity": round(float(sim), 4),
                    "user_msg": valid_items[i]["user_msg"],
                    "topic_id": valid_items[i]["topic_id"],
                    "topic_title": valid_items[i]["topic_title"],
                })

        scored.sort(key=lambda x: x["similarity"], reverse=True)
        top = scored[:top_k]
        if not top:
            return []

        # 批量补充 ai_msg
        c = self.conn.cursor()
        cids = tuple(s["conversation_id"] for s in top)
        placeholders = ",".join("?" for _ in cids)
        c.execute(
            f"SELECT id, ai_msg FROM conversations WHERE id IN ({placeholders})", cids
        )
        ai_map = {row["id"]: row["ai_msg"] or "" for row in c.fetchall()}
        c.close()
        for s in top:
            s["ai_msg"] = ai_map.get(s["conversation_id"], "")
        return top

    def search_by_keyword(self, query: str, top_k: int = 50) -> List[Dict]:
        """Search by keyword.
        
        Args:
            query: Description.
            top_k: Description.
        """
        c = self.conn.cursor()
        c.execute('''
            SELECT c.id as conversation_id, c.user_msg, c.ai_msg, c.topic_id, t.title as topic_title
            FROM conversations c
            JOIN topics t ON c.topic_id = t.topic_id
            WHERE c.user_msg LIKE ?
            ORDER BY c.stamp DESC
            LIMIT ?
        ''', (f"%{query}%", top_k))
        rows = c.fetchall()
        c.close()
        results = []
        qlen = len(query) if query else 1
        for row in rows:
            d = dict(row)
            user_msg = d.get("user_msg", "") or ""
            score = user_msg.lower().count(query.lower()) * len(query) / max(len(user_msg), 1)
            d["similarity"] = min(round(score * 10, 4), 1.0)
            results.append(d)
        results.sort(key=lambda x: x["similarity"], reverse=True)
        return results

    def get_vector_count(self) -> int:
        """Get the vector count."""
        c = self.conn.cursor()
        c.execute("SELECT COUNT(*) FROM msg_vectors")
        count = c.fetchone()[0]
        c.close()
        return count

    def get_unvectorized_conversations(self, limit: int = 100) -> List[Dict]:
        """Get the unvectorized conversations.
        
        Args:
            limit: Description.
        """
        c = self.conn.cursor()
        c.execute('''
            SELECT c.id, c.user_msg, c.topic_id
            FROM conversations c
            LEFT JOIN msg_vectors v ON c.id = v.conversation_id
            WHERE v.conversation_id IS NULL AND c.user_msg != ''
            ORDER BY c.stamp DESC
            LIMIT ?
        ''', (limit,))
        rows = c.fetchall()
        c.close()
        return [dict(r) for r in rows]

    def vectorize_conversation(self, conversation_id: int, user_msg: str,
                                 model_name: str = "", embedding: Optional[List[float]] = None) -> bool:
        """Vectorize conversation.
        
        Args:
            conversation_id: Description.
            user_msg: Description.
            model_name: Description.
            embedding: Description.
        """
        if not embedding:
            return False
        self.store_embedding(conversation_id, embedding, model_name, len(embedding))
        return True

    def batch_vectorize(self, conversation_data: List[Dict], model_name: str = "") -> int:
        """Batch vectorize.
        
        Args:
            conversation_data: Description.
            model_name: Description.
        """
        count = 0
        for item in conversation_data:
            cid = item.get("conversation_id")
            emb = item.get("embedding")
            if cid and emb:
                self.store_embedding(cid, emb, model_name, len(emb))
                count += 1
        return count

    def delete_vector(self, conversation_id: str):
        """Delete vector.
        
        Args:
            conversation_id: Description.
        """
        c = self.conn.cursor()
        c.execute("DELETE FROM msg_vectors WHERE conversation_id = ?", (conversation_id,))
        self.conn.commit()
        c.close()
