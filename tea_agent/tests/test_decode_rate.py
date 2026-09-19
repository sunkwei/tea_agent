"""解码速度（tok/s）显示 — 回归测试。

覆盖三层契约：

1. 纯函数口径（session/decode_rate.py）
   - 速度 = 输出 token / (首增量 → 流结束)，**排除**首 token 等待；
   - 窗口过短 / token 为 0 / 时钟回拨 → 返回 None（不下发可疑数字）；
   - 文案格式随量级切换，无数据返回空串。
2. 会话接线（onlinesession._process_stream_with_reasoning）
   - 真实流式消费后 context 上出现实测 tok/s；
   - 供应商不回传 usage 时退化为字符估算并标记 estimated；
   - 断流重试后统计的是最终那一版输出（不是两次尝试之和 / 一次尝试的耗时）。
3. 服务端下发（agent_module._build_usage_data）
   - 有数据 → decode_tps_text 字段；无数据 → **不带字段**（前端据此隐藏，
     而不是把 0 读成「速度为零」）。

另覆盖「前端 usage-bar 必须包含 tok/s 段」的契约（静态断言 app.js / style.css /
index.html 三者一致，防止只改后端不改 UI 的静默失效）。
"""

import pathlib
from types import SimpleNamespace

import pytest

from tea_agent.session.decode_rate import (
    MAX_PLAUSIBLE_TPS,
    MIN_DECODE_SECONDS,
    completion_tokens_total,
    compute_decode_stats,
    compute_decode_tps,
    compute_ttft_ms,
    decode_usage_fields,
    format_decode_tps,
    format_ttft,
    record_decode_stats,
    reset_decode_stats,
)

# ──────────────────────────────────────────────
#  1. 纯函数口径
# ──────────────────────────────────────────────


class TestComputeDecodeTps:
    def test_basic_rate(self):
        """100 token / 2s = 50 tok/s。"""
        assert compute_decode_tps(100, 10.0, 12.0) == pytest.approx(50.0)

    def test_excludes_first_token_wait(self):
        """首 token 等待不计入：窗口从 first_ts 起算，而非请求发出时刻。"""
        # prefill 用了 9 秒（0 → 9），随后 1 秒产出 100 token → 100 tok/s，
        # 若把 prefill 计入会得到 10 tok/s（差 10 倍，这正是要防的失真）。
        assert compute_decode_tps(100, 9.0, 10.0) == pytest.approx(100.0)

    def test_zero_tokens_returns_none(self):
        assert compute_decode_tps(0, 1.0, 2.0) is None
        assert compute_decode_tps(None, 1.0, 2.0) is None

    def test_missing_timestamps_return_none(self):
        assert compute_decode_tps(100, None, 2.0) is None
        assert compute_decode_tps(100, 1.0, None) is None

    def test_zero_or_short_window_returns_none(self):
        """窗口过短 → 除法噪声极大，宁可不显示（契约：不显示优于显示假数）。"""
        assert compute_decode_tps(100, 1.0, 1.0) is None
        assert compute_decode_tps(100, 1.0, 1.0 + MIN_DECODE_SECONDS / 2) is None

    def test_clock_skew_returns_none(self):
        """结束早于开始（时钟异常）→ None，而非负速度。"""
        assert compute_decode_tps(100, 5.0, 4.0) is None

    def test_implausibly_high_returns_none(self):
        assert compute_decode_tps(10**9, 1.0, 2.0) is None
        assert compute_decode_tps(MAX_PLAUSIBLE_TPS + 1, 1.0, 2.0) is None

    def test_accepts_string_tokens(self):
        """容错：token 数可能来自 JSON/表单，字符串数字应可用。"""
        assert compute_decode_tps("120", 1.0, 3.0) == pytest.approx(60.0)

    def test_non_numeric_tokens_returns_none(self):
        assert compute_decode_tps("abc", 1.0, 3.0) is None


class TestComputeTtft:
    def test_basic(self):
        assert compute_ttft_ms(10.0, 10.5) == pytest.approx(500.0)

    def test_negative_returns_none(self):
        assert compute_ttft_ms(10.0, 9.0) is None

    def test_missing_returns_none(self):
        assert compute_ttft_ms(None, 1.0) is None
        assert compute_ttft_ms(1.0, None) is None


