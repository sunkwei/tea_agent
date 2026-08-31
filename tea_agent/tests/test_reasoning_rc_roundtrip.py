"""
reasoning_content 完整回传链路回归测试（DeepSeek V4 thinking 模式 400 根治）。

覆盖三处新增防线：
1. `_load_single_conversation`：非工具轮次（is_func_calling=False）有 rounds 时
   必须保留 reasoning_content —— 纯文本轮在思考模式同样产出 RC，按 ai_msg 重建
   会丢 RC，恢复会话后触发 400 "must be passed back"。
2. `create_chat_stream` 发送前防御性补全：thinking 模式 + 带 tools 的请求，
   任何 assistant 消息缺 reasoning_content 字段都自动补空串（兜底所有旁路）。
3. `tool_loop_runner` RC 400 自愈：检测到该 400 后记录诊断、强制关闭 thinking
   重试，置 ctx._rc400_recovery 使本回合剩余请求保持降级，对话不再中断。

背景：DeepSeek 官方文档 —— 「for requests carrying the tools parameter, the
reasoning_content must be fully passed back to the API in all subsequent requests」。
字段缺失/值丢失/截断均触发 400：
  The reasoning_content in the thinking mode must be passed back to the API.
"""
from unittest.mock import MagicMock

import pytest

from tea_agent.basesession import BaseChatSession
from tea_agent.onlinesession import APIComponent, OnlineToolSession
from tea_agent.session.context import SessionContext
from tea_agent.session.tool_loop_runner import (
    _is_rc_passed_back_error,
    execute_tool_loop,
)


# ════════════════════════════════════════════════════════════
# 1. _load_single_conversation 保留 RC（恢复会话链路）
# ════════════════════════════════════════════════════════════

class TestLoadSingleConversationRC:
    def test_plain_text_round_preserves_rc(self):
        """is_func_calling=False 的纯文本轮：rounds 存在时必须保留 reasoning_content。

        旧实现按 is_func_calling 区分加载，纯文本轮被 ai_msg 重建 → RC 丢失 →
        恢复会话后 DeepSeek 400 "must be passed back"。
        """
        conv = {
            "user_msg": "你好",
            "ai_msg": "你好！有什么可以帮你？",
            "is_func_calling": False,
            "rounds_json_parsed": [
                {
                    "role": "assistant",
                    "content": "你好！有什么可以帮你？",
                    "reasoning_content": "用户打招呼，直接友好回应即可",
                },
            ],
        }
        msgs = BaseChatSession._load_single_conversation(conv)
        assistant = [m for m in msgs if m["role"] == "assistant"][-1]
        assert assistant["content"] == "你好！有什么可以帮你？"
        assert assistant.get("reasoning_content") == "用户打招呼，直接友好回应即可"

    def test_tool_call_round_preserves_rc(self):
        """is_func_calling=True 的工具轮：RC 保留（原有行为不回退）。"""
        conv = {
            "user_msg": "搜索一下",
            "ai_msg": "已搜索",
            "is_func_calling": True,
            "rounds_json_parsed": [
                {
                    "role": "assistant",
                    "content": "",
                    "reasoning_content": "需要调用搜索工具",
                    "tool_calls": [{
                        "id": "c1", "type": "function",
                        "function": {"name": "toolkit_search", "arguments": "{}"},
                    }],
                },
                {"role": "tool", "tool_call_id": "c1", "content": "结果"},
                {"role": "assistant", "content": "已搜索", "reasoning_content": "整理结果"},
            ],
        }
        msgs = BaseChatSession._load_single_conversation(conv)
        assistants = [m for m in msgs if m["role"] == "assistant"]
        assert assistants[0].get("reasoning_content") == "需要调用搜索工具"
        assert assistants[1].get("reasoning_content") == "整理结果"

    def test_no_rounds_falls_back_to_ai_msg(self):
        """无 rounds（旧数据/非思考模型）→ 回退 ai_msg，不带 RC 字段。"""
        conv = {
            "user_msg": "hi",
            "ai_msg": "hello",
            "is_func_calling": False,
            "rounds_json_parsed": None,
        }
        msgs = BaseChatSession._load_single_conversation(conv)
        assistant = [m for m in msgs if m["role"] == "assistant"][-1]
        assert assistant["content"] == "hello"
        assert "reasoning_content" not in assistant

    def test_corrupt_rounds_falls_back_to_ai_msg(self):
        """rounds_json_parsed 非列表脏数据 → 安全回退 ai_msg，不崩溃。"""
        conv = {
            "user_msg": "hi",
            "ai_msg": "hello",
            "is_func_calling": False,
            "rounds_json_parsed": {"role": "assistant"},  # 脏数据（dict 而非 list）
        }
        msgs = BaseChatSession._load_single_conversation(conv)
        assistant = [m for m in msgs if m["role"] == "assistant"][-1]
        assert assistant["content"] == "hello"


