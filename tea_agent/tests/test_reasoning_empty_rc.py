"""
含空字符串 reasoning_content 的 tool_calls 消息必须保留字段（DeepSeek V4 思考模式回归）。

背景：DeepSeek-V4 思考模式在部分 tool_call 轮次返回 reasoning_content=""（空字符串）。
若客户端因值为空而丢弃该字段（`if reasoning_content:` 的 falsy 判断），下一轮携带
tools 参数的请求会触发 400 "The reasoning_content in the thinking mode must be
passed back to the API."（参见 karminski/deepseek-reasoning-content-field-issue-pov、
anything-llm #5683、langchain #35094 等生态证据）。

本测试锁定修复后的行为：
1. build_api_messages 对「字段存在但为空串」的 tool_calls 消息不再误告警（空串是
   模型返回的合法值，必须原样回传；只有字段缺失才是 400 风险）
2. build_api_messages 对「字段缺失」的 tool_calls 消息**自动补空串**（字段缺失即
   触发 400 "must be passed back"；补空串满足"字段存在"，杜绝 400 且不再告警）
3. rounds 收集器 / lite 会话构建器同样保留空串 RC 字段（DB 回放一致）
"""
import logging
from types import SimpleNamespace

import pytest

from tea_agent.basesession import BaseChatSession
from tea_agent.session.context import SessionContext
from tea_agent.session.history_builder import build_api_messages


class _Sess(BaseChatSession):
    def chat_stream(self, msg, callback):
        return "", False

    @property
    def messages(self):
        return self.context.messages if hasattr(self, "context") else []

    @messages.setter
    def messages(self, v):
        if hasattr(self, "context"):
            self.context.messages = v


def _make_session() -> tuple[SessionContext, _Sess]:
    ctx = SessionContext()
    ctx.model = "deepseek-v4-flash"
    ctx.supports_reasoning = True
    ctx.supports_vision = False
    ctx.max_context_tokens = 128000
    ctx.messages = [{"role": "system", "content": "system prompt"}]
    ctx._injected_os_info_text = ""
    ctx._semantic_summary = ""
    ctx._tool_chain_summary = ""
    ctx._level2 = []
    sess = _Sess(model="deepseek-v4-flash")
    sess.context = ctx
    return ctx, sess


def _tool_call_msg(name: str = "toolkit_todo", rc: str | None = None) -> dict:
    """rc=None 表示不带 reasoning_content 字段；rc='' 表示带空串字段。"""
    msg = {
        "role": "assistant",
        "content": "",
        "tool_calls": [{
            "id": "c1",
            "type": "function",
            "function": {"name": name, "arguments": "{}"},
        }],
    }
    if rc is not None:
        msg["reasoning_content"] = rc
    return msg


def _warnings(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if "缺少 reasoning_content" in r.getMessage()]


class TestBuildApiMessagesDefensiveCheck:
    def test_empty_string_rc_is_valid_no_warning(self, caplog):
        """字段存在但为空串 → 原样回传，不误告警（这才是 DeepSeek 返回的合法值）。"""
        ctx, sess = _make_session()
        sess.add_user_message("执行工具")
        ctx.messages.append(_tool_call_msg(rc=""))
        with caplog.at_level(logging.WARNING):
            msgs = build_api_messages(ctx, "测试")
        tc = [m for m in msgs if m.get("role") == "assistant" and m.get("tool_calls")][0]
        assert "reasoning_content" in tc        # 字段保留
        assert tc["reasoning_content"] == ""    # 空串原样回传
        assert _warnings(caplog) == []

    def test_missing_rc_auto_filled(self, caplog):
        """字段缺失 → 自动补空串（杜绝 400），不再告警（DeepSeek V4 字段缺失即 400）。"""
        ctx, sess = _make_session()
        sess.add_user_message("执行工具")
        ctx.messages.append(_tool_call_msg(rc=None))
        with caplog.at_level(logging.WARNING):
            msgs = build_api_messages(ctx, "测试")
        tc = [m for m in msgs if m.get("role") == "assistant" and m.get("tool_calls")][0]
        assert "reasoning_content" in tc       # 字段自动补全
        assert tc["reasoning_content"] == ""   # 空串（满足"字段存在"）
        assert _warnings(caplog) == []         # 已修复 → 不再告警

    def test_non_reasoning_model_no_warning(self, caplog):
        """supports_reasoning=False（普通模型）时不做该校验，不告警。"""
        ctx, sess = _make_session()
        ctx.supports_reasoning = False
        sess.add_user_message("执行工具")
        ctx.messages.append(_tool_call_msg(rc=None))
        with caplog.at_level(logging.WARNING):
            build_api_messages(ctx, "测试")
        assert _warnings(caplog) == []


class TestRoundsCollectorPreservesEmptyRC:
    def test_collect_assistant_tool_calls_round_keeps_empty_rc(self):
        from tea_agent.onlinesession import ToolComponent

        stub = SimpleNamespace(
            ctx=SimpleNamespace(supports_reasoning=True, _rounds_collector=[]),
        )
        tc = SimpleNamespace(
            id="c1", function=SimpleNamespace(name="toolkit_todo", arguments="{}")
        )
        ToolComponent.collect_assistant_tool_calls_round(stub, "content", [tc], "")
        entry = stub.ctx._rounds_collector[0]
        assert "reasoning_content" in entry
        assert entry["reasoning_content"] == ""

    def test_collect_assistant_text_round_keeps_empty_rc(self):
        from tea_agent.onlinesession import ToolComponent

        stub = SimpleNamespace(
            ctx=SimpleNamespace(supports_reasoning=True, _rounds_collector=[]),
        )
        ToolComponent.collect_assistant_text_round(stub, "content", "")
        entry = stub.ctx._rounds_collector[0]
        assert "reasoning_content" in entry
        assert entry["reasoning_content"] == ""


class TestLiteSessionBuildMessagePreservesEmptyRC:
    def test_build_assistant_message_keeps_empty_rc(self):
        from tea_agent.litesession import LiteSession

        stub = SimpleNamespace(supports_reasoning=True)
        tc = SimpleNamespace(
            id="c1", function=SimpleNamespace(name="toolkit_exec", arguments="{}")
        )
        msg = LiteSession._build_assistant_message(stub, "content", [tc], "")
        assert "reasoning_content" in msg
        assert msg["reasoning_content"] == ""

    def test_build_assistant_message_non_reasoning_omits_rc(self):
        from tea_agent.litesession import LiteSession

        stub = SimpleNamespace(supports_reasoning=False)
        tc = SimpleNamespace(
            id="c1", function=SimpleNamespace(name="toolkit_exec", arguments="{}")
        )
        msg = LiteSession._build_assistant_message(stub, "content", [tc], "思考内容")
        assert "reasoning_content" not in msg
