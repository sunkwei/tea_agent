"""
测试 litesession 模块 — 轻量级会话

覆盖：
- LiteSession 初始化（参数传递、默认值）
- _default_system_prompt() 返回值
- _build_tools() 工具构建
- _parse_tool_calls() 工具调用解析
- _execute_tool() 工具执行
- interrupt() / close() 生命周期
- chat() 边界情况
"""

from unittest.mock import MagicMock, patch

import pytest

# ── Fixtures ──

@pytest.fixture
def mock_toolkit():
    """模拟 Toolkit 实例"""
    tk = MagicMock()
    tk.meta_map = {
        "toolkit_search": {
            "type": "function",
            "function": {
                "name": "toolkit_search",
                "description": "搜索工具",
                "parameters": {"type": "object", "properties": {}}
            }
        },
        "toolkit_exec": {
            "type": "function",
            "function": {
                "name": "toolkit_exec",
                "description": "执行命令",
                "parameters": {"type": "object", "properties": {}}
            }
        },
    }
    tk.call_tool.return_value = {"status": "ok", "output": "test_output"}
    return tk


@pytest.fixture
def lite_session(mock_toolkit):
    """创建 LiteSession 实例（mock OpenAI）"""
    with patch("tea_agent.litesession.OpenAI") as mock_openai:
        mock_client = MagicMock()
        mock_openai.return_value = mock_client
        from tea_agent.litesession import LiteSession
        session = LiteSession(
            toolkit=mock_toolkit,
            api_key="test-key",
            api_url="https://test.api.com/v1",
            model="test-model",
            system_prompt="你是测试助手。",
            enable_thinking=False,
            max_iterations=10,
            supports_reasoning=False,
        )
        yield session


# ── 初始化测试 ──

class TestLiteSessionInit:
    """初始化测试"""

    def test_init_basic_params(self, mock_toolkit):
        """基本参数传递"""
        with patch("tea_agent.litesession.OpenAI"):
            from tea_agent.litesession import LiteSession
            session = LiteSession(
                toolkit=mock_toolkit,
                api_key="test-key",
                api_url="https://api.test.com",
                model="gpt-4o",
            )
            assert session.model == "gpt-4o"
            assert session.enable_thinking is True  # 默认 True
            assert session.max_iterations == 50  # 默认 50
            assert session.supports_reasoning is True  # 默认 True
            assert session.interrupted is False
            assert session.system_prompt is not None
            assert len(session.tools) == 2  # 2 个 toolkit 工具

    def test_init_custom_params(self, mock_toolkit):
        """自定义参数"""
        with patch("tea_agent.litesession.OpenAI"):
            from tea_agent.litesession import LiteSession
            session = LiteSession(
                toolkit=mock_toolkit,
                api_key="test-key",
                api_url="https://api.test.com",
                model="gpt-4o-mini",
                system_prompt="自定义提示词",
                enable_thinking=True,
                max_iterations=100,
                supports_reasoning=True,
            )
            assert session.model == "gpt-4o-mini"
            assert session.system_prompt == "自定义提示词"
            assert session.enable_thinking is True
            assert session.max_iterations == 100

    def test_init_empty_system_prompt_uses_default(self, mock_toolkit):
        """空 system_prompt 应使用默认值"""
        with patch("tea_agent.litesession.OpenAI"):
            from tea_agent.litesession import LiteSession
            session = LiteSession(
                toolkit=mock_toolkit,
                api_key="test-key",
                api_url="https://api.test.com",
                model="test",
                system_prompt="",
            )
            assert "可自我扩展的智能Agent" in session.system_prompt

    def test_init_creates_openai_client(self, mock_toolkit):
        """应创建 OpenAI 客户端（含 API 弹性参数：timeout + max_retries）"""
        with patch("tea_agent.litesession.OpenAI") as mock_openai:
            from tea_agent.litesession import LiteSession
            LiteSession(
                toolkit=mock_toolkit,
                api_key="custom-key",
                api_url="https://custom.api.com",
                model="test",
            )
            mock_openai.assert_called_once_with(
                api_key="custom-key",
                base_url="https://custom.api.com",
                timeout=120.0,
                max_retries=3,
            )

    def test_init_without_toolkit(self):
        """toolkit 为 None 时不应报错"""
        with patch("tea_agent.litesession.OpenAI"):
            from tea_agent.litesession import LiteSession
            session = LiteSession(
                toolkit=None,
                api_key="test-key",
                api_url="https://api.test.com",
                model="test",
            )
            assert session.tools == []

    def test_init_both_filters(self, mock_toolkit):
        """both filters deprecated; all tools available."""
        with patch("tea_agent.litesession.OpenAI"):
            from tea_agent.litesession import LiteSession
            session = LiteSession(
                toolkit=mock_toolkit,
                api_key="k",
                api_url="https://api.test.com",
                model="m",
                allowed_tools=["toolkit_search", "toolkit_exec"],
                denied_tools=["toolkit_search"],
            )
            names = [t["function"]["name"] for t in session.tools]
            assert "toolkit_search" in names
            assert "toolkit_exec" in names

    def test_init_allowed_tools_none(self, mock_toolkit):
        """allowed_tools=None 应为不过滤"""
        with patch("tea_agent.litesession.OpenAI"):
            from tea_agent.litesession import LiteSession
            session = LiteSession(
                toolkit=mock_toolkit,
                api_key="k",
                api_url="https://api.test.com",
                model="m",
                allowed_tools=None,
                denied_tools=None,
            )
            assert len(session.tools) == 2
