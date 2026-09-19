"""解码速率（tok/s）库函数测试（session/decode_speed.py）。

覆盖：
- 纯函数：度量定义（Σ/Σ 聚合、TTFT 分离）、样本有效性、口径纯度
- 采集器 ``OnlineToolSession._record_decode_sample`` 的旁路隔离（异常必须被吞）

历史：本文件曾覆盖「假 chunk 流 → context._decode_samples → agent_module 下发
speed 字段」的整条接线。2026-09-20 的 master 合并（b3e5ebf）在两条并行的解码
速率实现中选定 ``session/decode_rate.py``（usage-bar 的 decode_tps_text），
decode_speed 的流式接线与前端徽章随之退役 —— 相关接线用例已删除，库函数与
采集器保留备用（重新接线时必须沿用「不可能抛错的局部闭包」写法，见
onlinesession.py ``_record_decode_sample`` 文档）。
"""

from __future__ import annotations

import logging
import math
from types import SimpleNamespace

import pytest

from tea_agent.session.decode_speed import (
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
# 采集器旁路隔离（_record_decode_sample）
# ============================================================


def _make_bare_session():
    """绕过 __init__ 构造 OnlineToolSession —— 采集器只触碰 context。"""
    from tea_agent.onlinesession import OnlineToolSession
    from tea_agent.session.context import SessionContext

    sess = OnlineToolSession.__new__(OnlineToolSession)
    sess.context = SessionContext()
    sess.context.model = "test-model"
    return sess


class TestRecorderIsolation:
    """采集器是纯旁路：内部异常一律 debug 级吞掉，绝不外泄给调用方。"""

    def test_record_failure_does_not_raise(self, monkeypatch):
        """采集是旁路：内部异常必须被吞（绝不把对话主流程带崩）。"""
        import tea_agent.onlinesession as mod
        import tea_agent.session.decode_speed as ds

        sess = _make_bare_session()

        def _boom(*_a, **_kw):
            raise RuntimeError("collector exploded")

        monkeypatch.setattr(ds, "make_sample", _boom)
        with _CaplogCapture() as records:
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


class _CaplogCapture:
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
