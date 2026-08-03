"""DeepSeek 前缀缓存命中率报告工具。

依据官方文档 api-docs.deepseek.com/guides/kv_cache/ ：
- DeepSeek API 的 Context Caching 默认对所有用户启用
- usage 响应中带两个字段：
    prompt_cache_hit_tokens  — 本次请求命中缓存的前缀 token 数
    prompt_cache_miss_tokens — 本次请求未命中缓存的 token 数
- 命中率 = hit / (hit + miss)，best-effort，不保证 100%
"""


def format_cache_hit_rate(usage: dict) -> str:
    """从 usage 字典格式化缓存命中率字符串。

    Args:
        usage: API usage 字典（含 prompt_cache_hit_tokens / prompt_cache_miss_tokens）

    Returns:
        命中率描述字符串；无缓存字段（hit+miss=0）时返回空串。
        例: "缓存命中率: 87.5% (hit 35,000 / miss 5,000)"
    """
    usage = usage or {}
    hit = int(usage.get("prompt_cache_hit_tokens", 0) or 0)
    miss = int(usage.get("prompt_cache_miss_tokens", 0) or 0)
    total = hit + miss
    if total <= 0:
        return ""
    rate = hit / total * 100
    return f"缓存命中率: {rate:.1f}% (hit {hit:,} / miss {miss:,})"


def cache_hit_rate_number(usage: dict) -> float | None:
    """返回缓存命中率数值（0~100）；无缓存数据返回 None。"""
    usage = usage or {}
    hit = int(usage.get("prompt_cache_hit_tokens", 0) or 0)
    miss = int(usage.get("prompt_cache_miss_tokens", 0) or 0)
    total = hit + miss
    if total <= 0:
        return None
    return hit / total * 100
