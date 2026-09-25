"""解码速度（tok/s）测量与格式化 —— 纯函数，供会话层与服务端 UI 复用。

口径说明（与 llama.cpp / vLLM 的 *decode speed* 对齐）：

    解码速度 = 本轮输出 token 数 / 解码耗时

其中「解码耗时」= 首个输出增量（content 或 reasoning）到达 → 流结束，
**刻意排除首 token 等待（prefill / TTFT）**。若把 prefill 计入，长上下文下
同一次生成的读数会被拖低数倍，失去横向可比性；因此 TTFT 单独作为字段上报。

设计约束：
- 全部为纯函数（时间戳由调用方注入），判定确定性，可在秒级单测中覆盖；
- 输入非法/窗口过短/时序异常（时钟回拨）一律返回 None 或空串，
  **绝不下发可疑数字** —— UI 侧据此隐藏该字段而不是显示 0 tok/s；
- 不依赖任何 tea_agent 模块（叶子模块），避免给 session 包引入循环导入。
"""

from __future__ import annotations

import logging
from typing import Any

# 仅用标准库 logging：本模块刻意不依赖任何 tea_agent 模块（叶子模块，见上方
# 设计约束），加它不会引入循环导入。
logger = logging.getLogger("session.decode_rate")

# 采样窗口下限（秒）：短于此窗口的除法噪声过大（首个增量与流结束几乎同时），
# 宁可不显示也不显示抖动的天文数字。
MIN_DECODE_SECONDS = 0.05

# 防御性上界（tok/s）：真实端点极少超过此值；超出说明时间戳异常
# （如时钟回拨 / 复用旧时间戳），作为「无数据」处理。
MAX_PLAUSIBLE_TPS = 5000.0


# ──────────────────────────────────────────────
#  计算（纯函数）
# ──────────────────────────────────────────────


def compute_decode_tps(
    tokens: int | float | None,
    first_ts: float | None,
    end_ts: float | None,
) -> float | None:
    """计算解码速度（token/秒）。

    Args:
        tokens: 本轮输出 token 数（必须 > 0 才有意义）
        first_ts: 首个输出增量的时间戳（time.monotonic）
        end_ts: 流结束时间戳（time.monotonic），须 >= first_ts

    Returns:
        float | None: 速度；数据缺失 / 窗口过短 / 时序异常时返回 None
    """
    try:
        n = float(tokens or 0)
    except (TypeError, ValueError):
        return None
    if n <= 0:
        return None
    if first_ts is None or end_ts is None:
        return None
    elapsed = float(end_ts) - float(first_ts)
    if elapsed < MIN_DECODE_SECONDS:
        return None
    tps = n / elapsed
    if tps <= 0 or tps > MAX_PLAUSIBLE_TPS:
        return None
    return tps


def compute_ttft_ms(start_ts: float | None, first_ts: float | None) -> float | None:
    """计算首 token 等待时间（毫秒）。数据缺失 / 时序异常返回 None。"""
    if start_ts is None or first_ts is None:
        return None
    delta = (float(first_ts) - float(start_ts)) * 1000.0
    if delta < 0:
        return None
    return delta


def compute_decode_stats(
    tokens: int | float | None,
    start_ts: float | None,
    first_ts: float | None,
    end_ts: float | None,
    estimated: bool = False,
) -> dict[str, Any]:
    """汇总一次流式生成的解码性能数据。

    Args:
        tokens: 本轮输出 token 数
        start_ts: 请求发出时间戳
        first_ts: 首个输出增量时间戳
        end_ts: 流结束时间戳
        estimated: tokens 是否为启发式估算（供应商未回传 usage）

    Returns:
        dict: decode_tps / decode_tokens / decode_seconds / ttft_ms / estimated /
            decode_tps_text（UI 文案，无数据时为空串）
    """
    tps = compute_decode_tps(tokens, first_ts, end_ts)
    seconds = 0.0
    if tps is not None and first_ts is not None and end_ts is not None:
        seconds = max(0.0, float(end_ts) - float(first_ts))
    ttft_ms = compute_ttft_ms(start_ts, first_ts)
    return {
        "decode_tps": tps if tps is not None else 0.0,
        "decode_tokens": int(tokens or 0),
        "decode_seconds": round(seconds, 3),
        "ttft_ms": round(ttft_ms, 1) if ttft_ms is not None else 0.0,
        "estimated": bool(estimated),
        "decode_tps_text": format_decode_tps(tps),
    }


# ──────────────────────────────────────────────
#  格式化（UI 文案）
# ──────────────────────────────────────────────


