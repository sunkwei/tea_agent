"""
历史消息构建模块单元测试 — 覆盖 get_subconscious_context 和 to_multimodal。

测试范围:
- get_subconscious_context: 正常读取 / 无数据 / 文件不存在
- to_multimodal: 支持视觉 / 不支持视觉 / 有图片 / 无图片
"""

import json
import os
import pytest
from unittest.mock import patch, MagicMock


# ============================================================
# 1. get_subconscious_context
# ============================================================

class TestGetSubconsciousContext:
    """潜意识上下文读取测试"""

    def test_returns_none_when_file_not_exists(self, tmp_path):
        """文件不存在时应返回 None"""
        from tea_agent.session._history_builder import get_subconscious_context
        result = get_subconscious_context(str(tmp_path))
        assert result is None

    def test_returns_none_when_empty_state(self, tmp_path):
        """空状态文件应返回 None"""
        from tea_agent.session._history_builder import get_subconscious_context
        state_file = tmp_path / "subconscious_state.json"
        state_file.write_text(json.dumps({"goals": [], "insights": [], "last_focus": "mixed"}))
        result = get_subconscious_context(str(tmp_path))
        assert result is None

    def test_returns_context_with_goals(self, tmp_path):
        """有目标时应返回格式化上下文"""
        from tea_agent.session._history_builder import get_subconscious_context
        state = {
            "goals": ["目标1", "目标2"],
            "insights": [],
            "last_focus": "pragmatic"
        }
        state_file = tmp_path / "subconscious_state.json"
        state_file.write_text(json.dumps(state))
        
        result = get_subconscious_context(str(tmp_path))
        assert result is not None
        assert "潜意识引擎状态" in result
        assert "pragmatic" in result
        assert "目标1" in result
        assert "目标2" in result

    def test_returns_context_with_insights(self, tmp_path):
        """有洞察时应返回格式化上下文"""
        from tea_agent.session._history_builder import get_subconscious_context
        state = {
            "goals": [],
            "insights": ["洞察A", "洞察B"],
            "last_focus": "creative"
        }
        state_file = tmp_path / "subconscious_state.json"
        state_file.write_text(json.dumps(state))
        
        result = get_subconscious_context(str(tmp_path))
        assert result is not None
        assert "洞察A" in result
        assert "洞察B" in result

    def test_returns_context_with_both(self, tmp_path):
        """同时有目标和洞察时应返回完整上下文"""
        from tea_agent.session._history_builder import get_subconscious_context
        state = {
            "goals": ["目标1"],
            "insights": ["洞察1"],
            "last_focus": "mixed"
        }
        state_file = tmp_path / "subconscious_state.json"
        state_file.write_text(json.dumps(state))
        
        result = get_subconscious_context(str(tmp_path))
        assert result is not None
        assert "🎯" in result
        assert "💡" in result
        assert "目标1" in result
        assert "洞察1" in result

    def test_limits_goals_and_insights_to_3(self, tmp_path):
        """最多显示 3 个目标和 3 个洞察"""
        from tea_agent.session._history_builder import get_subconscious_context
        state = {
            "goals": ["g1", "g2", "g3", "g4", "g5"],
            "insights": ["i1", "i2", "i3", "i4"],
            "last_focus": "mixed"
        }
        state_file = tmp_path / "subconscious_state.json"
        state_file.write_text(json.dumps(state))
        
        result = get_subconscious_context(str(tmp_path))
        assert result is not None
        # g4, g5, i4 不应出现
        assert "g4" not in result
        assert "g5" not in result
        assert "i4" not in result

    def test_handles_invalid_json(self, tmp_path):
        """无效 JSON 应返回 None"""
        from tea_agent.session._history_builder import get_subconscious_context
        state_file = tmp_path / "subconscious_state.json"
        state_file.write_text("not valid json{{{")
        
        result = get_subconscious_context(str(tmp_path))
        assert result is None


# ============================================================
# 2. to_multimodal
# ============================================================

class TestToMultimodal:
    """多模态消息转换测试"""

    def test_no_images_returns_unchanged(self):
        """无图片时应原样返回"""
        from tea_agent.session._history_builder import to_multimodal
        msg = {"role": "user", "content": "hello"}
        result = to_multimodal(msg, supports_vision=True)
        assert result["content"] == "hello"
        assert "images" not in result

    def test_empty_images_returns_unchanged(self):
        """空图片列表应原样返回"""
        from tea_agent.session._history_builder import to_multimodal
        msg = {"role": "user", "content": "hello", "images": []}
        result = to_multimodal(msg, supports_vision=True)
        assert result["content"] == "hello"
        assert "images" not in result

    def test_vision_supported_converts_to_multimodal(self, tmp_path):
        """支持视觉时应转换为多模态格式"""
        from tea_agent.session._history_builder import to_multimodal
        # 创建临时图片文件
        img_path = tmp_path / "test.png"
        img_path.write_bytes(b"fake png data")
        
        msg = {
            "role": "user",
            "content": "描述这张图片",
            "images": [str(img_path)]
        }
        result = to_multimodal(msg, supports_vision=True)
        assert "images" not in result
        assert isinstance(result["content"], list)
        assert len(result["content"]) == 2  # text + image
        assert result["content"][0]["type"] == "text"
        assert result["content"][0]["text"] == "描述这张图片"
        assert result["content"][1]["type"] == "image_url"

    def test_vision_not_supported_removes_images(self, tmp_path):
        """不支持视觉时应移除图片"""
        from tea_agent.session._history_builder import to_multimodal
        img_path = tmp_path / "test.png"
        img_path.write_bytes(b"fake png data")
        
        msg = {
            "role": "user",
            "content": "描述这张图片",
            "images": [str(img_path)]
        }
        result = to_multimodal(msg, supports_vision=False)
        assert result["content"] == "描述这张图片"
        assert "images" not in result

    def test_multiple_images(self, tmp_path):
        """多图片应全部转换"""
        from tea_agent.session._history_builder import to_multimodal
        # 创建多个临时图片文件
        img1 = tmp_path / "test1.png"
        img1.write_bytes(b"fake png 1")
        img2 = tmp_path / "test2.jpg"
        img2.write_bytes(b"fake jpg 2")
        
        msg = {
            "role": "user",
            "content": "比较这两张图",
            "images": [str(img1), str(img2)]
        }
        result = to_multimodal(msg, supports_vision=True)
        assert isinstance(result["content"], list)
        assert len(result["content"]) == 3  # text + 2 images

    def test_removes_images_key_from_result(self, tmp_path):
        """转换后应移除 images 键"""
        from tea_agent.session._history_builder import to_multimodal
        img_path = tmp_path / "test.png"
        img_path.write_bytes(b"fake png data")
        
        msg = {
            "role": "user",
            "content": "test",
            "images": [str(img_path)]
        }
        result = to_multimodal(msg, supports_vision=True)
        assert "images" not in result
