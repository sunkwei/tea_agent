"""断流重试（_process_stream_with_reasoning retry_factory）回归测试。

背景: 模型 API 流式响应可能中途断连（httpx.RemoteProtocolError:
"peer closed connection without sending complete message body
(incomplete chunked read)"）。create_chat_stream 的重试只保护请求
创建阶段，流迭代中断需在消费层兜底。

覆盖:
- 断流后 retry_factory 重取流 → 内容完整（丢弃半截重新生成）
- 无 retry_factory 时异常原样抛出
- 重试次数超限后抛出
- 非可重试错误不重试
"""

import os
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

try:
    import httpx
    _RemoteProtocolError = httpx.RemoteProtocolError
except Exception:  # pragma: no cover
    class _RemoteProtocolError(Exception):
        pass

from tea_agent.onlinesession import OnlineToolSession  # noqa: E402


class _FakeSession:
    """最小 session 桩：绑定真实 _process_stream_with_reasoning 方法。"""

    def __init__(self):
        self.context = SimpleNamespace(no_stream_chunk=False)
        self.api = SimpleNamespace(_accumulate_usage=lambda usage: None)

        def _accumulate_tool_calls(delta, tool_calls_data):
            """等价于 APIComponent.accumulate_tool_calls_from_delta（按 index 累积）。"""
            if not delta.tool_calls:
                return
            for tc in delta.tool_calls:
                idx = tc.index
                while len(tool_calls_data) <= idx:
                    tool_calls_data.append({"id": "", "name": "", "arguments": ""})
                if tc.id:
                    tool_calls_data[idx]["id"] = tc.id
                if tc.function:
                    if tc.function.name:
                        tool_calls_data[idx]["name"] = tc.function.name
                    if tc.function.arguments:
                        tool_calls_data[idx]["arguments"] += tc.function.arguments

        self.api.accumulate_tool_calls_from_delta = _accumulate_tool_calls

    _process_stream_with_reasoning = OnlineToolSession._process_stream_with_reasoning


def _make_chunk(content: str = "", reasoning: str = "", tool_call=None):
    """构造 OpenAI 流式 chunk（delta 结构；tool_call 为单个或 None）。"""
    delta = SimpleNamespace(
        content=content,
        reasoning_content=reasoning,
        tool_calls=[tool_call] if tool_call else None,
    )
    choice = SimpleNamespace(delta=delta)
    return SimpleNamespace(choices=[choice], usage=None)


class _Stream:
    """可迭代流：items 按序产出，可配置在指定位置抛异常。"""

    def __init__(self, items, fail_at=None, exc=None):
        self._items = list(items)
        self._idx = 0
        self._fail_at = fail_at
        self._exc = exc or _RemoteProtocolError(
            "peer closed connection without sending complete message body (incomplete chunked read)"
        )

    def __iter__(self):
        return self

    def __next__(self):
        if self._fail_at is not None and self._idx == self._fail_at:
            raise self._exc
        if self._idx >= len(self._items):
            raise StopIteration
        item = self._items[self._idx]
        self._idx += 1
        return item


@pytest.fixture
def fake():
    return _FakeSession()


# ── 1. 断流后重试成功 ──

def test_stream_retry_recovers_after_interruption(fake):
    """第一次流中途断连，retry_factory 重取流后内容完整。"""
    first = _Stream([_make_chunk("你好"), _make_chunk("，世界")], fail_at=1)
    second = _Stream([_make_chunk("你好，世界！")])
    factory_calls = []

    def retry_factory():
        factory_calls.append(1)
        return second

    cb = MagicMock()
    content, tool_calls, reasoning = fake._process_stream_with_reasoning(
        first, cb, retry_factory=retry_factory
    )
    assert content == "你好，世界！"          # 完整内容（丢弃半截重新生成）
    assert factory_calls == [1]               # 重试工厂被调用一次
    assert len(tool_calls) == 0
    # callback 收到中断提示
    any_retry_hint = any(
        "自动重试" in str(c.args[0]) for c in cb.call_args_list
    )
    assert any_retry_hint


def test_stream_retry_with_tool_calls(fake):
    """断流重试后工具调用完整（流式增量半截参数被丢弃）。"""
    # 第一次流：第一个 chunk 给了工具调用片段，第二个 chunk 断流
    tc_partial = SimpleNamespace(
        index=0, id="call_1", function=SimpleNamespace(name="toolkit_x", arguments='{"q"')
    )
    first = _Stream([_make_chunk(tool_call=tc_partial)], fail_at=1)
    tc_full = SimpleNamespace(
        index=0, id="call_1", function=SimpleNamespace(name="toolkit_x", arguments='{"q": 1}')
    )
    second = _Stream([_make_chunk(tool_call=tc_full)])
    calls = []

    def retry_factory():
        calls.append(1)
        return second

    cb = MagicMock()
    content, tool_calls, reasoning = fake._process_stream_with_reasoning(
        first, cb, retry_factory=retry_factory
    )
    assert len(calls) == 1
    # 工具调用数据来自第二次流（完整参数，扁平结构 id/name/arguments）
    assert len(tool_calls) == 1
    assert tool_calls[0]["arguments"] == '{"q": 1}'
    assert tool_calls[0]["name"] == "toolkit_x"


# ── 2. 无 retry_factory → 原样抛出 ──

def test_stream_raises_without_retry_factory(fake):
    """未提供 retry_factory 时断流异常原样抛出。"""
    stream = _Stream([_make_chunk("x")], fail_at=0)
    with pytest.raises(Exception) as ei:
        fake._process_stream_with_reasoning(stream, MagicMock())
    assert "chunked read" in str(ei.value) or "peer closed" in str(ei.value)


# ── 3. 重试次数超限 ──

def test_stream_raises_after_max_retries(fake):
    """重试工厂每次返回断流流 → 超过 max_stream_retries 后抛出。"""
    calls = []

    def retry_factory():
        calls.append(1)
        return _Stream([_make_chunk("x")], fail_at=0)  # 每次都断流

    with pytest.raises(Exception):
        fake._process_stream_with_reasoning(
            _Stream([_make_chunk("x")], fail_at=0),
            MagicMock(),
            retry_factory=retry_factory,
            max_stream_retries=2,
        )
    assert len(calls) == 2  # 恰好重试 2 次后放弃


# ── 4. 非可重试错误不重试 ──

def test_stream_does_not_retry_non_retryable_error(fake):
    """ValueError（非网络类错误）不触发重试。"""
    stream = _Stream([_make_chunk("x")], fail_at=0, exc=ValueError("bad args"))
    calls = []

    def retry_factory():
        calls.append(1)
        return _Stream([_make_chunk("ok")])

    with pytest.raises(ValueError):
        fake._process_stream_with_reasoning(
            stream, MagicMock(), retry_factory=retry_factory
        )
    assert calls == []  # 未重试


# ── 5. 正常流不受影响 ──

def test_stream_normal_no_retry(fake):
    """正常流一次消费完成，retry_factory 不被调用。"""
    stream = _Stream([_make_chunk("hello"), _make_chunk(" world")])
    calls = []

    def retry_factory():
        calls.append(1)
        return stream

    cb = MagicMock()
    content, tool_calls, reasoning = fake._process_stream_with_reasoning(
        stream, cb, retry_factory=retry_factory
    )
    assert content == "hello world"
    assert calls == []
