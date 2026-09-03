"""
测试 providers 模块 — LLM Provider 注册表

覆盖：
- PROVIDERS 数据完整性
- list_providers() 输出格式
- get_provider() 精确/模糊/不存在查询
- generate_config() 配置生成
"""

import pytest

from tea_agent.providers import (
    PROVIDERS,
    generate_config,
    get_model,
    get_provider,
    list_providers,
    model_entries,
    model_ids,
)


class TestProvidersData:
    """PROVIDERS 数据完整性测试"""

    def test_providers_dict_not_empty(self):
        """PROVIDERS 字典不应为空"""
        assert len(PROVIDERS) > 0, "PROVIDERS 字典为空"

    def test_all_providers_have_required_keys(self):
        """每个 Provider 必须包含 api_url 和 default_model"""
        required = {"api_url", "default_model"}
        for name, info in PROVIDERS.items():
            missing = required - set(info.keys())
            assert not missing, f"Provider '{name}' 缺少字段: {missing}"

    def test_all_providers_have_valid_api_url(self):
        """api_url 必须是 http/https 链接"""
        for name, info in PROVIDERS.items():
            url = info["api_url"]
            assert url.startswith("http"), f"Provider '{name}' api_url 无效: {url}"

    def test_providers_default_model_in_models_list(self):
        """default_model 应出现在模型 id 列表中（目录化后 models 为富条目）"""
        for name, info in PROVIDERS.items():
            ids = model_ids(info)
            assert info["default_model"] in ids, (
                f"Provider '{name}' default_model '{info['default_model']}' "
                f"不在 models 列表中: {ids}"
            )

    def test_providers_model_entries_have_id(self):
        """models 条目应为富对象（id + 窗口/输出上限）"""
        for name, info in PROVIDERS.items():
            for entry in model_entries(info):
                assert "id" in entry, f"Provider '{name}' 有条目缺 id: {entry}"
                assert isinstance(entry["id"], str) and entry["id"], (
                    f"Provider '{name}' 模型 id 无效: {entry.get('id')!r}"
                )
                assert entry.get("context_window", 0) > 0, (
                    f"Provider '{name}' 模型 {entry['id']} 缺 context_window"
                )
                assert entry.get("max_output_tokens", 0) > 0, (
                    f"Provider '{name}' 模型 {entry['id']} 缺 max_output_tokens"
                )

    def test_get_model_merges_provider_fallback(self):
        """get_model 应返回模型级能力（未声明时继承供应商级）"""
        entry = get_model(PROVIDERS["DeepSeek"], "deepseek-chat")
        assert entry is not None
        assert entry["id"] == "deepseek-chat"
        assert entry["context_window"] > 0
        assert isinstance(entry.get("supports_vision"), bool)
        assert isinstance(entry.get("supports_thinking"), bool)
        assert get_model(PROVIDERS["DeepSeek"], "no-such-model") is None

    def test_providers_without_models_have_default_model(self):
        """没有 models 列表的 Provider 必须有 default_model"""
        for name, info in PROVIDERS.items():
            if "models" not in info:
                assert "default_model" in info, (
                    f"Provider '{name}' 既没有 models 列表也没有 default_model"
                )

    def test_provider_names_are_unique(self):
        """Provider 名称应唯一"""
        names = list(PROVIDERS.keys())
        assert len(names) == len(set(names)), "Provider 名称不唯一"

    def test_provider_description_exists(self):
        """建议每个 Provider 有 description"""
        for name, info in PROVIDERS.items():
            assert "description" in info, f"Provider '{name}' 缺少 description"


class TestListProviders:
    """list_providers() 测试"""

    def test_returns_list(self):
        """应返回列表"""
        result = list_providers()
        assert isinstance(result, list)

    def test_each_item_has_required_keys(self):
        """每个条目必须包含 name/api_url/default_model/models 等字段"""
        required_keys = {"name", "api_url", "default_model", "models",
                         "supports_thinking", "supports_vision", "description"}
        for item in list_providers():
            missing = required_keys - set(item.keys())
            assert not missing, f"Provider '{item.get('name')}' 结果缺少: {missing}"

    def test_sorted_by_name(self):
        """结果应按名称排序"""
        result = list_providers()
        names = [r["name"] for r in result]
        assert names == sorted(names), "Providers 列表未按名称排序"

    def test_models_is_list(self):
        """models 字段应为列表"""
        for item in list_providers():
            assert isinstance(item["models"], list), (
                f"Provider '{item['name']}' models 不是列表"
            )

    def test_supports_flags_are_bool(self):
        """supports_thinking 和 supports_vision 应为布尔值"""
        for item in list_providers():
            assert isinstance(item["supports_thinking"], bool), (
                f"Provider '{item['name']}' supports_thinking 不是 bool"
            )
            assert isinstance(item["supports_vision"], bool), (
                f"Provider '{item['name']}' supports_vision 不是 bool"
            )


