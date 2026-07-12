"""
轻量级文本嵌入工具，支持两种模式：
1. API 模式：通过兼容 OpenAI embeddings 的 API 获取向量
2. 本地 TF-IDF 回退：纯 Python stdlib 实现，零额外依赖

用法:
    from tea_agent.embedding_util import EmbeddingEngine
    engine = EmbeddingEngine(config)
    vec = engine.embed("你好世界")           # -> [float, ...]
    results = engine.search("搜索词", top_k=10)  # -> [dict, ...]

设计要点:
- API 优先：配置了 api_url + api_key + model_name 时使用远程 API
- TF-IDF 回退：无 API 时自动使用本地字符 bigram TF-IDF（零外部依赖）
- 自动降级：API 调用失败时静默回退到 TF-IDF
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

# ── 尝试导入 requests（API 模式需要）──
try:
    import requests
    HAS_REQUESTS: bool = True
except ImportError:
    HAS_REQUESTS = False
    requests = None  # type: ignore[assignment]


# ── 本地 TF-IDF 回退 ────────────────────────────────────────────

class _SimpleTFIDF:
    """极简 TF-IDF 实现：字符 bigram 特征 + 哈希降维 + 余弦相似度。

    原理：
    - 使用字符级 bigram 作为特征（对中文等非空格分隔语言友好）
    - 通过 MD5 哈希将 bigram 映射到固定维度向量空间
    - 支持增量式文档添加来构建 IDF 语料库

    Attributes:
        vector_dim: 向量维度（固定大小，便于缓存和检索）
    """

    def __init__(self, vector_dim: int = 256) -> None:
        """初始化 TF-IDF 向量器。

        Args:
            vector_dim: 输出向量维度，默认 256。越大精度越高但占用更多内存。
        """
        self.vector_dim = vector_dim
        self._doc_freq: Counter[str] = Counter()  # bigram → 出现过该 bigram 的文档数
        self._doc_count: int = 0

    def _tokenize(self, text: str) -> list[str]:
        """将文本切分为字符 bigram 序列（对中文友好）。

        Args:
            text: 输入文本

        Returns:
            bigram 字符串列表，如 "你好世界" → ["你好", "好世", "世界"]
        """
        text = text.strip().lower()
        if len(text) < 2:
            return [text] if text else []
        return [text[i:i+2] for i in range(len(text) - 1)]

    def _hash_token(self, token: str) -> int:
        """将 bigram token 通过 MD5 哈希映射到 [0, vector_dim) 范围。

        Args:
            token: bigram 字符串

        Returns:
            0 到 vector_dim-1 之间的整数索引
        """
        h = int(hashlib.md5(token.encode('utf-8')).hexdigest(), 16)
        return h % self.vector_dim

    def add_document(self, text: str) -> None:
        """向语料库添加一个文档，用于构建全局 IDF 统计。

        Args:
            text: 文档文本
        """
        tokens = set(self._tokenize(text))
        for t in tokens:
            self._doc_freq[t] += 1
        self._doc_count += 1

    def vectorize(self, text: str) -> list[float]:
        """将文本转为 TF-IDF 向量（哈希降维 + L2 归一化）。

        Args:
            text: 输入文本

        Returns:
            vector_dim 维的浮点数向量
        """
        tokens = self._tokenize(text)
        if not tokens:
            return [0.0] * self.vector_dim

        tf: Counter[str] = Counter(tokens)
        vec = [0.0] * self.vector_dim
        total = len(tokens)

        for token, count in tf.items():
            idx = self._hash_token(token)
            # TF: 词频 / 总词数
            tf_val = count / total
            # IDF: log((N+1)/(df+1)) + 1（平滑版）
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
    """文本向量引擎 — API 优先，自动回退 TF-IDF。

    工作模式：
    - **API 模式**：配置了 api_url/api_key/model_name 时使用远程 embeddings API
    - **TF-IDF 模式**：无 API 配置或 API 调用失败时，自动使用本地字符 bigram TF-IDF
    - **自动降级**：API 调用异常时静默回退到 TF-IDF，保证服务不中断

    用法:
        engine = EmbeddingEngine(config)
        vector = engine.embed("你好世界")       # -> [float, ...]
        vectors = engine.embed_batch(["a", "b"]) # -> [[float, ...], ...]
    """

    def __init__(self, config: Any = None) -> None:
        """初始化嵌入引擎。

        Args:
            config: EmbeddingConfig dataclass、dict 或 None。
                    None 时使用 TF-IDF 模式（始终可用）。
        """
        self.api_url: str = ""
        self.model_name: str = ""
        self.api_key: str = ""
        self.dimension: int = 0
        self._use_api: bool = False
        self._tfidf = _SimpleTFIDF()

        # Token 用量跟踪（全局累计 + 会话累计）
        self._total_embedding_tokens: int = 0
        self._total_embedding_prompt_tokens: int = 0
        self._session_embedding_tokens: int = 0
        self._session_embedding_prompt_tokens: int = 0

        if config is not None:
            self._init_from_config(config)

    def _init_from_config(self, config: Any) -> None:
        """从配置对象或字典初始化 API 参数。

        Args:
            config: 支持 EmbeddingConfig dataclass 或 dict。
                    优先读取 api_url / model_name / api_key / dimension 字段。
        """
        if hasattr(config, 'api_url'):
            self.api_url = getattr(config, 'api_url', "") or ""
            self.model_name = getattr(config, 'model_name', "") or ""
            self.api_key = getattr(config, 'api_key', "") or ""
            self.dimension = getattr(config, 'dimension', 0) or 0
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
        """当前模式: 'api' | 'tfidf'"""
        return "api" if self._use_api else "tfidf"

    @property
    def configured(self) -> bool:
        """是否已配置（API 模式需要 URL + model，TF-IDF 始终可用）"""
        return True  # TF-IDF 始终作为回退

    def embed(self, text: str) -> list[float]:
        """将文本转为向量。API 优先，失败时自动回退 TF-IDF。

        Args:
            text: 待嵌入的文本

        Returns:
            浮点数向量列表（维度取决于 API 模型或 TF-IDF 的 256 维）
        """
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
                logger.warning(f"API 嵌入失败，回退 TF-IDF: {e}")
                return self._embed_tfidf(text)
        else:
            return self._embed_tfidf(text)

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """批量嵌入文本。API 模式尝试批量请求，TF-IDF 逐个处理。

        Args:
            texts: 文本列表

        Returns:
            向量列表，每个文本对应一个向量
        """
        if self._use_api:
            try:
                result = self._embed_api_batch(texts)
                logger.info(f"✅ embedding 批量成功: {self.model_name}, batch_size={len(texts)}")
                return result
            except Exception as e:
                logger.warning(f"API 批量嵌入失败，逐个 TF-IDF: {e}")
        return [self._embed_tfidf(t) for t in texts]

    def _build_url(self) -> str:
        """构建 embeddings API URL，自动处理 /v1 和 /embeddings 后缀。

        Returns:
            完整的 API URL 字符串
        """
        base = self.api_url.rstrip("/")
        if base.endswith("/embeddings"):
            return base
        if base.endswith("/v1"):
            return base + "/embeddings"
        return base + "/v1/embeddings"

    def _embed_api(self, text: str) -> list[float]:
        """通过远程 API 获取单个文本的嵌入向量。

        Args:
            text: 输入文本

        Returns:
            浮点数向量

        Raises:
            RuntimeError: API 返回格式异常
            requests.RequestException: 网络或 HTTP 错误
        """
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

        logger.info(f"embedding request: model={self.model_name}, text_len={len(text)}, url={url}")

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
        """通过远程 API 批量获取文本嵌入向量。

        Args:
            texts: 文本列表

        Returns:
            向量列表，顺序与输入保持一致

        Raises:
            RuntimeError: API 返回格式异常
        """
        url = self._build_url()
        logger.debug(f"embedding batch request: model={self.model_name}, batch_size={len(texts)}, url={url}")
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

    def _embed_tfidf(self, text: str) -> list[float]:
        """使用本地 TF-IDF 进行文本向量化（API 不可用时的回退方案）。

        Args:
            text: 输入文本

        Returns:
            256 维 TF-IDF 向量
        """
        return self._tfidf.vectorize(text)

    def build_tfidf_vocabulary(self, texts: list[str]) -> None:
        """用一批文本来构建 TF-IDF 语料库（提升本地搜索质量）。

        调用此方法后，TF-IDF 的 IDF 统计将基于提供的文档集合计算。
        建议在使用本地模式前，先用数据库中已有的文本数据初始化。

        Args:
            texts: 文档文本列表
        """
        for t in texts:
            if t and t.strip():
                self._tfidf.add_document(t.strip())
        logger.debug(f"TF-IDF 词汇表: {self._tfidf._doc_count} 文档, "
                     f"{len(self._tfidf._doc_freq)} 特征")

    def cosine_similarity(self, a: list[float], b: list[float]) -> float:
        """计算两个向量的余弦相似度（使用 numpy 加速）。

        Args:
            a: 向量 A
            b: 向量 B

        Returns:
            [-1, 1] 范围的相似度。任一向量为零向量时返回 0.0。

        Raises:
            ValueError: 两向量维度不匹配
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

    def get_embedding_usage(self, reset: bool = True) -> dict[str, int]:
        """获取并可选重置本次会话的嵌入 token 用量。

        Args:
            reset: True 时归零会话计数器（用于会话结束时读取本轮用量）

        Returns:
            {"total_tokens": int, "prompt_tokens": int} 格式的用量字典
        """
        usage = {
            "total_tokens": self._session_embedding_tokens,
            "prompt_tokens": self._session_embedding_prompt_tokens,
        }
        if reset:
            self._session_embedding_tokens = 0
            self._session_embedding_prompt_tokens = 0
        return usage

    def search(self, query: str, top_k: int = 10, min_similarity: float = 0.3) -> list[float]:
        """将查询文本转为向量，供下游向量搜索使用。

        这是便捷方法，只负责生成查询向量。
        实际向量搜索需调用 store.search_by_vector()。

        Args:
            query: 搜索文本
            top_k: 结果数量（此方法忽略，仅返回向量）
            min_similarity: 最低相似度阈值（此方法忽略，仅返回向量）

        Returns:
            查询文本的嵌入向量
        """
        return self.embed(query)


# ── 便捷函数 ────────────────────────────────────────────────────

_engine_singleton: EmbeddingEngine | None = None


def get_embedding_engine(reload: bool = False) -> EmbeddingEngine:
    """获取全局 EmbeddingEngine 单例。

    第一次调用时自动从配置初始化。
    后续调用返回缓存实例（除非 reload=True 强制重建）。

    Args:
        reload: True 时强制重建引擎实例

    Returns:
        EmbeddingEngine 实例
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