def format_decode_tps(tps: float | None) -> str:
    """格式化解码速度为 UI 文案。无有效数据返回空串（前端据此隐藏）。

    精度按量级切换；阈值取「四舍五入后的边界」（99.5 / 9.995）而非整数边界，
    避免出现 ``99.99 → "100.0 tok/s"`` 这类位数与读数不自洽的文案。
    """
    if tps is None:
        return ""
    try:
        v = float(tps)
    except (TypeError, ValueError):
        return ""
    if v <= 0:
        return ""
    if v >= 99.5:
        return f"⚡ {v:.0f} tok/s"
    if v >= 9.995:
        return f"⚡ {v:.1f} tok/s"
    return f"⚡ {v:.2f} tok/s"


def format_ttft(ttft_ms: float | None) -> str:
    """格式化首 token 等待时间。无有效数据返回空串。"""
    if ttft_ms is None:
        return ""
    try:
        v = float(ttft_ms)
    except (TypeError, ValueError):
        return ""
    if v < 0:
        return ""
    if v >= 1000:
        return f"首 token {v / 1000:.2f}s"
    return f"首 token {v:.0f}ms"


# ──────────────────────────────────────────────
#  会话接线
# ──────────────────────────────────────────────


def record_decode_stats(
    ctx: Any,
    tokens: int | float | None,
    start_ts: float | None,
    first_ts: float | None,
    end_ts: float | None,
    estimated: bool = False,
) -> dict[str, Any]:
    """把一次流式生成的解码性能写入会话 context（旁路写入，失败静默降级）。

    写入失败不影响主对话流程 —— 与审计/统计类旁路写入的 fail-open 约定一致。

    Returns:
        dict: 同 compute_decode_stats
    """
    stats = compute_decode_stats(tokens, start_ts, first_ts, end_ts, estimated)
    if ctx is None:
        return stats
    try:
        ctx._decode_tps = stats["decode_tps"]
        ctx._decode_tokens = stats["decode_tokens"]
        ctx._decode_seconds = stats["decode_seconds"]
        ctx._ttft_ms = stats["ttft_ms"]
        ctx._decode_estimated = stats["estimated"]
        ctx._decode_tps_text = stats["decode_tps_text"]
    except Exception:
        logger.debug("record_decode_stats: 解码速度字段写入失败（遥测缺失，不影响生成）", exc_info=True)
    return stats


def completion_tokens_total(ctx: Any) -> int:
    """读取会话累计输出 token 数（usage.completion_tokens）。

    解码速度需要「本次调用产出了多少 token」，而 usage 是累计值 ——
    取调用前后的差值即可，不依赖供应商是否在流中逐块回传 usage。

    读不到（无 usage / 字段缺失 / 类型异常）返回 0，调用方按「无数据」处理。
    做成模块级纯函数而非会话方法：调用点无需依赖宿主对象上存在某个新方法，
    最小桩对象（如测试用的 _FakeSession）不会因新增方法而崩溃。
    """
    try:
        usage = getattr(ctx, "_last_usage", None) or {}
        if not isinstance(usage, dict):
            return 0
        return int(usage.get("completion_tokens", 0) or 0)
    except (TypeError, ValueError, AttributeError):
        return 0


def reset_decode_stats(ctx: Any) -> None:
    """清零解码速度统计（新用户回合入口调用）。

    不清零会让「本回合未产出 token」（如纯工具调用即失败）的前端继续显示
    上一回合的速度 —— 数字是真的，但归属于别的一轮，属于误导。
    """
    if ctx is None:
        return
    try:
        ctx._decode_tps = 0.0
        ctx._decode_tokens = 0
        ctx._decode_seconds = 0.0
        ctx._ttft_ms = 0.0
        ctx._decode_estimated = False
        ctx._decode_tps_text = ""
    except Exception:
        logger.debug("reset_decode_stats: 解码速度字段写入失败（遥测缺失，不影响生成）", exc_info=True)


def decode_usage_fields(ctx: Any) -> dict[str, Any]:
    """从会话 context 提取解码速度字段，供前端 usage 事件直接展示。

    无数据时返回空 dict（前端不渲染该段），而不是下发 0 —— 0 会被误读为
    「速度为零」而不是「尚未测量」。
    """
    if ctx is None:
        return {}
    try:
        tps = float(getattr(ctx, "_decode_tps", 0.0) or 0.0)
    except (TypeError, ValueError):
        return {}
    text = getattr(ctx, "_decode_tps_text", "") or format_decode_tps(tps)
    if tps <= 0 or not text:
        return {}
    fields: dict[str, Any] = {
        "decode_tps": round(tps, 1),
        "decode_tps_text": text,
        "decode_tokens": int(getattr(ctx, "_decode_tokens", 0) or 0),
        "decode_seconds": round(float(getattr(ctx, "_decode_seconds", 0.0) or 0.0), 2),
        "decode_estimated": bool(getattr(ctx, "_decode_estimated", False)),
    }
    ttft_text = format_ttft(getattr(ctx, "_ttft_ms", 0.0) or None)
    if ttft_text:
        fields["ttft_text"] = ttft_text
    return fields
