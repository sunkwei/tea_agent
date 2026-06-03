# version: 1.0.0

"""
语义搜索模块 (SemanticSearch)

基于 embedding 的语义搜索，替代简单的 LIKE 匹配：
1. 支持多种 embedding 后端
2. 向量存储与检索
3. 融合排序（语义 + 关键词）
4. 缓存机制
"""

import logging
import json
import hashlib
import os
from typing import Dict, List, Optional, Tuple
from datetime import datetime
import sqlite3

logger = logging.getLogger("Storage.SemanticSearch")


class EmbeddingProvider:
    """Embedding 提供者基类"""
    
    def embed(self, text: str) -> List[float]:
        """将文本转换为向量"""
        raise NotImplementedError


class SimpleHashEmbedding(EmbeddingProvider):
    """简单哈希 Embedding（用于演示，实际应替换为真正的 embedding 模型）"""
    
    def __init__(self, dim: int = 128):
        self.dim = dim
    
    def embed(self, text: str) -> List[float]:
        """基于哈希的简单 embedding"""
        # 使用 MD5 哈希生成伪向量
        hash_obj = hashlib.md5(text.encode('utf-8'))
        hash_bytes = hash_obj.digest()
        
        # 扩展到所需维度
        result = []
        for i in range(self.dim):
            byte_idx = i % len(hash_bytes)
            result.append(hash_bytes[byte_idx] / 255.0)
        
        # 归一化
        norm = sum(x*x for x in result) ** 0.5
        if norm > 0:
            result = [x/norm for x in result]
        
        return result


