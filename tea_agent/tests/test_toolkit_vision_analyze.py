"""
toolkit_vision_analyze 测试 — 视觉模型委托分析工具
"""

from unittest.mock import MagicMock, patch


def test_meta_exists():
    """工具应注册到 Toolkit.meta_map"""
    from tea_agent.tlk import Toolkit
    tk = Toolkit()
    assert "toolkit_vision_analyze" in tk.meta_map
    meta = tk.meta_map["toolkit_vision_analyze"]
    assert meta["function"]["name"] == "toolkit_vision_analyze"
    props = meta["function"]["parameters"]["properties"]
    assert "image" in props
    assert "image" in meta["function"]["parameters"]["required"]


def test_to_data_url_passthrough_data_url():
    """data URL 原样透传"""
    from tea_agent.toolkit.toolkit_vision_analyze import _to_data_url
    url = "data:image/png;base64,AAAA"
    assert _to_data_url(url) == url


def test_to_data_url_remote_url():
    """http(s) URL 原样透传（模型端拉取）"""
    from tea_agent.toolkit.toolkit_vision_analyze import _to_data_url
    assert _to_data_url("https://x.com/a.png") == "https://x.com/a.png"


def test_to_data_url_local_file(tmp_path):
    """本地文件编码为 base64 data URL"""
    from tea_agent.toolkit.toolkit_vision_analyze import _to_data_url
    img = tmp_path / "test.png"
    img.write_bytes(b"\x89PNG fake")
    result = _to_data_url(str(img))
    assert result.startswith("data:image/png;base64,")


def test_to_data_url_missing_file():
    """不存在的路径返回 None"""
    from tea_agent.toolkit.toolkit_vision_analyze import _to_data_url
    assert _to_data_url("nonexistent.png") is None


def test_analyze_no_vision_model():
    """未配置视觉模型时返回清晰错误"""
    with patch("tea_agent.toolkit.toolkit_vision_analyze._get_vision_client",
               return_value=(None, None, None)):
        from tea_agent.toolkit.toolkit_vision_analyze import toolkit_vision_analyze
        result = toolkit_vision_analyze(image="/tmp/x.png")
        assert result["ok"] is False
        assert "未配置视觉模型" in result["error"]


def test_analyze_success():
    """配置视觉模型时返回分析文本"""
    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.choices[0].message.content = "图片中有一只猫"
    mock_client.chat.completions.create.return_value = mock_resp

    with patch("tea_agent.toolkit.toolkit_vision_analyze._get_vision_client",
               return_value=(mock_client, "mimo-v2.5", {"supports_reasoning": True})):
        from tea_agent.toolkit.toolkit_vision_analyze import toolkit_vision_analyze
        result = toolkit_vision_analyze(
            image="data:image/png;base64,AAAA", prompt="描述这张图"
        )
        assert result["ok"] is True
        assert result["text"] == "图片中有一只猫"
        assert result["model"] == "mimo-v2.5"
        # 验证请求体包含 image_url 与 prompt
        _, kwargs = mock_client.chat.completions.create.call_args
        content = kwargs["messages"][0]["content"]
        assert content[0]["type"] == "text"
        assert content[0]["text"] == "描述这张图"
        assert content[1]["type"] == "image_url"
        assert content[1]["image_url"]["url"] == "data:image/png;base64,AAAA"


def test_analyze_api_error():
    """视觉模型调用失败时返回错误（失败隔离）"""
    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = RuntimeError("API down")

    with patch("tea_agent.toolkit.toolkit_vision_analyze._get_vision_client",
               return_value=(mock_client, "mimo-v2.5", {})):
        from tea_agent.toolkit.toolkit_vision_analyze import toolkit_vision_analyze
        result = toolkit_vision_analyze(image="data:image/png;base64,AAAA")
        assert result["ok"] is False
        assert "视觉模型调用失败" in result["error"]
