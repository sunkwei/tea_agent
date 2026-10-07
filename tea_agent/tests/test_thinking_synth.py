"""thinking_synth 测试 —— Muse/Spark inline-thinking 合成判定。

覆盖两层：
1. 纯函数/纯对象层（``is_muse_model`` / ``synth_nonstream_thinking`` /
   ``MuseThinkingSynthesizer``）—— 脱离会话，确定性可复现；
2. 接线层 —— 把真实的 ``_process_stream_with_reasoning`` 绑到最小桩上，钉住
   「合成信号序列」（``[THINK]`` 增量 + 收尾 ``[THINK_DONE]``）与正文完整性。

后者是关键：本次重构把这段逻辑从 252 行的流式热循环里抽出来，若抽取时丢掉
``[THINK_DONE]`` 兜底，前端思考面板会永久悬挂 —— 而单测纯函数是发现不了的。
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from tea_agent.onlinesession import OnlineToolSession
from tea_agent.session.thinking_synth import (
    CONTENT_EARLY,
    CONTENT_GUARD,
    MIN_CONTENT_LEN,
    NONSTREAM_SYNTH_BUDGET,
    THINK_BUDGET,
    THINK_DONE_AT,
    MuseThinkingSynthesizer,
    is_muse_model,
    synth_nonstream_thinking,
)

# ════════════════════════════════════════════════════════════
# 1. is_muse_model
# ════════════════════════════════════════════════════════════


class TestIsMuseModel:
    @pytest.mark.parametrize(
        "model,expected",
        [
            ("muse-spark", True),
            ("MUSE-Spark-1.5", True),
            ("spark", True),
            ("openai/gpt-4o", False),
            ("qwen3.8-vllm", False),
            ("", False),
            (None, False),
        ],
    )
    def test_detection(self, model, expected):
        assert is_muse_model(model) is expected


# ════════════════════════════════════════════════════════════
# 2. synth_nonstream_thinking
# ════════════════════════════════════════════════════════════


class TestNonStreamSynth:
    def test_non_muse_never_synthesizes(self):
        assert synth_nonstream_thinking("gpt-4o", "思考" * 500) == ""

    def test_empty_content_returns_empty(self):
        assert synth_nonstream_thinking("muse-spark", "") == ""

    def test_short_plain_content_returns_empty(self):
        """短正文且无思考痕迹 → 不合成（避免把短回答误当思考）。"""
        assert synth_nonstream_thinking("muse-spark", "好的") == ""

    def test_short_content_with_marker_synthesizes(self):
        """短但有思考痕迹（如「分析」）→ 合成。"""
        out = synth_nonstream_thinking("muse-spark", "分析一下这个问题")
        assert out == "分析一下这个问题"

    def test_long_content_synthesizes(self):
        out = synth_nonstream_thinking("muse-spark", "x" * (NONSTREAM_SYNTH_BUDGET + 500))
        assert len(out) == NONSTREAM_SYNTH_BUDGET

    def test_long_content_without_marker_synthesizes(self):
        """超长正文即便无标记词也合成（长度本身即判据）。"""
        assert synth_nonstream_thinking("muse-spark", "y" * 300) == "y" * 300


# ════════════════════════════════════════════════════════════
# 3. MuseThinkingSynthesizer（流式判定）
# ════════════════════════════════════════════════════════════


class TestSynthesizerGating:
    def test_disabled_when_thinking_off(self):
        s = MuseThinkingSynthesizer("muse-spark", enable_thinking=False)
        assert s.feed("思考" * 50, 0, 0) == ("", False)

    def test_disabled_for_non_muse_model(self):
        s = MuseThinkingSynthesizer("gpt-4o", enable_thinking=True)
        assert s.feed("思考" * 50, 0, 0) == ("", False)

    def test_empty_delta_is_noop(self):
        s = MuseThinkingSynthesizer("muse-spark", enable_thinking=True)
        assert s.feed("", 0, 0) == ("", False)
        assert s.active is False

    def test_never_synthesizes_after_real_reasoning(self):
        """已有原生 reasoning_content → 正文不是思考，绝不再合成。"""
        s = MuseThinkingSynthesizer("muse-spark", enable_thinking=True)
        s.note_native_reasoning()
        assert s.feed("正文正文正文正文正文正文", reasoning_len=42, content_len=0) == ("", False)
        assert s.active is False

    def test_short_early_chunk_needs_marker(self):
        """开头短包（≤ MIN_CONTENT_LEN）且无标记 → 不足以起合成。"""
        s = MuseThinkingSynthesizer("muse-spark", enable_thinking=True)
        short = "x" * MIN_CONTENT_LEN
        assert s.feed(short, 0, 0) == ("", False)

    def test_early_chunk_above_min_starts_synthesis(self):
        s = MuseThinkingSynthesizer("muse-spark", enable_thinking=True)
        take, done = s.feed("这是一个足够长的开头片段" * 3, 0, 0)
        assert take
        assert s.active is True
        assert done is False

    def test_explicit_marker_starts_synthesis_midway(self):
        """正文已很长（超出 CONTENT_EARLY），但首包带「### 思考」标记 → 仍起合成。"""
        s = MuseThinkingSynthesizer("muse-spark", enable_thinking=True)
        take, _ = s.feed("### 思考\n先分析一下", 0, CONTENT_EARLY + 100)
        assert take.startswith("### 思考")

    def test_guard_stops_new_synthesis_when_content_long(self):
        s = MuseThinkingSynthesizer("muse-spark", enable_thinking=True)
        assert s.feed("正文", 0, CONTENT_GUARD) == ("", False)

    def test_budget_exhausted_stops_synthesis(self):
        s = MuseThinkingSynthesizer("muse-spark", enable_thinking=True)
        assert s.feed("正文", THINK_BUDGET, 0) == ("", False)


