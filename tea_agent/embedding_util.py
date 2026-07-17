"""
轻量级文本嵌入工具。
1. API 模式：通过兼容 OpenAI embeddings 的 API 获取向量
2. 本地 BM25 回退：纯 Python stdlib，零额外依赖（相比 TF-IDF，BM25 对代码搜索更优）
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
from collections import Counter
from typing import Any

logger = logging.getLogger("Embedding")

__all__ = [
    "EmbeddingEngine",
    "get_embedding_engine",
]

try:
    import requests

    HAS_REQUESTS: bool = True
except ImportError:
    HAS_REQUESTS = False
    requests = None


class _SimpleBM25:
    """BM25 文本向量化：字符 bigram + 哈希降维 + BM25 评分。

    相比 TF-IDF 的改进：
    - 引入 k1 和 b 参数，控制词频饱和度和文档长度归一化
    - 对代码搜索更优：短名高频符号不被过分惩罚
    """

    def __init__(self, vector_dim: int = 256, k1: float = 1.2, b: float = 0.75) -> None:
        self.vector_dim = vector_dim
        self.k1 = k1
        self.b = b
        self._doc_freq: Counter[str] = Counter()
        self._doc_count: int = 0
        self._avg_dl: float = 0.0
        self._total_dl: int = 0

    def _tokenize(self, text: str) -> list[str]:
        """字符 bigram 分词。"""
        text = text.strip().lower()
        if len(text) < 2:
            return [text] if text else []
        return [text[i : i + 2] for i in range(len(text) - 1)]

    def _hash_token(self, token: str) -> int:
        h = int(hashlib.md5(token.encode("utf-8")).hexdigest(), 16)
        return h % self.vector_dim

    def add_document(self, text: str) -> None:
        """添加文档到语料库，构建 BM25 统计。"""
        tokens = set(self._tokenize(text))
        for t in tokens:
            self._doc_freq[t] += 1
        self._total_dl += len(tokens)
        self._doc_count += 1
        self._avg_dl = self._total_dl / max(self._doc_count, 1)

    def vectorize(self, text: str) -> list[float]:
        """文本 → BM25 向量（哈希降维 + L2 归一化）。

        BM25(q, d) = Σ IDF(q) * TF(q, d) * (k1 + 1) / (TF(q, d) + k1 * (1 - b + b * |d| / avgdl))
        """
        tokens = self._tokenize(text)
        if not tokens:
            return [0.0] * self.vector_dim

        tf: Counter[str] = Counter(tokens)
        vec = [0.0] * self.vector_dim
        doc_len = len(tokens)
        avgdl = self._avg_dl if self._avg_dl > 0 else doc_len

        for token, count in tf.items():
            idx = self._hash_token(token)
            # BM25 TF 饱和函数
            tf_val = count
            denom = tf_val + self.k1 * (1 - self.b + self.b * doc_len / avgdl)
            bm25_tf = tf_val * (self.k1 + 1) / denom if denom > 0 else 0

            # BM25 IDF
            df = self._doc_freq.get(token, 0)
            idf = math.log((self._doc_count - df + 0.5) / (df + 0.5) + 1)
            vec[idx] += idf * bm25_tf

        # L2 归一化
        norm = math.sqrt(sum(v * v for v in vec))
        if norm > 0:
            vec = [v / norm for v in vec]
        return vec


# ── EmbeddingEngine ─────────────────────────────────────────────


class EmbeddingEngine:
    """文本向量引擎 — API 优先，自动回退 BM25。"""

    def __init__(self, config: Any = None) -> None:
        self.api_url: str = ""
        self.model_name: str = ""
        self.api_key: str = ""
        self.dimension: int = 0
        self._use_api: bool = False
        self._bm25 = _SimpleBM25()

        self._total_embedding_tokens: int = 0
        self._total_embedding_prompt_tokens: int = 0
        self._session_embedding_tokens: int = 0
        self._session_embedding_prompt_tokens: int = 0

        if config is not None:
            self._init_from_config(config)

    def _init_from_config(self, config: Any) -> None:
        """从 Config dataclass 或 dict 初始化。"""
        if hasattr(config, "api_url"):
            self.api_url = getattr(config, "api_url", "") or ""
            self.model_name = getattr(config, "model_name", "") or ""
            self.api_key = getattr(config, "api_key", "") or ""
            self.dimension = getattr(config, "dimension", 0) or 0
        elif isinstance(config, dict):
            self.api_url = config.get("api_url", "")
            self.model_name = config.get("model_name", "")
            self.api_key = config.get("api_key", "")
            self.dimension = config.get("dimension", 0)

        # api_key 为空时尝试从 main_model 回退
        if not self.api_key:
            try:
                from tea_agent.config import get_config

                cfg = get_config()
                self.api_key = cfg.main_model.api_key or ""
            except Exception:
                logger.debug("无法从 main_model 获取 api_key，将使用 TF-IDF 模式")

        self._use_api = bool(self.api_url and self.model_name and HAS_REQUESTS)

    @property
    def mode(self) -> str:
        return "api" if self._use_api else "tfidf"

    @property
    def configured(self) -> bool:
        return True

    def embed(self, text: str) -> list[float]:
        """文本 → 向量。API 优先，失败时自动回退 TF-IDF。"""
        if not text or not text.strip():
            return [0.0] * (self.dimension or 256)

        text = text.strip()

        if self._use_api:
            try:
                result = self._embed_api(text)
                dim = len(result)
                logger.info(f"✅ embedding 成功: {self.model_name}, dim={dim}")
                return result
            except Exception as e:
                logger.warning(f"API 嵌入失败，回退 BM25: {e}")
                return self._embed_bm25(text)
        else:
            return self._embed_bm25(text)

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """批量嵌入。API 模式尝试批量请求，TF-IDF 逐个处理。"""
        if self._use_api:
            try:
                result = self._embed_api_batch(texts)
                logger.info(
                    f"✅ embedding 批量成功: {self.model_name}, batch_size={len(texts)}"
                )
                return result
            except Exception as e:
                logger.warning(f"API 批量嵌入失败，逐个 BM25: {e}")
        return [self._embed_bm25(t) for t in texts]

    def _build_url(self) -> str:
        """构建 embeddings API URL。"""
        base = self.api_url.rstrip("/")
        if base.endswith("/embeddings"):
            return base
        if base.endswith("/v1"):
            return base + "/embeddings"
        return base + "/v1/embeddings"

    def _embed_api(self, text: str) -> list[float]:
        """通过远程 API 获取嵌入向量。"""
        url = self._build_url()
        headers: dict[str, str] = {
            "Content-Type": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload: dict[str, Any] = {
            "model": self.model_name,
            "input": text,
        }

        logger.info(
            f"embedding request: model={self.model_name}, text_len={len(text)}, url={url}"
        )

        resp = requests.post(url, json=payload, headers=headers, timeout=30)
        resp.raise_for_status()
        data: dict[str, Any] = resp.json()

        # 提取 token 用量
        usage = data.get("usage", {}) or {}
        if usage:
            pt = usage.get("prompt_tokens", 0) or 0
            tt = usage.get("total_tokens", 0) or pt
            self._total_embedding_tokens += tt
            self._total_embedding_prompt_tokens += pt
            self._session_embedding_tokens += tt
            self._session_embedding_prompt_tokens += pt

        # OpenAI 兼容格式: {"data": [{"embedding": [...]}]}
        data_list = data.get("data", [])
        if data_list and len(data_list) > 0:
            emb = data_list[0].get("embedding", [])
            if emb:
                if not self.dimension:
                    self.dimension = len(emb)
                return emb

        raise RuntimeError(f"API 返回格式异常: {json.dumps(data)[:200]}")

    def _embed_api_batch(self, texts: list[str]) -> list[list[float]]:
        """批量获取嵌入向量。"""
        url = self._build_url()
        logger.debug(
            f"embedding batch request: model={self.model_name}, batch_size={len(texts)}, url={url}"
        )
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload: dict[str, Any] = {
            "model": self.model_name,
            "input": texts,
        }

        resp = requests.post(url, json=payload, headers=headers, timeout=60)
        resp.raise_for_status()
        data: dict[str, Any] = resp.json()

        data_list = data.get("data", [])
        if data_list:
            embeddings = [
                item["embedding"]
                for item in sorted(data_list, key=lambda x: x.get("index", 0))
            ]
            if embeddings:
                if not self.dimension:
                    self.dimension = len(embeddings[0])
                return embeddings

        raise RuntimeError("API 批量返回格式异常")

    def _embed_bm25(self, text: str) -> list[float]:
        """BM25 文本向量化（API 不可用时的回退）。"""
        return self._bm25.vectorize(text)

    def _embed_tfidf(self, text: str) -> list[float]:
        """TF-IDF 文本向量化（兼容旧调用）。"""
        return self._bm25.vectorize(text)

    def build_tfidf_vocabulary(self, texts: list[str]) -> None:
        """用文本构建 BM25 语料库（提升本地搜索质量）。"""
        for t in texts:
            if t and t.strip():
                self._bm25.add_document(t.strip())
        logger.debug(
            f"BM25 语料库: {self._bm25._doc_count} 文档, "
            f"{len(self._bm25._doc_freq)} 特征"
        )

    def cosine_similarity(self, a: list[float], b: list[float]) -> float:
        """计算两个向量的余弦相似度。"""
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

    def get_embedding_usage(self, reset: bool = True) -> dict[str, int]:
        """获取并可选重置本轮 embedding token 用量。"""
        usage = {
            "total_tokens": self._session_embedding_tokens,
            "prompt_tokens": self._session_embedding_prompt_tokens,
        }
        if reset:
            self._session_embedding_tokens = 0
            self._session_embedding_prompt_tokens = 0
        return usage

    def search(
        self, query: str, top_k: int = 10, min_similarity: float = 0.3
    ) -> list[float]:
        """查询文本 → 嵌入向量（供下游向量搜索使用）。"""
        return self.embed(query)


_engine_singleton: EmbeddingEngine | None = None


def get_embedding_engine(reload: bool = False) -> EmbeddingEngine:
    """获取全局 EmbeddingEngine 单例。"""
    global _engine_singleton
    if _engine_singleton is None or reload:
        try:
            from tea_agent.config import get_config

            cfg = get_config()
            _engine_singleton = EmbeddingEngine(cfg.embedding)
        except Exception:
            _engine_singleton = EmbeddingEngine()
    return _engine_singleton
