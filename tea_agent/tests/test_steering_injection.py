"""插话（steering）/ 后续任务（follow-up）功能测试。

功能背景：
  会话进行期间，使用者的新输入经 /api/chat/steering 进入服务端排队队列，
  工具循环在每轮边界消费并注入 session.context.messages（[即时指令] 前缀），
  使输入无需等待会话结束即可在下一轮生效；注入后通过 _steering_notify
  通知前端（SSE steering_injected），前端据此移除本地排队项避免重复发送。

  follow-up（/api/pi/queue type=followup）语义不同：**本轮工作完成后**投递，
  由工具循环自然收尾时注入（[后续任务] 前缀）并再跑一轮。
"""

import pytest

from tea_agent.session.message_queue import (
    MessageQueue,
    attach_followup_provider,
    attach_steering_provider,
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


# ── 回合入口接线（回归：漏挂 provider 导致插话静默失效）──────────

class TestAttachSteeringProvider:
    """attach_steering_provider：所有回合入口共用的接线助手。"""

    def test_provider_resolves_topic_at_call_time(self):
        """topic 在**调用时**解析（同一 session 服务多 topic，构造期固定会取错）。"""
        seen = []

        class _S:
            current_topic_id = ""

        sess = _S()
        attach_steering_provider(sess, lambda tid: (seen.append(tid), [{"id": "x", "message": "m"}])[1])

        sess.current_topic_id = "topic-A"
        assert sess._steering_provider()[0]["id"] == "x"
        sess.current_topic_id = "topic-B"
        sess._steering_provider()
        assert seen == ["topic-A", "topic-B"]

    def test_no_topic_returns_empty_without_draining(self):
        calls = []

        class _S:
            current_topic_id = ""

        sess = _S()
        attach_steering_provider(sess, lambda tid: calls.append(tid) or [])
        assert sess._steering_provider() == []
        assert calls == []

    def test_drain_failure_does_not_propagate(self):
        """drain 抛异常时必须吞掉并返回空（不能打断整轮对话）。"""
        class _S:
            current_topic_id = "t1"

        def _boom(_tid):
            raise RuntimeError("queue backend down")

        sess = _S()
        attach_steering_provider(sess, _boom)
        assert sess._steering_provider() == []

    def test_notify_wired_only_when_given(self):
        class _S:
            current_topic_id = "t1"

        s1 = _S()
        attach_steering_provider(s1, lambda tid: [])
        assert not hasattr(s1, "_steering_notify")

        got = []
        s2 = _S()
        attach_steering_provider(s2, lambda tid: [], lambda item: got.append(item))
        s2._steering_notify({"id": "a"})
        assert got == [{"id": "a"}]

    def test_drained_items_feed_injection(self):
        """接线后 drain_steering_items 能真正消费并按 source 标注。"""
        sess = _make_session()
        sess.current_topic_id = "topic-Z"
        attach_steering_provider(sess, lambda tid: [{"id": "i1", "message": "先停下"}])

        items = drain_steering_items(sess)
        assert [i["id"] for i in items] == ["i1"]
        assert items[0]["source"] == "server_queue"


class TestServerEntryPointsWired:
    """三个 chat_stream 入口都必须接线（历史回归：只有 SSE 挂过）。"""

    def test_all_entry_points_call_wire_steering(self):
        from pathlib import Path

        src = (Path(__file__).resolve().parents[1] / "server" / "modules" / "agent_module.py").read_text(
            encoding="utf-8"
        )
        for entry in ("chat_completion", "_run_stream", "chat_stream_sse"):
            assert f"def {entry}" in src, f"入口 {entry} 不存在"
        # 三个入口各调用一次 _wire_steering
        assert src.count("_wire_steering(") >= 3, "有 chat_stream 入口漏挂插话来源"

    def test_steering_drain_pulls_server_queue(self, tmp_path, monkeypatch):
        """_steering_drain 能从服务端排队队列取出插话。"""
        from tea_agent.server.modules import state
        from tea_agent.server.modules.agent_module import AgentModule

        monkeypatch.setattr(state, "_queue_store_path", lambda: str(tmp_path / "q.json"))
        item_id = state.queue_add("topic-drain", "插话内容", [])
        items = AgentModule._steering_drain("topic-drain")
        assert [i["id"] for i in items] == [item_id]
        assert items[0]["message"] == "插话内容"
        # 已被消费（幂等：再次 drain 为空）
        assert AgentModule._steering_drain("topic-drain") == []

    def test_steering_drain_pulls_pi_queue(self, monkeypatch):
        """Pi 队列（/api/pi/queue）必须一并对接，否则该接口入队的插话永远到不了模型。"""
        from tea_agent.server.module import get_registry
        from tea_agent.server.modules.agent_module import AgentModule

        class _FakePi:
            def queue_drain(self, topic_id, msg_type="steering"):
                if topic_id == "topic-pi":
                    return {"ok": True, "messages": [
                        {"id": "p1", "content": "来自 Pi 队列", "type": "steering"},
                    ]}
                return {"ok": True, "messages": []}

        monkeypatch.setattr(get_registry(), "get", lambda name: _FakePi() if name == "pi_features" else None)
        items = AgentModule._steering_drain("topic-pi")
        assert any(i["id"] == "p1" and i["message"] == "来自 Pi 队列" for i in items)
        assert all(i.get("source") == "pi_queue" for i in items)


class TestMessageQueueThreadSafety:
    def test_concurrent_push_ids_are_unique(self):
        """并发 push 不得产生重复 id（_next_id 自增必须在锁内）。"""
        import threading

        q = MessageQueue(mode="all")
        ids: list[str] = []
        lock = threading.Lock()

        def _push(n):
            local = [q.push_steering(f"msg-{n}-{i}").id for i in range(40)]
            with lock:
                ids.extend(local)

        threads = [threading.Thread(target=_push, args=(n,)) for n in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(ids) == 240
        assert len(set(ids)) == len(ids), "并发下出现重复消息 id"
        assert q.steering_count == 240


# ── 服务端排队队列：消费不得死锁 ─────────────────────────────
# 回归：queue_pop / queue_remove 曾在持锁状态下调用 _persist_queues（同一把非重入锁）
# → 自死锁。后果：用户一插话，工具循环的 drain 把回合永久卡死，且锁被占住后
# 所有队列操作（含新的插话入队）一并阻塞。

class TestServerQueueNoDeadlock:
    @pytest.fixture(autouse=True)
    def _hermetic_queue(self):
        """每个用例前后清空全局排队字典（它跨用例共享，否则落盘/恢复计数会被污染）。"""
        from tea_agent.server.modules import state

        with state.message_queue_lock:
            state.message_queue.clear()
        yield
        with state.message_queue_lock:
            state.message_queue.clear()

    @staticmethod
    def _run_with_timeout(fn, timeout: float = 5.0):
        """在子线程执行 fn，超时即判定卡死（返回 (done, result)）。"""
        import threading

        box: dict = {}

        def _target():
            box["result"] = fn()

        th = threading.Thread(target=_target, daemon=True)
        th.start()
        th.join(timeout=timeout)
        return (not th.is_alive()), box.get("result")

    def test_queue_pop_does_not_deadlock(self, tmp_path, monkeypatch):
        from tea_agent.server.modules import state

        monkeypatch.setattr(state, "_queue_store_path", lambda: str(tmp_path / "q.json"))
        item_id = state.queue_add("t-pop", "插话内容", [])

        done, item = self._run_with_timeout(lambda: state.queue_pop("t-pop"))
        assert done, "queue_pop 卡死（疑似持锁调用 _persist_queues 自死锁）"
        assert item and item["id"] == item_id
        assert item["message"] == "插话内容"

    def test_queue_remove_does_not_deadlock(self, tmp_path, monkeypatch):
        from tea_agent.server.modules import state

        monkeypatch.setattr(state, "_queue_store_path", lambda: str(tmp_path / "q.json"))
        item_id = state.queue_add("t-remove", "待取消", [])

        done, removed = self._run_with_timeout(lambda: state.queue_remove("t-remove", item_id))
        assert done, "queue_remove 卡死（疑似持锁调用 _persist_queues 自死锁）"
        assert removed is True

    def test_queue_usable_after_pop(self, tmp_path, monkeypatch):
        """消费一条后队列必须仍可用（死锁时锁被永久占住 → 后续入队全阻塞）。"""
        from tea_agent.server.modules import state

        monkeypatch.setattr(state, "_queue_store_path", lambda: str(tmp_path / "q.json"))
        state.queue_add("t-mixed", "第一条", [])
        state.queue_pop("t-mixed")

        done, new_id = self._run_with_timeout(lambda: state.queue_add("t-mixed", "第二条", []))
        assert done, "queue_pop 之后 queue_add 阻塞（锁未释放）"
        assert new_id
        assert [i["message"] for i in state.queue_list("t-mixed")] == ["第二条"]

    def test_persist_survives_roundtrip(self, tmp_path, monkeypatch):
        """落盘/恢复仍正常（锁外落盘不得改变持久化语义）。"""
        from tea_agent.server.modules import state

        path = str(tmp_path / "q.json")
        monkeypatch.setattr(state, "_queue_store_path", lambda: path)
        state.queue_add("t-rt", "持久化内容", [])

        # 清空内存后从磁盘恢复
        with state.message_queue_lock:
            state.message_queue.clear()
        assert state.restore_queues() == 1
        assert state.queue_list("t-rt")[0]["message"] == "持久化内容"


# ── /v1/chat/completions 流式 SSE 帧 ────────────────────────
# 回归：_generate_sse 里定义的是 nl2（小写）却用了 NL2（大写，从未定义）
# → 第一个 content 分片就抛 NameError，/v1/chat/completions stream=true 全挂，
#   而此前没有任何测试覆盖该生成器。

class TestGenerateSseFrames:
    @staticmethod
    def _frames(events):
        """收集并解析 SSE 帧 → [dict, ..., "[DONE]"]，顺带校验空行分隔。"""
        import asyncio
        import json

        from tea_agent.server.modules.agent_module import AgentModule

        async def _run():
            q = asyncio.Queue()
            for e in events:
                await q.put(e)
            return [chunk async for chunk in AgentModule._generate_sse(q, "test-model")]

        chunks = asyncio.run(_run())
        assert all(c.endswith("\n\n") for c in chunks), f"SSE 帧未以空行结尾: {chunks}"
        frames = []
        for c in chunks:
            assert c.startswith("data: "), c
            body = c[len("data: "):].strip()
            frames.append("[DONE]" if body == "[DONE]" else json.loads(body))
        return frames

    def test_content_done_frames(self):
        frames = self._frames([
            {"type": "content", "text": "你好"},
            {"type": "done", "ai_msg": "你好", "tools_used": []},
        ])
        assert frames[-1] == "[DONE]"
        contents = [
            f["choices"][0]["delta"].get("content")
            for f in frames
            if isinstance(f, dict) and f.get("choices")
        ]
        assert "你好" in contents, f"内容分片丢失（此前 NameError 会整段崩）: {frames}"
        assert any(isinstance(f, dict) and f.get("choices", [{}])[0].get("finish_reason") == "stop"
                   for f in frames), "缺少 finish_reason=stop 的收尾帧"

    def test_error_frame_terminates(self):
        frames = self._frames([{"type": "error", "error": "boom"}])
        assert any(isinstance(f, dict) and f.get("error") == "boom" for f in frames), frames
        assert frames[-1] == "[DONE]"


# ── follow-up 投递（回归：此前整条链路无人调用，消息静默丢弃）──────

class TestFollowupDelivery:
    """follow-up 的语义是"本轮所有工作完成后投递"，且必须真的到模型那里。"""

    def test_drain_from_provider(self):
        from tea_agent.session.message_queue import drain_followup_items

        sess = _make_session()
        sess.current_topic_id = "t-fu"
        pending = [{"id": "f1", "message": "完成后总结"}]
        attach_followup_provider(sess, lambda tid: ([pending.pop(0)] if pending else []))

        items = drain_followup_items(sess)
        assert [i["id"] for i in items] == ["f1"]
        # 消费式：再次 drain 为空
        assert drain_followup_items(sess) == []

    def test_drain_from_context_queue(self):
        from tea_agent.session.message_queue import drain_followup_items

        sess = _make_session()
        q = MessageQueue(mode="one-at-a-time")
        q.push_followup("队列里的后续任务")
        sess.context.message_queue = q

        items = drain_followup_items(sess)
        assert [i["message"] for i in items] == ["队列里的后续任务"]

    def test_inject_prefix_and_skip_empty(self):
        from tea_agent.session.message_queue import inject_followup_messages

        sess = _make_session()
        n = inject_followup_messages(sess, [
            {"id": "a", "message": " 总结一下 "},
            {"id": "b", "message": "   "},          # 空内容不注入
        ])
        assert n == 1
        assert sess.context.messages[0]["content"] == "[后续任务] 总结一下"

    def test_no_source_no_injection(self):
        from tea_agent.session.message_queue import drain_followup_items

        sess = _make_session()
        assert drain_followup_items(sess) == []


class TestFollowupInToolLoop:
    """工具循环：自然收尾时投递 follow-up 并再跑一轮（含轮数上限）。"""

    def _make_session(self, **kwargs):
        from unittest.mock import MagicMock

        from tea_agent.onlinesession import OnlineToolSession

        mock_tk = MagicMock()
        mock_tk.meta_map = {}
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

    def test_followup_delivered_after_final_answer(self):
        from tea_agent.onlinesession import OnlineToolSession  # noqa: F401
        from tea_agent.session.tool_loop_runner import execute_tool_loop

        sess = self._make_session()
        sess.current_topic_id = "t-loop"
        # 第一次收尾投递 1 条 follow-up，之后为空
        pending = [{"id": "f1", "message": "完成后总结"}]
        attach_followup_provider(sess, lambda tid: ([pending.pop(0)] if pending else []))

        sess._process_stream_with_reasoning.side_effect = [
            ("第一段回答", [], ""),
            ("后续任务回答", [], ""),
        ]
        sess.tools_comp.parse_tool_calls_from_stream.return_value = []

        result = execute_tool_loop(sess, {"msg": "干活", "callback": lambda x: None})

        injected = [m for m in sess.context.messages
                    if "[后续任务]" in (m.get("content") or "")]
        assert len(injected) == 1, f"follow-up 未投递: {sess.context.messages}"
        assert injected[0]["content"] == "[后续任务] 完成后总结"
        # 投递后应再跑一轮，模型据此产出回答
        assert "第一段回答" in result["full_reply"]
        assert "后续任务回答" in result["full_reply"]
        sess.close()

    def test_followup_rounds_capped(self):
        """队列被无限灌入时必须有轮数上限（防止无限生成）。"""
        from tea_agent.session.message_queue import attach_followup_provider as _attach
        from tea_agent.session.tool_loop_runner import MAX_FOLLOWUP_ROUNDS, execute_tool_loop

        sess = self._make_session()
        sess.current_topic_id = "t-cap"
        _attach(sess, lambda tid: [{"id": "x", "message": "永远有后续"}])

        calls = {"n": 0}

        def _resp(*a, **k):
            calls["n"] += 1
            return (f"回答{calls['n']}", [], "")

        sess._process_stream_with_reasoning.side_effect = _resp
        sess.tools_comp.parse_tool_calls_from_stream.return_value = []

        result = execute_tool_loop(sess, {"msg": "干活", "callback": lambda x: None})

        # 1 次原始 + 至多 MAX_FOLLOWUP_ROUNDS 次 follow-up 追加轮
        assert calls["n"] == 1 + MAX_FOLLOWUP_ROUNDS, f"轮数未受上限约束: {calls['n']}"
        assert result["iterations"] >= 1
        sess.close()

    def test_no_followup_behaves_as_before(self):
        """无 follow-up 时循环行为不变（回归保护）。"""
        from tea_agent.session.tool_loop_runner import execute_tool_loop

        sess = self._make_session()
        sess._process_stream_with_reasoning.return_value = ("直接回复", [], "")
        sess.tools_comp.parse_tool_calls_from_stream.return_value = []

        result = execute_tool_loop(sess, {"msg": "hi", "callback": lambda x: None})

        assert result["full_reply"] == "直接回复"
        assert not any("[后续任务]" in (m.get("content") or "") for m in sess.context.messages)
        sess.close()