_LONG_SEED = "这是一个足够长的开头片段用来触发合成判定的文本内容"


def _activated() -> MuseThinkingSynthesizer:
    """返回一个已越过首包判定、进入合成期的合成器。"""
    s = MuseThinkingSynthesizer("muse-spark", enable_thinking=True)
    take, done = s.feed(_LONG_SEED, 0, 0)
    assert take and not done
    assert s.active is True
    return s


class TestSynthesizerBudgetAndDone:
    def test_done_at_threshold(self):
        s = _activated()
        take, done = s.feed("z" * 100, THINK_DONE_AT - 1, 0)
        assert take == "z" * 100
        assert done is True
        assert s.done is True

    def test_done_on_step_marker(self):
        """首包含「### 第一步」且足够长 → 起合成并立即闭合（前端不必再等）。"""
        s = MuseThinkingSynthesizer("muse-spark", enable_thinking=True)
        take, done = s.feed("### 第一步 开始分析这个问题吧我们一步一步来推进", 0, 0)
        assert take
        assert done is True

    def test_budget_caps_take(self):
        """reasoning 已接近预算 → 只取剩余额度，不越界。"""
        s = _activated()
        take, done = s.feed("q" * 5000, THINK_BUDGET - 10, 0)
        assert len(take) == 10
        assert done is True  # 到顶即闭合

    def test_after_done_no_more_output(self):
        s = _activated()
        s.feed("z" * 100, THINK_DONE_AT - 1, 0)
        assert s.done is True
        assert s.feed("更多内容" * 10, 100, 0) == ("", False)


class TestFinalDone:
    def test_muse_needs_final_done_when_open(self):
        s = _activated()
        assert s.done is False
        assert s.needs_final_done(has_reasoning=True) is True

    def test_no_final_done_without_reasoning(self):
        s = MuseThinkingSynthesizer("muse-spark", enable_thinking=True)
        assert s.needs_final_done(has_reasoning=False) is False

    def test_no_final_done_when_already_closed(self):
        s = _activated()
        s.feed("z" * 100, THINK_DONE_AT - 1, 0)
        assert s.done is True
        assert s.needs_final_done(has_reasoning=True) is False

    def test_spark_keeps_legacy_no_final_done(self):
        """口径保留（重构前即如此）：流式收尾兜底只认 ``muse``，不含 ``spark``。

        非流式路径对 spark 是补 [THINK_DONE] 的（见 synth_nonstream_thinking 的调用方），
        两条路径口径不一致属历史遗留。此处**钉住现状**而非顺手改掉 —— 行为变更需单独
        评估（前端是否会因缺 DONE 悬挂），不在纯重构里夹带。
        """
        s = MuseThinkingSynthesizer("spark-x", enable_thinking=True)
        s.feed("开头片段够长了吧啦啦啦", 0, 0)
        assert s.needs_final_done(has_reasoning=True) is False

    def test_state_is_per_instance(self):
        """合成状态随实例走，不跨轮污染（旧实现用实例属性存，易残留）。"""
        a = MuseThinkingSynthesizer("muse-spark", enable_thinking=True)
        a.feed("z" * 100, THINK_DONE_AT - 1, 0)
        b = MuseThinkingSynthesizer("muse-spark", enable_thinking=True)
        assert b.done is False
        assert b.active is False