class TestFormat:
    def test_empty_for_no_data(self):
        assert format_decode_tps(None) == ""
        assert format_decode_tps(0) == ""
        assert format_decode_tps(-5) == ""
        assert format_decode_tps("x") == ""

    @pytest.mark.parametrize(
        "tps,expect",
        [
            (150.0, "⚡ 150 tok/s"),
            (99.99, "⚡ 100 tok/s"),
            (42.34, "⚡ 42.3 tok/s"),
            (9.999, "⚡ 10.0 tok/s"),
            (4.567, "⚡ 4.57 tok/s"),
        ],
    )
    def test_precision_by_magnitude(self, tps, expect):
        assert format_decode_tps(tps) == expect

    def test_ttft_text(self):
        assert format_ttft(250.0) == "首 token 250ms"
        assert format_ttft(2500.0) == "首 token 2.50s"
        assert format_ttft(None) == ""


class TestComputeDecodeStats:
    def test_bundle(self):
        st = compute_decode_stats(200, 1.0, 3.0, 5.0)
        assert st["decode_tps"] == pytest.approx(100.0)
        assert st["decode_tokens"] == 200
        assert st["decode_seconds"] == pytest.approx(2.0)
        assert st["ttft_ms"] == pytest.approx(2000.0)
        assert st["estimated"] is False
        assert st["decode_tps_text"] == "⚡ 100 tok/s"

    def test_no_data_yields_empty_text_and_zero_tps(self):
        st = compute_decode_stats(0, 1.0, None, 2.0)
        assert st["decode_tps"] == 0.0
        assert st["decode_tps_text"] == ""


class TestCtxHelpers:
    def test_completion_tokens_total(self):
        ctx = SimpleNamespace(_last_usage={"completion_tokens": 42})
        assert completion_tokens_total(ctx) == 42

    def test_completion_tokens_total_defensive(self):
        assert completion_tokens_total(None) == 0
        assert completion_tokens_total(SimpleNamespace()) == 0
        assert completion_tokens_total(SimpleNamespace(_last_usage={})) == 0
        assert completion_tokens_total(SimpleNamespace(_last_usage={"completion_tokens": "oops"})) == 0
        assert completion_tokens_total(SimpleNamespace(_last_usage="not-a-dict")) == 0

    def test_record_then_read_fields(self):
        ctx = SimpleNamespace()
        record_decode_stats(ctx, 120, 1.0, 2.0, 4.0)
        fields = decode_usage_fields(ctx)
        assert fields["decode_tps"] == pytest.approx(60.0)
        assert fields["decode_tps_text"] == "⚡ 60.0 tok/s"
        assert fields["decode_tokens"] == 120
        assert fields["ttft_text"] == "首 token 1.00s"

    def test_decode_usage_fields_absent_when_unmeasured(self):
        """未测量 → 不带字段（而非 decode_tps=0）。"""
        assert decode_usage_fields(SimpleNamespace()) == {}
        assert decode_usage_fields(None) == {}

    def test_record_never_raises_on_broken_ctx(self):
        class Boom:
            def __setattr__(self, k, v):
                raise RuntimeError("read-only")

        # 旁路统计写入失败必须静默降级，不得把主对话流程带崩
        st = record_decode_stats(Boom(), 10, 1.0, 2.0, 3.0)
        assert st["decode_tps"] == pytest.approx(10.0)

    def test_reset_clears(self):
        ctx = SimpleNamespace()
        record_decode_stats(ctx, 100, 1.0, 2.0, 4.0)
        assert decode_usage_fields(ctx)
        reset_decode_stats(ctx)
        assert decode_usage_fields(ctx) == {}


# ──────────────────────────────────────────────
#  2. 会话接线（真实 _process_stream_with_reasoning）
# ──────────────────────────────────────────────

try:
    from tea_agent.onlinesession import OnlineToolSession
except Exception:  # pragma: no cover - 依赖缺失时跳过
    OnlineToolSession = None


class _FakeDelta:
    def __init__(self, content="", reasoning=""):
        self.content = content
        self.reasoning_content = reasoning
        self.tool_calls = None


class _FakeChunk:
    def __init__(self, content="", reasoning="", usage=None):
        self.choices = [SimpleNamespace(delta=_FakeDelta(content, reasoning))]
        self.usage = usage


class _FakeStream:
    def __init__(self, chunks):
        self._chunks = list(chunks)

    def __iter__(self):
        return iter(self._chunks)


class _FakeSession:
    """最小会话桩：绑定真实流消费方法 + 真实解码速度接线。"""

    _process_stream_with_reasoning = OnlineToolSession._process_stream_with_reasoning if OnlineToolSession else None
    _log_assistant_chunk = OnlineToolSession._log_assistant_chunk if OnlineToolSession else None
    _log_turn_end_marker = OnlineToolSession._log_turn_end_marker if OnlineToolSession else None

    def __init__(self, completion_each_chunk=10):
        from tea_agent.session.context import SessionContext

        self.context = SessionContext()
        self._completion_each_chunk = completion_each_chunk
        self.api = SimpleNamespace(_accumulate_usage=self._accumulate)
        self.storage = None
        self.current_topic_id = ""

    def _accumulate(self, usage):
        self.context._last_usage["completion_tokens"] += usage.completion_tokens


