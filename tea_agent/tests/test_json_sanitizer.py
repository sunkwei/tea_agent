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


# ============================================================
# 4. 裸控制字符 / 裸标量值修复 — 嵌入式小模型线上回归
#    线上 WARNING 样本: {"app": bash, "args": ["-lc", "set -u\necho ..."]}
# ============================================================

class TestEscapeRawControlChars:
    """escape_raw_control_chars：字符串内裸控制字符转义"""

    def test_real_newline_inside_string_is_escaped(self):
        """字符串内的真实换行应转义为 \\n 且内容不变"""
        from tea_agent.session.json_sanitizer import escape_raw_control_chars
        s = '{"cmd": "echo a\necho b"}'
        fixed = escape_raw_control_chars(s)
        assert json.loads(fixed)["cmd"] == "echo a\necho b"

    def test_tab_and_cr_escaped(self):
        """制表符 / 回车同样转义"""
        from tea_agent.session.json_sanitizer import escape_raw_control_chars
        fixed = escape_raw_control_chars('{"cmd": "a\tb\rc"}')
        assert json.loads(fixed)["cmd"] == "a\tb\rc"

    def test_newline_outside_string_preserved(self):
        """字符串外部的换行是合法空白，必须原样保留（格式化 JSON）"""
        from tea_agent.session.json_sanitizer import escape_raw_control_chars
        s = '{\n  "a": 1\n}'
        assert escape_raw_control_chars(s) == s
        assert json.loads(escape_raw_control_chars(s)) == {"a": 1}

    def test_clean_input_unchanged_byte_for_byte(self):
        """无裸控制字符时逐字节返回（前缀缓存友好）"""
        from tea_agent.session.json_sanitizer import escape_raw_control_chars
        s = '{"a": "x\\ny"}'
        assert escape_raw_control_chars(s) is s

    def test_empty_input(self):
        """空输入安全返回"""
        from tea_agent.session.json_sanitizer import escape_raw_control_chars
        assert escape_raw_control_chars("") == ""


class TestQuoteBareValues:
    """quote_bare_values：未加引号的裸标量值补引号"""

    def test_bare_value_quoted(self):
        """{"app": bash} → {"app": "bash"}"""
        from tea_agent.session.json_sanitizer import quote_bare_values
        fixed = quote_bare_values('{"app": bash, "n": 2}')
        assert json.loads(fixed) == {"app": "bash", "n": 2}

    def test_array_element_bare_value(self):
        """数组元素裸值也补引号"""
        from tea_agent.session.json_sanitizer import quote_bare_values
        fixed = quote_bare_values('{"args": [bash, -lc]}')
        assert json.loads(fixed) == {"args": ["bash", "-lc"]}

    def test_json_literals_untouched(self):
        """true/false/null 与数字不能加引号"""
        from tea_agent.session.json_sanitizer import quote_bare_values
        fixed = quote_bare_values('{"a": true, "b": false, "c": null, "d": 12}')
        assert json.loads(fixed) == {"a": True, "b": False, "c": None, "d": 12}

    def test_string_content_not_touched(self):
        """字符串内容里的 "x: y," 形态不能被误改"""
        from tea_agent.session.json_sanitizer import quote_bare_values
        s = '{"cmd": "sed -n 1,5p x: y, z"}'
        assert quote_bare_values(s) == s
        assert json.loads(quote_bare_values(s))["cmd"] == "sed -n 1,5p x: y, z"

    def test_escaped_quote_in_string_not_touched(self):
        """含转义引号的字符串不破坏扫描状态"""
        from tea_agent.session.json_sanitizer import quote_bare_values
        s = '{"cmd": "echo \\"a: b,\\""}'
        assert quote_bare_values(s) == s

    def test_already_quoted_unchanged(self):
        """已合法 JSON 原样返回"""
        from tea_agent.session.json_sanitizer import quote_bare_values
        s = '{"app": "bash", "args": ["-lc", "echo hi"]}'
        assert quote_bare_values(s) == s


