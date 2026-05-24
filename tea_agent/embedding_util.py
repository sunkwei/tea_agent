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

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False
    requests = None


class _SimpleTFIDF:
    """极简 TF-IDF：字符 bigram 特征 + 余弦相似度"""

    def __init__(self, vector_dim: int = 256):
        """Initialize  .
        
        Args:
            vector_dim: Description.
        """
        self.vector_dim = vector_dim
        self._doc_freq: Counter = Counter()
        self._doc_count: int = 0

    def _tokenize(self, text: str) -> List[str]:
        """
        字符 bigram 分词（对中文友好）

        Args:
            text (str): Description.

        Returns:
            List[str]: Description.
        """
        text = text.strip().lower()
        if len(text) < 2:
            return [text] if text else []
        tokens = []
        for i in range(len(text) - 1):
            tokens.append(text[i:i+2])
        return tokens

    def _hash_token(self, token: str) -> int:
        """
        将 token 哈希到 [0, vector_dim) 范围

        Args:
            token (str): Description.

        Returns:
            int: Description.
        """
        h = int(hashlib.md5(token.encode('utf-8')).hexdigest(), 16)
        return h % self.vector_dim

    def add_document(self, text: str):
        """
        向语料库添加文档（用于构建 IDF）

        Args:
            text (str): Description.
        """
        tokens = set(self._tokenize(text))
        for t in tokens:
            self._doc_freq[t] += 1
        self._doc_count += 1

    def vectorize(self, text: str) -> List[float]:
        """
        将文本转为 TF-IDF 向量（稀疏向量 + 哈希降维）

        Args:
            text (str): Description.

        Returns:
            List[float]: Description.
        """
        tokens = self._tokenize(text)
        if not tokens:
            return [0.0] * self.vector_dim

        tf: Counter = Counter(tokens)
        vec = [0.0] * self.vector_dim
        total = len(tokens)

        for token, count in tf.items():
            idx = self._hash_token(token)
            tf_val = count / total
            df = self._doc_freq.get(token, 0)
            idf = math.log((self._doc_count + 1) / (df + 1)) + 1
            vec[idx] += tf_val * idf

        norm = math.sqrt(sum(v * v for v in vec))
        if norm > 0:
            vec = [v / norm for v in vec]
        return vec


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

        self._total_embedding_tokens = 0
        self._total_embedding_prompt_tokens = 0
        self._session_embedding_tokens = 0
        self._session_embedding_prompt_tokens = 0

        if config is not None:
            self._init_from_config(config)

    def _init_from_config(self, config):
        """
        从配置初始化

        Args:
            config: Description.
        """
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
        """
        当前模式: 'api' | 'tfidf'

        Returns:
            str: Description.
        """
        return "api" if self._use_api else "tfidf"

    @property
    def configured(self) -> bool:
        """
        是否已配置（API 模式需要 URL + model，TF-IDF 始终可用）

        Returns:
            bool: Description.
        """
        return True

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
                return self._embed_tfidf(text)
        else:
            return self._embed_tfidf(text)

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """
        批量嵌入（API 模式尝试批量请求，TF-IDF 逐个处理）

        Args:
            texts (List[str]): Description.

        Returns:
            List[List[float]]: Description.
        """
        if self._use_api:
            try:
                return self._embed_api_batch(texts)
            except Exception as e:
                logger.warning(f"API 批量嵌入失败，逐个 TF-IDF: {e}")
        return [self._embed_tfidf(t) for t in texts]

    def _build_url(self) -> str:
        """
        构建 embeddings API URL，自动处理 /v1 前缀

        Returns:
            str: Description.
        """
        base = self.api_url.rstrip("/")
        if base.endswith("/embeddings"):
            return base
        if base.endswith("/v1"):
            return base + "/embeddings"
        return base + "/v1/embeddings"

    def _embed_api(self, text: str) -> List[float]:
        """
        通过 API 获取单个文本的嵌入

        Args:
            text (str): Description.

        Returns:
            List[float]: Description.
        """
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

        usage = data.get("usage", {})
        if usage:
            pt = usage.get("prompt_tokens", 0) or 0
            tt = usage.get("total_tokens", 0) or pt
            self._total_embedding_tokens += tt
            self._total_embedding_prompt_tokens += pt
            self._session_embedding_tokens += tt
            self._session_embedding_prompt_tokens += pt

        if "data" in data and len(data["data"]) > 0:
            emb = data["data"][0].get("embedding", [])
            if emb:
                if not self.dimension:
                    self.dimension = len(emb)
                return emb

        raise RuntimeError(f"API 返回格式异常: {json.dumps(data)[:200]}")

    def _embed_api_batch(self, texts: List[str]) -> List[List[float]]:
        """
        通过 API 批量获取嵌入

        Args:
            texts (List[str]): Description.

        Returns:
            List[List[float]]: Description.
        """
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
        """
        本地 TF-IDF 向量化

        Args:
            text (str): Description.

        Returns:
            List[float]: Description.
        """
        return self._tfidf.vectorize(text)

    def build_tfidf_vocabulary(self, texts: List[str]):
        """
        用一批文本构建 TF-IDF 语料库（提升本地搜索质量）

        Args:
            texts (List[str]): Description.
        """
        for t in texts:
            if t and t.strip():
                self._tfidf.add_document(t.strip())
        logger.debug(f"TF-IDF 词汇表: {self._tfidf._doc_count} 文档, "
                     f"{len(self._tfidf._doc_freq)} 特征")

    def cosine_similarity(self, a: List[float], b: List[float]) -> float:
        """
        计算两个向量的余弦相似度（numpy 加速）

        Args:
            a (List[float]): Description.
            b (List[float]): Description.

        Returns:
            float: Description.
        """
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


def get_embedding_engine(reload: bool = False) -> EmbeddingEngine:
    """
    获取全局 EmbeddingEngine 单例

    Args:
        reload (bool): Description.

    Returns:
        EmbeddingEngine: Description.
    """
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