# ════════════════════════════════════════════════════════════
# 4. 接线层：_process_stream_with_reasoning 的信号序列
# ════════════════════════════════════════════════════════════


class _FakeSession:
    """最小桩：只绑真实流式方法所需的属性。"""

    def __init__(self, model="muse-spark", enable_thinking=True):
        self.context = SimpleNamespace(
            no_stream_chunk=False,
            model=model,
            enable_thinking=enable_thinking,
        )
        self.api = SimpleNamespace(_accumulate_usage=lambda usage: None)
        self.api.accumulate_tool_calls_from_delta = lambda delta, acc: None

    _process_stream_with_reasoning = OnlineToolSession._process_stream_with_reasoning
    _log_assistant_chunk = lambda self, content: None  # noqa: E731
    _log_turn_end_marker = lambda self, reason: None  # noqa: E731


def _chunk(content="", reasoning=""):
    delta = SimpleNamespace(content=content, reasoning_content=reasoning, tool_calls=None)
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta)], usage=None)


def _calls(cb):
    return [str(c.args[0]) for c in cb.call_args_list]


def test_stream_muse_emits_think_and_done():
    """Muse 流式：思考增量以 [THINK] 前缀实时推送，收尾有 [THINK_DONE]。"""
    sess = _FakeSession(model="muse-spark", enable_thinking=True)
    chunks = [_chunk("这是思考过程的开头部分"), _chunk("继续推理细节"), _chunk("结论：完成")]
    cb = MagicMock()
    content, _tools, reasoning = sess._process_stream_with_reasoning(iter(chunks), cb)
    emitted = _calls(cb)

    assert content == "这是思考过程的开头部分继续推理细节结论：完成"  # 正文完整不截断
    assert reasoning  # 合成了思考
    assert any(e == "[THINK_DONE]" for e in emitted), f"缺少 [THINK_DONE]: {emitted}"
    assert any(e.startswith("[THINK]") for e in emitted)
    # 每个正文增量都原样回调（思考面板之外，正文流不受影响）
    for piece in ("这是思考过程的开头部分", "继续推理细节", "结论：完成"):
        assert piece in emitted


def test_stream_non_muse_never_synthesizes_think():
    sess = _FakeSession(model="gpt-4o", enable_thinking=True)
    cb = MagicMock()
    sess._process_stream_with_reasoning(iter([_chunk("普通回答内容")]), cb)
    emitted = _calls(cb)
    assert not any(e.startswith("[THINK]") for e in emitted)
    assert "[THINK_DONE]" not in emitted


def test_stream_real_reasoning_not_overwritten_by_synthesis():
    """原生 reasoning_content 存在时，合成器不得介入（[THINK] 只来自真实 RC）。"""
    sess = _FakeSession(model="muse-spark", enable_thinking=True)
    cb = MagicMock()
    _content, _tools, reasoning = sess._process_stream_with_reasoning(iter([_chunk("正文很长很长很长很长很长很长", reasoning="原生思考内容")]), cb)
    assert reasoning == "原生思考内容"


def test_stream_synthesis_state_not_leaked_to_instance():
    """拿掉实例属性后，连续两轮各自独立闭环（第 1 轮的 done 不影响第 2 轮）。"""
    sess = _FakeSession(model="muse-spark", enable_thinking=True)
    for _ in range(2):
        cb = MagicMock()
        sess._process_stream_with_reasoning(iter([_chunk("第一段足够长的思考内容"), _chunk("第二段继续")]), cb)
        assert "[THINK_DONE]" in _calls(cb)
    assert not hasattr(sess, "_muse_syn_done")
    assert not hasattr(sess, "_muse_syn_active")