class TestEscapeUnescapedInnerQuotes:
    """escape_unescaped_inner_quotes：字符串内未转义的裸引号"""

    def test_inner_quotes_escaped(self):
        """echo "x" 形式的裸引号应转义，结构引号保留"""
        from tea_agent.session.json_sanitizer import escape_unescaped_inner_quotes
        s = '{"cmd": "echo "hello" && ls"}'
        fixed = escape_unescaped_inner_quotes(s)
        assert json.loads(fixed)["cmd"] == 'echo "hello" && ls'

    def test_noop_on_valid_json(self):
        """合法 JSON（内层引号已转义）必须逐字节不变"""
        from tea_agent.session.json_sanitizer import escape_unescaped_inner_quotes
        for s in (
            '{"cmd": "echo \\"hi\\""}',
            '{"a": "x,", "b": "y:", "c": "z[1]"}',
            '{"a": "", "b": ["p", "q"]}',
            '{"a": "line1\\nline2", "b": {"c": 1}}',
        ):
            assert escape_unescaped_inner_quotes(s) == s

    def test_no_quote_fast_path(self):
        """不含引号或空输入原样返回"""
        from tea_agent.session.json_sanitizer import escape_unescaped_inner_quotes
        assert escape_unescaped_inner_quotes("no quotes here") == "no quotes here"
        assert escape_unescaped_inner_quotes("") == ""

    def test_escaped_quote_content_not_double_escaped(self):
        """已转义的引号不得被二次转义"""
        from tea_agent.session.json_sanitizer import escape_unescaped_inner_quotes
        s = '{"cmd": "a \\"b\\" c"}'
        assert escape_unescaped_inner_quotes(s) == s
        assert json.loads(s)["cmd"] == 'a "b" c'


