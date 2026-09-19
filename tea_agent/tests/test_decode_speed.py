"""解码速率（tok/s）功能测试。

覆盖三层，重点在**静默失效**类缺陷：
- decode_speed 纯函数：度量定义（Σ/Σ 聚合、TTFT 分离）、样本有效性、口径纯度
- OnlineToolSession 采集：从假 chunk 流到 context._decode_samples 的接线
- agent_module._build_usage_data：下发给前端的 speed 字段

回归背景：采集点必须能在 time.monotonic 被函数级 ``import time`` 遮蔽时变红
（该 bug 会让整个采样静默失效，且不影响任何现有测试）。
"""

from __future__ import annotations

import logging
import math
from types import SimpleNamespace

import pytest

from tea_agent.session.decode_speed import (
    MAX_SAMPLES,
    format_speed,
    make_sample,
    summarize,
)

# ============================================================
# make_sample — 单次调用的样本构建
# ============================================================


class TestMakeSample:
    def test_streaming_sample_fields(self):
        """t_request=100 t_first=103 t_end=115 → 解码 12s、TTFT 3s、总 15s。"""
        s = make_sample(100.0, 103.0, 115.0, 312)
        assert s is not None
        assert s["completion_tokens"] == 312
        assert s["decode_seconds"] == pytest.approx(12.0)
        assert s["ttft_seconds"] == pytest.approx(3.0)
        assert s["total_seconds"] == pytest.approx(15.0)
        assert s["estimated"] is False

    def test_decode_window_excludes_ttft(self):
        """排队/prefill 久（TTFT 大）不应拉低解码窗口 —— 两者必须分离。"""
        short_wait = make_sample(0.0, 1.0, 11.0, 100)      # TTFT 1s, 解码 10s
        long_wait = make_sample(0.0, 9.0, 19.0, 100)       # TTFT 9s, 解码 10s
        assert short_wait["decode_seconds"] == pytest.approx(long_wait["decode_seconds"])
        assert short_wait["ttft_seconds"] < long_wait["ttft_seconds"]

    def test_non_streaming_has_no_decode_window(self):
        """非流式无法区分排队与解码 → decode_seconds=None，不参与 tok/s。"""
        s = make_sample(100.0, None, 110.0, 50, streaming=False)
        assert s is not None
        assert s["decode_seconds"] is None
        assert s["total_seconds"] == pytest.approx(10.0)
        assert s["ttft_seconds"] is None

    def test_missing_completion_tokens_returns_none(self):
        """端点既无 usage 也无估算文本 → 宁可不显示，不编数字。"""
        assert make_sample(100.0, 103.0, 115.0, None) is None
        assert make_sample(100.0, 103.0, 115.0, 0) is None
        assert make_sample(100.0, 103.0, 115.0, "abc") is None

    def test_estimated_fallback_marks_provenance(self):
        """usage 缺失但有文本估算值 → 样本带 estimated=True（口径不混淆）。"""
        s = make_sample(100.0, 103.0, 115.0, None, est_tokens=80)
        assert s is not None
        assert s["estimated"] is True
        assert s["completion_tokens"] == 80

    def test_real_usage_wins_over_estimate(self):
        """同时有实测与估算时，必须用实测且不标记 estimated。"""
        s = make_sample(100.0, 103.0, 115.0, 42, est_tokens=999)
        assert s["completion_tokens"] == 42
        assert s["estimated"] is False

    @pytest.mark.parametrize(
        "t_request,t_first,t_end,streaming,why",
        [
            (100.0, 115.0, 115.05, True, "解码窗口过短 → 噪声"),
            (100.0, None, 115.0, True, "流式但从未收到首 token"),
            (100.0, 116.0, 115.0, True, "时间戳倒挂（end < first）"),
            (None, None, 115.0, False, "非流式且缺 t_request"),
            (100.0, None, None, False, "非流式且缺 t_end 且无时钟"),
            (None, None, None, True, "全缺"),
        ],
    )
    def test_invalid_timing_returns_none(self, t_request, t_first, t_end, streaming, why):
        """时序不可用一律返回 None —— 宁可不显示也不给错数（{why}）。"""
        assert make_sample(t_request, t_first, t_end, 100, streaming=streaming) is None

    def test_missing_t_request_keeps_decode_window(self):
        """缺 t_request 只影响 TTFT/total，解码窗口依然有效（不该整条丢弃）。"""
        s = make_sample(None, 103.0, 115.0, 100)
        assert s is not None
        assert s["decode_seconds"] == pytest.approx(12.0)
        assert s["ttft_seconds"] is None
        assert s["total_seconds"] is None

    def test_mixed_clock_sources_are_rejected(self):
        """t_request 与 t_end 来自不同时间源时，会算出数百小时的荒谬时长。

        这种样本一旦显示就是「848 小时 / 0.0 tok/s」级别的误导，必须整条丢弃，
        而不是让人以为模型慢到离谱。
        """
        real_now = 305784.0 + 100.0  # 与 t_request=100.0 明显不同源
        assert make_sample(100.0, None, real_now, 100, streaming=False) is None
        # 解码窗口同样过闸
        assert make_sample(100.0, 101.0, real_now, 100) is None

    def test_plausible_long_stream_is_kept(self):
        """护栏只拦「不可能」，不拦「确实很慢」：1 小时的长流仍应保留。"""
        s = make_sample(0.0, 1.0, 3600.0, 1000)
        assert s is not None
        assert s["decode_seconds"] == pytest.approx(3599.0)

    def test_clock_injection_used_when_no_end(self):
        """t_end 缺省时取注入时钟 —— 保证时间相关逻辑可确定性测试。"""
        s = make_sample(100.0, 103.0, None, 50, clock=lambda: 113.0)
        assert s["decode_seconds"] == pytest.approx(10.0)


