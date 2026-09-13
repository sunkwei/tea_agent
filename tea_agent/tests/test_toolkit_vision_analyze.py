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


def test_analyze_empty_content_on_length():
    """回归：reasoning 耗尽 max_tokens 时不得静默返回 ok=True + 空文本。

    实测：max_tokens=300 时推理占满 300，content 为空、finish_reason='length'。
    旧实现返回 ok=True，调用方会误判为「图中无内容」。
    """
    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.choices[0].message.content = ""
    mock_resp.choices[0].finish_reason = "length"
    mock_client.chat.completions.create.return_value = mock_resp

    with patch("tea_agent.toolkit.toolkit_vision_analyze._get_vision_client",
               return_value=(mock_client, "deepseek-v4-flash-vision-exp", {})):
        from tea_agent.toolkit.toolkit_vision_analyze import toolkit_vision_analyze
        result = toolkit_vision_analyze(image="data:image/png;base64,AAAA", max_tokens=300)
        assert result["ok"] is False, "空文本不得伪装成功"
        assert "max_tokens" in result["error"]
        assert result["finish_reason"] == "length"


def test_analyze_empty_content_on_stop():
    """通用：任何空输出都报错（区分 finish_reason）"""
    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.choices[0].message.content = ""
    mock_resp.choices[0].finish_reason = "stop"
    mock_client.chat.completions.create.return_value = mock_resp

    with patch("tea_agent.toolkit.toolkit_vision_analyze._get_vision_client",
               return_value=(mock_client, "m", {})):
        from tea_agent.toolkit.toolkit_vision_analyze import toolkit_vision_analyze
        result = toolkit_vision_analyze(image="data:image/png;base64,AAAA")
        assert result["ok"] is False
        assert "输出为空" in result["error"]


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


def test_analyze_detail_passthrough():
    """detail 参数应透传到 image_url 内容块（DeepSeek 视觉 API）"""
    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.choices[0].message.content = "蓝色"
    mock_client.chat.completions.create.return_value = mock_resp

    with patch("tea_agent.toolkit.toolkit_vision_analyze._get_vision_client",
               return_value=(mock_client, "deepseek-v4-flash-vision-exp", {})):
        from tea_agent.toolkit.toolkit_vision_analyze import toolkit_vision_analyze
        result = toolkit_vision_analyze(image="data:image/png;base64,AAAA", detail="high")
        assert result["ok"] is True
        _, kwargs = mock_client.chat.completions.create.call_args
        content = kwargs["messages"][0]["content"]
        assert content[1]["type"] == "image_url"
        assert content[1]["image_url"]["url"] == "data:image/png;base64,AAAA"
        assert content[1]["image_url"]["detail"] == "high"


def test_analyze_detail_from_options():
    """detail 未显式传参时回退 options.detail"""
    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.choices[0].message.content = "红色"
    mock_client.chat.completions.create.return_value = mock_resp

    with patch("tea_agent.toolkit.toolkit_vision_analyze._get_vision_client",
               return_value=(mock_client, "deepseek-v4-flash-vision-exp", {"detail": "low"})):
        from tea_agent.toolkit.toolkit_vision_analyze import toolkit_vision_analyze
        result = toolkit_vision_analyze(image="data:image/png;base64,AAAA")
        assert result["ok"] is True
        _, kwargs = mock_client.chat.completions.create.call_args
        content = kwargs["messages"][0]["content"]
        assert content[1]["image_url"]["detail"] == "low"


def test_analyze_detail_invalid_omitted():
    """非法 detail 值应被省略（不发送给 API）"""
    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.choices[0].message.content = "OK"
    mock_client.chat.completions.create.return_value = mock_resp

    with patch("tea_agent.toolkit.toolkit_vision_analyze._get_vision_client",
               return_value=(mock_client, "m", {})):
        from tea_agent.toolkit.toolkit_vision_analyze import toolkit_vision_analyze
        result = toolkit_vision_analyze(image="data:image/png;base64,AAAA", detail="bogus")
        assert result["ok"] is True
        _, kwargs = mock_client.chat.completions.create.call_args
        content = kwargs["messages"][0]["content"]
        assert "detail" not in content[1]["image_url"]


# ── 韧性回退（首选视觉模型不可用时改用主模型）──