class TestReportedEmbeddedModelFailures:
    """线上嵌入式小模型 WARNING 样本的端到端修复回归"""

    def test_bare_value_truncated_repaired(self):
        """裸值 + 截断：修复为完整 JSON（原实现直接丢弃）"""
        from tea_agent.session.json_sanitizer import normalize_tool_args
        raw = '{"app": bash, "args": ["-lc", "echo hello'
        fixed = normalize_tool_args("toolkit_exec", raw)
        assert fixed is not None
        assert json.loads(fixed) == {"app": "bash", "args": ["-lc", "echo hello"]}

    def test_bare_value_complete_repaired(self):
        """裸值 + 完整：修复为完整 JSON（原实现直接丢弃）"""
        from tea_agent.session.json_sanitizer import normalize_tool_args
        raw = '{"app": bash, "args": ["-lc", "echo hi"]}'
        fixed = normalize_tool_args("toolkit_exec", raw)
        assert fixed is not None
        assert json.loads(fixed) == {"app": "bash", "args": ["-lc", "echo hi"]}

    def test_bare_value_with_real_newlines_repaired(self):
        """裸值 + 多行脚本（真实换行）：两者同时出现也能修复"""
        from tea_agent.session.json_sanitizer import normalize_tool_args
        raw = '{"app": bash, "args": ["-lc", "echo a\necho b"]}'
        fixed = normalize_tool_args("toolkit_exec", raw)
        assert fixed is not None
        assert json.loads(fixed)["args"][1] == "echo a\necho b"

    def test_real_newline_truncated_keeps_full_command(self):
        """真实换行 + 截断：不得退化成"从尾部删除"而丢掉已完整的命令内容"""
        from tea_agent.session.json_sanitizer import normalize_tool_args
        raw = '{"app": "bash", "args": ["-lc", "set -u\ncd /data/app\necho hello'
        fixed = normalize_tool_args("toolkit_exec", raw)
        assert fixed is not None
        parsed = json.loads(fixed)
        assert parsed["app"] == "bash"
        # 关键回归点：旧实现返回 args == ["-lc"]，命令内容被静默丢弃
        assert parsed["args"] == ["-lc", "set -u\ncd /data/app\necho hello"]

    def test_real_newline_complete_repaired(self):
        """完整 JSON 但字符串内是真实换行：原实现判为不可修复并丢弃"""
        from tea_agent.session.json_sanitizer import normalize_tool_args
        raw = '{"app": "bash", "args": ["-lc", "echo a\necho b"]}'
        fixed = normalize_tool_args("toolkit_exec", raw)
        assert fixed is not None
        assert json.loads(fixed)["args"][1] == "echo a\necho b"

    def test_valid_json_still_byte_identical(self):
        """合法 JSON 仍逐字节原样返回（不得因新步骤被重写）"""
        from tea_agent.session.json_sanitizer import normalize_tool_args
        raw = '{"app": "bash", "args": ["-lc", "echo hi"], "timeout": 30}'
        assert normalize_tool_args("toolkit_exec", raw) == raw

    def test_relaxed_json_loads_handles_bare_value(self):
        """relaxed_json_loads 同样能解析裸值"""
        from tea_agent.basesession import relaxed_json_loads
        assert relaxed_json_loads('{"app": bash, "args": ["-lc"]}') == {
            "app": "bash", "args": ["-lc"]
        }

    def test_relaxed_json_loads_handles_real_newline(self):
        """relaxed_json_loads 保留真实换行内容"""
        from tea_agent.basesession import relaxed_json_loads
        assert relaxed_json_loads('{"cmd": "echo a\necho b"}')["cmd"] == "echo a\necho b"

    def test_raw_inner_quotes_complete_repaired(self):
        """完整 JSON 但脚本里有未转义的裸引号（echo "x"）：原实现直接丢弃"""
        from tea_agent.session.json_sanitizer import normalize_tool_args
        raw = '{"app": bash, "args": ["-lc", "echo "=== start ===" && ls -l"]}'
        fixed = normalize_tool_args("toolkit_exec", raw)
        assert fixed is not None
        assert json.loads(fixed) == {
            "app": "bash", "args": ["-lc", 'echo "=== start ===" && ls -l']
        }

    def test_raw_inner_quotes_truncated_keeps_full_command(self):
        """裸引号 + 截断：不得退化成砍掉后半段（args 只剩 ["-lc"]）"""
        from tea_agent.session.json_sanitizer import normalize_tool_args
        raw = '{"app": "bash", "args": ["-lc", "set -u\necho "=== start ==="\ncd /data/app'
        fixed = normalize_tool_args("toolkit_exec", raw)
        assert fixed is not None
        parsed = json.loads(fixed)
        assert len(parsed["args"]) == 2
        assert parsed["args"][1] == 'set -u\necho "=== start ==="\ncd /data/app'

    def test_embedded_sample_bare_value_truncated(self):
        """线上日志样本（前 100 字符）：裸值 + 截断，必须修复且内容完整"""
        from tea_agent.session.json_sanitizer import normalize_tool_args
        raw = (
            r'{"app": bash, "args": ["-lc", "set -u\nR=/userdata/zonekey/sunkw/zk_analysis_rk'
            r'\nT=/tmp/pkgtest\nZ=$'
        )
        fixed = normalize_tool_args("toolkit_exec", raw)
        assert fixed is not None
        parsed = json.loads(fixed)
        assert parsed["app"] == "bash"
        assert len(parsed["args"]) == 2
        assert "zk_analysis_rk" in parsed["args"][1]
        assert parsed["args"][1].endswith("Z=$")

    def test_sanitize_repairs_instead_of_dropping(self):
        """历史消息 sanitize 也应修复裸值参数，而不是移除该 tool_call"""
        from tea_agent.session.json_sanitizer import sanitize_api_messages
        messages = [{
            "role": "assistant",
            "content": "",
            "tool_calls": [{
                "id": "c1",
                "type": "function",
                "function": {
                    "name": "toolkit_exec",
                    "arguments": '{"app": bash, "args": ["-lc", "df -h"]}',
                },
            }],
        }]
        result = sanitize_api_messages(messages)
        assert len(result) == 1
        calls = result[0].get("tool_calls")
        assert calls and len(calls) == 1
        assert json.loads(calls[0]["function"]["arguments"]) == {
            "app": "bash", "args": ["-lc", "df -h"]
        }


