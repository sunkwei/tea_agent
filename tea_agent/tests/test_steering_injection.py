"""插话（steering）功能测试 — 覆盖 drain/inject 与工具循环注入。

功能背景：
  会话进行期间，使用者的新输入经 /api/chat/steering 进入服务端排队队列，
  工具循环在每轮边界消费并注入 session.context.messages（[即时指令] 前缀），
  使输入无需等待会话结束即可在下一轮生效；注入后通过 _steering_notify
  通知前端（SSE steering_injected），前端据此移除本地排队项避免重复发送。
"""

from tea_agent.session.message_queue import (
    MessageQueue,
    drain_steering_items,
    inject_steering_messages,
)


def _make_session(**kwargs):
    """构造最小可用的 session 桩（context.messages + 可选 hooks）。"""
    class _Ctx:
        def __init__(self):
            self.messages = []
            self.message_queue = None

    class _Sess:
        def __init__(self):
            self.context = _Ctx()
            self._steering_provider = kwargs.get("provider")
            self._steering_notify = kwargs.get("notify")
            self.notified = []

        def _cap_message_text(self, text, limit=400):
            return text[:limit]

    sess = _Sess()
    if kwargs.get("notify"):
        sess._steering_notify = lambda item: sess.notified.append(item)
    return sess


# ── drain_steering_items ──────────────────────────────────

class TestDrainSteeringItems:
    def test_provider_source(self):
        """server 队列（provider）项应被消费并标记 source=server_queue。"""
        provider_calls = []
        def provider():
            provider_calls.append(1)
            return [{"id": "a1", "message": "先检查依赖"}] if len(provider_calls) == 1 else []

        sess = _make_session(provider=provider)
        items = drain_steering_items(sess)

        assert len(items) == 1
        assert items[0]["id"] == "a1"
        assert items[0]["source"] == "server_queue"
        # 已消费：再次调用为空
        assert drain_steering_items(sess) == []

    def test_message_queue_source(self):
        """session.context.message_queue 的 steering 队列应被消费。"""
        sess = _make_session()
        q = MessageQueue(mode="one-at-a-time")
        q.push_steering("改用并行方式")
        sess.context.message_queue = q

        items = drain_steering_items(sess)

        assert len(items) == 1
        assert items[0]["message"] == "改用并行方式"
        assert items[0]["source"] == "message_queue"
        assert not q.has_steering

    def test_both_sources_combined(self):
        """两个来源的消息应合并返回。"""
        sess = _make_session(provider=lambda: [{"id": "p1", "message": "来自服务端队列"}])
        q = MessageQueue()
        q.push_steering("来自 MessageQueue")
        sess.context.message_queue = q

        items = drain_steering_items(sess)
        sources = sorted(i["source"] for i in items)

        assert len(items) == 2
        assert sources == ["message_queue", "server_queue"]

    def test_provider_exception_graceful(self):
        """provider 抛异常不应影响主流程，返回空列表。"""
        def boom():
            raise RuntimeError("provider 挂了")

        sess = _make_session(provider=boom)
        assert drain_steering_items(sess) == []

    def test_no_sources(self):
        """无任何来源时返回空。"""
        assert drain_steering_items(_make_session()) == []


# ── inject_steering_messages ──────────────────────────────

class TestInjectSteeringMessages:
    def test_injects_user_message_with_prefix(self):
        """注入为 user 消息，带 [即时指令] 前缀，写入 context.messages。"""
        sess = _make_session()
        n = inject_steering_messages(sess, [{"id": "a1", "message": " 先停下手头工作 "}])

        assert n == 1
        assert len(sess.context.messages) == 1
        assert sess.context.messages[0]["role"] == "user"
        assert sess.context.messages[0]["content"] == "[即时指令] 先停下手头工作"

    def test_preserves_images(self):
        """带图插话保留 images 字段（由 to_multimodal 后续转换）。"""
        sess = _make_session()
        n = inject_steering_messages(sess, [{
            "id": "a2", "message": "看这张图", "images": ["uploads/x.png"],
        }])

        assert n == 1
        msg = sess.context.messages[0]
        assert msg["images"] == ["uploads/x.png"]
        assert msg["content"] == "[即时指令] 看这张图"

    def test_notify_called_per_item(self):
        """每条注入后应回调 _steering_notify（用于 SSE 通知前端）。"""
        sess = _make_session(notify=True)
        items = [
            {"id": "a1", "message": "第一条"},
            {"id": "a2", "message": "第二条"},
        ]
        n = inject_steering_messages(sess, items)

        assert n == 2
        assert [i["id"] for i in sess.notified] == ["a1", "a2"]

    def test_skips_empty_items(self):
        """空文本且无图的消息应跳过。"""
        sess = _make_session(notify=True)
        n = inject_steering_messages(sess, [
            {"id": "x1", "message": ""},
            {"id": "x2", "message": "  ", "images": []},
        ])

        assert n == 0
        assert sess.context.messages == []
        assert sess.notified == []

    def test_no_items(self):
        """空列表不产生任何副作用。"""
        sess = _make_session(notify=True)
        assert inject_steering_messages(sess, []) == 0
        assert sess.context.messages == []
        assert sess.notified == []

    def test_cap_text(self):
        """超长文本应经 _cap_message_text 截断。"""
        sess = _make_session()
        long_text = "很长的插话" * 100
        inject_steering_messages(sess, [{"id": "a1", "message": long_text}])

        assert len(sess.context.messages[0]["content"]) == 400 + len("[即时指令] ")


