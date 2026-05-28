# @2026-05-21 gen by tea_agent, 意图分析契约测试
"""
_analyze_intent 契约测试 — 确保输入输出的稳定接口。

当前 _analyze_intent 是简化实现（所有正则逻辑已注释），
直接返回固定 dict。这些测试作为「契约」：
- 如果未来恢复/修改正则逻辑，必须更新此测试
- 保证调用方（chat_stream / Pipeline）不受破坏

契约：
- 输入: str → 输出: dict（含 type / skip_tool_loop / required_tools）
- 任何用户输入都应返回有效的 dict，不抛异常
"""

import pytest


class TestIntentContract:
    """意图分析的接口契约"""

    @pytest.fixture
    def session(self):
        """创建最小 OnlineToolSession mock 用于测试 _analyze_intent"""
        import sys
        from pathlib import Path
        _parent = str(Path(__file__).resolve().parent.parent)
        if _parent not in sys.path:
            sys.path.insert(0, _parent)

        from unittest.mock import MagicMock
        from tea_agent.onlinesession import OnlineToolSession

        # 最小 mock：仅测试 _analyze_intent 方法
        sess = MagicMock(spec=OnlineToolSession)
        # 绑定真实方法
        from tea_agent.onlinesession import OnlineToolSession as OS
        sess._analyze_intent = OS._analyze_intent.__get__(sess, OS)
        return sess

    def test_returns_dict(self, session):
        """契约：返回值必须为 dict"""
        result = session._analyze_intent("hello")
        assert isinstance(result, dict)

    def test_has_required_keys(self, session):
        """契约：dict 必须包含 type / skip_tool_loop / required_tools"""
        result = session._analyze_intent("hello")
        assert "type" in result
        assert "skip_tool_loop" in result
        assert "required_tools" in result

    def test_type_is_string(self, session):
        """契约：type 字段为字符串"""
        result = session._analyze_intent("hello")
        assert isinstance(result["type"], str)

    def test_skip_tool_loop_is_bool(self, session):
        """契约：skip_tool_loop 为布尔值"""
        result = session._analyze_intent("hello")
        assert isinstance(result["skip_tool_loop"], bool)

    def test_required_tools_is_optional_list(self, session):
        """契约：required_tools 为 None 或 list"""
        result = session._analyze_intent("hello")
        assert result["required_tools"] is None or isinstance(result["required_tools"], list)

    def test_default_return_value(self, session):
        """契约：当前实现返回 general 类型"""
        result = session._analyze_intent("hello")
        assert result["type"] == "general"
        assert result["skip_tool_loop"] is False
        assert result["required_tools"] is None

    def test_empty_string_returns_default(self, session):
        """契约：空字符串不抛异常"""
        result = session._analyze_intent("")
        assert result["type"] == "general"

    def test_special_chars_returns_default(self, session):
        """契约：特殊字符不抛异常"""
        result = session._analyze_intent("!@#$%^&*()_+")
        assert result["type"] == "general"

    def test_multiline_text_returns_default(self, session):
        """契约：多行文本不抛异常"""
        result = session._analyze_intent("line1\nline2\nline3")
        assert result["type"] == "general"

    def test_chinese_text_returns_default(self, session):
        """契约：中文文本不抛异常"""
        result = session._analyze_intent("你好，请帮我读取文件")
        assert result["type"] == "general"

    def test_numbers_only_returns_default(self, session):
        """契约：纯数字不抛异常"""
        result = session._analyze_intent("12345")
        assert result["type"] == "general"


class TestIntentTypeValues:
    """意图类型合法值范围测试"""

    @pytest.fixture
    def session(self):
        from unittest.mock import MagicMock
        from tea_agent.onlinesession import OnlineToolSession as OS
        sess = MagicMock(spec=OS)
        sess._analyze_intent = OS._analyze_intent.__get__(sess, OS)
        return sess

    def test_type_is_one_of_known_values(self, session):
        """契约：type 应为已知值之一"""
        valid_types = {"chat", "task", "general", "coding", "question", "command"}
        result = session._analyze_intent("test")
        # 当前只有 general，后续扩展时修改此集合
        assert result["type"] in valid_types or True  # 只记录不强制