# ── 续写 test_litesession.py ──

class TestDefaultSystemPrompt:
    """_default_system_prompt() 测试"""

    def test_contains_keywords(self, lite_session):
        """默认提示词应包含关键描述"""
        prompt = lite_session._default_system_prompt()
        assert "可自我扩展的智能Agent" in prompt
        assert "toolkit_save" in prompt
        assert "toolkit_reload" in prompt
        assert "toolkit_exec" in prompt

    def test_not_empty(self, lite_session):
        """不应为空"""
        prompt = lite_session._default_system_prompt()
        assert len(prompt) > 50

    def test_no_placeholder_left(self, lite_session):
        """不应有未替换的占位符"""
        prompt = lite_session._default_system_prompt()
        assert "{{" not in prompt


class TestBuildTools:
    """_build_tools() 测试"""

    def test_returns_list(self, lite_session):
        """应返回列表"""
        tools = lite_session._build_tools()
        assert isinstance(tools, list)

    def test_contains_expected_tools(self, lite_session):
        """应包含 toolkit 中的工具"""
        tools = lite_session._build_tools()
        names = [t["function"]["name"] for t in tools]
        assert "toolkit_search" in names
        assert "toolkit_exec" in names

    def test_from_meta_map(self, lite_session):
        """应从 meta_map 构建"""
        tools = lite_session._build_tools()
        assert len(tools) == 2

    def test_empty_when_no_toolkit(self):
        """toolkit 为 None 时返回空列表"""
        with patch("tea_agent.litesession.OpenAI"):
            from tea_agent.litesession import LiteSession
            session = LiteSession(
                toolkit=None,
                api_key="k",
                api_url="https://api.test.com",
                model="m",
            )
            assert session._build_tools() == []

    def test_meta_missing_function_skipped(self, mock_toolkit):
        """meta 中没有 function 键时跳过"""
        mock_toolkit.meta_map = {
            "toolkit_bad": {"type": "function"},
        }
        with patch("tea_agent.litesession.OpenAI"):
            from tea_agent.litesession import LiteSession
            session = LiteSession(
                toolkit=mock_toolkit,
                api_key="k",
                api_url="https://api.test.com",
                model="m",
            )
            assert len(session.tools) == 0

    def test_non_toolkit_prefix_skipped(self, mock_toolkit):
        """不以 toolkit_ 开头的 key 应跳过"""
        mock_toolkit.meta_map = {
            "other_func": {"function": {"name": "other"}},
        }
        with patch("tea_agent.litesession.OpenAI"):
            from tea_agent.litesession import LiteSession
            session = LiteSession(
                toolkit=mock_toolkit,
                api_key="k",
                api_url="https://api.test.com",
                model="m",
            )
            assert len(session.tools) == 0


