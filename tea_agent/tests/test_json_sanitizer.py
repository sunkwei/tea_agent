"""
JSON 校验与修复模块单元测试 — 覆盖 try_fix_truncated_json 和 sanitize_api_messages。

测试范围:
- try_fix_truncated_json: 合法 JSON / 截断 JSON / 无法修复 / 边界情况
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

    # ── 新增边界情况测试 ──

    def test_string_with_escaped_quotes(self):
        """字符串中包含转义引号"""
        from tea_agent.session.json_sanitizer import try_fix_truncated_json
        s = '{"msg": "he said \\"hello'
        result = try_fix_truncated_json(s)
        assert result is not None
        parsed = json.loads(result)
        assert "he said" in parsed["msg"]

    def test_truncated_at_comma(self):
        """在逗号处截断"""
        from tea_agent.session.json_sanitizer import try_fix_truncated_json
        s = '{"a": 1,'
        result = try_fix_truncated_json(s)
        assert result is not None
        parsed = json.loads(result)
        assert parsed["a"] == 1

    def test_truncated_at_colon(self):
        """在冒号处截断 — 无法确定值类型，返回 None"""
        from tea_agent.session.json_sanitizer import try_fix_truncated_json
        s = '{"a":'
        result = try_fix_truncated_json(s)
        # 冒号后无法确定值类型，修复算法无法补全，返回 None 可接受
        assert result is None

    def test_deeply_nested_truncated(self):
        """深层嵌套截断"""
        from tea_agent.session.json_sanitizer import try_fix_truncated_json
        s = '{"a": {"b": {"c": {"d": {"e": 1'
        result = try_fix_truncated_json(s)
        assert result is not None
        parsed = json.loads(result)
        assert parsed["a"]["b"]["c"]["d"]["e"] == 1

    def test_mixed_brackets_and_braces(self):
        """混合方括号和花括号的截断"""
        from tea_agent.session.json_sanitizer import try_fix_truncated_json
        s = '{"items": [1, {"x": 2'
        result = try_fix_truncated_json(s)
        assert result is not None
        parsed = json.loads(result)
        assert parsed["items"][0] == 1
        assert parsed["items"][1]["x"] == 2

    def test_truncated_with_unicode(self):
        """包含 unicode 的截断"""
        from tea_agent.session.json_sanitizer import try_fix_truncated_json
        s = '{"msg": "你好世界'
        result = try_fix_truncated_json(s)
        assert result is not None
        parsed = json.loads(result)
        assert "你好" in parsed["msg"]

    def test_truncated_with_empty_string_value(self):
        """空字符串值的截断"""
        from tea_agent.session.json_sanitizer import try_fix_truncated_json
        s = '{"key": ""'
        result = try_fix_truncated_json(s)
        assert result is not None
        parsed = json.loads(result)
        assert parsed["key"] == ""

    def test_truncated_array_of_objects(self):
        """对象数组的截断"""
        from tea_agent.session.json_sanitizer import try_fix_truncated_json
        s = '[{"a": 1}, {"b": 2}'
        result = try_fix_truncated_json(s)
        assert result is not None
        parsed = json.loads(result)
        assert parsed == [{"a": 1}, {"b": 2}]

    def test_single_char_truncated(self):
        """极短截断"""
        from tea_agent.session.json_sanitizer import try_fix_truncated_json
        # 单字符无法修复成合法 JSON
        assert try_fix_truncated_json("{") is not None  # 可补全为 {}
        assert try_fix_truncated_json("[") is not None  # 可补全为 []

    def test_truncated_with_trailing_backslash(self):
        """末尾反斜杠的截断（转义序列不完整）"""
        from tea_agent.session.json_sanitizer import try_fix_truncated_json
        s = '{"msg": "line1\\'
        result = try_fix_truncated_json(s)
        # 反斜杠截断导致字符串未闭合，但修复算法可能补全
        # 不要求必然修复成功，但不应崩溃
        if result is not None:
            parsed = json.loads(result)
            assert "msg" in parsed

    def test_truncated_before_key(self):
        """在 key 之前截断"""
        from tea_agent.session.json_sanitizer import try_fix_truncated_json
        s = '{"a": 1, "'
        result = try_fix_truncated_json(s)
        assert result is not None
        parsed = json.loads(result)
        assert parsed["a"] == 1

    def test_multiple_truncation_attempts_via_comma(self):
        """通过移除末尾无效部分修复"""
        from tea_agent.session.json_sanitizer import try_fix_truncated_json
        s = '{"a": 1, "b": 2, "c": 3, '
        result = try_fix_truncated_json(s)
        assert result is not None
        parsed = json.loads(result)
        assert "a" in parsed
        assert "b" in parsed


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

    # ── 新增边界情况测试 ──

    def test_tool_call_with_dict_arguments(self):
        """参数已经是 dict 类型的情况"""
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
                            "arguments": {"action": "read", "filename": "test.py"}
                        }
                    }
                ]
            }
        ]
        result = sanitize_api_messages(messages)
        assert len(result) == 1
        assert len(result[0]["tool_calls"]) == 1

    def test_tool_call_with_empty_arguments(self):
        """空字符串参数应保留"""
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
                            "arguments": ""
                        }
                    }
                ]
            }
        ]
        result = sanitize_api_messages(messages)
        assert len(result) == 1
        assert len(result[0]["tool_calls"]) == 1

    def test_all_tool_calls_invalid(self):
        """所有 tool_calls 都非法时应输出占位消息"""
        from tea_agent.session.json_sanitizer import sanitize_api_messages
        messages = [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_bad",
                        "type": "function",
                        "function": {
                            "name": "bad_tool",
                            "arguments": '{{invalid'
                        }
                    }
                ]
            }
        ]
        result = sanitize_api_messages(messages)
        assert len(result) == 1
        # 所有 tool_calls 被移除后，应保留 assistant 消息但无 tool_calls
        assert "tool_calls" not in result[0] or len(result[0]["tool_calls"]) == 0
        assert "[工具调用参数损坏，已移除]" in result[0].get("content", "")

    def test_mixed_valid_invalid_multiple_assistant_messages(self):
        """多个 assistant 消息的混合场景"""
        from tea_agent.session.json_sanitizer import sanitize_api_messages
        messages = [
            {"role": "user", "content": "hello"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": "c1", "type": "function", "function": {"name": "ok", "arguments": "{}"}},
                    # {"x 截断无法修复（需要确定值类型），会被正常移除
                    {"id": "c2", "type": "function", "function": {"name": "bad", "arguments": '{"x'}},
                ]
            },
            {"role": "tool", "content": "result", "tool_call_id": "c1"},
            {
                "role": "assistant",
                "content": "done",
                "tool_calls": [
                    {"id": "c3", "type": "function", "function": {"name": "f", "arguments": '{"a": 1}'}},
                ]
            }
        ]
        result = sanitize_api_messages(messages)
        assert len(result) == 4
        # 第一个 assistant 中 c1 保留，c2 因无法修复被移除
        assert len(result[1]["tool_calls"]) == 1
        assert result[1]["tool_calls"][0]["id"] == "c1"

    def test_reasoning_content_preserved(self):
        """reasoning_content 应保留"""
        from tea_agent.session.json_sanitizer import sanitize_api_messages
        messages = [
            {
                "role": "assistant",
                "content": "final answer",
                "reasoning_content": "my reasoning",
            }
        ]
        result = sanitize_api_messages(messages)
        assert result[0].get("reasoning_content") == "my reasoning"


# ============================================================
# 3. normalize_tool_args — 源头规范化（截断参数入库前修复）
# ============================================================

class TestNormalizeToolArgs:
    """normalize_tool_args 源头规范化测试"""

    def test_valid_json_returned_unchanged(self):
        """合法 JSON 应原样返回（逐字节一致，前缀缓存友好）"""
        from tea_agent.session.json_sanitizer import normalize_tool_args
        raw = '{"app": "bash", "args": ["-c", "echo hi"]}'
        assert normalize_tool_args("toolkit_exec", raw) == raw

    def test_truncated_json_fixed(self):
        """截断 JSON 应修复为完整 JSON"""
        from tea_agent.session.json_sanitizer import normalize_tool_args
        # 缺少右括号的截断参数（对应线上常驻 WARNING 示例）
        raw = '{"app": "bash", "args": ["-c"]'
        fixed = normalize_tool_args("toolkit_exec", raw)
        assert fixed is not None
        parsed = json.loads(fixed)
        assert parsed["app"] == "bash"
        assert parsed["args"] == ["-c"]

    def test_broken_json_returns_none(self):
        """无法修复的 JSON 应返回 None（调用方丢弃该 tool_call）"""
        from tea_agent.session.json_sanitizer import normalize_tool_args
        assert normalize_tool_args("toolkit_exec", "invalid json{{{") is None

    def test_empty_returns_as_is(self):
        """空字符串/None 原样返回"""
        from tea_agent.session.json_sanitizer import normalize_tool_args
        assert normalize_tool_args("toolkit_exec", "") == ""
        assert normalize_tool_args("toolkit_exec", "   ") == "   "
        assert normalize_tool_args("toolkit_exec", None) is None

    def test_dict_arguments_passthrough(self):
        """非字符串 arguments（dict）原样透传"""
        from tea_agent.session.json_sanitizer import normalize_tool_args
        obj = {"a": 1}
        assert normalize_tool_args("toolkit_exec", obj) is obj