# ============================================================
# summarize — 聚合口径
# ============================================================


class TestSummarize:
    def test_uses_total_over_total_not_mean_of_rates(self):
        """核心契约：tok/s = Σtokens / Σ秒，而不是对各轮速率取算术平均。

        两例速率分别都是 10 与 50 的调和场景：平均值会把短轮次的极端值
        当成整体表现，Σ/Σ 才代表「这次会话真实解码了多少」。
        """
        samples = [
            make_sample(0.0, 1.0, 11.0, 100),    # 100 tok / 10 s = 10 tok/s
            make_sample(20.0, 21.0, 23.0, 100),  # 100 tok / 2 s  = 50 tok/s
        ]
        out = summarize(samples)
        assert out["tok_per_sec"] == pytest.approx(200 / 12, abs=0.05)  # ≈16.7
        assert out["tok_per_sec"] != pytest.approx(30.0)  # 绝非速率平均
        assert out["streams"] == 2
        assert out["completion_tokens"] == 200

    def test_skips_non_streaming_samples(self):
        """无解码窗口的样本（非流式）不参与速率，只统计有窗口的。"""
        samples = [
            make_sample(0.0, None, 20.0, 100, streaming=False),
            make_sample(30.0, 31.0, 41.0, 200),
        ]
        out = summarize(samples)
        assert out["streams"] == 1
        assert out["completion_tokens"] == 200
        assert out["tok_per_sec"] == pytest.approx(20.0)

    def test_real_samples_take_precedence_over_estimated(self):
        """实测与估算不得混算：存在实测时忽略估算样本。"""
        real = make_sample(0.0, 1.0, 11.0, 100)
        est = make_sample(20.0, 21.0, 23.0, None, est_tokens=10_000)
        out = summarize([real, est])
        assert out["completion_tokens"] == 100
        assert out["estimated"] is False
        assert out["tok_per_sec"] == pytest.approx(10.0)

    def test_all_estimated_is_flagged(self):
        """全是估算 → 结果标记 estimated=True，前端据此加 ~ 前缀。"""
        out = summarize([make_sample(0.0, 1.0, 11.0, None, est_tokens=100)])
        assert out["estimated"] is True
        assert out["tok_per_sec"] == pytest.approx(10.0)

    @pytest.mark.parametrize(
        "junk",
        [None, [], {}, "not-a-list", [None, 1, "x"], [{"completion_tokens": 0}],
         [{"completion_tokens": "x", "decode_seconds": 1}], [[]]],
    )
    def test_garbage_input_returns_none(self, junk):
        """任何畸形输入都降级为 None，不抛异常（旁路观测不得冒泡）。"""
        assert summarize(junk) is None

    def test_non_finite_numbers_are_rejected(self):
        """NaN/inf/负数样本被丢弃（否则聚合出 nan 会一路渲染成 tok/s NaN）。"""
        bad = [
            {"completion_tokens": 10, "decode_seconds": float("nan")},
            {"completion_tokens": 10, "decode_seconds": float("inf")},
            {"completion_tokens": 10, "decode_seconds": -5.0},
            {"completion_tokens": 10, "decode_seconds": True},
        ]
        assert summarize(bad) is None
        mixed = bad + [make_sample(0.0, 1.0, 11.0, 100)]
        out = summarize(mixed)
        assert out is not None and math.isfinite(out["tok_per_sec"])

    def test_ttft_averaged_and_optional(self):
        out = summarize([make_sample(0.0, 2.0, 12.0, 100), make_sample(0.0, 4.0, 14.0, 100)])
        assert out["ttft_seconds"] == pytest.approx(3.0)
        # 无 TTFT（缺 t_request）时字段为 None 而非 0
        no_ttft = summarize([{"completion_tokens": 10, "decode_seconds": 1.0,
                              "ttft_seconds": None}])
        assert no_ttft["ttft_seconds"] is None


