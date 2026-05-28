# @2026-05-21 gen by tea_agent, 意图分析模块契约测试
"""
session_intent 模块测试 — 独立纯函数 analyze_intent()。

Contract:
- 输入: str → 输出: dict（含 type / skip_tool_loop / required_tools）
- 任何用户输入都应返回有效的 dict，不抛异常
"""

import pytest
from tea_agent.session_intent import analyze_intent


class TestIntentContract:
    """analyze_intent 的接口契约"""

    def test_returns_dict(self):
        result = analyze_intent("hello")
        assert isinstance(result, dict)

    def test_has_required_keys(self):
        result = analyze_intent("hello")
        assert "type" in result
        assert "skip_tool_loop" in result
        assert "required_tools" in result

    def test_type_is_string(self):
        result = analyze_intent("hello")
        assert isinstance(result["type"], str)

    def test_skip_tool_loop_is_bool(self):
        result = analyze_intent("hello")
        assert isinstance(result["skip_tool_loop"], bool)

    def test_required_tools_is_optional_list(self):
        result = analyze_intent("hello")
        assert result["required_tools"] is None or isinstance(result["required_tools"], list)

    def test_default_return_value(self):
        result = analyze_intent("hello")
        assert result["type"] == "general"
        assert result["skip_tool_loop"] is False
        assert result["required_tools"] is None

    def test_empty_string_returns_default(self):
        result = analyze_intent("")
        assert result["type"] == "general"

    def test_special_chars_returns_default(self):
        result = analyze_intent("!@#$%^&*()_+")
        assert result["type"] == "general"

    def test_multiline_text_returns_default(self):
        result = analyze_intent("line1\nline2\nline3")
        assert result["type"] == "general"

    def test_chinese_text_returns_default(self):
        result = analyze_intent("你好，请帮我读取文件")
        assert result["type"] == "general"

    def test_numbers_only_returns_default(self):
        result = analyze_intent("12345")
        assert result["type"] == "general"
