"""api_retry 弹性重试工具测试。"""
import time

import pytest

from tea_agent.api_retry import _is_retryable, call_with_retry

# 动态创建与 openai SDK 同名的异常类，模拟真实可重试/不可重试错误
APIConnectionError = type("APIConnectionError", (Exception,), {})
RateLimitError = type("RateLimitError", (Exception,), {})
AuthenticationError = type("AuthenticationError", (Exception,), {})


def test_retryable_exception_names():
    assert _is_retryable(APIConnectionError("connect error"))
    assert _is_retryable(RateLimitError("rate limited"))
    # 类名含关键词
    assert _is_retryable(Exception("connection reset by peer"))
    assert _is_retryable(Exception("Request timed out"))


def test_non_retryable_exception():
    assert not _is_retryable(AuthenticationError("invalid api key"))
    assert not _is_retryable(ValueError("bad param"))


def test_retry_success_after_failures():
    """连接错误重试 2 次后成功。"""
    calls = []

    def flaky_fn():
        calls.append(1)
        if len(calls) <= 2:
            raise APIConnectionError("connect error")
        return "ok"

    result = call_with_retry(flaky_fn, max_retries=3, backoff=0.01,
                             sleep_recovery_wait=0.0)
    assert result == "ok"
    assert len(calls) == 3  # 首次 + 2 次重试


def test_retry_exhausted_raises():
    """重试耗尽后抛出最后一个异常。"""
    calls = []

    def always_fail():
        calls.append(1)
        raise APIConnectionError("still down")

    with pytest.raises(APIConnectionError):
        call_with_retry(always_fail, max_retries=2, backoff=0.01,
                        sleep_recovery_wait=0.0)
    assert len(calls) == 3  # 首次 + 2 次重试


def test_non_retryable_raises_immediately():
    """不可重试错误（认证/参数）立即抛出，不重试。"""
    calls = []

    def auth_fail():
        calls.append(1)
        raise AuthenticationError("invalid api key")

    with pytest.raises(AuthenticationError):
        call_with_retry(auth_fail, max_retries=3, backoff=0.01)
    assert len(calls) == 1  # 只调用一次


def test_on_retry_callback_invoked():
    """重试回调被调用且带正确参数。"""
    calls = []
    retries = []

    def flaky():
        calls.append(1)
        if len(calls) <= 1:
            raise APIConnectionError("down")

    def on_retry(attempt, exc, wait):
        retries.append((attempt, type(exc).__name__, wait))

    call_with_retry(flaky, max_retries=3, backoff=0.01,
                    sleep_recovery_wait=0.0, on_retry=on_retry)
    assert len(retries) == 1
    assert retries[0][0] == 1
    assert retries[0][1] == "APIConnectionError"


def test_connection_error_extra_wait():
    """连接类错误应增加 sleep_recovery_wait 等待时间。"""
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) <= 1:
            raise APIConnectionError("connect error")
        return "ok"

    t0 = time.time()
    call_with_retry(flaky, max_retries=2, backoff=0.01, sleep_recovery_wait=0.05)
    elapsed = time.time() - t0
    # 等待至少 sleep_recovery_wait
    assert elapsed >= 0.05


def test_backoff_increases():
    """指数退避：第 2 次重试等待 > 第 1 次。"""
    waits = []

    def on_retry(attempt, exc, wait):
        waits.append(wait)

    calls = []

    def flaky():
        calls.append(1)
        if len(calls) <= 3:
            raise APIConnectionError("down")
        return "ok"

    call_with_retry(flaky, max_retries=5, backoff=0.01,
                    sleep_recovery_wait=0.0, on_retry=on_retry)
    # 退避序列：0.01, 0.02, 0.04（2^0, 2^1, 2^2）
    assert len(waits) == 3
    assert waits[1] > waits[0]
    assert waits[2] > waits[1]


def test_max_retries_zero():
    """max_retries=0：一次失败立即抛出，不重试。"""
    calls = []

    def flaky():
        calls.append(1)
        raise APIConnectionError("down")

    with pytest.raises(APIConnectionError):
        call_with_retry(flaky, max_retries=0, backoff=0.01)
    assert len(calls) == 1


def test_kwargs_passed_through():
    """kwargs 正确透传给目标函数。"""
    seen = {}

    def target(model=None, messages=None, stream=False):
        seen["model"] = model
        seen["messages"] = messages
        seen["stream"] = stream
        return "ok"

    result = call_with_retry(
        target, model="m", messages=[1], stream=True, max_retries=1
    )
    assert result == "ok"
    assert seen == {"model": "m", "messages": [1], "stream": True}


def test_config_defaults():
    """AgentConfig 默认弹性参数合理。"""
    from tea_agent.config import AgentConfig

    cfg = AgentConfig()
    assert cfg.api_max_retries == 3
    assert cfg.api_retry_backoff == 2.0
    assert cfg.api_sleep_recovery_wait == 5.0
    assert cfg.api_request_timeout == 120.0
    assert cfg.api_connect_timeout == 30.0