# ============================================================
# format_speed — 展示文案
# ============================================================


class TestFormatSpeed:
    def test_renders_one_decimal(self):
        assert format_speed({"tok_per_sec": 42.34}) == "⚡ 42.3 tok/s"

    def test_live_marker(self):
        assert format_speed({"tok_per_sec": 42.3}, live=True).startswith("⏱")

    def test_estimated_marker(self):
        assert format_speed({"tok_per_sec": 42.3, "estimated": True}) == "⚡ ~42.3 tok/s"

    @pytest.mark.parametrize("summary", [None, {}, {"tok_per_sec": 0}, {"tok_per_sec": None}])
    def test_no_data_returns_empty_string(self, summary):
        """无数据返回空串 —— 前端据此隐藏，而不是显示 '0.0 tok/s' 误导。"""
        assert format_speed(summary) == ""

    def test_thousands_separator(self):
        assert format_speed({"tok_per_sec": 12345.6}) == "⚡ 12,345.6 tok/s"


# ============================================================
# OnlineToolSession 采集接线（假 chunk 流）
# ============================================================


def _delta(content=None, reasoning=None, tool_calls=None):
    return SimpleNamespace(content=content, reasoning_content=reasoning,
                           tool_calls=tool_calls)


def _chunk(content=None, reasoning=None, usage=None, tool_calls=None, no_choices=False):
    if no_choices:
        return SimpleNamespace(usage=usage, choices=[])
    return SimpleNamespace(
        usage=usage,
        choices=[SimpleNamespace(delta=_delta(content, reasoning, tool_calls))],
    )


def _make_bare_session():
    """绕过 __init__ 构造 OnlineToolSession，只装配被测通路所需属性。"""
    from tea_agent.onlinesession import OnlineToolSession
    from tea_agent.session.context import SessionContext

    sess = OnlineToolSession.__new__(OnlineToolSession)
    sess.context = SessionContext()
    sess.context.no_stream_chunk = False
    sess.context.model = "test-model"
    sess._accumulated = []
    sess.api = SimpleNamespace(
        _accumulate_usage=lambda u: sess._accumulated.append(u),
        accumulate_tool_calls_from_delta=lambda d, out: None,
        reset_usage=lambda: setattr(sess.context, "_last_usage", {"total_tokens": 0}),
        reset_cheap_usage=lambda: setattr(sess.context, "_last_cheap_usage", {}),
    )
    sess._log_assistant_chunk = lambda _t: None
    # reset_session_state 直接操作这些字段；__new__ 绕过了 __init__，需手工补齐
    import threading as _th
    sess._max_iter_wait = _th.Event()
    sess._rounds_collector = []
    sess._extra_iterations = 0
    # __del__/close 通路的最小字段，避免 GC 时报属性缺失干扰其它用例输出
    sess._http_clients = {}
    sess.current_topic_id = None
    return sess