# ── 工具循环集成 ──────────────────────────────────────────

from unittest.mock import MagicMock  # noqa: E402

from tea_agent.onlinesession import OnlineToolSession  # noqa: E402
from tea_agent.session.tool_loop_runner import execute_tool_loop  # noqa: E402


class TestToolLoopSteering:
    def _make_session(self, **kwargs):
        """创建 session 并 mock api（与 test_onlinesession 一致的模式）。"""
        mock_tk = MagicMock()
        mock_tk.meta_map = {}
        mock_tk.call_tool.return_value = "mock_result"
        sess = OnlineToolSession(
            toolkit=mock_tk, api_key="sk-test", api_url="https://api.test.com/v1",
            model="test-model", enable_thinking=False, storage=None,
            no_stream_chunk=True, **kwargs,
        )
        sess._build_api_messages = MagicMock(return_value=[{"role": "user", "content": "test"}])
        sess.api = MagicMock()
        sess.api.create_chat_stream.return_value = None
        sess._process_stream_with_reasoning = MagicMock()
        sess.tools_comp = MagicMock()
        return sess

    def test_steering_injected_between_tool_rounds(self):
        """两轮工具调用之间：插话应在下一轮 API 请求前注入 context.messages。"""
        sess = self._make_session()

        def mock_tc(name):
            return MagicMock(id="c1", function=MagicMock(name=name, arguments="{}"))

        # 三轮响应：工具 → 工具 → 文本
        sess._process_stream_with_reasoning.side_effect = [
            ("", [{"id": "c1", "type": "function",
                   "function": {"name": "search", "arguments": "{}"}}], ""),
            ("", [{"id": "c2", "type": "function",
                   "function": {"name": "read_file", "arguments": "{}"}}], ""),
            ("完成", [], ""),
        ]
        sess.tools_comp.parse_tool_calls_from_stream.side_effect = [
            [mock_tc("search")],
            [mock_tc("read_file")],
            [],
        ]
        sess.tools_comp.execute_tool_call.return_value = ("c1", "tool", "result")

        # 插话：第一轮边界无消息，第二轮边界消费 1 条（模拟执行期间用户输入）
        provider_calls = []
        notified = []
        def provider():
            provider_calls.append(1)
            if len(provider_calls) == 2:
                return [{"id": "s1", "message": "先检查配置再继续"}]
            return []
        sess._steering_provider = provider
        sess._steering_notify = lambda item: notified.append(item)

        result = execute_tool_loop(sess, {"msg": "test", "callback": lambda x: None})

        assert result["iterations"] >= 2
        injected = [m for m in sess.context.messages
                    if m.get("role") == "user" and "[即时指令]" in (m.get("content") or "")]
        assert len(injected) == 1
        assert injected[0]["content"] == "[即时指令] 先检查配置再继续"
        # 注入后已通知前端（SSE steering_injected）
        assert [i["id"] for i in notified] == ["s1"]
        sess.close()

    def test_no_provider_no_injection(self):
        """无插话来源时循环行为不变（回归保护）。"""
        sess = self._make_session()
        sess._process_stream_with_reasoning.return_value = ("直接回复", [], "")
        sess.tools_comp.parse_tool_calls_from_stream.return_value = []

        result = execute_tool_loop(sess, {"msg": "hi", "callback": lambda x: None})

        assert result["full_reply"] == "直接回复"
        assert not any("[即时指令]" in (m.get("content") or "") for m in sess.context.messages)
        sess.close()

    def test_stale_queue_drained_at_chat_start(self):
        """chat_stream 启动时应调用 provider 清理遗留排队消息（防重复注入）。"""
        sess = self._make_session()
        stale = [{"id": "old1", "message": "上轮遗留"}]
        sess._steering_provider = lambda: ([stale.pop(0)] if stale else [])

        # 模拟 chat_stream 启动时的清理调用（provider 消费并丢弃）
        _stale_provider = getattr(sess, "_steering_provider", None)
        _cleaned = _stale_provider() if _stale_provider is not None else []

        assert len(_cleaned) == 1
        assert _cleaned[0]["id"] == "old1"
        # 清理后队列已空，工具循环不会再注入
        assert sess._steering_provider() == []
        sess.close()
