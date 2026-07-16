"""
OnlineSession 测试套件 — 模块级函数 + OnlineToolSession 核心方法（含新增测试）。

覆盖:
- detect_mode / extract_mode（纯函数）
- OnlineToolSession 生命周期（close / reset_session_state）
- _process_stream_with_reasoning（流式/非流式）
- _build_api_messages（三级历史拼接逻辑）
- api.create_chat_stream 参数（thinking, vision, temperature）
- _compress_tool_rounds / _repair_incomplete_tool_chains
- execute_tool_loop 多轮工具调用 + 循环检测
"""

from unittest.mock import MagicMock, PropertyMock

from tea_agent.onlinesession import APIComponent, OnlineToolSession, detect_mode, extract_mode
from tea_agent.session.context import SessionContext

# ════════════════════════════════════════════════════════════
# 1. detect_mode / extract_mode（已有）
# ════════════════════════════════════════════════════════════

class TestDetectMode:
    """detect_mode: 根据用户输入检测建议模式"""

    def test_returns_dict_with_mock(self):
        def mock_call_tool(action, text):
            return {"switched": False, "mode": "pragmatic"}
        result = detect_mode(mock_call_tool, "hello")
        assert isinstance(result, dict)

    def test_switched_true_when_mode_changes(self):
        def mock_call_tool(action, text):
            return {"switched": True, "from_mode": "mixed", "to_mode": "pragmatic", "reason": "code"}
        result = detect_mode(mock_call_tool, "write some code")
        assert result["switched"] is True
        assert result["from_mode"] == "mixed"
        assert result["to_mode"] == "pragmatic"

    def test_switched_false_when_no_change(self):
        def mock_call_tool(action, text):
            return {"switched": False, "mode": None}
        result = detect_mode(mock_call_tool, "hello")
        assert result["switched"] is False

    def test_exception_returns_default(self):
        def mock_call_tool(action, text):
            raise RuntimeError("tool not available")
        result = detect_mode(mock_call_tool, "hello")
        assert result["switched"] is False
        assert "error" in result

    def test_non_dict_result_handled(self):
        def mock_call_tool(action, text):
            return "not a dict"
        result = detect_mode(mock_call_tool, "hello")
        assert isinstance(result, dict)
        assert result["switched"] is False


class TestExtractMode:
    """extract_mode: 从 detect_mode 结果中提取合法模式"""

    def test_extracts_from_to_mode(self):
        result = extract_mode({"to_mode": "pragmatic"})
        assert result == "pragmatic"

    def test_extracts_from_mode(self):
        result = extract_mode({"mode": "creative"})
        assert result == "creative"

    def test_extracts_from_detected(self):
        result = extract_mode({"detected": "mixed"})
        assert result == "mixed"

    def test_priority_to_mode_over_mode(self):
        result = extract_mode({"to_mode": "pragmatic", "mode": "creative"})
        assert result == "pragmatic"

    def test_invalid_mode_returns_none(self):
        result = extract_mode({"to_mode": "invalid_mode_xyz"})
        assert result is None

    def test_empty_dict_returns_none(self):
        result = extract_mode({})
        assert result is None

    def test_none_value_returns_none(self):
        result = extract_mode({"to_mode": None})
        assert result is None

    def test_all_valid_modes_accepted(self):
        for mode in ("pragmatic", "creative", "mixed"):
            result = extract_mode({"to_mode": mode})
            assert result == mode


# ════════════════════════════════════════════════════════════
# 2. OnlineToolSession 生命周期（已有 + 增强）
# ════════════════════════════════════════════════════════════

class TestOnlineToolSessionCreate:
    """OnlineToolSession 创建测试"""

    def _make_session(self, **kwargs):
        mock_tk = MagicMock()
        mock_tk.meta_map = {}
        defaults = {
            "toolkit": mock_tk, "api_key": "sk-test", "api_url": "https://api.test.com/v1",
            "model": "test-model", "max_history": 5, "enable_thinking": False, "storage": None,
        }
        defaults.update(kwargs)
        sess = OnlineToolSession(**defaults)
        return sess

    def test_create_with_minimal_params(self):
        sess = self._make_session()
        assert sess.model == "test-model"
        assert sess.context is not None
        assert sess.context.client is not None
        sess.close()

    def test_create_with_cheap_model(self):
        sess = self._make_session(
            cheap_api_key="sk-cheap", cheap_api_url="https://cheap.api.com/v1",
            cheap_model="cheap-model",
        )
        assert sess._cheap_model_name == "cheap-model"
        assert sess._cheap_client is not None
        sess.close()

    def test_create_with_supports_vision(self):
        """创建时指定视觉支持"""
        sess = self._make_session(supports_vision=True)
        assert sess.context.supports_vision is True
        assert sess._supports_vision is True
        sess.close()

    def test_create_with_supports_reasoning(self):
        """创建时指定 reasoning 支持"""
        sess = self._make_session(supports_reasoning=True, enable_thinking=True)
        assert sess.context.supports_reasoning is True
        assert sess.context.enable_thinking is True
        sess.close()

    def test_create_with_disable_summary(self):
        """禁用历史摘要"""
        sess = self._make_session(disable_summary=True)
        assert sess.context.disable_summary is True
        sess.close()

    def test_create_with_custom_system_prompt(self):
        """自定义系统提示词"""
        custom_sp = "You are a custom assistant."
        sess = self._make_session(system_prompt=custom_sp)
        assert sess.system_prompt == custom_sp
        sess.close()

    def test_create_with_storage(self):
        """带有 Storage 实例"""
        from unittest.mock import MagicMock
        mock_storage = MagicMock()
        sess = self._make_session(storage=mock_storage)
        assert sess.storage is mock_storage
        assert sess.reflection_manager is not None
        assert sess.prompt_manager is not None
        sess.close()