pytestmark_session = pytest.mark.skipif(OnlineToolSession is None, reason="OnlineToolSession 不可用")


@pytestmark_session
class TestStreamDecodeWiring:
    def test_records_tps_from_usage(self):
        """真实流式消费 → context 上出现实测 tok/s（供应商 usage 口径）。"""
        chunks = []
        for _ in range(10):
            # 每个 chunk 带 usage：供应商逐块回传（DeepSeek 风格）
            chunks.append(
                _FakeChunk(
                    "你好世界",
                    usage=SimpleNamespace(
                        completion_tokens=5,
                        prompt_tokens=1,
                        total_tokens=6,
                    ),
                )
            )
        sess = _FakeSession()
        sess._process_stream_with_reasoning(_FakeStream(chunks), lambda t: None)
        assert sess.context._decode_tokens == 50
        # 窗口极短（本地跑 10 个 chunk 毫秒级）→ 契约是「宁可不显示」
        assert sess.context._decode_tps == 0.0
        assert sess.context._decode_tps_text == ""

    def test_tps_recorded_when_window_long_enough(self, monkeypatch):
        """窗口足够长时给出正的实测 tok/s（用注入的单调钟避免 sleep）。"""
        import tea_agent.onlinesession as os_mod

        clock = {"t": 0.0}

        def fake_monotonic():
            clock["t"] += 1.0  # 每次调用推进 1 秒 → 窗口确定可预期
            return clock["t"]

        monkeypatch.setattr(os_mod.time, "monotonic", fake_monotonic)
        chunks = [
            _FakeChunk(
                "a",
                usage=SimpleNamespace(
                    completion_tokens=10,
                    prompt_tokens=1,
                    total_tokens=11,
                ),
            )
            for _ in range(4)
        ]
        sess = _FakeSession()
        sess._process_stream_with_reasoning(_FakeStream(chunks), lambda t: None)
        assert sess.context._decode_tokens == 40
        assert sess.context._decode_tps > 0
        assert "tok/s" in sess.context._decode_tps_text

    def test_recorded_window_excludes_prefill(self, monkeypatch):
        """接线的关键语义：解码窗口从**首增量**起算，不含首 token 等待。

        用可注入单调钟精确校验：请求发出 → 首增量 → 流结束，若把请求发出
        时刻当作窗口起点，decode_seconds 会等于总耗时（本用例中是其两倍）。
        """
        import tea_agent.onlinesession as os_mod

        clock = {"t": 0.0}

        def fake_monotonic():
            clock["t"] += 1.0
            return clock["t"]

        monkeypatch.setattr(os_mod.time, "monotonic", fake_monotonic)
        chunks = [
            _FakeChunk(
                "z",
                usage=SimpleNamespace(
                    completion_tokens=6,
                    prompt_tokens=1,
                    total_tokens=7,
                ),
            )
            for _ in range(3)
        ]
        sess = _FakeSession()
        sess._process_stream_with_reasoning(_FakeStream(chunks), lambda t: None)
        # 总耗时（请求发出 → 流结束）= 2s；解码窗口（首增量 → 流结束）= 1s
        assert sess.context._decode_seconds == pytest.approx(1.0)
        assert sess.context._ttft_ms == pytest.approx(1000.0)
        assert sess.context._decode_tps == pytest.approx(18.0)  # 18 token / 1s

    def test_estimated_flag_when_no_usage(self):
        """供应商不回传 usage → 退化为字符估算并显式标记 estimated。"""
        chunks = [_FakeChunk("这是一段没有 usage 的中文输出，用于触发估算路径。") for _ in range(3)]
        sess = _FakeSession()
        sess._process_stream_with_reasoning(_FakeStream(chunks), lambda t: None)
        assert sess.context._decode_estimated is True
        assert sess.context._decode_tokens > 0

    def test_no_output_no_stats(self):
        """空流（无任何输出增量）→ 不产生速度数据。"""
        sess = _FakeSession()
        sess._process_stream_with_reasoning(_FakeStream([]), lambda t: None)
        assert sess.context._decode_tps == 0.0
        assert sess.context._decode_tps_text == ""

    def test_retry_counts_only_final_version(self, monkeypatch):
        """断流重试后：token 只统计最终那一版，不叠加被丢弃的尝试。"""
        import tea_agent.onlinesession as os_mod
        from tea_agent.tests.test_stream_retry import _RemoteProtocolError

        clock = {"t": 0.0}
        monkeypatch.setattr(os_mod.time, "monotonic", lambda: clock.__setitem__("t", clock["t"] + 1.0) or clock["t"])

        class _FailOnceStream:
            def __init__(self):
                self._n = 0

            def __iter__(self):
                return self

            def __next__(self):
                self._n += 1
                if self._n == 2:
                    raise _RemoteProtocolError("peer closed connection without sending complete message body (incomplete chunked read)")
                if self._n > 3:
                    raise StopIteration
                return _FakeChunk(
                    "x" * 20,
                    usage=SimpleNamespace(
                        completion_tokens=3,
                        prompt_tokens=0,
                        total_tokens=3,
                    ),
                )

        good = _FakeStream(
            [
                _FakeChunk(
                    "y" * 20,
                    usage=SimpleNamespace(
                        completion_tokens=7,
                        prompt_tokens=0,
                        total_tokens=7,
                    ),
                )
                for _ in range(2)
            ]
        )
        sess = _FakeSession()
        monkeypatch.setattr(os_mod.time, "sleep", lambda s: None)
        content, _, _ = sess._process_stream_with_reasoning(_FailOnceStream(), lambda t: None, retry_factory=lambda: good)
        assert content == "y" * 40
        # 最终那一版 = 2 chunk × 7 = 14；若把被丢弃的尝试也算进去会更大
        assert sess.context._decode_tokens == 14