class TestSessionSampling:
    def test_stream_sample_with_advancing_clock(self, monkeypatch):
        """流式采集主路径：时钟递增时样本数值 = tokens / 解码窗口。"""
        # 该测试同时是「time 被函数级 import 遮蔽 → UnboundLocalError」的回归防线。
        import tea_agent.onlinesession as mod

        sess = _make_bare_session()
        sess.context._stream_t_request = 1000.0
        # 该路径只有两次取时：首个有产出 chunk → t_first；流读完 → t_end
        seq = iter([1002.0, 1013.0])
        monkeypatch.setattr(mod, "time",
                            SimpleNamespace(monotonic=lambda: next(seq, 1013.0),
                                            sleep=lambda _s: None))

        chunks = [
            _chunk(content="让我想想"),
            _chunk(content="你好"),
            _chunk(usage=SimpleNamespace(completion_tokens=220, prompt_tokens=10,
                                         total_tokens=230), no_choices=True),
        ]
        sess._process_stream_with_reasoning(iter(chunks), lambda _t: None)

        samples = sess.context._decode_samples
        assert len(samples) == 1
        s = samples[0]
        assert s["completion_tokens"] == 220
        assert s["decode_seconds"] == pytest.approx(11.0)   # 1013 - 1002
        assert s["ttft_seconds"] == pytest.approx(2.0)      # 1002 - 1000
        assert summarize(samples)["tok_per_sec"] == pytest.approx(20.0)

    def test_usage_less_endpoint_falls_back_to_estimate(self, monkeypatch):
        """端点不回 usage（不带 include_usage 的代理）→ 用文本估算并标记口径。"""
        import tea_agent.onlinesession as mod

        sess = _make_bare_session()
        sess.context._stream_t_request = 0.0
        seq = iter([1.0, 11.0])
        monkeypatch.setattr(mod, "time",
                            SimpleNamespace(monotonic=lambda: next(seq, 11.0),
                                            sleep=lambda _s: None))

        chunks = [_chunk(content="x" * 400)]  # 无 usage chunk
        sess._process_stream_with_reasoning(iter(chunks), lambda _t: None)

        samples = sess.context._decode_samples
        assert len(samples) == 1
        assert samples[0]["estimated"] is True
        assert samples[0]["completion_tokens"] > 0

    def test_record_failure_does_not_raise(self, monkeypatch):
        """采集是旁路：内部异常必须被吞（绝不把对话主流程带崩）。"""
        import tea_agent.onlinesession as mod
        import tea_agent.session.decode_speed as ds

        sess = _make_bare_session()

        def _boom(*_a, **_kw):
            raise RuntimeError("collector exploded")

        monkeypatch.setattr(ds, "make_sample", _boom)
        with caplog_handler() as records:
            assert sess._record_decode_sample(
                SimpleNamespace(completion_tokens=10), t_first=1.0, t_end=2.0) is None
        assert records, "应以 debug 级留痕"
        assert all(r.levelno < logging.ERROR for r in records)
        assert sess.context._decode_samples == []
        assert mod.OnlineToolSession is not None  # 会话类仍可用（未被打断）

    def test_samples_capped(self, monkeypatch):
        """样本数有上限，长工具循环不会无限增长内存。"""
        import tea_agent.session.decode_speed as ds

        sess = _make_bare_session()
        sess.context._stream_t_request = 0.0
        monkeypatch.setattr(ds, "MAX_SAMPLES", 3)
        for i in range(10):
            sess._record_decode_sample(SimpleNamespace(completion_tokens=10),
                                       t_first=float(i), t_end=float(i) + 5)
        assert len(sess.context._decode_samples) <= 3

    def test_reset_session_state_clears_samples(self):
        """回合开始必须清零 —— 否则上一回合的速率会串进本回合显示。"""
        sess = _make_bare_session()
        sess.context._decode_samples = [{"completion_tokens": 1, "decode_seconds": 1}]
        sess.context._stream_t_request = 123.0
        sess.reset_session_state()
        assert sess.context._decode_samples == []
        assert sess.context._stream_t_request is None