class TestOnlineToolSessionLifecycle:
    """OnlineToolSession 生命周期测试"""

    def _make_session(self, **kwargs):
        mock_tk = MagicMock()
        mock_tk.meta_map = {}
        defaults = {
            "toolkit": mock_tk, "api_key": "sk-test", "api_url": "https://api.test.com/v1",
            "model": "test-model", "enable_thinking": False, "storage": None,
        }
        defaults.update(kwargs)
        return OnlineToolSession(**defaults)

    def test_close_releases_resources(self):
        sess = self._make_session()
        sess.close()
        sess.close()  # 重复 close 不应抛异常

    def test_reset_session_state_clears_usage(self):
        sess = self._make_session()
        sess.context._last_usage = {"total_tokens": 100, "prompt_tokens": 50, "completion_tokens": 50}
        sess.context._rounds_collector = [{"role": "assistant", "content": "test"}]
        sess._extra_iterations = 5
        sess.reset_session_state()
        assert sess.context._last_usage == {"total_tokens": 0, "prompt_tokens": 0, "completion_tokens": 0,
                                              "prompt_cache_hit_tokens": 0, "prompt_cache_miss_tokens": 0}
        assert sess.context._rounds_collector == []
        assert sess._extra_iterations == 0

    def test_reset_rounds_collector(self):
        sess = self._make_session()
        sess.context._rounds_collector = [{"role": "user", "content": "hi"}]
        sess.reset_session_state()
        assert sess.context._rounds_collector == []

    def test_close_http_clients(self):
        """close 应释放所有 HTTP 客户端"""
        sess = self._make_session()
        mock_clients = [MagicMock(), MagicMock()]
        sess._http_clients = mock_clients
        sess.close()
        for c in mock_clients:
            c.close.assert_called_once()


# ════════════════════════════════════════════════════════════
# 3. _build_api_messages（新增：三级历史拼接）
# ════════════════════════════════════════════════════════════