# ──────────────────────────────────────────────
#  3. 服务端下发
# ──────────────────────────────────────────────


class TestServerUsagePayload:
    def _session(self, **ctx_kw):
        from tea_agent.session.context import SessionContext

        s = SimpleNamespace()
        s.context = SessionContext()
        s._last_usage = {"total_tokens": 30, "prompt_tokens": 10, "completion_tokens": 20}
        s._last_cheap_usage = {}
        for k, v in ctx_kw.items():
            setattr(s.context, k, v)
        return s

    def test_fields_present_when_measured(self):
        from tea_agent.server.modules.agent_module import _build_usage_data

        data = _build_usage_data(
            self._session(
                _decode_tps=42.0,
                _decode_tps_text="⚡ 42.0 tok/s",
                _decode_tokens=84,
                _decode_seconds=2.0,
                _decode_estimated=False,
            )
        )
        assert data["decode_tps_text"] == "⚡ 42.0 tok/s"
        assert data["decode_tps"] == pytest.approx(42.0)

    def test_fields_absent_when_unmeasured(self):
        """未测量 → 字段不存在（前端隐藏该段，而非显示 0 tok/s）。"""
        from tea_agent.server.modules.agent_module import _build_usage_data

        data = _build_usage_data(self._session())
        assert "decode_tps_text" not in data
        assert "decode_tps" not in data


# ──────────────────────────────────────────────
#  4. 前端接线契约（静态断言：防「只改后端不改 UI」的静默失效）
# ──────────────────────────────────────────────


_STATIC = pathlib.Path(__file__).resolve().parents[1] / "server" / "static"


class TestFrontendWiring:
    def test_app_js_renders_tps_segment(self):
        js = (_STATIC / "app.js").read_text(encoding="utf-8")
        assert "usage-tps" in js, "usage-bar 缺少 tok/s 段"
        assert "decode_tps_text" in js, "前端未消费服务端下发的 tok/s 文本"
        assert "_paintLiveTps" in js, "缺少流式期间的实时 tok/s 绘制"

    def test_app_js_no_replay_estimation(self):
        """缓冲区重放路径不得做实时估算（重放节奏 ≠ 解码速度）。"""
        js = (_STATIC / "app.js").read_text(encoding="utf-8")
        marker = "case 'usage':"
        idx = js.index(marker, js.index("function _renderBufferEvent"))
        seg = js[idx : idx + 600]
        assert "updateUsage(event.usage)" in seg
        assert "_liveTpsTick" not in seg

    def test_live_estimation_matches_backend_heuristic(self):
        """前端估算口径与后端 estimate_tokens 一致（中文 1.5 字/token，英文 4 字符/token）。"""
        js = (_STATIC / "app.js").read_text(encoding="utf-8")
        assert "cnChars / 1.5" in js
        assert "otherChars / 4.0" in js

    def test_style_defines_tps_colour(self):
        css = (_STATIC / "style.css").read_text(encoding="utf-8")
        assert ".usage-tps" in css
        assert "--cyan" in css

    def test_index_html_bumps_asset_version(self):
        html = (_STATIC / "index.html").read_text(encoding="utf-8")
        assert "app.js?v=" in html
        # 版本号必须晚于上一版（md_list_fix），否则浏览器会用缓存里的旧 app.js
        assert "md_list_fix" not in html