class SemanticSearch:
    """语义搜索引擎"""
    
    def __init__(self, storage, embedding_provider: Optional[EmbeddingProvider] = None):
        """初始化
        
        Args:
            storage: Storage 实例
            embedding_provider: Embedding 提供者
        """
        self.storage = storage
        self.embedding_provider = embedding_provider or SimpleHashEmbedding()
        self._init_vector_table()
    
    def _init_vector_table(self):
        """初始化向量存储表"""
        c = self.storage.conn.cursor()
        c.execute('''
            CREATE TABLE IF NOT EXISTS memory_vectors (
                memory_id TEXT PRIMARY KEY,
                embedding BLOB NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (memory_id) REFERENCES memories(id) ON DELETE CASCADE
            )
        ''')
        self.storage.conn.commit()
        c.close()
    
    def index_memory(self, memory_id: str, content: str) -> bool:
        """为记忆创建向量索引"""
        try:
            embedding = self.embedding_provider.embed(content)
            embedding_bytes = json.dumps(embedding).encode('utf-8')
            
            c = self.storage.conn.cursor()
            c.execute("""
                INSERT OR REPLACE INTO memory_vectors (memory_id, embedding)
                VALUES (?, ?)
            """, (memory_id, embedding_bytes))
            self.storage.conn.commit()
            c.close()
            
            return True
            
        except Exception as e:
            logger.error(f"索引记忆失败: {e}")
            return False
    
    def index_all_memories(self) -> int:
        """索引所有活跃记忆"""
        c = self.storage.conn.cursor()
        c.execute("""
            SELECT m.id, m.content 
            FROM memories m 
            LEFT JOIN memory_vectors v ON m.id = v.memory_id
            WHERE m.is_active = 1 AND v.memory_id IS NULL
        """)
        
        rows = c.fetchall()
        c.close()
        
        count = 0
        for row in rows:
            if self.index_memory(row["id"], row["content"]):
                count += 1
        
        logger.info(f"索引了 {count} 条新记忆")
        return count
    
    def semantic_search(self, query: str, top_k: int = 10) -> List[Dict]:
        """语义搜索
        
        Args:
            query: 查询文本
            top_k: 返回数量
            
        Returns:
            搜索结果列表
        """
        # 1. 获取查询向量
        query_embedding = self.embedding_provider.embed(query)
        
        # 2. 加载所有向量
        c = self.storage.conn.cursor()
        c.execute("""
            SELECT v.memory_id, v.embedding
            FROM memory_vectors v
            JOIN memories m ON v.memory_id = m.id
            WHERE m.is_active = 1
        """)
        
        rows = c.fetchall()
        c.close()
        
        # 3. 计算相似度
        scores = []
        for row in rows:
            memory_embedding = json.loads(row["embedding"].decode('utf-8'))
            similarity = self._cosine_similarity(query_embedding, memory_embedding)
            scores.append((row["memory_id"], similarity))
        
        # 4. 排序并返回 top_k
        scores.sort(key=lambda x: x[1], reverse=True)
        top_ids = [item[0] for item in scores[:top_k]]
        
        # 5. 获取完整记忆信息
        if not top_ids:
            return []
        
        placeholders = ",".join(["?" for _ in top_ids])
        c = self.storage.conn.cursor()
        c.execute(f"""
            SELECT * FROM memories 
            WHERE id IN ({placeholders}) AND is_active = 1
        """, top_ids)
        
        memories = [dict(r) for r in c.fetchall()]
        c.close()
        
        # 按相似度排序
        id_to_score = dict(scores)
        memories.sort(key=lambda m: id_to_score.get(m["id"], 0), reverse=True)
        
        return memories
    
    def hybrid_search(self, query: str, top_k: int = 10, 
                      semantic_weight: float = 0.7) -> List[Dict]:
        """混合搜索（语义 + 关键词）
        
        Args:
            query: 查询文本
            top_k: 返回数量
            semantic_weight: 语义搜索权重 (0-1)
            
        Returns:
            搜索结果列表
        """
        # 1. 语义搜索结果
        semantic_results = self.semantic_search(query, top_k=top_k*2)
        semantic_scores = {m["id"]: i for i, m in enumerate(semantic_results)}
        
        # 2. 关键词搜索结果
        keyword_results = self.storage.search_memories(query=query, limit=top_k*2)
        keyword_scores = {m["id"]: i for i, m in enumerate(keyword_results)}
        
        # 3. 融合评分
        all_ids = set(semantic_scores.keys()) | set(keyword_scores.keys())
        combined_scores = []
        
        for memory_id in all_ids:
            sem_score = 1.0 / (semantic_scores.get(memory_id, len(semantic_results)) + 1)
            kw_score = 1.0 / (keyword_scores.get(memory_id, len(keyword_results)) + 1)
            
            combined = semantic_weight * sem_score + (1 - semantic_weight) * kw_score
            combined_scores.append((memory_id, combined))
        
        # 4. 排序
        combined_scores.sort(key=lambda x: x[1], reverse=True)
        top_ids = [item[0] for item in combined_scores[:top_k]]
        
        # 5. 获取完整信息
        if not top_ids:
            return []
        
        placeholders = ",".join(["?" for _ in top_ids])
        c = self.storage.conn.cursor()
        c.execute(f"""
            SELECT * FROM memories 
            WHERE id IN ({placeholders}) AND is_active = 1
        """, top_ids)
        
        memories = [dict(r) for r in c.fetchall()]
        c.close()
        
        return memories
    
    def _cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        """计算余弦相似度"""
        if len(vec1) != len(vec2):
            return 0.0
        
        dot_product = sum(a*b for a, b in zip(vec1, vec2))
        norm1 = sum(a*a for a in vec1) ** 0.5
        norm2 = sum(b*b for b in vec2) ** 0.5
        
        if norm1 == 0 or norm2 == 0:
            return 0.0
        
        return dot_product / (norm1 * norm2)
    
    def get_vector_stats(self) -> Dict:
        """获取向量索引统计"""
        c = self.storage.conn.cursor()
        
        c.execute("SELECT COUNT(*) as total FROM memory_vectors")
        indexed = c.fetchone()["total"]
        
        c.execute("SELECT COUNT(*) as total FROM memories WHERE is_active = 1")
        total_memories = c.fetchone()["total"]
        
        c.close()
        
        return {
            "indexed_memories": indexed,
            "total_memories": total_memories,
            "coverage": indexed / total_memories if total_memories > 0 else 0
        }
    
    def delete_vector(self, memory_id: str) -> bool:
        """删除向量索引"""
        try:
            c = self.storage.conn.cursor()
            c.execute("DELETE FROM memory_vectors WHERE memory_id = ?", (memory_id,))
            self.storage.conn.commit()
            c.close()
            return True
        except Exception as e:
            logger.error(f"删除向量失败: {e}")
            return False
