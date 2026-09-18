"""解码速率（decode tokens / second）测量 —— 纯函数，无副作用。

度量定义（与行业惯例对齐，避免数字被误读）
────────────────────────────────────────────
``tok/s = Σ completion_tokens / Σ 解码窗口秒数``

- **解码窗口** = 首 token 到达 → 该次流读完。请求发出到首 token 的那段等待
  （网络 RTT、排队、prefill、思考前的调度）**不计入** tok/s，而是单独作为
  TTFT 上报。否则一个 3s 的排队会把速率打到地板，得到的数字既不是模型的
  解码能力、也不是任何其它有意义的量。
- **``completion_tokens`` 取服务端上报值**，而非按字符估算：DeepSeek 等模型
  把 reasoning token 一并计入，正好对应「实际解码了多长」。
- 多轮 LLM 调用（工具循环）按 **Σ/Σ 聚合**，不是对各轮速率取算术平均 ——
  短轮次的极端值不会污染整体。

非流式模式（``no_stream_chunk``）拿不到首 token，只记总耗时：
``decode_seconds`` 置 ``None``（而非 0），聚合时被排除，绝不用
「请求耗时」冒充「解码耗时」制造虚高数字。

工具执行时间天然不在样本内：每个样本只覆盖单次模型流。
"""

from __future__ import annotations

import time

__all__ = [
    "MAX_SAMPLES",
    "format_speed",
    "make_sample",
    "summarize",
]

# 样本上限：只保最近 N 次模型调用，避免长会话把上下文对象撑大
MAX_SAMPLES = 200
# 小于此秒数的解码窗口视为噪声（除零保护 / 首末包同批到达）
_MIN_DECODE_SECONDS = 0.2
# 高于此速率在真实 API 上不可能出现 → 判为坏样本（如时间戳倒挂）
_MAX_TPS = 100_000.0
# 低于此秒数的 TTFT 无意义（同批次到达 / 时间源抖动）
_MIN_TTFT_SECONDS = 0.001
# 单次模型调用的时长上限（6 小时）。超出即判为坏样本：真实解码不可能这么久，
# 只可能是**时间源混用**（如 t_request 与 t_end 来自不同 epoch / 平台 monotonic
# 起点异常）—— 这种样本会显示成「848 小时」这类荒谬数字，必须整条丢弃。
_MAX_PLAUSIBLE_SECONDS = 6 * 3600.0


def _fmt_secs(value: float) -> float:
    """按量级给有效位数，保证 ``completion_tokens / decode_seconds`` 能反算出
    显示的 ``tok_per_sec``。

    固定 2 位小数会让亚秒窗口自相矛盾：``43 tok / 0.31s`` 却显示 137.8 tok/s
    （按显示值反算是 138.7）—— 数字对不上，观感就像测量不可信。
    """
    if value < 1:
        return round(value, 3)
    if value < 100:
        return round(value, 2)
    return round(value, 1)


