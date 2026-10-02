"""token_meter — 前缀缓存命中率观测（借鉴 dsh token-budget 记账）。

从 usage 提取缓存命中/未命中，滑动窗口聚合命中率 —— 前缀缓存治理
（tool_shield/tool_profiles/消息尾部注入）是否有效的唯一硬指标。
旁路观测：fail-open，不影响计费累计。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger("token_meter")

MAX_SAMPLES = 200


def cache_hit_ratio(usage: object) -> float | None:
    """从 usage 对象/dict 提取缓存命中率；无法计算返回 None。

    兼容字段：prompt_cache_hit_tokens（DeepSeek）/ prompt_tokens_details.cached_tokens（OpenAI）。
    """
    hit = _get(usage, "prompt_cache_hit_tokens")
    if hit is None:
        details = _get(usage, "prompt_tokens_details") or _get(usage, "cached_tokens")
        if details is not None and not isinstance(details, (int, float)):
            hit = _get(details, "cached_tokens")
        elif isinstance(details, (int, float)):
            hit = details
    prompt = _get(usage, "prompt_tokens")
    if hit is None or prompt is None or prompt <= 0:
        return None
    return max(0.0, min(1.0, hit / prompt))


def _get(obj: object, name: str):
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


@dataclass
class TokenMeter:
    """滑动窗口缓存命中率。"""

    samples: list[float] = field(default_factory=list)

    def record(self, usage: object) -> float | None:
        """记录一次请求的命中率；返回本次命中率（无数据 None）。"""
        try:
            r = cache_hit_ratio(usage)
            if r is not None:
                self.samples.append(r)
                if len(self.samples) > MAX_SAMPLES:
                    del self.samples[: len(self.samples) - MAX_SAMPLES]
            return r
        except Exception as e:  # noqa: BLE001 — 观测失败不影响调用
            logger.debug("token_meter 记录跳过: %s", e)
            return None

    def summary(self) -> dict:
        if not self.samples:
            return {"samples": 0, "avg_hit_ratio": None, "last": None}
        return {
            "samples": len(self.samples),
            "avg_hit_ratio": round(sum(self.samples) / len(self.samples), 4),
            "last": round(self.samples[-1], 4),
        }
