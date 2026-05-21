"""
# 2026-05-06 gen by claude, 文本向量生成器
轻量级文本嵌入工具，支持两种模式：
1. API 模式：通过兼容 OpenAI embeddings 的 API 获取向量
2. 本地 TF-IDF 回退：纯 Python stdlib 实现，零额外依赖

用法:
    from tea_agent.embedding_util import EmbeddingEngine
    engine = EmbeddingEngine(config)
    vec = engine.embed("你好世界")           # -> [float, ...]
    results = engine.search("搜索词", top_k=10)  # -> [dict, ...]
"""

import math
import json
import hashlib
import logging
from typing import List, Dict, Optional, Tuple
from collections import Counter

logger = logging.getLogger("Embedding")

# 尝试导入 requests（API 模式需要）
try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False
    requests = None  # type: ignore

# ── 本地 TF-IDF 回退 ────────────────────────────────────────────
# 一个极简的 TF-IDF 实现，用于在没有 embedding API 时提供基本语义搜索。
# 使用字符级 bigram 作为特征（对中文友好），全局使用固定维度的稀疏向量。

class _SimpleTFIDF:
    """极简 TF-IDF：字符 bigram 特征 + 余弦相似度"""

    def __init__(self, vector_dim: int = 256):
        self.vector_dim = vector_dim
        self._doc_freq: Counter = Counter()  # bigram → 出现过该 bigram 的文档数
        self._doc_count: int = 0

    def _tokenize(self, text: str) -> List[str]:
        """字符 bigram 分词（对中文友好）"""
        text = text.strip().lower()
        if len(text) < 2:
            return [text] if text else []
        tokens = []
        for i in range(len(text) - 1):
            tokens.append(text[i:i+2])
        return tokens

    def _hash_token(self, token: str) -> int:
        """将 token 哈希到 [0, vector_dim) 范围"""
        h = int(hashlib.md5(token.encode('utf-8')).hexdigest(), 16)
        return h % self.vector_dim

    def add_document(self, text: str):
        """向语料库添加文档（用于构建 IDF）"""
        tokens = set(self._tokenize(text))
        for t in tokens:
            self._doc_freq[t] += 1
        self._doc_count += 1

    def vectorize(self, text: str) -> List[float]:
        """将文本转为 TF-IDF 向量（稀疏向量 + 哈希降维）"""
        tokens = self._tokenize(text)
        if not tokens:
            return [0.0] * self.vector_dim

        tf: Counter = Counter(tokens)
        vec = [0.0] * self.vector_dim
        total = len(tokens)

        for token, count in tf.items():
            idx = self._hash_token(token)
            # TF
            tf_val = count / total
            # IDF: log((N+1)/(df+1)) + 1
            df = self._doc_freq.get(token, 0)
            idf = math.log((self._doc_count + 1) / (df + 1)) + 1
            vec[idx] += tf_val * idf

        # L2 归一化
        norm = math.sqrt(sum(v * v for v in vec))
        if norm > 0:
            vec = [v / norm for v in vec]
        return vec

# ── EmbeddingEngine ─────────────────────────────────────────────

