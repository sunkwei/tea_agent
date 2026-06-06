"""
OnlineSession 模块级函数测试 — detect_mode 和 extract_mode。

analyze_intent 已在 test_session_intent.py 中覆盖。
"""

import pytest
from tea_agent.onlinesession import detect_mode, extract_mode


class TestDetectMode:
    """detect_mode: 根据用户输入检测建议模式"""

    def test_returns_dict_with_mock(self):
        """正常调用返回 dict"""
        def mock_call_tool(action, text):
            return {"switched": False, "mode": "pragmatic"}

        result = detect_mode(mock_call_tool, "hello")
        assert isinstance(result, dict)

    def test_switched_true_when_mode_changes(self):
        """当模式变化时 switched=True"""
        def mock_call_tool(action, text):
            return {"switched": True, "from_mode": "mixed", "to_mode": "pragmatic", "reason": "code"}

        result = detect_mode(mock_call_tool, "write some code")
        assert result["switched"] is True
        assert result["from_mode"] == "mixed"
        assert result["to_mode"] == "pragmatic"

    def test_switched_false_when_no_change(self):
        """模式未变化时 switched=False"""
        def mock_call_tool(action, text):
            return {"switched": False, "mode": None}

        result = detect_mode(mock_call_tool, "hello")
        assert result["switched"] is False

    def test_exception_returns_default(self):
        """异常时返回默认 dict"""
        def mock_call_tool(action, text):
            raise RuntimeError("tool not available")

        result = detect_mode(mock_call_tool, "hello")
        assert result["switched"] is False
        assert "error" in result

    def test_non_dict_result_handled(self):
        """非 dict 返回值也能处理"""
        def mock_call_tool(action, text):
            return "not a dict"

        result = detect_mode(mock_call_tool, "hello")
        assert isinstance(result, dict)
        assert result["switched"] is False


class TestExtractMode:
    """extract_mode: 从 detect_mode 结果中提取合法模式"""

    def test_extracts_from_to_mode(self):
        """从 to_mode 提取"""
        result = extract_mode({"to_mode": "pragmatic"})
        assert result == "pragmatic"

    def test_extracts_from_mode(self):
        """从 mode 提取"""
        result = extract_mode({"mode": "creative"})
        assert result == "creative"

    def test_extracts_from_detected(self):
        """从 detected 提取"""
        result = extract_mode({"detected": "mixed"})
        assert result == "mixed"

    def test_priority_to_mode_over_mode(self):
        """to_mode 优先于 mode"""
        result = extract_mode({"to_mode": "pragmatic", "mode": "creative"})
        assert result == "pragmatic"

    def test_invalid_mode_returns_none(self):
        """无效模式返回 None"""
        result = extract_mode({"to_mode": "invalid_mode_xyz"})
        assert result is None

    def test_empty_dict_returns_none(self):
        """空 dict 返回 None"""
        result = extract_mode({})
        assert result is None

    def test_none_value_returns_none(self):
        """None 值返回 None"""
        result = extract_mode({"to_mode": None})
        assert result is None

    def test_all_valid_modes_accepted(self):
        """所有合法模式均可提取"""
        for mode in ("pragmatic", "creative", "mixed"):
            result = extract_mode({"to_mode": mode})
            assert result == mode
