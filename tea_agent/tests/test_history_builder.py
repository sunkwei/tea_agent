"""
历史消息构建模块单元测试 — 覆盖 to_multimodal。

测试范围:
- to_multimodal: 支持视觉 / 不支持视觉 / 有图片 / 无图片
"""



# ============================================================
# to_multimodal
# ============================================================

class TestToMultimodal:
    """多模态消息转换测试"""

    def test_no_images_returns_unchanged(self):
        """无图片时应原样返回"""
        from tea_agent.session.history_builder import to_multimodal
        msg = {"role": "user", "content": "hello"}
        result = to_multimodal(msg, supports_vision=True)
        assert result["content"] == "hello"
        assert "images" not in result

    def test_empty_images_returns_unchanged(self):
        """空图片列表应原样返回"""
        from tea_agent.session.history_builder import to_multimodal
        msg = {"role": "user", "content": "hello", "images": []}
        result = to_multimodal(msg, supports_vision=True)
        assert result["content"] == "hello"
        assert "images" not in result

    def test_vision_supported_converts_to_multimodal(self, tmp_path):
        """支持视觉时应转换为多模态格式"""
        from tea_agent.session.history_builder import to_multimodal
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
        from tea_agent.session.history_builder import to_multimodal
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
        from tea_agent.session.history_builder import to_multimodal
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
        from tea_agent.session.history_builder import to_multimodal
        img_path = tmp_path / "test.png"
        img_path.write_bytes(b"fake png data")

        msg = {
            "role": "user",
            "content": "test",
            "images": [str(img_path)]
        }
        result = to_multimodal(msg, supports_vision=True)
        assert "images" not in result

    def test_data_url_passthrough(self):
        """data URL 图片（API server 传入）应直接透传，不当作文件路径处理"""
        from tea_agent.session.history_builder import to_multimodal
        data_url = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="

        msg = {
            "role": "user",
            "content": "看看这张图",
            "images": [data_url],
        }
        result = to_multimodal(msg, supports_vision=True)
        parts = result["content"]
        assert isinstance(parts, list)
        assert len(parts) == 2  # text + image
        assert parts[0]["type"] == "text"
        assert parts[1]["type"] == "image_url"
        assert parts[1]["image_url"]["url"] == data_url
        assert "images" not in result

    def test_messages_contain_images_detects_image_url(self):
        """含 image_url 内容的消息应被识别为含图"""
        from tea_agent.session.history_builder import messages_contain_images
        msgs = [
            {"role": "user", "content": "文本"},
            {"role": "user", "content": [
                {"type": "text", "text": "描述"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,xx"}},
            ]},
        ]
        assert messages_contain_images(msgs) is True

    def test_messages_contain_images_detects_images_field(self):
        """含未转换 images 字段的消息应被识别为含图"""
        from tea_agent.session.history_builder import messages_contain_images
        msgs = [{"role": "user", "content": "文本", "images": ["/tmp/a.png"]}]
        assert messages_contain_images(msgs) is True

    def test_messages_contain_images_false_for_text(self):
        """纯文本消息列表返回 False"""
        from tea_agent.session.history_builder import messages_contain_images
        msgs = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "你好！"},
        ]
        assert messages_contain_images(msgs) is False