class caplog_handler:
    """捕获 session 记录器的日志（含 DEBUG），且恢复原级别。"""

    def __init__(self):
        self.records: list[logging.LogRecord] = []
        self._lg = logging.getLogger("session")
        self._h = logging.Handler()

    def __enter__(self):
        self._h.emit = self.records.append
        self._old_level = self._lg.level
        self._lg.setLevel(logging.DEBUG)
        self._lg.addHandler(self._h)
        return self.records

    def __exit__(self, *_exc):
        self._lg.removeHandler(self._h)
        self._lg.setLevel(self._old_level)
        return False
# ============================================================
# 观测不得影响主流程序列（重构回归）
# ============================================================


class TestSamplingCannotBreakStreaming:
    """采样代码位于「断流重试」的 try 内 —— 在那里抛错等于伪造一次网络断流。

    真实踩过的坑（本次开发过程）：把 ``self._record_decode_sample(...)`` 直接
    写进消费循环，鸭子类型的 session 替身（test_stream_retry 的 _FakeSession）
    没有该方法 → 属性查找抛 AttributeError → 被外层 except 判为断流 → 指数退避
    重试 → 3 个无关用例真的走了重试路径、1 个耗尽重试把回复变成错误文案。
    6 个用例同时变红才暴露。

    现在的契约：采样只经 ``_sample`` 闭包触发 —— 函数局部名查找不可能失败，
    异常一律在其 try 内被 debug 级吞掉。
    """

    @staticmethod
    def _chunks():
        return [
            _chunk(content="你好世界"),
            _chunk(usage=SimpleNamespace(completion_tokens=50, prompt_tokens=5,
                                         total_tokens=55), no_choices=True),
        ]

    def test_duck_typed_session_without_collector(self):
        """采集能力完全缺失时，流必须正常返回内容且不触发任何重试。"""
        sess = _make_bare_session()

        def _missing(*_a, **_kw):
            raise AttributeError("_record_decode_sample 不存在")

        # 用实例属性遮蔽类方法，模拟替身/部分构造对象缺少该能力
        sess.__dict__["_record_decode_sample"] = _missing

        retried = []
        content, _tools, _rc = sess._process_stream_with_reasoning(
            iter(self._chunks()), lambda _t: None,
            retry_factory=lambda: retried.append(1) or iter(self._chunks()),
        )
        assert content == "你好世界"
        assert retried == [], "观测能力缺失绝不能被误判为断流而重试"

    def test_collector_raising_is_swallowed(self, monkeypatch):
        """采集内部抛任何异常都必须被吞掉，主流程照常返回完整内容。"""
        import tea_agent.onlinesession as mod

        sess = _make_bare_session()

        def _boom(*_a, **_kw):
            raise RuntimeError("collector exploded")

        monkeypatch.setattr(mod.OnlineToolSession, "_record_decode_sample", _boom)

        retried = []
        content, _t, _r = sess._process_stream_with_reasoning(
            iter(self._chunks()), lambda _t: None,
            retry_factory=lambda: retried.append(1) or iter(self._chunks()))
        assert content == "你好世界"
        assert retried == []

    def test_broken_clock_is_not_mistaken_for_interruption(self, monkeypatch, caplog):
        """时钟失效属观测通路，必须静默降级，不得走重试。

        这条同时锁死一个陷阱实现：若把取时写在 ``_sample(...)`` 的**参数位置**，
        异常发生在闭包的 try 之外 → 会被判为断流。t_end 的求值必须留在闭包内部。
        """
        import logging

        import tea_agent.onlinesession as mod

        sess = _make_bare_session()

        def _bad_monotonic():
            raise RuntimeError("clock unavailable")

        monkeypatch.setattr(mod, "time",
                            SimpleNamespace(monotonic=_bad_monotonic,
                                            sleep=lambda _s: None))
        retried = []
        with caplog.at_level(logging.DEBUG, logger="session"):
            content, _t, _r = sess._process_stream_with_reasoning(
                iter(self._chunks()), lambda _t: None,
                retry_factory=lambda: retried.append(1) or iter(self._chunks()))
        assert content == "你好世界"
        assert retried == [], "时钟失效不是网络断流"
        assert sess.context._decode_samples == []

    def test_normal_path_still_collects(self, monkeypatch):
        """反向保险：上述防御不能把正常采集一并吞掉（否则功能静默失效）。"""
        import tea_agent.onlinesession as mod

        sess = _make_bare_session()
        sess.context._stream_t_request = 0.0
        seq = iter([1.0, 11.0])
        monkeypatch.setattr(mod, "time",
                            SimpleNamespace(monotonic=lambda: next(seq, 11.0),
                                            sleep=lambda _s: None))
        sess._process_stream_with_reasoning(iter(self._chunks()), lambda _t: None)
        assert len(sess.context._decode_samples) == 1
        assert summarize(sess.context._decode_samples)["tok_per_sec"] == pytest.approx(5.0)