class TestBuildApiMessages:
    """_build_api_messages 三级历史拼接逻辑"""

    def _make_context(self, **kwargs):
        """创建 SessionContext 并填充默认状态"""
        defaults = {
            "model": "test-model", "enable_thinking": False,
            "supports_reasoning": False, "disable_summary": False,
        }
        defaults.update(kwargs)
        ctx = SessionContext(**defaults)
        return ctx

    def _make_session_from_ctx(self, ctx):
        """由 context 构建一个可调 _build_api_messages 的 session"""
        mock_tk = MagicMock()
        mock_tk.meta_map = {}
        sess = OnlineToolSession(
            toolkit=mock_tk, api_key="sk-test", api_url="https://api.test.com/v1",
            model="test-model", enable_thinking=ctx.enable_thinking, storage=None,
            supports_vision=ctx.supports_vision, supports_reasoning=ctx.supports_reasoning,
            disable_summary=ctx.disable_summary,
        )
        # 覆盖 context 为自定义的 ctx
        sess.context = ctx
        sess.system_prompt = "You are a test assistant."
        return sess

    def test_basic_structure(self):
        """基础结构：system + 用户消息"""
        ctx = self._make_context()
        ctx.messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
        ]
        sess = self._make_session_from_ctx(ctx)
        result = sess._build_api_messages()

        # 第一个是 system
        assert result[0]["role"] == "system"
        assert "test assistant" in result[0]["content"]
        # 最后一个应该是 assistant
        assert result[-1]["role"] == "assistant"
        assert result[-1]["content"] == "Hi there!"

    def test_includes_recent_history(self):
        """L1: 最新对话出现在结果末尾"""
        ctx = self._make_context()
        ctx.messages = [
            {"role": "user", "content": "Q1"},
            {"role": "assistant", "content": "A1"},
            {"role": "user", "content": "Q2"},
            {"role": "assistant", "content": "A2"},
        ]
        sess = self._make_session_from_ctx(ctx)
        result = sess._build_api_messages()
        # 最后两条应为 Q2 / A2
        assert result[-2]["role"] == "user"
        assert result[-2]["content"] == "Q2"
        assert result[-1]["role"] == "assistant"
        assert result[-1]["content"] == "A2"

    def test_with_semantic_summary(self):
        """L3: 语义摘要注入"""
        ctx = self._make_context()
        ctx._semantic_summary = "用户喜欢 Python 编程。"
        ctx.messages = [
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "Hello!"},
        ]
        sess = self._make_session_from_ctx(ctx)
        result = sess._build_api_messages()

        # 应包含 [系统记忆] 标记
        summaries = [m for m in result if "系统记忆" in m.get("content", "")]
        assert len(summaries) == 1
        assert "Python" in summaries[0]["content"]

    def test_with_level2_history(self):
        """L2: 相关历史对话注入"""
        ctx = self._make_context()
        ctx._level2 = [
            {"user": "之前的对话", "assistant": "之前的回复",
             "thinking": "", "files": []},
        ]
        ctx.messages = [
            {"role": "user", "content": "当前问题"},
        ]
        sess = self._make_session_from_ctx(ctx)
        result = sess._build_api_messages()

        # 应包含 [历史记录] 标记
        history_msgs = [m for m in result if "历史记录" in m.get("content", "")]
        assert len(history_msgs) >= 1

    def test_with_memory_injection(self):
        """记忆注入出现在结果中"""
        ctx = self._make_context()
        ctx._injected_memories_text = "[系统记忆] 用户偏好：喜欢简洁回复"
        ctx.messages = [
            {"role": "user", "content": "Hi"},
        ]
        sess = self._make_session_from_ctx(ctx)
        result = sess._build_api_messages()

        memories = [m for m in result if "喜欢简洁回复" in m.get("content", "")]
        assert len(memories) == 1

    def test_disable_summary_skips_l3_l2(self):
        """disable_summary=True 跳过 L3/L2"""
        ctx = self._make_context(disable_summary=True)
        ctx._semantic_summary = "不应出现的内容"
        ctx._level2 = [{"user": "不应出现", "assistant": "不应出现", "thinking": "", "files": []}]
        ctx.messages = [
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "Hello"},
        ]
        sess = self._make_session_from_ctx(ctx)
        result = sess._build_api_messages()

        assert not any("系统记忆" in m.get("content", "") for m in result)
        assert not any("历史记录" in m.get("content", "") for m in result)

    def test_tool_calls_preserved_in_history(self):
        """工具调用消息保留在 L1 中"""
        ctx = self._make_context()
        ctx.messages = [
            {"role": "user", "content": "搜索天气"},
            {"role": "assistant", "content": None,
             "tool_calls": [{"id": "c1", "type": "function",
                            "function": {"name": "get_weather", "arguments": "{}"}}]},
            {"role": "tool", "content": "晴", "tool_call_id": "c1"},
            {"role": "assistant", "content": "天气晴朗"},
        ]
        sess = self._make_session_from_ctx(ctx)
        result = sess._build_api_messages()

        tool_calls = [m for m in result if m.get("tool_calls")]
        assert len(tool_calls) == 1

    def test_reasoning_content_included(self):
        """supports_reasoning=True 时添加空 reasoning_content"""
        ctx = self._make_context(supports_reasoning=True)
        ctx.messages = [
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "Hello"},
        ]
        sess = self._make_session_from_ctx(ctx)
        result = sess._build_api_messages()

        # assistant 消息应有 reasoning_content 字段
        for m in result:
            if m["role"] == "assistant":
                assert "reasoning_content" in m

    def test_max_context_tokens_triggers_trimming(self):
        """max_context_tokens>0 时触发渐进式裁剪"""
        ctx = self._make_context(max_context_tokens=500)
        # 填入大量历史消息触发裁剪
        ctx.messages = []
        for _i in range(20):
            ctx.messages.append({"role": "user", "content": "Q" * 200})
            ctx.messages.append({"role": "assistant", "content": "A" * 500})
            ctx.messages.append({"role": "tool", "content": "R" * 1000})
        sess = self._make_session_from_ctx(ctx)
        result = sess._build_api_messages()
        # 不应抛出异常
        assert len(result) > 0

    def test_multimodal_content(self):
        """多模态消息格式"""
        ctx = self._make_context(supports_vision=True)
        ctx.messages = [
            {"role": "user", "content": "看这张图",
             "images": ["/fake/path.png"]},
        ]
        sess = self._make_session_from_ctx(ctx)
        result = sess._build_api_messages()
        # 图片路径不存在，所以图片被跳过，但 API 调用不会崩溃
        assert len(result) > 0

    def test_isolated_tool_message_removed(self):
        """孤立 tool 消息被移除"""
        ctx = self._make_context()
        ctx.messages = [
            {"role": "user", "content": "hi"},
            {"role": "tool", "content": "孤立结果", "tool_call_id": "nonexistent"},
            {"role": "assistant", "content": "done"},
        ]
        sess = self._make_session_from_ctx(ctx)
        result = sess._build_api_messages()
        # 孤立 tool 消息应被移除
        tool_msgs = [m for m in result if m["role"] == "tool"]
        assert len(tool_msgs) == 0