# ============================================================
# fix_invalid_escapes — JSON 非法转义序列修复
# ============================================================
# 实测依据：~/.tea_agent/tea_agent.log 中 toolkit_exec 长参数被丢弃的首要原因是
# json.loads 报 Invalid \escape —— 模型把 Python/路径字面量里的单引号按母语习惯
# 转义为 \'，而 JSON 仅允许 9 种转义前导字符。
# 注：用 chr() 构造反斜杠，使本文件源码不含裸转义序列，便于审阅与维护。

_BS = chr(92)   # 单个反斜杠
_SQ = chr(39)   # 单引号
_DQ = chr(34)   # 双引号


class TestFixInvalidEscapes:
    """非法转义序列（\' 等）的修复。"""

    def test_invalid_quote_escape_repaired(self):
        """\' 属非法转义，去掉多余反斜杠后应可解析。"""
        from tea_agent.session.json_sanitizer import fix_invalid_escapes

        raw = '{"code": "os.chdir(r' + _BS + _SQ + 'C:' + _BS + _BS + 'Users' + _BS + _SQ + ')"}'
        obj = json.loads(fix_invalid_escapes(raw))
        assert obj == {"code": "os.chdir(r'C:" + _BS + "Users')"}

    def test_raw_backslash_before_letter_repaired(self):
        """反斜杠 + 普通字母（非 JSON 合法转义）应补成字面反斜杠。"""
        from tea_agent.session.json_sanitizer import fix_invalid_escapes

        raw = '{"p": "C:' + _BS + 'Users"}'
        obj = json.loads(fix_invalid_escapes(raw))
        assert obj == {"p": "C:" + _BS + "Users"}

    def test_regex_backslash_d_repaired(self):
        from tea_agent.session.json_sanitizer import fix_invalid_escapes

        raw = '{"re": "' + _BS + 'd+"}'
        obj = json.loads(fix_invalid_escapes(raw))
        assert obj == {"re": _BS + "d+"}

    def test_valid_escapes_byte_identical(self):
        """9 种合法转义必须逐字节保持不变（前缀缓存友好）。"""
        from tea_agent.session.json_sanitizer import fix_invalid_escapes

        samples = [
            '{"a": "x' + _BS + 'ny"}',            # \n
            '{"a": "x' + _BS + 'ty"}',            # \t
            '{"a": "x' + _BS + 'ry"}',            # \r
            '{"a": "x' + _BS + _BS + 'y"}',        # 字面反斜杠
            '{"a": "x' + _BS + _DQ + 'y"}',        # \"
            '{"a": "x' + _BS + 'u4e2dy"}',         # \uXXXX
            '{"a": "x' + _BS + '/y"}',             # \/
            '{"a": "x' + _BS + 'by"}',             # \b
            '{"a": "x' + _BS + 'fy"}',             # \f
        ]
        for s in samples:
            assert fix_invalid_escapes(s) == s, s

    def test_no_backslash_fast_path(self):
        from tea_agent.session.json_sanitizer import fix_invalid_escapes

        s = '{"a": "b"}'
        assert fix_invalid_escapes(s) == s

    def test_empty_and_plain_inputs(self):
        from tea_agent.session.json_sanitizer import fix_invalid_escapes

        assert fix_invalid_escapes("") == ""
        assert fix_invalid_escapes("abc") == "abc"

    def test_idempotent(self):
        from tea_agent.session.json_sanitizer import fix_invalid_escapes

        raw = '{"code": "a' + _BS + _SQ + 'b"}'
        once = fix_invalid_escapes(raw)
        assert fix_invalid_escapes(once) == once
        assert json.loads(once)

    def test_normalize_tool_args_repairs_invalid_escape(self):
        """端到端：曾直接 DROP 的真实载荷，现在必须修复成功。"""
        from tea_agent.session.json_sanitizer import normalize_tool_args

        raw = (
            '{"app": "python", "args": ["-c", "import subprocess,os' + _BS + 'n'
            + 'os.chdir(r' + _BS + _SQ + 'C:' + _BS + _BS + 'Users' + _BS + _SQ + ')"' + ']}'
        )
        fixed = normalize_tool_args("toolkit_exec", raw)
        assert fixed is not None, "不应再被丢弃"
        obj = json.loads(fixed)
        assert obj["app"] == "python"
        assert "os.chdir" in obj["args"][1]

    def test_normalize_keeps_full_command_not_truncated(self):
        """关键安全属性：修复必须保留完整命令，禁止退化成「从尾部删除」静默截断。"""
        from tea_agent.session.json_sanitizer import normalize_tool_args

        tail = "MARKER_TAIL_SHOULD_SURVIVE"
        raw = (
            '{"app": "python", "args": ["-c", "import os' + _BS + 'n'
            + 'os.chdir(r' + _BS + _SQ + 'C:' + _BS + _BS + 'x' + _BS + _SQ + ')"' + _BS + 'n'
            + tail + '"]}'
        )
        fixed = normalize_tool_args("toolkit_exec", raw)
        assert fixed is not None
        assert tail in fixed, "命令尾部被静默截断"

    def test_normalize_bare_value_with_invalid_escape(self):
        """裸值 + 非法转义 组合缺陷（日志 08:56 形态）。"""
        from tea_agent.session.json_sanitizer import normalize_tool_args

        raw = (
            '{"app": python, "args": ["-c", "p=r' + _BS + _SQ + 'C:' + _BS + _BS + 'Users' + _SQ
            + _BS + 'n' + 'print(p)"]}'
        )
        fixed = normalize_tool_args("toolkit_exec", raw)
        assert fixed is not None
        obj = json.loads(fixed)
        assert obj["app"] == "python"

    def test_sanitize_api_messages_repairs_invalid_escape(self):
        """历史脏参数（已入库）同样应被修复而非移除。"""
        from tea_agent.session.json_sanitizer import sanitize_api_messages

        raw = '{"cmd": "echo ' + _BS + _SQ + 'hi' + _BS + _SQ + '"}'
        msgs = [{
            "role": "assistant",
            "content": "",
            "tool_calls": [{
                "id": "1",
                "type": "function",
                "function": {"name": "toolkit_exec", "arguments": raw},
            }],
        }]
        out = sanitize_api_messages(msgs)
        calls = out[0].get("tool_calls")
        assert calls, "tool_call 不应被移除"
        json.loads(calls[0]["function"]["arguments"])

    def test_try_fix_truncated_handles_invalid_escape(self):
        from tea_agent.session.json_sanitizer import try_fix_truncated_json

        raw = '{"a": "x' + _BS + _SQ + 'y"}'
        fixed = try_fix_truncated_json(raw)
        assert fixed is not None
        assert json.loads(fixed) == {"a": "x'y"}

    def test_valid_json_still_byte_identical_end_to_end(self):
        """合法 JSON 经 normalize 必须原样返回（不重排、不重编码）。"""
        from tea_agent.session.json_sanitizer import normalize_tool_args

        raw = '{"app": "python", "args": ["-c", "print(1)"]}'
        assert normalize_tool_args("toolkit_exec", raw) == raw