# ============================================================
# server 下发通路
# ============================================================


class TestUsageDataSurfacing:
    @staticmethod
    def _fake_session(samples):
        ctx = SimpleNamespace(model="m", cheap_model="", _decode_samples=samples,
                              _last_request_prompt_tokens=0, messages=[])
        return SimpleNamespace(_last_usage={"total_tokens": 70, "prompt_tokens": 10,
                                            "completion_tokens": 60},
                               _last_cheap_usage={}, context=ctx)

    def test_speed_field_present_when_measured(self):
        from tea_agent.server.modules.agent_module import _build_usage_data

        samples = [make_sample(0.0, 2.0, 12.0, 100)]
        data = _build_usage_data(self._fake_session(samples))
        assert data["speed"]["tok_per_sec"] == pytest.approx(10.0)
        assert data["speed"]["streams"] == 1
        assert data["speed"]["ttft_seconds"] == pytest.approx(2.0)

    def test_speed_absent_without_samples(self):
        """没有可测样本时不塞 speed 字段（前端据缺失隐藏，不显示 0）。"""
        from tea_agent.server.modules.agent_module import _build_usage_data

        for samples in ([], None):
            data = _build_usage_data(self._fake_session(samples))
            assert "speed" not in data
            assert data["total_tokens"] == 70  # 主体 usage 不受影响

    def test_broken_samples_do_not_break_usage(self):
        """样本内容畸形 → usage 仍正常返回（旁路失败降级）。"""
        from tea_agent.server.modules.agent_module import _build_usage_data

        junk = [{"completion_tokens": None, "decode_seconds": "x"}, 42, None]
        data = _build_usage_data(self._fake_session(junk))
        assert "speed" not in data
        assert data["completion_tokens"] == 60

    def test_missing_context_attribute_is_tolerated(self):
        """老式/替身 session 没有 _decode_samples 属性时不得抛 AttributeError。"""
        from tea_agent.server.modules.agent_module import _build_usage_data

        ctx = SimpleNamespace(model="m", cheap_model="", messages=[])
        sess = SimpleNamespace(_last_usage={"total_tokens": 1, "prompt_tokens": 1,
                                            "completion_tokens": 1},
                               _last_cheap_usage={}, context=ctx)
        assert "speed" not in _build_usage_data(sess)


# ============================================================
# 请求打点
# ============================================================


class TestRequestTimestampStamped:
    def test_create_chat_stream_stamps_t_request(self, monkeypatch):
        """主模型请求发出时必须打 t_request（TTFT 的基准点）。"""
        from tea_agent.session.components.api import APIComponent
        from tea_agent.session.context import SessionContext

        ctx = SessionContext()
        ctx.no_stream_chunk = False
        ctx.supports_reasoning = False
        ctx._thinking_supported = False
        ctx.enable_thinking = False
        ctx.client = None
        ctx.model = "m"
        ctx.reasoning_effort = "auto"
        ctx.thinking_strength = 0.0
        ctx.tools = []
        ctx._stream_t_request = None

        comp = APIComponent(ctx)
        monkeypatch.setattr(comp, "_match_model_family", lambda _m: {}, raising=False)

        sent = {}

        class _Cli:
            class chat:  # noqa: N801
                class completions:  # noqa: N801
                    @staticmethod
                    def create(**kw):
                        sent.update(kw)
                        return "STREAM"

        ctx.client = _Cli
        result = comp.create_chat_stream([{"role": "user", "content": "hi"}], tools=[])
        assert result == "STREAM"
        assert isinstance(ctx._stream_t_request, float)

    def test_cheap_model_request_does_not_pollute_main_window(self, monkeypatch):
        """便宜模型（摘要等）不刷新 t_request —— 否则会污染主对话 TTFT。"""
        from tea_agent.session.components.api import APIComponent
        from tea_agent.session.context import SessionContext

        ctx = SessionContext()
        ctx.no_stream_chunk = False
        ctx.supports_reasoning = False
        ctx._cheap_thinking_supported = False
        ctx.enable_thinking = False
        ctx.client = None
        ctx.model = "m"
        ctx.reasoning_effort = "auto"
        ctx.thinking_strength = 0.0
        ctx._stream_t_request = 555.0

        comp = APIComponent(ctx)
        monkeypatch.setattr(comp, "_match_model_family", lambda _m: {}, raising=False)

        class _Cli:
            class chat:  # noqa: N801
                class completions:  # noqa: N801
                    @staticmethod
                    def create(**_kw):
                        return "STREAM"

        ctx.client = _Cli
        comp.create_chat_stream([{"role": "user", "content": "hi"}], tools=[],
                                is_cheap=True)
        assert ctx._stream_t_request == 555.0