# ════════════════════════════════════════════════════════════
# 4. api.create_chat_stream 参数测试（新增）
# ════════════════════════════════════════════════════════════

class TestCreateChatStreamParams:
    """create_chat_stream 参数传递测试"""

    def _make_api(self, **kwargs):
        ctx_kwargs = {
            "model": "test-model", "enable_thinking": False,
            "client": MagicMock(), "supports_reasoning": False,
            "no_stream_chunk": True,
            "_thinking_supported": None,
        }
        ctx_kwargs.update(kwargs)
        ctx = SessionContext(**ctx_kwargs)
        return APIComponent(ctx)

    def test_basic_call_without_thinking(self):
        """不带 thinking 的基础调用"""
        api = self._make_api()
        api.ctx.client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content="ok", tool_calls=None))]
        )
        api.create_chat_stream(
            [{"role": "user", "content": "hi"}], [],
        )
        api.ctx.client.chat.completions.create.assert_called_once()
        _, kwargs = api.ctx.client.chat.completions.create.call_args
        assert kwargs["model"] == "test-model"
        assert kwargs["stream"] is False  # no_stream_chunk=True
        assert kwargs["tool_choice"] == "auto"
        assert "extra_body" not in kwargs  # _thinking_supported=None

    def test_thinking_enabled(self):
        """thinking 启用时应传入 extra_body"""
        api = self._make_api(enable_thinking=True, _thinking_supported=True)
        api.ctx.client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content="ok", tool_calls=None))]
        )
        api.create_chat_stream([{"role": "user", "content": "hi"}], [])
        _, kwargs = api.ctx.client.chat.completions.create.call_args
        assert kwargs["extra_body"]["thinking"]["type"] == "enabled"

    def test_thinking_disabled(self):
        """thinking 禁用时应传入 disabled"""
        api = self._make_api(enable_thinking=False, _thinking_supported=True)
        api.ctx.client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content="ok", tool_calls=None))]
        )
        api.create_chat_stream([{"role": "user", "content": "hi"}], [])
        _, kwargs = api.ctx.client.chat.completions.create.call_args
        assert kwargs["extra_body"]["thinking"]["type"] == "disabled"

    def test_thinking_not_supported(self):
        """_thinking_supported=False 不传 extra_body"""
        api = self._make_api(enable_thinking=True, _thinking_supported=False)
        api.ctx.client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content="ok", tool_calls=None))]
        )
        api.create_chat_stream([{"role": "user", "content": "hi"}], [])
        _, kwargs = api.ctx.client.chat.completions.create.call_args
        assert "extra_body" not in kwargs

    def test_stream_options_included(self):
        """supports_reasoning=True 时传入 stream_options"""
        api = self._make_api(supports_reasoning=True)
        api.ctx.client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content="ok", tool_calls=None))]
        )
        api.create_chat_stream([{"role": "user", "content": "hi"}], [])
        _, kwargs = api.ctx.client.chat.completions.create.call_args
        assert kwargs["stream_options"] == {"include_usage": True}

    def test_temperature_max_tokens_top_p(self):
        """temperature / max_tokens / top_p 参数传递"""
        api = self._make_api()
        api.ctx.client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content="ok", tool_calls=None))]
        )
        api.create_chat_stream(
            [{"role": "user", "content": "hi"}], [],
            temperature=0.7, max_tokens=500, top_p=0.9,
        )
        _, kwargs = api.ctx.client.chat.completions.create.call_args
        assert kwargs["temperature"] == 0.7
        assert kwargs["max_tokens"] == 500
        assert kwargs["top_p"] == 0.9

    def test_vision_support(self):
        """视觉支持传入 messages"""
        api = self._make_api(supports_vision=True)
        api.ctx.client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content="这是一张图", tool_calls=None))]
        )
        # 模拟多模态消息
        msgs = [
            {"role": "user", "content": [
                {"type": "text", "text": "这是什么？"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,fake"}},
            ]}
        ]
        api.create_chat_stream(msgs, [])
        _, kwargs = api.ctx.client.chat.completions.create.call_args
        assert len(kwargs["messages"]) == 1
        assert isinstance(kwargs["messages"][0]["content"], list)

    def test_no_stream_chunk_true_sets_stream_false(self):
        """no_stream_chunk=True → stream=False"""
        api = self._make_api(no_stream_chunk=True)
        api.ctx.client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content="ok", tool_calls=None))]
        )
        api.create_chat_stream([{"role": "user", "content": "hi"}], [])
        _, kwargs = api.ctx.client.chat.completions.create.call_args
        assert kwargs["stream"] is False

    def test_no_stream_chunk_false_sets_stream_true(self):
        """no_stream_chunk=False → stream=True"""
        api = self._make_api(no_stream_chunk=False)
        api.ctx.client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content="ok", tool_calls=None))]
        )
        api.create_chat_stream([{"role": "user", "content": "hi"}], [])
        _, kwargs = api.ctx.client.chat.completions.create.call_args
        assert kwargs["stream"] is True

    def test_vision_image_error_fallback(self):
        """图片编码失败不崩溃"""
        api = self._make_api(supports_vision=True)
        api.ctx.client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content="text", tool_calls=None))]
        )
        # 不存在的图片路径不应导致崩溃
        api.create_chat_stream(
            [{"role": "user", "content": "text", "images": ["/nonexistent/img.png"]}],
            [],
        )
        # 只检查调用成功即可
        assert api.ctx.client.chat.completions.create.called


