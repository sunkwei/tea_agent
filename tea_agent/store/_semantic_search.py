# version: 2.0.0
# @2026-06-07 gen by deepseek-v4-pro, Step2: 替换哈希嵌入为 EmbeddingEngine

"""
语义搜索模块 (SemanticSearch) — v2

基于 EmbeddingEngine（API/TF-IDF）的语义搜索：
1. 使用真实的 embedding 替代旧的 MD5 哈希伪向量
2. 语义搜索复用 MemoryStore 的本地 embedding BLOB 存储
3. 支持新旧记忆的 batch 回填索引
4. 混合搜索（语义 + 关键词）
"""

import logging

logger = logging.getLogger("Storage.SemanticSearch")


class SemanticSearch:
    """语义搜索引擎 v2 — 使用 EmbeddingEngine（API/TF-IDF）"""

    def __init__(self, storage, embedding_engine=None):
        """
        Args:
            storage: Storage 实例
            embedding_engine: EmbeddingEngine 实例，默认从 storage 获取
        """
        self.storage = storage
        # 优先使用传入的引擎，其次从 MemoryStore 获取
        self.embedding_engine = embedding_engine or getattr(
            storage._memories, 'embedding_engine', None
        )

    def _cosine_similarity(self, vec1: list, vec2: list) -> float:
        """计算两个向量的余弦相似度。

        Args:
            vec1: 第一个向量
            vec2: 第二个向量

        Returns:
            余弦相似度 -1 到 1，1 表示完全相同
        """
        if not vec1 or not vec2:
            return 0.0
        if len(vec1) != len(vec2):
            return 0.0
        if vec1 == vec2:
            return 1.0

        # 计算点积和模
        dot_product = sum(a * b for a, b in zip(vec1, vec2, strict=False))
        norm1 = sum(a * a for a in vec1) ** 0.5
        norm2 = sum(b * b for b in vec2) ** 0.5

        if norm1 == 0 or norm2 == 0:
            return 0.0

        return dot_product / (norm1 * norm2)

    # ── 回填索引 ──

    def index_memory(self, memory_id: str, content: str) -> bool:
        """为单条记忆计算并存储 embedding（用于回填旧数据）。

        新记忆在 add_memory 时自动计算，此方法仅用于回填。
        """
        if self.embedding_engine is None:
            logger.warning("EmbeddingEngine 不可用，无法索引")
            return False
        try:
            embedding = self.embedding_engine.embed(content)
            if not embedding:
                return False
            # 直接更新 memories 表的 embedding 列
            import numpy as np
            arr = np.array(embedding, dtype=np.float32)
            blob = arr.tobytes()
            c = self.storage.conn.cursor()
            c.execute(
                "UPDATE memories SET embedding = ?, content_hash = ? WHERE id = ?",
                (blob, content[:16], memory_id),
            )
            self.storage.conn.commit()
            c.close()
            return True
        except Exception as e:
            logger.error(f"索引记忆 {memory_id} 失败: {e}")
            return False

    def index_all_memories(self) -> int:
        """批量回填所有缺少 embedding 的活跃记忆。

        Returns:
            成功索引的数量
        """
        if self.embedding_engine is None:
            logger.warning("EmbeddingEngine 不可用")
            return 0

        c = self.storage.conn.cursor()
        c.execute(
            "SELECT id, content FROM memories "
            "WHERE is_active = 1 AND embedding IS NULL"
        )
        rows = c.fetchall()
        c.close()

        if not rows:
            logger.info("所有活跃记忆已有 embedding，无需回填")
            return 0

        count = 0
        for row in rows:
            if self.index_memory(row["id"], row["content"]):
                count += 1

        logger.info(f"回填索引: {count}/{len(rows)} 条记忆")
        return count

    # ── 搜索 ──

    def semantic_search(self, query: str, top_k: int = 10,
                         min_similarity: float = 0.3) -> list[dict]:
        """语义搜索：将查询转为向量后搜索记忆。

        Args:
            query: 查询文本
            top_k: 返回数量
            min_similarity: 最低相似度阈值

        Returns:
            按相似度降序排列的记忆列表（含 similarity 字段）
        """
        if self.embedding_engine is None:
            logger.warning("EmbeddingEngine 不可用，回退关键词搜索")
            return self.storage.search_memories(query=query, limit=top_k)

        # 1. 计算查询向量
        query_embedding = self.embedding_engine.embed(query)
        if not query_embedding:
            return []

        # 2. 使用 MemoryStore 的向量搜索
        return self.storage._memories.search_by_vector(
            query_embedding, top_k=top_k, min_similarity=min_similarity
        )

    def hybrid_search(self, query: str, top_k: int = 10,
                      semantic_weight: float = 0.7) -> list[dict]:
        """混合搜索：语义搜索 + 关键词搜索融合。

        Args:
            query: 查询文本
            top_k: 返回数量
            semantic_weight: 语义搜索权重 (0-1)，剩余为关键词权重

        Returns:
            融合排序的记忆列表
        """
        # 1. 语义搜索结果
        semantic_results = self.semantic_search(query, top_k=top_k * 2)
        sem_scores = {m["id"]: 1.0 / (i + 1) for i, m in enumerate(semantic_results)}

        # 2. 关键词搜索结果
        keyword_results = self.storage.search_memories(query=query, limit=top_k * 2)
        kw_scores = {m["id"]: 1.0 / (i + 1) for i, m in enumerate(keyword_results)}

        # 3. 融合
        all_ids = set(sem_scores.keys()) | set(kw_scores.keys())
        combined = []
        for mid in all_ids:
            score = (semantic_weight * sem_scores.get(mid, 0)
                     + (1 - semantic_weight) * kw_scores.get(mid, 0))
            combined.append((mid, score))

        combined.sort(key=lambda x: x[1], reverse=True)
        top_ids = [item[0] for item in combined[:top_k]]

        if not top_ids:
            return []

        placeholders = ",".join(["?" for _ in top_ids])
        c = self.storage.conn.cursor()
        c.execute(
            f"SELECT * FROM memories WHERE id IN ({placeholders}) AND is_active = 1",
            top_ids,
        )
        memories = [dict(r) for r in c.fetchall()]
        c.close()

        return memories

    def get_vector_stats(self) -> dict:
        """获取向量索引统计。"""
        c = self.storage.conn.cursor()
        c.execute("SELECT COUNT(*) as total FROM memories WHERE is_active = 1")
        total = c.fetchone()["total"]
        c.execute("SELECT COUNT(*) as indexed FROM memories WHERE is_active = 1 AND embedding IS NOT NULL")
        indexed = c.fetchone()["indexed"]
        c.close()
        return {
            "indexed_memories": indexed,
            "total_memories": total,
            "coverage": round(indexed / total, 4) if total > 0 else 0,
            "engine_mode": getattr(self.embedding_engine, 'mode', 'unavailable'),
        }
