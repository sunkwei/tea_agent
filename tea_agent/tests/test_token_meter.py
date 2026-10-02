"""token_meter 前缀缓存命中率观测回归测试。"""

from __future__ import annotations

from types import SimpleNamespace

from tea_agent.token_meter import TokenMeter, cache_hit_ratio


def test_ratio_from_deepseek_fields():
    u = SimpleNamespace(prompt_tokens=1000, prompt_cache_hit_tokens=800)
    assert cache_hit_ratio(u) == 0.8


def test_ratio_from_openai_details():
    u = SimpleNamespace(
        prompt_tokens=1000,
        prompt_tokens_details=SimpleNamespace(cached_tokens=500),
    )
    assert cache_hit_ratio(u) == 0.5


def test_ratio_from_dict():
    assert cache_hit_ratio({"prompt_tokens": 200, "prompt_cache_hit_tokens": 100}) == 0.5


def test_ratio_none_when_missing():
    assert cache_hit_ratio(SimpleNamespace(prompt_tokens=100)) is None
    assert cache_hit_ratio(SimpleNamespace(prompt_cache_hit_tokens=10)) is None
    assert cache_hit_ratio(SimpleNamespace(prompt_tokens=0, prompt_cache_hit_tokens=0)) is None


def test_ratio_clamped():
    u = SimpleNamespace(prompt_tokens=100, prompt_cache_hit_tokens=150)
    assert cache_hit_ratio(u) == 1.0


def test_meter_window_and_summary():
    m = TokenMeter()
    assert m.record(SimpleNamespace(prompt_tokens=100)) is None  # 无命中数据
    m.record(SimpleNamespace(prompt_tokens=100, prompt_cache_hit_tokens=90))
    m.record(SimpleNamespace(prompt_tokens=100, prompt_cache_hit_tokens=50))
    s = m.summary()
    assert s["samples"] == 2
    assert s["avg_hit_ratio"] == 0.7
    assert s["last"] == 0.5


def test_meter_never_raises_on_garbage():
    m = TokenMeter()
    assert m.record(object()) is None
    assert m.record(None) is None