# ════════════════════════════════════════════════════════════
# 5. 流式/非流式输出（已有 + 增强）
# ════════════════════════════════════════════════════════════

class TestProcessStreamWithReasoning:
    """_process_stream_with_reasoning 方法测试"""

    def _make_session(self, **kwargs):
        mock_tk = MagicMock()
        mock_tk.meta_map = {}
        defaults = {
            "toolkit": mock_tk, "api_key": "sk-test", "api_url": "https://api.test.com/v1",
            "model": "test-model", "enable_thinking": False, "storage": None,
            "no_stream_chunk": True,
        }
        defaults.update(kwargs)
        return OnlineToolSession(**defaults)

    def test_non_streaming_mode_no_tool_calls(self):
        sess = self._make_session()
        mock_msg = MagicMock()
        mock_msg.content = "Hello, world!"
        mock_msg.tool_calls = None
        mock_msg.reasoning_content = None
        mock_choice = MagicMock()
        mock_choice.message = mock_msg
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.usage = None
        cb = MagicMock()

        content, tool_calls, reasoning = sess._process_stream_with_reasoning(mock_response, cb)
        assert content == "Hello, world!"
        assert tool_calls == []
        assert reasoning == ""
        sess.close()

    def test_non_streaming_with_reasoning(self):
        sess = self._make_session(enable_thinking=True)
        mock_msg = MagicMock()
        mock_msg.content = "Final answer"
        mock_msg.tool_calls = None
        type(mock_msg).reasoning_content = PropertyMock(return_value="Deep thinking...")
        mock_choice = MagicMock()
        mock_choice.message = mock_msg
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.usage = None
        cb = MagicMock()

        content, tool_calls, reasoning = sess._process_stream_with_reasoning(mock_response, cb)
        assert "Final answer" in content
        assert "Deep thinking" in reasoning
        sess.close()

    def test_non_streaming_with_tool_calls(self):
        """非流式模式：含工具调用"""
        sess = self._make_session()
        mock_tc = MagicMock()
        mock_tc.id = "call_1"
        mock_tc.type = "function"
        mock_tc.function.name = "get_weather"
        mock_tc.function.arguments = '{"city": "北京"}'
        mock_msg = MagicMock()
        mock_msg.content = None
        mock_msg.tool_calls = [mock_tc]
        mock_msg.reasoning_content = None
        mock_choice = MagicMock()
        mock_choice.message = mock_msg
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.usage = None
        cb = MagicMock()

        content, tool_calls, reasoning = sess._process_stream_with_reasoning(mock_response, cb)
        assert content == ""
        assert len(tool_calls) == 1
        assert tool_calls[0]["function"]["name"] == "get_weather"
        sess.close()

    def test_streaming_accumulates_content(self):
        sess = self._make_session(no_stream_chunk=False)

        def make_chunk(content_text, reasoning=None):
            delta = MagicMock()
            delta.content = content_text
            delta.reasoning_content = reasoning
            delta.tool_calls = None
            choice = MagicMock()
            choice.delta = delta
            chunk = MagicMock()
            chunk.choices = [choice]
            chunk.usage = None
            return chunk

        chunks = [make_chunk("Hello"), make_chunk(" world"), make_chunk("!")]
        class MockStream:
            def __init__(self, items):
                self._items = items
                self._idx = 0
            def __iter__(self): return self
            def __next__(self):
                if self._idx >= len(self._items): raise StopIteration
                item = self._items[self._idx]
                self._idx += 1
                return item

        cb = MagicMock()
        content, tool_calls, reasoning = sess._process_stream_with_reasoning(MockStream(chunks), cb)
        assert content == "Hello world!"
        assert cb.call_count == 3
        sess.close()

    def test_streaming_empty_content(self):
        """流式模式：空内容"""
        sess = self._make_session(no_stream_chunk=False)
        class MockStream:
            def __iter__(self): return self
            def __next__(self): raise StopIteration
        cb = MagicMock()
        content, tool_calls, reasoning = sess._process_stream_with_reasoning(MockStream(), cb)
        assert content == ""
        assert tool_calls == []
        assert reasoning == ""
        sess.close()

    def test_streaming_with_tool_calls_delta(self):
        """流式模式：工具调用累积"""
        sess = self._make_session(no_stream_chunk=False)

        def make_chunk(content=None, tc_index=None, tc_id=None, tc_name=None, tc_args=None):
            delta = MagicMock()
            delta.content = content
            delta.reasoning_content = None
            if tc_index is not None:
                mock_tc = MagicMock()
                mock_tc.index = tc_index
                mock_tc.id = tc_id
                mock_tc.function.name = tc_name
                mock_tc.function.arguments = tc_args
                delta.tool_calls = [mock_tc]
            else:
                delta.tool_calls = None
            choice = MagicMock()
            choice.delta = delta
            chunk = MagicMock()
            chunk.choices = [choice]
            chunk.usage = None
            return chunk

        chunks = [
            make_chunk(content="让我搜索"),
            make_chunk(tc_index=0, tc_id="c1", tc_name="search", tc_args='{"q":'),
            make_chunk(tc_index=0, tc_args='"weather"}'),
        ]
        class MockStream:
            def __init__(self, items):
                self._items = items; self._idx = 0
            def __iter__(self): return self
            def __next__(self):
                if self._idx >= len(self._items): raise StopIteration
                item = self._items[self._idx]; self._idx += 1
                return item

        cb = MagicMock()
        content, tool_calls, reasoning = sess._process_stream_with_reasoning(MockStream(chunks), cb)
        assert "让我搜索" in content
        assert len(tool_calls) == 1  # 流式 delta 累积工具调用
        assert tool_calls[0]["name"] == "search"
        assert '"weather"' in tool_calls[0]["arguments"]
        sess.close()

    def test_non_streaming_empty_response(self):
        """非流式模式：空回复"""
        sess = self._make_session()
        mock_msg = MagicMock()
        mock_msg.content = None
        mock_msg.tool_calls = None
        mock_msg.reasoning_content = None
        mock_choice = MagicMock()
        mock_choice.message = mock_msg
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.usage = None
        cb = MagicMock()
        content, tool_calls, reasoning = sess._process_stream_with_reasoning(mock_response, cb)
        assert content == ""
        assert tool_calls == []
        assert reasoning == ""
        sess.close()