# ============================================================
# Windows 路径字面量保护（2026-09-19）
# ============================================================

class TestWindowsPathProtection:
    """`\\t \\f \\n \\b \\r` 在 Windows 路径里应读作「字面反斜杠 + 字母」。

    修复链按 JSON 语义透传时，路径会被静默改写（``C:\\foo`` → ``C:<换页>oo``）：
    语法上无可指摘，但用户拿到一个不存在的路径且毫无提示。
    修法为**窄条件** —— 仅当字面量自身以盘符（``X:\\`` / ``X:/``）或 UNC（``\\\\``）
    开头时才保护，故 ``"a\\tb"``（真制表符）与 ``"C:\\temp"``（路径）能各得其所。
    """

    def test_path_backslash_t_preserved(self):
        """路径里的 \\t 不得解为制表符。"""
        from tea_agent.session.json_sanitizer import normalize_tool_args

        raw = '{"filename": "C:' + _BS + 'tea_agent"}'
        got = json.loads(normalize_tool_args("toolkit_file", raw))
        assert got == {"filename": "C:" + _BS + "tea_agent"}, got

    def test_path_backslash_f_preserved(self):
        """路径里的 \\f 不得解为换页符。"""
        from tea_agent.session.json_sanitizer import normalize_tool_args

        raw = '{"path": "C:' + _BS + 'foo' + _BS + 'file.py"}'
        got = json.loads(normalize_tool_args("toolkit_file", raw))
        assert got == {"path": "C:" + _BS + "foo" + _BS + "file.py"}, got

    def test_path_backslash_n_b_r_preserved(self):
        """\\n \\b \\r 在路径里同样保持字面。"""
        from tea_agent.session.json_sanitizer import normalize_tool_args

        raw = '{"p": "C:' + _BS + 'new' + _BS + 'backup' + _BS + 'repo"}'
        got = json.loads(normalize_tool_args("t", raw))
        assert got == {"p": "C:" + _BS + "new" + _BS + "backup" + _BS + "repo"}, got

    def test_unc_path_ambiguous_escape_preserved(self):
        """UNC 形态：歧义转义保持字面。

        注：JSON 文本里的前导 ``\\\\`` 按规范就是**一个**字面反斜杠，
        故期望值是 1 个前导反斜杠 —— 与保护逻辑无关，是 JSON 语义本身。
        """
        from tea_agent.session.json_sanitizer import normalize_tool_args

        raw = '{"p": "' + _BS * 2 + 'srv' + _BS + 'share' + _BS + 'f.txt"}'
        got = json.loads(normalize_tool_args("t", raw))
        assert got == {"p": _BS + "srv" + _BS + "share" + _BS + "f.txt"}, got

    def test_non_path_tab_keeps_semantics(self):
        """非路径字面量里的 \\t 仍须是制表符 —— 保护不得越界。"""
        from tea_agent.session.json_sanitizer import normalize_tool_args

        raw = '{"a": "x' + _BS + 'ty"}'
        got = json.loads(normalize_tool_args("t", raw))
        assert got == {"a": "x\ty"}, got

    def test_path_and_tab_coexist_in_one_json(self):
        """同一 JSON 内路径与制表符并存，各自正确（窄范围的关键证据）。"""
        from tea_agent.session.json_sanitizer import normalize_tool_args

        raw = '{"path": "C:' + _BS + 'foo", "note": "a' + _BS + 'tb"}'
        got = json.loads(normalize_tool_args("t", raw))
        assert got == {"path": "C:" + _BS + "foo", "note": "a\tb"}, got

    def test_valid_double_backslash_not_double_escaped(self):
        """已是合法 JSON 的双反斜杠路径不得被二次转义。"""
        from tea_agent.session.json_sanitizer import normalize_tool_args

        raw = '{"p": "C:' + _BS * 2 + 'Users' + _BS * 2 + 'x"}'
        assert normalize_tool_args("t", raw) == raw

    def test_escape_path_backslashes_identity(self):
        """非路径输入必须**逐字节不变**（前缀缓存友好，且绝不误改）。"""
        from tea_agent.session.json_sanitizer import escape_path_backslashes

        for t in ('{"a": 1}', '{"a": "x' + _BS + 'ty"}', '{"p": "/unix/path/t"}',
                  '{"url": "https://x.test/a"}', '{"a": "a' + _BS * 2 + 'b"}', "", "no backslash"):
            assert escape_path_backslashes(t) == t, repr(t)