def _cfg_with_main(model_name: str, supports_vision: bool = True):
    """构造带 main_model 的配置 mock。"""
    cfg = MagicMock()
    cfg.main_model.supports_vision = supports_vision
    cfg.main_model.is_configured = True
    cfg.main_model.model_name = model_name
    cfg.main_model.options = {}
    return cfg


def test_fallback_to_main_model_when_vision_fails():
    """韧性回退：首选视觉模型失败（如配额耗尽）时改用支持视觉的主模型。

    实测动机：vision_model 所在 provider 月度配额用尽后，工具此前直接失败，
    而主模型本可完成同一任务 —— 单点故障不该废掉整条「截图→分析」能力。
    """
    primary = MagicMock()
    primary.chat.completions.create.side_effect = RuntimeError("429 quota exceeded")
    fallback = MagicMock()
    fb_resp = MagicMock()
    fb_resp.choices[0].message.content = "回退模型识别出的内容"
    fallback.chat.completions.create.return_value = fb_resp

    with patch("tea_agent.toolkit.toolkit_vision_analyze._get_vision_client",
               return_value=(primary, "primary-vision", {})):
        with patch("tea_agent.toolkit.toolkit_vision_analyze._client_for",
                   return_value=fallback):
            with patch("tea_agent.config.get_config",
                       return_value=_cfg_with_main("main-vision-model")):
                from tea_agent.toolkit.toolkit_vision_analyze import toolkit_vision_analyze
                result = toolkit_vision_analyze(image="data:image/png;base64,AAAA")
                assert result["ok"] is True
                assert result["text"] == "回退模型识别出的内容"
                assert result["model"] == "main-vision-model"
                assert result["fallback_from"] == "primary-vision"


def test_fallback_on_empty_output():
    """首选返回空内容（reasoning 耗尽预算）时同样触发回退。"""
    primary = MagicMock()
    empty = MagicMock()
    empty.choices[0].message.content = ""
    empty.choices[0].finish_reason = "length"
    primary.chat.completions.create.return_value = empty

    fallback = MagicMock()
    fb_resp = MagicMock()
    fb_resp.choices[0].message.content = "回退成功"
    fb_resp.choices[0].finish_reason = "stop"
    fallback.chat.completions.create.return_value = fb_resp

    with patch("tea_agent.toolkit.toolkit_vision_analyze._get_vision_client",
               return_value=(primary, "primary-vision", {})):
        with patch("tea_agent.toolkit.toolkit_vision_analyze._client_for",
                   return_value=fallback):
            with patch("tea_agent.config.get_config",
                       return_value=_cfg_with_main("main-vision-model")):
                from tea_agent.toolkit.toolkit_vision_analyze import toolkit_vision_analyze
                result = toolkit_vision_analyze(image="data:image/png;base64,AAAA")
                assert result["ok"] is True
                assert result["text"] == "回退成功"


def test_no_fallback_when_same_model():
    """首选与主模型同名时不重复调用（避免无谓重试与重复计费）。"""
    primary = MagicMock()
    primary.chat.completions.create.side_effect = RuntimeError("boom")

    with patch("tea_agent.toolkit.toolkit_vision_analyze._get_vision_client",
               return_value=(primary, "same-model", {})):
        with patch("tea_agent.config.get_config",
                   return_value=_cfg_with_main("same-model")):
            from tea_agent.toolkit.toolkit_vision_analyze import toolkit_vision_analyze
            result = toolkit_vision_analyze(image="data:image/png;base64,AAAA")
            assert result["ok"] is False
            assert "视觉模型调用失败" in result["error"]
            assert primary.chat.completions.create.call_count == 1


def test_no_fallback_when_main_lacks_vision():
    """主模型不支持视觉时不做回退，直接返回首选错误。"""
    primary = MagicMock()
    primary.chat.completions.create.side_effect = RuntimeError("boom")

    with patch("tea_agent.toolkit.toolkit_vision_analyze._get_vision_client",
               return_value=(primary, "primary-vision", {})):
        with patch("tea_agent.config.get_config",
                   return_value=_cfg_with_main("text-only", supports_vision=False)):
            from tea_agent.toolkit.toolkit_vision_analyze import toolkit_vision_analyze
            result = toolkit_vision_analyze(image="data:image/png;base64,AAAA")
            assert result["ok"] is False
            assert "未配置视觉模型" not in result["error"]