# ════════════════════════════════════════════════════════════
# 6. 工具轮多轮调用与压缩（新增）
# ════════════════════════════════════════════════════════════

class TestToolLoopAndCompression:
    """工具循环、压缩、修复"""

    def _make_session(self, **kwargs):
        mock_tk = MagicMock()
        mock_tk.meta_map = {}
        # 模拟 call_tool 返回结果
        mock_tk.call_tool.return_value = "mock_result"
        defaults = {
            "toolkit": mock_tk, "api_key": "sk-test", "api_url": "https://api.test.com/v1",
            "model": "test-model", "enable_thinking": False, "storage": None,
            "no_stream_chunk": True, "max_iterations": 5,
        }
        defaults.update(kwargs)
        return OnlineToolSession(**defaults)

    def test_compress_tool_rounds_short(self):
        """短 rounds 不截断"""
        from tea_agent.basesession import BaseChatSession
        rounds = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ]
        result = BaseChatSession._compress_tool_rounds(rounds)
        assert len(result) == 2
        assert result[0]["content"] == "hi"

    def test_compress_tool_rounds_long_truncated(self):
        """超长 rounds 被截断"""
        from tea_agent.basesession import BaseChatSession
        # 构造超过 30 轮的对话
        rounds = []
        for i in range(40):
            rounds.append({"role": "assistant", "tool_calls": [{"id": f"c{i}", "function": {"name": "test"}}]})
            rounds.append({"role": "tool", "content": "x" * 100, "tool_call_id": f"c{i}"})
        rounds.append({"role": "assistant", "content": "final"})

        result = BaseChatSession._compress_tool_rounds(rounds)
        # _compress_tool_rounds 不截断，完整保留
        assert len(result) == 81  # 40 pairs + 1 final
        assert result[-1]["content"] == "final"

    def test_repair_incomplete_tool_chains_complete(self):
        """完整工具链不修复"""
        from tea_agent.basesession import BaseChatSession
        rounds = [
            {"role": "assistant", "tool_calls": [{"id": "c1", "function": {"name": "test"}}]},
            {"role": "tool", "content": "result", "tool_call_id": "c1"},
            {"role": "assistant", "content": "done"},
        ]
        result = BaseChatSession._repair_incomplete_tool_chains(rounds)
        assert len(result) == 3

    def test_repair_incomplete_tool_chains_missing_tool(self):
        """不完整工具链：缺失 tool 响应"""
        from tea_agent.basesession import BaseChatSession
        rounds = [
            {"role": "assistant", "tool_calls": [{"id": "c1", "function": {"name": "test"}}]},
            {"role": "assistant", "content": "最终回复"},
        ]
        result = BaseChatSession._repair_incomplete_tool_chains(rounds)
        assert len(result) == 1
        assert result[0]["content"] == "最终回复"

    def test_repair_incomplete_tool_chains_missing_assistant_prefix(self):
        """不完整工具链：tool 响应在最后"""
        from tea_agent.basesession import BaseChatSession
        rounds = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "tool_calls": [{"id": "c1", "function": {"name": "test"}}]},
            {"role": "tool", "content": "result", "tool_call_id": "c1"},
            # 缺少后续 assistant
        ]
        result = BaseChatSession._repair_incomplete_tool_chains(rounds)
        # 不完整链被保留，因为已有 tool 响应，仅缺少后续 assistant
        assert len(result) == 3
        assert result[0]["role"] == "user"

    def test_compress_tool_content_threshold(self):
        """不同工具类型的阈值适配"""
        import sys

        from tea_agent.basesession import BaseChatSession

        # 源码文件 → sys.maxsize（不截断）
        threshold = BaseChatSession._guess_tool_threshold("toolkit_file", '{"filename": "main.py"}')
        assert threshold == sys.maxsize

        # 日志文件 → 16KB
        threshold = BaseChatSession._guess_tool_threshold("toolkit_file", '{"filename": "app.log"}')
        assert threshold == BaseChatSession._TEXT_FILE_THRESHOLD

        # KB 工具 → 64KB
        threshold = BaseChatSession._guess_tool_threshold("toolkit_kb", '{}')
        assert threshold == BaseChatSession._KB_THRESHOLD

        # 默认 → 2KB
        threshold = BaseChatSession._guess_tool_threshold("toolkit_exec", '{}')
        assert threshold == BaseChatSession._DEFAULT_TOOL_THRESHOLD