class TestGetProvider:
    """get_provider() 测试"""

    def test_get_exact_name(self):
        """精确名称应返回正确结果"""
        result = get_provider("DeepSeek")
        assert result is not None
        assert result["name"] == "DeepSeek"
        assert "api_url" in result

    def test_get_case_insensitive(self):
        """不区分大小写"""
        result = get_provider("deepseek")
        assert result is not None
        assert result["name"] == "DeepSeek"

    def test_get_partial_case(self):
        """混合大小写"""
        result = get_provider("dEEPSEEK")
        assert result is not None
        assert result["name"] == "DeepSeek"

    def test_get_nonexistent_provider(self):
        """不存在的 Provider 应返回 None"""
        result = get_provider("NonExistentProvider12345")
        assert result is None

    def test_get_empty_string(self):
        """空字符串应返回 None"""
        result = get_provider("")
        assert result is None

    def test_get_provider_has_models_list(self):
        """返回结果应包含 models 列表"""
        for name in PROVIDERS:
            result = get_provider(name)
            assert "models" in result
            assert isinstance(result["models"], list)
            assert len(result["models"]) > 0

    def test_every_provider_is_findable(self):
        """所有 PROVIDERS 中的 Provider 都能通过 get_provider 找到"""
        for name in PROVIDERS:
            result = get_provider(name)
            assert result is not None, f"get_provider('{name}') 返回 None"
            assert result["name"] == name


class TestGenerateConfig:
    """generate_config() 测试"""

    def test_generate_valid_config(self):
        """生成有效配置"""
        config = generate_config("DeepSeek", "sk-test-key")
        assert "api_key: sk-test-key" in config
        assert "api_url: https://api.deepseek.com" in config
        assert "model_name:" in config

    def test_generate_with_custom_model(self):
        """指定自定义模型"""
        config = generate_config("DeepSeek", "sk-key", model="deepseek-reasoner")
        assert 'model_name: "deepseek-reasoner"' in config

    def test_generate_with_vision_provider(self):
        """支持 vision 的 Provider 应生成 supports_vision: true"""
        config = generate_config("OpenAI", "sk-key")
        assert "supports_vision: true" in config

    def test_generate_without_vision(self):
        """不支持 vision 的 Provider 应生成 supports_vision: false"""
        config = generate_config("Baidu", "sk-key")
        assert "supports_vision: false" in config

    def test_deepseek_has_vision_model(self):
        """DeepSeek provider 应声明视觉能力并列出 deepseek-v4-flash-vision-exp"""
        p = get_provider("DeepSeek")
        assert p["supports_vision"] is True
        assert "deepseek-v4-flash-vision-exp" in p["models"]
        assert "deepseek-v4-flash" in p["models"]

    def test_generate_unknown_provider_raises(self):
        """未知 Provider 应抛出 ValueError"""
        with pytest.raises(ValueError, match="Unknown provider"):
            generate_config("NonExistentProvider", "sk-key")

    def test_generate_use_as_cheap(self):
        """use_as_cheap=True 应生成不同注释"""
        # 主要验证不抛异常
        config = generate_config("DeepSeek", "sk-key", use_as_cheap=True)
        assert "api_key" in config

    def test_generate_all_providers(self):
        """所有 Provider 都应能生成配置"""
        for name in PROVIDERS:
            config = generate_config(name, "sk-test")
            assert "api_key: sk-test" in config, f"Provider '{name}' 配置生成失败"
            assert "api_url" in config

    def test_generate_default_model_fallback(self):
        """不传 model 时应使用 default_model"""
        config = generate_config("OpenAI", "sk-key")
        assert 'model_name: "gpt-4o"' in config


class TestEdgeCases:
    """边界情况测试"""

    def test_providers_never_empty_models(self):
        """每个 Provider 至少有一个模型"""
        for name, info in PROVIDERS.items():
            models = info.get("models", [info["default_model"]])
            assert len(models) >= 1, f"Provider '{name}' 没有可用模型"

    def test_providers_url_no_trailing_space(self):
        """api_url 不应有尾随空格"""
        for name, info in PROVIDERS.items():
            url = info["api_url"]
            assert url == url.strip(), f"Provider '{name}' api_url 有尾随空格"

    def test_all_providers_accessible_through_list(self):
        """list_providers() 应包含所有 PROVIDERS"""
        listed = {r["name"] for r in list_providers()}
        assert listed == set(PROVIDERS.keys()), "list_providers 与 PROVIDERS 不一致"