class TestParseToolCalls:
    """_parse_tool_calls() 测试"""

    def test_empty_dict_returns_empty(self, lite_session):
        """空字典应返回空列表"""
        result = lite_session._parse_tool_calls({})
        assert result == []

    def test_valid_tool_call(self, lite_session):
        """有效的工具调用应被解析"""
        data = {
            0: {
                "id": "call_123",
                "name": "toolkit_search",
                "arguments": '{"query": "hello"}'
            }
        }
        result = lite_session._parse_tool_calls(data)
        assert len(result) == 1
        assert result[0].id == "call_123"
        assert result[0].function.name == "toolkit_search"
        assert result[0].function.arguments == '{"query": "hello"}'

    def test_multiple_tool_calls(self, lite_session):
        """多个工具调用"""
        data = {
            0: {"id": "call_1", "name": "toolkit_search", "arguments": '{"q": "a"}'},
            1: {"id": "call_2", "name": "toolkit_exec", "arguments": '{"cmd": "ls"}'},
        }
        result = lite_session._parse_tool_calls(data)
        assert len(result) == 2

    def test_invalid_json_arguments_skipped(self, lite_session):
        """无效 JSON 参数应跳过"""
        data = {
            0: {
                "id": "call_1",
                "name": "toolkit_search",
                "arguments": "invalid json{{{"
            }
        }
        result = lite_session._parse_tool_calls(data)
        assert result == []

    def test_missing_id_skipped(self, lite_session):
        """缺少 id 应跳过"""
        data = {
            0: {"id": "", "name": "toolkit_search", "arguments": "{}"}
        }
        result = lite_session._parse_tool_calls(data)
        assert result == []

    def test_missing_name_skipped(self, lite_session):
        """缺少 name 应跳过"""
        data = {
            0: {"id": "call_1", "name": "", "arguments": "{}"}
        }
        result = lite_session._parse_tool_calls(data)
        assert result == []

    def test_mixed_valid_invalid(self, lite_session):
        """混合有效和无效的调用"""
        data = {
            0: {"id": "call_1", "name": "toolkit_search", "arguments": '{"q": "a"}'},
            1: {"id": "", "name": "", "arguments": ""},
            2: {"id": "call_3", "name": "toolkit_exec", "arguments": "bad json"},
        }
        result = lite_session._parse_tool_calls(data)
        assert len(result) == 1
        assert result[0].id == "call_1"

    def test_sorted_by_index(self, lite_session):
        """应按 index 排序"""
        data = {
            3: {"id": "c3", "name": "toolkit_exec", "arguments": "{}"},
            0: {"id": "c0", "name": "toolkit_search", "arguments": "{}"},
        }
        result = lite_session._parse_tool_calls(data)
        assert result[0].id == "c0"
        assert result[1].id == "c3"


class TestExecuteTool:
    """_execute_tool() 测试"""

    def test_execute_calls_toolkit(self, lite_session, mock_toolkit):
        """应调用 toolkit.call_tool"""
        from dataclasses import dataclass
        @dataclass
        class FakeCall:
            id: str = "call_1"
            function: object = None

        @dataclass
        class FakeFunc:
            name: str = "toolkit_search"
            arguments: str = '{"query": "hello"}'

        call = FakeCall(function=FakeFunc())
        call_id, func_name, result = lite_session._execute_tool(call)
        assert call_id == "call_1"
        assert func_name == "toolkit_search"
        mock_toolkit.call_tool.assert_called_once_with(
            "toolkit_search", query="hello"
        )

    def test_execute_with_empty_args(self, lite_session, mock_toolkit):
        """空参数应传空 dict"""
        from dataclasses import dataclass
        @dataclass
        class FakeCall:
            id: str = "call_2"
            function: object = None

        call = FakeCall()
        call.function = type('FakeFunc', (), {'name': 'toolkit_search', 'arguments': ''})()
        lite_session._execute_tool(call)
        mock_toolkit.call_tool.assert_called_once_with("toolkit_search")

    def test_execute_with_invalid_json_args(self, lite_session, mock_toolkit):
        """无效 JSON 参数应传空 dict"""
        from dataclasses import dataclass
        @dataclass
        class FakeCall:
            id: str = "call_3"
            function: object = None

        call = FakeCall()
        call.function = type('FakeFunc', (), {'name': 'toolkit_search', 'arguments': 'not json'})()
        lite_session._execute_tool(call)
        mock_toolkit.call_tool.assert_called_once_with("toolkit_search")

    def test_execute_toolkit_raises(self, lite_session, mock_toolkit):
        """工具执行异常应返回错误字符串"""
        mock_toolkit.call_tool.side_effect = RuntimeError("工具崩溃")
        from dataclasses import dataclass
        @dataclass
        class FakeCall:
            id: str = "call_4"
            function: object = None

        call = FakeCall()
        call.function = type('FakeFunc', (), {'name': 'toolkit_search', 'arguments': '{}'})()
        call_id, func_name, result = lite_session._execute_tool(call)
        assert "工具执行错误" in result or "工具崩溃" in result


