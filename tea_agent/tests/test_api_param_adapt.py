"""api_retry 参数级 400 自适应降参的回归测试。

背景：模型返回 400 "max_tokens is too large: 250000. This model supports at
most 131072 completion tokens" 时，旧实现视为不可重试直接抛出 → 整轮失败。
新实现按报错文本中的硬上限就地降参重试，调用方无感知。
"""

from __future__ import annotations

import pytest

from tea_agent.api_retry import _adapt_request_params, call_with_retry


class FakeBadRequestError(Exception):
    """模拟 OpenAI SDK BadRequestError（400，不可重试）。"""


def _make_error(model_limit: int = 131072, requested: int = 250000) -> FakeBadRequestError:
    return FakeBadRequestError(
        f"Error code: 400 - {{'error': {{'code': '400', 'message': "
        f"'Param Incorrect', 'param': 'max_tokens is too large: {requested}. "
        f"This model supports at most {model_limit} completion tokens'}}}}"
    )


class TestAdaptRequestParams:
    def test_extract_cap_from_error_text(self):
        kwargs = {"max_tokens": 250000}
        assert _adapt_request_params(_make_error(), kwargs) is True
        assert kwargs["max_tokens"] == 131072

    def test_half_when_no_cap_in_text(self):
        kwargs = {"max_tokens": 2000}
        exc = FakeBadRequestError("Invalid max_tokens: exceeds limit")
        assert _adapt_request_params(exc, kwargs) is True
        assert kwargs["max_tokens"] == 1000

    def test_floor_not_below_minimum(self):
        kwargs = {"max_tokens": 300}
        exc = FakeBadRequestError("max_tokens is too large")
        assert _adapt_request_params(exc, kwargs) is False
        assert kwargs["max_tokens"] == 300

    def test_unrelated_error_not_adapted(self):
        kwargs = {"max_tokens": 250000}
        exc = FakeBadRequestError("messages is empty")
        assert _adapt_request_params(exc, kwargs) is False
        assert kwargs["max_tokens"] == 250000


class TestCallWithRetryAdaptation:
    def test_400_max_tokens_retries_with_reduced_value(self):
        """核心回归：400 参数超限 → 自动降参重试成功，而非抛出。"""
        calls: list[int] = []

        def fake_create(**kwargs):
            calls.append(kwargs["max_tokens"])
            if len(calls) == 1:
                raise _make_error()
            return "ok"

        result = call_with_retry(fake_create, max_retries=3, backoff=0.0, max_tokens=250000)
        assert result == "ok"
        assert calls == [250000, 131072]

    def test_original_kwargs_unchanged_after_success(self):
        """调用方传入的 kwargs 字典不被修改（call_with_retry 内部副本语义）。"""
        outer = {"max_tokens": 250000, "model": "m"}
        calls: list[int] = []

        def fake_create(**kwargs):
            calls.append(kwargs["max_tokens"])
            if len(calls) == 1:
                raise _make_error()
            return "ok"

        call_with_retry(fake_create, max_retries=3, backoff=0.0, **outer)
        assert outer["max_tokens"] == 250000

    def test_adapt_bounded_then_raises(self):
        """持续 400（无硬上限文本→对半降）时最多降 3 次，之后抛出。"""
        calls: list[int] = []

        def fake_create(**kwargs):
            calls.append(kwargs["max_tokens"])
            raise FakeBadRequestError("max_tokens is too large")

        with pytest.raises(FakeBadRequestError):
            call_with_retry(fake_create, max_retries=3, backoff=0.0, max_tokens=250000)
        assert calls == [250000, 125000, 62500, 31250]  # 首次 + 3 次降参

    def test_explicit_cap_below_floor_accepted(self):
        """报错给出的硬上限即使低于对半降下限也应采用。"""
        kwargs = {"max_tokens": 250000}
        assert _adapt_request_params(_make_error(model_limit=100), kwargs) is True
        assert kwargs["max_tokens"] == 100