# ============================================================
# 完整账本字段（防"把仅解码读成整体速度"）
# ============================================================


class TestLedgerFields:
    def test_wait_and_request_are_derived_from_total(self):
        """等待 = 请求总时长 − 解码窗口；这是 ⚡ 没算进去的那一半。"""
        s = make_sample(1000.0, 1022.0, 1032.8, 886)      # 等 22s / 解码 10.8s
        out = summarize([s])
        assert out["wait_seconds"] == pytest.approx(22.0, abs=0.01)
        assert out["request_seconds"] == pytest.approx(32.8, abs=0.01)
        assert out["ttft_seconds"] == pytest.approx(22.0, abs=0.01)

    def test_wait_sums_across_streams(self):
        """多轮工具的等待要累加（回合体感），不是取平均。"""
        ss = [make_sample(0.0 + i * 40, 22.0 + i * 40, 32.8 + i * 40, 886)
              for i in range(18)]
        out = summarize(ss)
        assert out["streams"] == 18
        assert out["wait_seconds"] == pytest.approx(22.0 * 18, rel=1e-3)
        assert out["ttft_seconds"] == pytest.approx(22.0, abs=0.01)  # 均值

    def test_ttft_max_exposes_the_worst_call(self):
        """均值会掩盖「某一次 prefill 卡了 40s」；峰值必须单独给出。"""
        ss = [make_sample(0.0, 1.0, 11.0, 800), make_sample(100.0, 140.0, 150.0, 800)]
        out = summarize(ss)
        assert out["ttft_seconds"] == pytest.approx(20.5, abs=0.01)  # (1+40)/2
        assert out["ttft_max_seconds"] == pytest.approx(40.0, abs=0.01)

    def test_missing_total_seconds_yields_no_fake_ledger(self):
        """没有总时长就不要编造等待 —— 宁可字段缺失。"""
        out = summarize([{"completion_tokens": 100, "decode_seconds": 2.0,
                          "total_seconds": None, "ttft_seconds": None,
                          "estimated": False}])
        assert out["wait_seconds"] is None
        assert out["request_seconds"] is None

    def test_displayed_numbers_are_self_consistent(self):
        """显示值必须能被读者反算回去。

        固定 2 位小数曾让 `43 tok / 0.31s` 配 `137.8 tok/s`（反算 138.7），
        数字自相矛盾 → 直接被怀疑"是不是测错了"。
        """
        out = summarize([make_sample(1000.0, 1001.06, 1001.372046, 43)])
        assert out["completion_tokens"] / out["decode_seconds"] == pytest.approx(
            out["tok_per_sec"], rel=5e-3)

    def test_ratio_of_long_context_turn_matches_reality(self):
        """复刻截图那轮：⚡≈82 而体感应慢约 3 倍。"""
        ss = [make_sample(0.0 + i * 33, 22.0 + i * 33, 32.8 + i * 33, 886)
              for i in range(18)]
        out = summarize(ss)
        assert 80 < out["tok_per_sec"] < 85
        assert out["request_seconds"] / out["decode_seconds"] == pytest.approx(3.0, abs=0.1)