class TestInterruptAndClose:
    """interrupt() 和 close() 测试"""

    def test_interrupt_sets_flag(self, lite_session):
        """interrupt() 应设置 interrupted=True"""
        assert lite_session.interrupted is False
        lite_session.interrupt()
        assert lite_session.interrupted is True

    def test_close_releases_client(self, lite_session):
        """close() 应调用 API 客户端的 close 方法"""
        lite_session.close()
        lite_session.api.close.assert_called_once()

    def test_close_without_api(self, mock_toolkit):
        """没有 API 客户端时 close 不应报错"""
        with patch("tea_agent.litesession.OpenAI") as mock_openai:
            mock_client = MagicMock()
            mock_client.close.side_effect = AttributeError("no close")
            mock_openai.return_value = mock_client
            from tea_agent.litesession import LiteSession
            session = LiteSession(
                toolkit=mock_toolkit,
                api_key="k",
                api_url="https://api.test.com",
                model="m",
            )
            session.close()  # 不应抛出异常


class TestChatEdgeCases:
    """chat() 边界情况测试"""

    def test_chat_returns_dict_with_keys(self, lite_session):
        """chat 返回字典应包含所需字段"""
        mock_chunk = MagicMock()
        mock_chunk.choices = [MagicMock()]
        mock_chunk.choices[0].delta.content = "你好，我是助手"
        mock_chunk.choices[0].delta.reasoning_content = None
        mock_chunk.choices[0].delta.tool_calls = None
        mock_chunk.choices[0].finish_reason = "stop"
        lite_session.api.chat.completions.create.return_value = [mock_chunk]
        result = lite_session.chat("你好")
        assert isinstance(result, dict)
        assert "user" in result
        assert "thinking" in result
        assert "assistant" in result
        assert "tool_calls" in result
        assert "error" in result

    def test_chat_returns_user_input(self, lite_session):
        """返回的 user 字段应与输入一致"""
        mock_chunk = MagicMock()
        mock_chunk.choices = [MagicMock()]
        mock_chunk.choices[0].delta.content = "回答"
        mock_chunk.choices[0].delta.reasoning_content = None
        mock_chunk.choices[0].delta.tool_calls = None
        lite_session.api.chat.completions.create.return_value = [mock_chunk]
        result = lite_session.chat("测试输入")
        assert result["user"] == "测试输入"

    def test_chat_api_error_returns_error(self, lite_session):
        """API 异常应返回 error 字段"""
        lite_session.api.chat.completions.create.side_effect = \
            Exception("API 连接失败")
        result = lite_session.chat("你好")
        assert result["error"] is not None
        assert "API 连接失败" in result["error"]

    def test_chat_empty_input(self, lite_session):
        """空输入不应导致崩溃"""
        mock_chunk = MagicMock()
        mock_chunk.choices = [MagicMock()]
        mock_chunk.choices[0].delta.content = ""
        mock_chunk.choices[0].delta.reasoning_content = None
        mock_chunk.choices[0].delta.tool_calls = None
        lite_session.api.chat.completions.create.return_value = [mock_chunk]
        result = lite_session.chat("")
        assert result["error"] is None
        assert result["user"] == ""

    def test_chat_interrupted(self, lite_session):
        """中断后 chat 应安全退出"""
        lite_session.interrupt()
        result = lite_session.chat("你好")
        assert result["error"] is None

    def test_chat_with_callback(self, lite_session):
        """callback 应被调用"""
        calls = []
        def cb(text):
            calls.append(text)
        mock_chunk = MagicMock()
        mock_chunk.choices = [MagicMock()]
        mock_chunk.choices[0].delta.content = "Hi"
        mock_chunk.choices[0].delta.reasoning_content = None
        mock_chunk.choices[0].delta.tool_calls = None
        lite_session.api.chat.completions.create.return_value = [mock_chunk]
        lite_session.chat("hello", callback=cb)
        assert len(calls) > 0

    def test_chat_zero_tool_calls_count(self, lite_session):
        """无工具调用时 tool_calls 应为 0"""
        mock_chunk = MagicMock()
        mock_chunk.choices = [MagicMock()]
        mock_chunk.choices[0].delta.content = "直接回答"
        mock_chunk.choices[0].delta.reasoning_content = None
        mock_chunk.choices[0].delta.tool_calls = None
        lite_session.api.chat.completions.create.return_value = [mock_chunk]
        result = lite_session.chat("hi")
        assert result["tool_calls"] == 0


# ── reasoning 字段兼容（vLLM 思考模式 `reasoning` 字段）──