def _num(value: object) -> float | None:
    """把入参安全转成非负 float；不可用返回 None。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    v = float(value)
    if v != v or v in (float("inf"), float("-inf")):  # NaN / inf
        return None
    return v if v >= 0 else None


def _plausible(seconds: float | None) -> bool:
    """时长是否在合理区间（None 视为可用，由调用方语义决定）。"""
    if seconds is None:
        return True
    return seconds <= _MAX_PLAUSIBLE_SECONDS


def make_sample(
    t_request: float | None,
    t_first: float | None,
    t_end: float | None,
    completion_tokens: object,
    streaming: bool = True,
    clock: object = None,
    est_tokens: object = None,
) -> dict | None:
    """构建一次模型调用的速率样本；数据不可用时返回 None（调用方直接丢弃）。

    Args:
        t_request: 请求发出时刻（monotonic）。非流式时可缺省。
        t_first: 首个携带内容的 chunk 到达时刻。
        t_end: 流读完（或响应返回）时刻。
        completion_tokens: 服务端上报的 completion_tokens。
        streaming: 本次是否为流式响应。非流式没有「首 token」，只记总耗时。
        clock: 可注入单调时钟（默认 ``time.monotonic``），供单测构造确定性时间。
        est_tokens: ``completion_tokens`` 缺失时的本地文本估算值，产出的样本会带
            ``estimated=True`` 标记 —— 估算口径绝不与实测悄悄混用。

    Returns:
        ``{"completion_tokens": int, "decode_seconds": float|None,
           "total_seconds": float|None, "ttft_seconds": float|None}``
        或 None。
    """
    toks = _num(completion_tokens)
    estimated = False
    if toks is None or toks <= 0:
        # 端点未上报 usage（不支持 stream_options 的第三方代理很常见）→ 退到文本估算。
        # 标记 estimated，供前端区分口径，不拿估算值冒充实测。
        toks = _num(est_tokens)
        if toks is None or toks <= 0:
            return None  # 连估算都不可用 → 宁可不显示，也不编一个数字
        estimated = True

    end = _num(t_end)
    if end is None:
        end = float(clock()) if clock is not None else time.monotonic()  # type: ignore[operator]

    if not streaming:
        start = _num(t_request)
        if start is None or end < start:
            return None
        total = end - start
        if not _plausible(total):
            return None  # 时间源混用 → 宁可不显示
        return {
            "completion_tokens": int(toks),
            # decode_seconds=None：非流式无法区分排队与解码，不参与 tok/s 计算
            "decode_seconds": None,
            "total_seconds": total if total > 0 else None,
            "ttft_seconds": None,
            "estimated": estimated,
        }

    first = _num(t_first)
    if first is None or end < first:
        return None
    decode = end - first
    if decode < _MIN_DECODE_SECONDS:
        return None  # 输出太短/首末包同批，算出的速率毫无参考价值
    if not _plausible(decode):
        return None  # 时间源混用（t_first/t_end 不同 epoch）

    req = _num(t_request)
    ttft = (first - req) if (req is not None and first >= req) else None
    if ttft is not None and ttft < _MIN_TTFT_SECONDS:
        ttft = None
    return {
        "completion_tokens": int(toks),
        "decode_seconds": decode,
        "total_seconds": (end - req) if (req is not None and end >= req) else None,
        "ttft_seconds": round(ttft, 3) if ttft is not None else None,
        "estimated": estimated,
    }


def summarize(samples: object) -> dict | None:
    """聚合样本为展示数据；没有任何可用速率时返回 None。

    Args:
        samples: ``make_sample`` 产出的样本列表（容忍 None / 含 None / 非 list）

    Returns:
        ``{"completion_tokens", "decode_seconds", "tok_per_sec",
           "ttft_seconds", "ttft_max_seconds", "wait_seconds",
           "request_seconds", "streams", "estimated"}`` 或 None
    """
    if not isinstance(samples, (list, tuple)):
        return None

    tokens = 0
    decode_secs = 0.0
    ttfts: list[float] = []
    streams = 0

    def _accumulate(items: list, require_real: bool
                    ) -> tuple[int, float, list, int, float]:
        agg_t = 0
        agg_s = 0.0
        agg_ttft: list[float] = []
        agg_n = 0
        agg_wait = 0.0
        for s in items:
            if not isinstance(s, dict):
                continue
            if bool(s.get("estimated")) != (not require_real):
                continue  # 实测与估算两条口径分开聚合，不混合
            try:
                toks = int(s.get("completion_tokens") or 0)
            except (TypeError, ValueError):
                continue
            if toks <= 0:
                continue
            dec = _num(s.get("decode_seconds"))
            if dec is None or dec < _MIN_DECODE_SECONDS:
                continue  # 无解码窗口的样本（非流式/坏样本）不参与速率
            agg_n += 1
            agg_t += toks
            agg_s += dec
            t = _num(s.get("ttft_seconds"))
            if t is not None:
                agg_ttft.append(t)
            # 等待（排队 + prefill）= 请求总时长 − 解码窗口；两者都可信时才计入，
            # 否则宁可留空，也不要在 tooltip 里给出一个假的"账本对得上"。
            tot = _num(s.get("total_seconds"))
            if tot is not None and tot >= dec:
                agg_wait += tot - dec
        return agg_t, agg_s, agg_ttft, agg_n, agg_wait

    # 实测优先：只要存在实测样本，估算样本就不参与展示（口径纯度）。
    tokens, decode_secs, ttfts, streams, wait_secs = _accumulate(
        list(samples), require_real=True)
    estimated_only = False
    if streams == 0:
        tokens, decode_secs, ttfts, streams, wait_secs = _accumulate(
            list(samples), require_real=False)
        estimated_only = streams > 0

    if streams == 0 or decode_secs < _MIN_DECODE_SECONDS:
        return None

    tps = tokens / decode_secs
    if not (0 < tps < _MAX_TPS):
        return None

    return {
        "completion_tokens": tokens,
        "decode_seconds": _fmt_secs(decode_secs),
        "tok_per_sec": round(tps, 1),
        # TTFT 取均值：每次请求的首 token 等待是独立事件，均值才有意义
        "ttft_seconds": _fmt_secs(sum(ttfts) / len(ttfts)) if ttfts else None,
        # 峰值：长上下文下均值会掩盖"某一次 prefill 卡了 30s"这类真痛点
        "ttft_max_seconds": _fmt_secs(max(ttfts)) if ttfts else None,
        # ⚡ 只量解码；以下是**没被 ⚡ 计入**的开销。缺了它们，一个 81.9 tok/s
        # 会被读成"整个回合只花了这么多时间"，进而误判在线模型不如自部署。
        "wait_seconds": _fmt_secs(wait_secs) if wait_secs > 0 else None,
        "request_seconds": (_fmt_secs(wait_secs + decode_secs)
                            if wait_secs > 0 else None),
        "streams": streams,
        # True → 全部样本来自本地文本估算，前端加 ~ 前缀标示口径
        "estimated": estimated_only,
    }


def format_speed(summary: dict | None, live: bool = False) -> str:
    """生成展示文案。

    Args:
        summary: ``summarize`` 的产出
        live: True 表示回合进行中的实时值（标注 ⏱ 前缀以区别于终值）

    Returns:
        如 ``⚡ 42.3 tok/s``；无数据时返回空串（前端据此隐藏，不显示 0 tok/s）
    """
    if not isinstance(summary, dict):
        return ""
    tps = _num(summary.get("tok_per_sec"))
    if tps is None or tps <= 0:
        return ""
    est = "~" if summary.get("estimated") else ""
    return f"{'⏱' if live else '⚡'} {est}{tps:,.1f} tok/s"