class EmbeddingEngine:
    """文本向量引擎：API 优先，自动回退 TF-IDF"""

    def __init__(self, config=None):
        """
        Args:
            config: tea_agent.config.EmbeddingConfig 或 dict 或 None
        """
        self.api_url = ""
        self.model_name = ""
        self.api_key = ""
        self.dimension = 0
        self._use_api = False
        self._tfidf = _SimpleTFIDF()

        # Token 用量跟踪
        self._total_embedding_tokens = 0       # 全局累计
        self._total_embedding_prompt_tokens = 0
        self._session_embedding_tokens = 0     # 单次会话累计（get_and_reset 后归零）
        self._session_embedding_prompt_tokens = 0

        if config is not None:
            self._init_from_config(config)

    def _init_from_config(self, config):
        """从配置初始化"""
        # 兼容 dataclass 和 dict
        if hasattr(config, 'api_url'):
            self.api_url = config.api_url or ""
            self.model_name = config.model_name or ""
            self.api_key = config.api_key or ""
            self.dimension = config.dimension or 0
        elif isinstance(config, dict):
            self.api_url = config.get("api_url", "")
            self.model_name = config.get("model_name", "")
            self.api_key = config.get("api_key", "")
            self.dimension = config.get("dimension", 0)

        # 如果 api_key 为空，尝试从 main_model 获取
        if not self.api_key:
            try:
                from tea_agent.config import get_config
                cfg = get_config()
                self.api_key = cfg.main_model.api_key
            except Exception:
                pass

        self._use_api = bool(self.api_url and self.model_name and HAS_REQUESTS)

    @property
    def mode(self) -> str:
        """当前模式: 'api' | 'tfidf'"""
        return "api" if self._use_api else "tfidf"

    @property
    def configured(self) -> bool:
        """是否已配置（API 模式需要 URL + model，TF-IDF 始终可用）"""
        return True  # TF-IDF 始终作为回退

    def embed(self, text: str) -> List[float]:
        """
        将文本转为向量。

        Args:
            text: 待嵌入的文本

        Returns:
            向量列表（维度取决于模型或 TF-IDF 的 256）
        """
        if not text or not text.strip():
            return [0.0] * (self.dimension or 256)

        text = text.strip()

        if self._use_api:
            try:
                return self._embed_api(text)
            except Exception as e:
                logger.warning(f"API 嵌入失败，回退 TF-IDF: {e}")
                # 回退到 TF-IDF
                return self._embed_tfidf(text)
        else:
            return self._embed_tfidf(text)

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """批量嵌入（API 模式尝试批量请求，TF-IDF 逐个处理）"""
        if self._use_api:
            try:
                return self._embed_api_batch(texts)
            except Exception as e:
                logger.warning(f"API 批量嵌入失败，逐个 TF-IDF: {e}")
        return [self._embed_tfidf(t) for t in texts]

    def _build_url(self) -> str:
        """构建 embeddings API URL，自动处理 /v1 前缀"""
        base = self.api_url.rstrip("/")
        # 如果已经指向 /embeddings 则直接返回
        if base.endswith("/embeddings"):
            return base
        # 如果末尾是 /v1，追加 /embeddings
        if base.endswith("/v1"):
            return base + "/embeddings"
        # 否则补全 /v1/embeddings
        return base + "/v1/embeddings"

    def _embed_api(self, text: str) -> List[float]:
        """通过 API 获取单个文本的嵌入"""
        url = self._build_url()
        headers = {
            "Content-Type": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload = {
            "model": self.model_name,
            "input": text,
        }

        import time
        asctime = time.strftime("%Y-%m-%d %H:%M:%S")
        print(f"{asctime}: call embedding: {self.model_name}, {text[:80]}")
        logger.info(f"embedding request: model={self.model_name}, text_len={len(text)}, text:{text[:80]}, url={url}")

        resp = requests.post(url, json=payload, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        # 提取 token 用量
        usage = data.get("usage", {})
        if usage:
            pt = usage.get("prompt_tokens", 0) or 0
            tt = usage.get("total_tokens", 0) or pt
            self._total_embedding_tokens += tt
            self._total_embedding_prompt_tokens += pt
            self._session_embedding_tokens += tt
            self._session_embedding_prompt_tokens += pt

        # OpenAI 兼容格式: {"data": [{"embedding": [...]}]}
        if "data" in data and len(data["data"]) > 0:
            emb = data["data"][0].get("embedding", [])
            if emb:
                if not self.dimension:
                    self.dimension = len(emb)
                return emb

        raise RuntimeError(f"API 返回格式异常: {json.dumps(data)[:200]}")

    def _embed_api_batch(self, texts: List[str]) -> List[List[float]]:
        """通过 API 批量获取嵌入"""
        url = self._build_url()
        logger.debug(f"embedding batch request: model={self.model_name}, batch_size={len(texts)}, url={url}")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload = {
            "model": self.model_name,
            "input": texts,
        }

        resp = requests.post(url, json=payload, headers=headers, timeout=60)
        resp.raise_for_status()
        data = resp.json()

        if "data" in data:
            embeddings = [item["embedding"] for item in sorted(data["data"], key=lambda x: x.get("index", 0))]
            if embeddings:
                if not self.dimension:
                    self.dimension = len(embeddings[0])
                return embeddings

        raise RuntimeError("API 批量返回格式异常")

    def _embed_tfidf(self, text: str) -> List[float]:
        """本地 TF-IDF 向量化"""
        return self._tfidf.vectorize(text)

    def build_tfidf_vocabulary(self, texts: List[str]):
        """用一批文本构建 TF-IDF 语料库（提升本地搜索质量）"""
        for t in texts:
            if t and t.strip():
                self._tfidf.add_document(t.strip())
        logger.debug(f"TF-IDF 词汇表: {self._tfidf._doc_count} 文档, "
                     f"{len(self._tfidf._doc_freq)} 特征")

    def cosine_similarity(self, a: List[float], b: List[float]) -> float:
        """计算两个向量的余弦相似度（numpy 加速）"""
        import numpy as np
        if len(a) != len(b):
            raise ValueError(f"向量维度不匹配: {len(a)} vs {len(b)}")
        aa = np.array(a, dtype=np.float32)
        bb = np.array(b, dtype=np.float32)
        dot = float(aa @ bb)
        na = float(np.linalg.norm(aa))
        nb = float(np.linalg.norm(bb))
        if na == 0 or nb == 0:
            return 0.0
        return dot / (na * nb)

    def get_embedding_usage(self, reset: bool = True) -> dict:
        """获取并可选重置本次会话的嵌入 token 用量。

        Args:
            reset: True=归零会话计数器（用于会话结束时读取本轮用量）

        Returns:
            {"total_tokens": int, "prompt_tokens": int}
        """
        usage = {
            "total_tokens": self._session_embedding_tokens,
            "prompt_tokens": self._session_embedding_prompt_tokens,
        }
        if reset:
            self._session_embedding_tokens = 0
            self._session_embedding_prompt_tokens = 0
        return usage

    def search(self, query: str, top_k: int = 10, min_similarity: float = 0.3) -> List[Dict]:
        """
        搜索与查询最相似的对话（需要先通过 store 获取向量数据）。

        这是便捷方法，实际搜索由 store.search_by_vector() 完成。
        此方法只负责生成查询向量。

        Args:
            query: 搜索文本
            top_k: 返回结果数
            min_similarity: 最低相似度阈值

        Returns:
            查询向量，供 store.search_by_vector() 使用
        """
        return self.embed(query)

# ── 便捷函数 ────────────────────────────────────────────────────

def get_embedding_engine(reload: bool = False) -> EmbeddingEngine:
    """获取全局 EmbeddingEngine 单例"""
    global _engine_singleton
    if _engine_singleton is None or reload:
        try:
            from tea_agent.config import get_config
            cfg = get_config()
            _engine_singleton = EmbeddingEngine(cfg.embedding)
        except Exception:
            _engine_singleton = EmbeddingEngine()
    return _engine_singleton

_engine_singleton: Optional[EmbeddingEngine] = None
