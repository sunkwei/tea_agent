"""
JSON 校验与修复模块单元测试 — 覆盖 try_fix_truncated_json 和 sanitize_api_messages。

测试范围:
- try_fix_truncated_json: 合法 JSON / 截断 JSON / 无法修复
- sanitize_api_messages: 正常消息 / 非法 tool_calls / 混合场景
"""

import json


# ============================================================
# 1. try_fix_truncated_json
# ============================================================

class TestTryFixTruncatedJson:
    """截断 JSON 修复测试"""

    def test_valid_json_returns_unchanged(self):
        """合法 JSON 应原样返回"""
        from tea_agent.session.json_sanitizer import try_fix_truncated_json
        s = '{"key": "value"}'
        result = try_fix_truncated_json(s)
        assert result == s
        assert json.loads(result) == {"key": "value"}

    def test_empty_string_returns_none(self):
        """空字符串应返回 None"""
        from tea_agent.session.json_sanitizer import try_fix_truncated_json
        assert try_fix_truncated_json("") is None
        assert try_fix_truncated_json("   ") is None
        assert try_fix_truncated_json(None) is None

    def test_truncated_object_closes_braces(self):
        """截断的对象应补全闭合括号"""
        from tea_agent.session.json_sanitizer import try_fix_truncated_json
        s = '{"key": "value", "nested": {"a": 1'
        result = try_fix_truncated_json(s)
        assert result is not None
        parsed = json.loads(result)
        assert parsed["key"] == "value"
        assert parsed["nested"]["a"] == 1

    def test_truncated_array_closes_brackets(self):
        """截断的数组应补全闭合括号"""
        from tea_agent.session.json_sanitizer import try_fix_truncated_json
        s = '[1, 2, 3'
        result = try_fix_truncated_json(s)
        assert result is not None
        assert json.loads(result) == [1, 2, 3]

    def test_truncated_string_closes_quote(self):
        """截断的字符串应补全引号"""
        from tea_agent.session.json_sanitizer import try_fix_truncated_json
        s = '{"key": "val'
        result = try_fix_truncated_json(s)
        assert result is not None
        parsed = json.loads(result)
        assert parsed["key"] == "val"

    def test_nested_truncated_json(self):
        """嵌套截断 JSON 应正确修复"""
        from tea_agent.session.json_sanitizer import try_fix_truncated_json
        s = '{"a": {"b": [1, 2'
        result = try_fix_truncated_json(s)
        assert result is not None
        parsed = json.loads(result)
        assert parsed["a"]["b"] == [1, 2]

    def test_invalid_json_returns_none(self):
        """无法修复的 JSON 应返回 None"""
        from tea_agent.session.json_sanitizer import try_fix_truncated_json
        s = '{"key": }'  # 语法错误，无法修复
        result = try_fix_truncated_json(s)
        assert result is None

    def test_complex_truncated_json(self):
        """复杂截断场景：多层嵌套 + 字符串"""
        from tea_agent.session.json_sanitizer import try_fix_truncated_json
        s = '{"tool_calls": [{"name": "toolkit_file", "args": {"action": "read", "file'
        result = try_fix_truncated_json(s)
        assert result is not None
        parsed = json.loads(result)
        assert "tool_calls" in parsed
        assert parsed["tool_calls"][0]["name"] == "toolkit_file"


# ============================================================
# 2. sanitize_api_messages
# ============================================================

class TestSanitizeApiMessages:
    """API 消息校验测试"""

    def test_valid_messages_pass_through(self):
        """合法消息应原样返回"""
        from tea_agent.session.json_sanitizer import sanitize_api_messages
        messages = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ]
        result = sanitize_api_messages(messages)
        assert len(result) == 2
        assert result[0]["role"] == "user"

    def test_valid_tool_calls_preserved(self):
        """合法 tool_calls 应保留"""
        from tea_agent.session.json_sanitizer import sanitize_api_messages
        messages = [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_123",
                        "type": "function",
                        "function": {
                            "name": "toolkit_file",
                            "arguments": '{"action": "read", "filename": "test.py"}'
                        }
                    }
                ]
            }
        ]
        result = sanitize_api_messages(messages)
        assert len(result) == 1
        assert len(result[0]["tool_calls"]) == 1

    def test_truncated_tool_call_fixed(self):
        """截断的 tool_call 参数应被修复"""
        from tea_agent.session.json_sanitizer import sanitize_api_messages
        messages = [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_123",
                        "type": "function",
                        "function": {
                            "name": "toolkit_file",
                            "arguments": '{"action": "read", "filename": "test'  # 截断
                        }
                    }
                ]
            }
        ]
        result = sanitize_api_messages(messages)
        # 应该保留（被修复）
        assert len(result) == 1
        assert len(result[0]["tool_calls"]) == 1
        # 验证修复后的 JSON 合法
        args = json.loads(result[0]["tool_calls"][0]["function"]["arguments"])
        assert args["action"] == "read"

    def test_invalid_tool_call_removed(self):
        """无法修复的 tool_call 应被移除"""
        from tea_agent.session.json_sanitizer import sanitize_api_messages
        messages = [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_123",
                        "type": "function",
                        "function": {
                            "name": "toolkit_file",
                            "arguments": '{"action": }'  # 语法错误
                        }
                    }
                ]
            }
        ]
        result = sanitize_api_messages(messages)
        # tool_calls 应为空或被移除
        assert len(result) == 1
        if "tool_calls" in result[0]:
            assert len(result[0]["tool_calls"]) == 0

    def test_mixed_valid_and_invalid_tool_calls(self):
        """混合场景：部分合法部分非法"""
        from tea_agent.session.json_sanitizer import sanitize_api_messages
        messages = [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "toolkit_file",
                            "arguments": '{"action": "read"}'  # 合法
                        }
                    },
                    {
                        "id": "call_2",
                        "type": "function",
                        "function": {
                            "name": "toolkit_exec",
                            "arguments": '{"command": "ls'  # 截断，可修复
                        }
                    }
                ]
            }
        ]
        result = sanitize_api_messages(messages)
        assert len(result) == 1
        assert len(result[0]["tool_calls"]) == 2  # 都应保留

    def test_non_assistant_messages_ignored(self):
        """非 assistant 消息应被忽略"""
        from tea_agent.session.json_sanitizer import sanitize_api_messages
        messages = [
            {"role": "user", "content": "hello"},
            {"role": "system", "content": "you are helpful"},
            {"role": "tool", "content": "result"},
        ]
        result = sanitize_api_messages(messages)
        assert len(result) == 3
        # 所有消息原样返回
        for msg in result:
            assert "content" in msg

    def test_empty_messages_list(self):
        """空消息列表应返回空列表"""
        from tea_agent.session.json_sanitizer import sanitize_api_messages
        result = sanitize_api_messages([])
        assert result == []
