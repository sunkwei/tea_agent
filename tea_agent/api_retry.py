"""
OpenAI 兼容接口调用的弹性重试工具。

场景：网络中断、PC 睡眠恢复、临时 5xx/429 等瞬时故障。
策略：
- 仅对**可恢复错误**重试（连接错误/超时/限流/5xx），认证与参数错误直接抛出；
- 指数退避：第 n 次重试等待 backoff * 2^(n-1) 秒；
- 连接类错误额外等待 sleep_recovery_wait（PC 睡眠恢复后网络栈重建需要时间）。

用法：
    from tea_agent.api_retry import call_with_retry

    stream = call_with_retry(
        client.chat.completions.create,
        max_retries=3, backoff=2.0, on_retry=_log_retry,
        model=..., messages=..., stream=True,
    )
"""

from __future__ import annotations

import contextlib
import logging
import re
import time
from collections.abc import Callable
from typing import Any

logger = logging.getLogger("tea_agent.api_retry")

# OpenAI SDK / httpx 可重试异常类型名（按类名匹配，避免硬依赖 import）
_RETRYABLE_EXC_NAMES = (
    # openai SDK
    "APIConnectionError",
    "APITimeoutError",
    "RateLimitError",
    "InternalServerError",
    "APIStatusError",
    # httpx 网络层
    "ConnectError",
    "ConnectTimeout",
    "ReadTimeout",
    "WriteTimeout",
    "RemoteProtocolError",
    "NetworkError",
    "ReadError",
    "PoolTimeout",
)

# 错误消息中的可重试关键词（部分网关/代理错误的透传文本）
_RETRYABLE_MSG_KEYWORDS = (
    "connection",
    "timeout",
    "timed out",
    "temporarily unavailable",
    "slow down",
    "reset by peer",
    "broken pipe",
    "network is unreachable",
    "temporary failure in name resolution",
)


def _is_retryable(exc: Exception) -> bool:
    """判断异常是否可重试（连接/超时/限流/5xx）。"""
    name = type(exc).__name__
    if name in _RETRYABLE_EXC_NAMES:
        return True
    # 某些网关/代理错误以文本透传
    msg = str(exc).lower()
    return any(k in msg for k in _RETRYABLE_MSG_KEYWORDS)


# ── 参数级 400 自适应（max_tokens 超上限）──
# 网络类错误重试即可，但「参数超出模型上限」类 400（如 max_tokens=250000 而模型
# 最多 131072 输出）重试永远不会成功 —— 正确姿势是降参后重试。这里就地修正
# kwargs 里的 max_tokens，调用方无感知、无需改签名。
_PARAM_ERR_KEYWORDS = ("max_tokens", "max output tokens", "completion tokens")
# 「at most 131072 completion tokens」类报错文本中的硬上限
_MAX_TOKENS_CAP_RE = re.compile(r"at most\s+(\d+)\s+(?:completion|output)\s*tokens", re.IGNORECASE)
_MIN_ADAPTIVE_MAX_TOKENS = 256
_PARAM_ADAPT_MAX = 3


def _adapt_request_params(exc: Exception, kwargs: dict) -> bool:
    """若 exc 是参数超限类错误，就地修正 kwargs["max_tokens"] 并返回 True。

    优先取报错文本中的硬上限（"at most N completion tokens"）；取不到则对半降。
    已到下限或修正后无变化时返回 False（交由常规重试/抛出逻辑处理）。
    """
    msg = str(exc)
    if not any(k in msg.lower() for k in _PARAM_ERR_KEYWORDS):
        return False
    cur = kwargs.get("max_tokens")
    if not isinstance(cur, (int, float)) or int(cur) <= 0:
        return False
    m = _MAX_TOKENS_CAP_RE.search(msg)
    if m:
        # 报错给出硬上限时直接采用（可低于对半降的下限——模型上限就是这么小）
        new_val = int(m.group(1))
    else:
        # 无硬上限可循 → 对半降，低于下限则放弃（防止无限减到 0）
        if int(cur) <= _MIN_ADAPTIVE_MAX_TOKENS:
            return False
        new_val = int(cur) // 2
        if new_val < _MIN_ADAPTIVE_MAX_TOKENS:
            return False
    if new_val <= 0 or new_val >= int(cur):
        return False
    kwargs["max_tokens"] = new_val
    return True


def _is_connection_error(exc: Exception) -> bool:
    """判断是否为连接层错误（睡眠恢复后网络栈重建，需额外等待）。"""
    name = type(exc).__name__
    return name in (
        "APIConnectionError",
        "ConnectError",
        "ConnectTimeout",
        "NetworkError",
        "RemoteProtocolError",
        "ReadError",
    ) or any(k in str(exc).lower() for k in ("reset by peer", "broken pipe", "network is unreachable"))


def call_with_retry(
    fn: Callable[..., Any],
    *args: Any,
    max_retries: int = 3,
    backoff: float = 2.0,
    sleep_recovery_wait: float = 5.0,
    on_retry: Callable[[int, Exception, float], None] | None = None,
    **kwargs: Any,
) -> Any:
    """调用 fn(*args, **kwargs)，对可恢复错误指数退避重试。

    Args:
        fn: 可调用对象（如 client.chat.completions.create）
        max_retries: 最大重试次数（不含首次尝试），默认 3
        backoff: 指数退避基数（秒），第 n 次重试等待 backoff * 2^(n-1)
        sleep_recovery_wait: 连接类错误的额外等待秒数（睡眠恢复场景）
        on_retry: 重试前回调 on_retry(attempt, exc, wait_seconds)

    Returns:
        fn 的返回值；重试耗尽后抛出最后一个异常
    """
    attempt = 0
    param_adapted = 0
    while True:
        try:
            return fn(*args, **kwargs)
        except Exception as e:  # noqa: BLE001 — 需捕获全部异常判断可重试性
            # 参数超限类 400：降参后立即重试（独立于网络重试计数，不退避）
            if param_adapted < _PARAM_ADAPT_MAX and _adapt_request_params(e, kwargs):
                param_adapted += 1
                logger.warning(
                    "API 参数超限，自适应降参第 %d/%d 次: %s → max_tokens=%s",
                    param_adapted, _PARAM_ADAPT_MAX, str(e)[:150], kwargs.get("max_tokens"),
                )
                continue
            if attempt >= max_retries or not _is_retryable(e):
                raise
            attempt += 1
            wait = backoff * (2 ** (attempt - 1))
            if _is_connection_error(e):
                wait += sleep_recovery_wait
            if on_retry is not None:
                with contextlib.suppress(Exception):
                    on_retry(attempt, e, wait)
            logger.warning(
                "API 调用失败，第 %d/%d 次重试: %s: %s，等待 %.1fs",
                attempt, max_retries, type(e).__name__, str(e)[:150], wait,
            )
            time.sleep(wait)