# ════════════════════════════════════════════════════════════
# 2. create_chat_stream 发送前防御性 RC 补全 + disable_thinking
# ════════════════════════════════════════════════════════════

class TestCreateChatStreamRCGuard:
    """create_chat_stream 的 RC 补全与 thinking 降级测试。"""

    @pytest.fixture(autouse=True)
    def _isolate_config(self, monkeypatch):
        mock_cfg = MagicMock()
        mock_cfg.main_model.options = {}
        mock_cfg.cheap_model.options = {}
        monkeypatch.setattr("tea_agent.config.get_config", lambda: mock_cfg)

    def _make_api(self, **kwargs):
        ctx_kwargs = {
            "model": "deepseek-v4-flash",
            "enable_thinking": True,
            "client": MagicMock(),
            "supports_reasoning": True,
            "no_stream_chunk": True,
            "_thinking_supported": True,
        }
        ctx_kwargs.update(kwargs)
        ctx = SessionContext(**ctx_kwargs)
        return APIComponent(ctx)

    def _call(self, api, msgs, tools):
        api.ctx.client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content="ok", tool_calls=None))]
        )
        api.create_chat_stream(msgs, tools)
        _, kwargs = api.ctx.client.chat.completions.create.call_args
        return kwargs

    def test_thinking_plus_tools_fills_missing_rc(self):
        """thinking 开启 + 带 tools：缺 RC 的 assistant 消息被补空串（兜底旁路）。"""
        api = self._make_api()
        msgs = [
            {"role": "system", "content": "sp"},
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "旧回复", "reasoning_content": "完整思考"},
            {"role": "assistant", "content": "无 RC 的消息"},  # 缺字段
            {"role": "assistant", "content": "", "tool_calls": [{
                "id": "c1", "type": "function",
                "function": {"name": "toolkit_todo", "arguments": "{}"},
            }]},  # 缺字段（含 tool_calls）
        ]
        kwargs = self._call(api, msgs, [{"type": "function", "function": {"name": "t"}}])
        sent = kwargs["messages"]
        by_content = {m.get("content"): m for m in sent if m.get("role") == "assistant"}
        assert by_content["旧回复"]["reasoning_content"] == "完整思考"   # 原值不动
        assert by_content["无 RC 的消息"]["reasoning_content"] == ""     # 补空串
        assert by_content[""]["reasoning_content"] == ""                 # tool_calls 也补

    def test_thinking_no_tools_no_fill(self):
        """thinking 开启但无 tools：不需要 RC，不补字段（避免污染其他端点）。"""
        api = self._make_api()
        msgs = [{"role": "user", "content": "hi"},
                {"role": "assistant", "content": "ok"}]
        kwargs = self._call(api, msgs, [])
        sent = kwargs["messages"]
        assert "reasoning_content" not in sent[1]

    def test_thinking_disabled_no_fill(self):
        """thinking 关闭 + 带 tools：不补字段（非思考模式无 RC 要求）。"""
        api = self._make_api(enable_thinking=False)
        msgs = [{"role": "user", "content": "hi"},
                {"role": "assistant", "content": "ok"}]
        kwargs = self._call(api, msgs, [{"type": "function", "function": {"name": "t"}}])
        sent = kwargs["messages"]
        assert "reasoning_content" not in sent[1]

    def test_disable_thinking_param_forces_disabled(self):
        """disable_thinking=True → extra_body thinking=disabled（自愈重试用）。"""
        api = self._make_api()
        msgs = [{"role": "user", "content": "hi"}]
        api.ctx.client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content="ok", tool_calls=None))]
        )
        api.create_chat_stream(msgs, [], disable_thinking=True)
        _, kwargs = api.ctx.client.chat.completions.create.call_args
        assert kwargs["extra_body"]["thinking"]["type"] == "disabled"

    def test_rc400_recovery_flag_forces_disabled(self):
        """ctx._rc400_recovery=True → 本回合剩余请求强制关闭 thinking。"""
        api = self._make_api()
        api.ctx._rc400_recovery = True
        msgs = [{"role": "user", "content": "hi"}]
        api.ctx.client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content="ok", tool_calls=None))]
        )
        api.create_chat_stream(msgs, [{"type": "function", "function": {"name": "t"}}])
        _, kwargs = api.ctx.client.chat.completions.create.call_args
        assert kwargs["extra_body"]["thinking"]["type"] == "disabled"

    def test_reset_session_state_clears_recovery_flag(self):
        """reset_session_state 清除 _rc400_recovery（下回合 thinking 恢复）。"""
        mock_tk = MagicMock()
        mock_tk.meta_map = {}
        sess = OnlineToolSession(
            toolkit=mock_tk, api_key="k", api_url="http://x", model="m",
            storage=None,
        )
        sess.context._rc400_recovery = True
        sess.reset_session_state()
        assert sess.context._rc400_recovery is False
        sess.close()