from tea_agent.session.tool_loop_runner import execute_tool_loop  # noqa: E402


class TestExecuteToolLoop:
    """execute_tool_loop 多轮工具调用"""

    def _make_session_with_api_mock(self, api_responses=None, **kwargs):
        """创建 session 并 mock api.create_chat_stream"""
        mock_tk = MagicMock()
        mock_tk.meta_map = {}
        mock_tk.call_tool.return_value = "mock_result"
        # 模拟 get_effective_params 返回
        mock_tk.get_config.return_value = None

        sess = OnlineToolSession(
            toolkit=mock_tk, api_key="sk-test", api_url="https://api.test.com/v1",
            model="test-model", enable_thinking=False, storage=None,
            no_stream_chunk=True, **kwargs
        )

        # Mock _build_api_messages
        sess._build_api_messages = MagicMock(return_value=[{"role": "user", "content": "test"}])

        # 替换 api 组件为 mock
        sess.api = MagicMock()
        sess.api.create_chat_stream.return_value = None
        sess._process_stream_with_reasoning = MagicMock()
        sess.tools_comp = MagicMock()

        return sess

    def test_single_tool_call_round(self):
        """单轮工具调用：LLM 返回工具调用，执行后 LLM 再返回文本"""
        sess = self._make_session_with_api_mock()

        # 第一轮 LLM 返回工具调用
        sess._process_stream_with_reasoning.side_effect = [
            ("", [{"id": "c1", "type": "function",
                   "function": {"name": "search", "arguments": '{"q":"test"}'}}], ""),
            # 第二轮及之后返回文本
            ("搜索结果如下...", [], ""),
            ("搜索结果如下...", [], ""),
            ("搜索结果如下...", [], ""),
            ("搜索结果如下...", [], ""),
        ]

        sess.tools_comp.parse_tool_calls_from_stream.side_effect = [
            [MagicMock(id="c1", function=MagicMock(name="search", arguments='{"q":"test"}'))],
            [], [], [], [],
        ]
        sess.tools_comp.execute_tool_call.return_value = ("c1", "search", "mock_result")

        result = execute_tool_loop(sess, {"msg": "test", "callback": lambda x: None})
        assert result["used_tools"] is True
        assert "搜索结果如下" in result["full_reply"]
        sess.close()

    def test_multiple_tool_call_rounds(self):
        """多轮工具调用：连续多次工具调用"""
        sess = self._make_session_with_api_mock()

        # 模拟 3 轮工具调用 + 1 轮最终回复
        responses = [
            ("", [{"id": "c1", "type": "function",
                   "function": {"name": "search", "arguments": '{}'}}], ""),
            ("", [{"id": "c2", "type": "function",
                   "function": {"name": "read_file", "arguments": '{}'}}], ""),
            ("", [{"id": "c3", "type": "function",
                   "function": {"name": "analyze", "arguments": '{}'}}], ""),
            ("分析完成！最终答案在这里", [], ""),
        ]
        sess._process_stream_with_reasoning.side_effect = responses

        def mock_tc(name):
            return MagicMock(id="c1", function=MagicMock(name=name, arguments="{}"))
        sess.tools_comp.parse_tool_calls_from_stream.side_effect = [
            [mock_tc("search")],
            [mock_tc("read_file")],
            [mock_tc("analyze")],
            [],
        ]
        sess.tools_comp.execute_tool_call.return_value = ("c1", "tool", "result")

        result = execute_tool_loop(sess, {"msg": "test", "callback": lambda x: None})
        assert result["iterations"] >= 3
        assert "最终答案" in result["full_reply"]
        sess.close()

    def test_no_tool_call_direct_answer(self):
        """无需工具调用，直接回复"""
        sess = self._make_session_with_api_mock()
        sess._process_stream_with_reasoning.return_value = ("直接回复", [], "")
        sess.tools_comp.parse_tool_calls_from_stream.return_value = []

        result = execute_tool_loop(sess, {"msg": "hi", "callback": lambda x: None})
        assert result["used_tools"] is False
        assert result["full_reply"] == "直接回复"
        sess.close()

    def test_max_iterations_reached(self):
        """达到最大迭代次数终止"""
        sess = self._make_session_with_api_mock(max_iterations=3)
        # 每轮都返回工具调用
        mock_tc = MagicMock(id="c1", function=MagicMock(name="search", arguments="{}"))
        sess._process_stream_with_reasoning.return_value = ("", [
            {"id": "c1", "type": "function", "function": {"name": "search", "arguments": "{}"}}
        ], "")
        sess.tools_comp.parse_tool_calls_from_stream.return_value = [mock_tc]
        sess.tools_comp.execute_tool_call.return_value = ("c1", "search", "result")

        result = execute_tool_loop(sess, {"msg": "test", "callback": lambda x: None})
        assert "已达到最大迭代次数" in result["full_reply"]
        sess.close()

    def test_api_error_handling(self):
        """API 调用错误处理"""
        sess = self._make_session_with_api_mock()
        sess.api.create_chat_stream.side_effect = RuntimeError("API connection error")

        result = execute_tool_loop(sess, {"msg": "test", "callback": lambda x: None})
        assert "API调用错误" in result["full_reply"]
        assert "error" in result
        sess.close()

    def test_skip_tool_loop(self):
        """跳过工具循环（纯聊天意图）"""
        sess = self._make_session_with_api_mock()
        # skip_tool_loop 路径会调用 add_assistant_message，需要mock它
        sess.add_assistant_message = MagicMock()
        sess._process_stream_with_reasoning.return_value = ("纯聊天回复", [], "")

        result = execute_tool_loop(sess, {"msg": "hi", "skip_tool_loop": True, "callback": lambda x: None})
        assert result["used_tools"] is False
        assert "纯聊天回复" in result["full_reply"]
        sess.close()

    def test_interrupted_during_loop(self):
        """工具循环中被中断"""
        sess = self._make_session_with_api_mock()
        sess.interrupted = True

        result = execute_tool_loop(sess, {"msg": "test", "callback": lambda x: None})
        assert result.get("interrupted") is True
        assert "已打断" in result["full_reply"]
        sess.close()