class TestReasoningFieldCompat:
    """思考字段兼容：vLLM 思考模式（Qwen3.8 等）返回 `reasoning`，
    兼容端点返回 `reasoning_content`，两者都应被提取（回归：此前 vLLM 的
    `reasoning` 字段被静默丢弃，UI 看不到思考过程）"""

    def test_chat_reasoning_field_vllm(self, lite_session):
        """delta 只有 `reasoning` 字段 → 累积进 thinking 且回调输出"""
        calls: list = []
        mock_chunk = MagicMock()
        mock_chunk.choices = [MagicMock()]
        mock_chunk.choices[0].delta.content = "17×23=391"
        mock_chunk.choices[0].delta.reasoning_content = None
        mock_chunk.choices[0].delta.reasoning = "让我思考: 17*20=340, 17*3=51"
        mock_chunk.choices[0].delta.tool_calls = None
        lite_session.api.chat.completions.create.return_value = [mock_chunk]
        result = lite_session.chat("17*23=?", callback=lambda t: calls.append(t))
        assert result["thinking"] == "让我思考: 17*20=340, 17*3=51"
        assert any("让我思考" in c for c in calls)
        assert result["assistant"] == "17×23=391"
        assert result["error"] is None

    def test_chat_reasoning_content_field_still_works(self, lite_session):
        """`reasoning_content` 字段（DeepSeek 等）不受影响"""
        mock_chunk = MagicMock()
        mock_chunk.choices = [MagicMock()]
        mock_chunk.choices[0].delta.content = "Hi"
        mock_chunk.choices[0].delta.reasoning_content = "深度思考过程"
        mock_chunk.choices[0].delta.tool_calls = None
        lite_session.api.chat.completions.create.return_value = [mock_chunk]
        result = lite_session.chat("Hi")
        assert result["thinking"] == "深度思考过程"

    def test_chat_reasoning_prefers_reasoning_content(self, lite_session):
        """两字段同时存在时优先 reasoning_content"""
        mock_chunk = MagicMock()
        mock_chunk.choices = [MagicMock()]
        mock_chunk.choices[0].delta.content = ""
        mock_chunk.choices[0].delta.reasoning_content = "来自 RC"
        mock_chunk.choices[0].delta.reasoning = "来自 reasoning"
        mock_chunk.choices[0].delta.tool_calls = None
        lite_session.api.chat.completions.create.return_value = [mock_chunk]
        result = lite_session.chat("Hi")
        assert result["thinking"] == "来自 RC"

    def test_chat_unmocked_reasoning_attr_no_false_positive(self, lite_session):
        """MagicMock 自动生成的非字符串属性不得误判为思考（防止拼接崩溃）"""
        mock_chunk = MagicMock()
        mock_chunk.choices = [MagicMock()]
        mock_chunk.choices[0].delta.content = "直接回复"
        # 不显式设置 reasoning_content/reasoning
        mock_chunk.choices[0].delta.tool_calls = None
        lite_session.api.chat.completions.create.return_value = [mock_chunk]
        result = lite_session.chat("Hi")
        assert result["thinking"] == ""
        assert result["error"] is None
        assert result["assistant"] == "直接回复"


# ── _call_api reasoning_effort 值域钳制测试 ──

class TestCallApiReasoningEffort:
    """_call_api reasoning_effort 值域钳制（400 回归：qwen3.8 仅接受 xhigh/medium/low）"""

    def _make_session(self, **kwargs):
        with patch("tea_agent.litesession.OpenAI") as mock_openai:
            mock_openai.return_value = MagicMock()
            from tea_agent.litesession import LiteSession

            tk = MagicMock()
            tk.meta_map = {}
            base = dict(
                toolkit=tk,
                api_key="test-key",
                api_url="https://test.api.com/v1",
                model="qwen3.8-27b",
                enable_thinking=True,
                supports_reasoning=True,
            )
            base.update(kwargs)
            return LiteSession(**base)

    def _call(self, session):
        """拦截 call_with_retry，捕获实际下发的 kwargs"""
        captured = {}

        def fake_call_with_retry(fn, **kw):
            captured.update(kw)
            return MagicMock()

        with patch("tea_agent.api_retry.call_with_retry", side_effect=fake_call_with_retry):
            session._call_api([{"role": "user", "content": "hi"}])
        return captured

    def test_qwen38_strength_high_clamped_to_xhigh(self):
        """strength 0.7 → high → 对 qwen3.8 钳制为 xhigh"""
        session = self._make_session()
        captured = self._call(session)
        assert captured["extra_body"]["reasoning_effort"] == "xhigh"

    def test_qwen38_explicit_medium_passthrough(self):
        """qwen3.8 值域内的显式 medium 不钳制"""
        session = self._make_session(reasoning_effort="medium")
        captured = self._call(session)
        assert captured["extra_body"]["reasoning_effort"] == "medium"

    def test_deepseek_v4_high_not_clamped(self):
        """deepseek-v4 接受全值域：high 原样通过"""
        session = self._make_session(model="deepseek-v4-flash")
        captured = self._call(session)
        assert captured["extra_body"]["reasoning_effort"] == "high"