# ════════════════════════════════════════════════════════════
# 3. tool_loop_runner RC 400 自愈
# ════════════════════════════════════════════════════════════

class TestToolLoopRC400Recovery:
    def _make_session(self, **kwargs):
        mock_tk = MagicMock()
        mock_tk.meta_map = {}
        mock_tk.call_tool.return_value = "mock_result"
        sess = OnlineToolSession(
            toolkit=mock_tk, api_key="sk-test", api_url="https://api.test.com/v1",
            model="deepseek-v4-flash", enable_thinking=True, storage=None,
            no_stream_chunk=True, supports_reasoning=True, **kwargs
        )
        sess._build_api_messages = MagicMock(
            return_value=[{"role": "user", "content": "test"}]
        )
        sess.api = MagicMock()
        sess._process_stream_with_reasoning = MagicMock()
        sess.tools_comp = MagicMock()
        return sess

    def test_rc_400_triggers_disable_thinking_retry(self):
        """首次 400 → 诊断 + 关闭 thinking 重试成功，对话不中断。"""
        sess = self._make_session()
        rc_400 = RuntimeError(
            "Error code: 400 - {'error': {'message': 'The reasoning_content in "
            "the thinking mode must be passed back to the API.', 'type': "
            "'invalid_request_error'}}"
        )
        sess.api.create_chat_stream.side_effect = [rc_400, MagicMock()]
        sess._process_stream_with_reasoning.return_value = ("自愈后的回复", [], "")
        sess.tools_comp.parse_tool_calls_from_stream.return_value = []

        result = execute_tool_loop(sess, {"msg": "hi", "callback": lambda x: None})

        # 自愈成功：回复正常返回，不出现 API调用错误
        assert result["full_reply"] == "自愈后的回复"
        assert "error" not in result
        # 第二次调用带 disable_thinking=True
        assert sess.api.create_chat_stream.call_count == 2
        second_kwargs = sess.api.create_chat_stream.call_args_list[1].kwargs
        assert second_kwargs["disable_thinking"] is True
        # 自愈标志置位（本回合剩余请求保持降级）
        assert sess.context._rc400_recovery is True
        sess.close()

    def test_non_rc_error_no_recovery(self):
        """其他错误不触发自愈，走原错误路径。"""
        sess = self._make_session()
        sess.api.create_chat_stream.side_effect = RuntimeError("API connection error")

        result = execute_tool_loop(sess, {"msg": "hi", "callback": lambda x: None})

        assert "API调用错误" in result["full_reply"]
        assert sess.api.create_chat_stream.call_count == 1
        assert sess.context._rc400_recovery is False
        sess.close()

    def test_rc_400_recovery_then_tool_call_continues(self):
        """自愈后后续工具轮次继续工作（thinking 保持关闭）。"""
        sess = self._make_session()
        rc_400 = RuntimeError(
            "Error code: 400 - {'error': {'message': 'The reasoning_content in "
            "the thinking mode must be passed back to the API.'}}"
        )
        sess.api.create_chat_stream.side_effect = [rc_400, MagicMock(), MagicMock()]
        sess._process_stream_with_reasoning.side_effect = [
            ("", [{"id": "c1", "type": "function",
                   "function": {"name": "toolkit_search", "arguments": "{}"}}], ""),
            ("最终答案", [], ""),
        ]
        sess.tools_comp.parse_tool_calls_from_stream.side_effect = [
            [MagicMock(id="c1", function=MagicMock(
                name="toolkit_search", arguments="{}"))],
            [],
        ]
        sess.tools_comp.execute_tool_call.return_value = ("c1", "toolkit_search", "r")

        result = execute_tool_loop(sess, {"msg": "hi", "callback": lambda x: None})

        assert result["full_reply"] == "最终答案"
        # 后续轮次调用也都带 disable_thinking=True
        for call in sess.api.create_chat_stream.call_args_list[1:]:
            assert call.kwargs.get("disable_thinking") is True
        sess.close()


# ════════════════════════════════════════════════════════════
# 4. 错误识别辅助函数
# ════════════════════════════════════════════════════════════

class TestIsRCPassedBackError:
    def test_matches_official_error(self):
        err = (
            "Error code: 400 - {'error': {'message': 'The reasoning_content in "
            "the thinking mode must be passed back to the API.', 'type': "
            "'invalid_request_error'}}"
        )
        assert _is_rc_passed_back_error(err) is True

    def test_matches_other_400_with_rc(self):
        # 部分代理网关只透传 message 片段
        assert _is_rc_passed_back_error("400 reasoning_content must be passed back") is True

    def test_does_not_match_other_errors(self):
        assert _is_rc_passed_back_error("429 Too Many Requests") is False
        assert _is_rc_passed_back_error("400 context length exceeded") is False
        assert _is_rc_passed_back_error("") is False
        assert _is_rc_passed_back_error(None) is False