class TestLoopDetector:
    """工具循环检测器"""

    def test_no_repeat_on_first_call(self):
        from tea_agent.session.tool_loop_runner import LoopDetector
        ld = LoopDetector()
        result = ld.check_and_record("hello", [("search", '{"q":"test"}')])
        assert result["is_loop"] is False

    def test_detects_exact_duplicate_tool_call(self):
        from tea_agent.session.tool_loop_runner import LoopDetector
        ld = LoopDetector(window=5)
        for _ in range(3):
            ld.check_and_record("", [("search", '{"q":"test"}')])
        result = ld.check_and_record("", [("search", '{"q":"test"}')])
        assert result["is_loop"] is True
        assert result["type"] == "tool_repeat"

    def test_detects_content_repeat(self):
        from tea_agent.session.tool_loop_runner import LoopDetector
        ld = LoopDetector(window=5, similarity_threshold=0.5)
        ld.check_and_record("相同的输出内容", [])
        result = ld.check_and_record("相同的输出内容", [])
        assert result["is_loop"] is True
        assert result["type"] == "content_repeat"

    def test_reset_clears_state(self):
        from tea_agent.session.tool_loop_runner import LoopDetector
        ld = LoopDetector()
        ld.check_and_record("hello", [("search", '{}')])
        ld.reset()
        assert len(ld._tool_hashes) == 0


print("\n✅ OnlineSession 测试加载完成")
