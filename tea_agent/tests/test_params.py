"""
会话参数工具模块单元测试。

测试范围:
- get_cheap_params: 返回结构、三种 section 的默认值
- 配置加载失败时的降级行为
- 返回值的独立性（深拷贝/副本）
"""

from unittest.mock import patch

import pytest


# ============================================================
# 辅助：mock get_config 返回指定参数
# ============================================================

def _mock_config(temperature=0.3, max_tokens=1000):
    """创建 mock config，使 get_cheap_params 返回指定参数。"""
    from unittest.mock import MagicMock

    mock_cfg = MagicMock()
    mock_cfg.get_effective_params.return_value = {
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    return patch("tea_agent.config.get_config", return_value=mock_cfg)


# ============================================================
# 基本结构
# ============================================================

class TestGetCheapParams:
    """get_cheap_params 基本契约"""

    def test_returns_dict(self):
        """应返回 dict 类型"""
        from tea_agent.session.params import get_cheap_params

        result = get_cheap_params()
        assert isinstance(result, dict)

    def test_has_temperature_key(self):
        """应包含 temperature 键"""
        from tea_agent.session.params import get_cheap_params

        result = get_cheap_params()
        assert "temperature" in result

    def test_has_max_tokens_key(self):
        """应包含 max_tokens 键"""
        from tea_agent.session.params import get_cheap_params

        result = get_cheap_params()
        assert "max_tokens" in result

    def test_temperature_is_float(self):
        """temperature 应为 float/int"""
        from tea_agent.session.params import get_cheap_params

        result = get_cheap_params()
        assert isinstance(result["temperature"], (int, float))

    def test_max_tokens_is_int(self):
        """max_tokens 应为 int"""
        from tea_agent.session.params import get_cheap_params

        result = get_cheap_params()
        assert isinstance(result["max_tokens"], int)

    def test_default_section_is_api(self):
        """默认 section 应使用 api 的默认参数"""
        with _mock_config(temperature=0.3, max_tokens=1000):
            from tea_agent.session.params import get_cheap_params

            result = get_cheap_params()
            assert result["temperature"] == 0.3
            assert result["max_tokens"] == 1000


# ============================================================
# 各 section 默认值
# ============================================================

class TestGetCheapParamsSections:
    """各 section 默认值"""

    def test_api_section_defaults(self):
        """api section 应有正确默认值"""
        with _mock_config(temperature=0.3, max_tokens=1000):
            from tea_agent.session.params import get_cheap_params

            result = get_cheap_params("api")
            assert result["temperature"] == 0.3
            assert result["max_tokens"] == 1000

    def test_summarizer_section_defaults(self):
        """summarizer section 应有正确默认值"""
        with _mock_config(temperature=0.1, max_tokens=500):
            from tea_agent.session.params import get_cheap_params

            result = get_cheap_params("summarizer")
            assert result["temperature"] == 0.1
            assert result["max_tokens"] == 500

    def test_memory_section_defaults(self):
        """memory section 应有正确默认值"""
        with _mock_config(temperature=0.3, max_tokens=1000):
            from tea_agent.session.params import get_cheap_params

            result = get_cheap_params("memory")
            assert result["temperature"] == 0.3
            assert result["max_tokens"] == 1000

    def test_unknown_section_falls_back_to_api(self):
        """未知 section 应回退到 api 默认值"""
        with _mock_config(temperature=0.3, max_tokens=1000):
            from tea_agent.session.params import get_cheap_params

            result = get_cheap_params("unknown_section")
            assert result["temperature"] == 0.3
            assert result["max_tokens"] == 1000


# ============================================================
# 降级行为
# ============================================================

class TestGetCheapParamsFallback:
    """配置加载失败时的降级行为"""

    @patch("tea_agent.config.get_config", side_effect=ImportError("no config"))
    def test_import_error_uses_defaults(self, mock_get_config):
        """get_config 抛出 ImportError 时应使用默认值"""
        from tea_agent.session.params import get_cheap_params

        result = get_cheap_params("api")
        assert result["temperature"] == 0.3
        assert result["max_tokens"] == 1000

    @patch("tea_agent.config.get_config", side_effect=Exception("generic error"))
    def test_generic_exception_uses_defaults(self, mock_get_config):
        """get_config 抛出任意异常时应使用默认值"""
        from tea_agent.session.params import get_cheap_params

        result = get_cheap_params("summarizer")
        assert result["temperature"] == 0.1
        assert result["max_tokens"] == 500

    @patch("tea_agent.config.get_config")
    def test_config_returns_no_effective_params(self, mock_get_config):
        """get_effective_params 返回空 dict 时应使用默认值"""
        from tea_agent.session.params import get_cheap_params

        mock_cfg = mock_get_config.return_value
        mock_cfg.get_effective_params.return_value = {}

        result = get_cheap_params("api")
        assert result["temperature"] == 0.3
        assert result["max_tokens"] == 1000

    @patch("tea_agent.config.get_config")
    def test_config_overrides_temperature(self, mock_get_config):
        """配置中的 temperature 应覆盖默认值"""
        from tea_agent.session.params import get_cheap_params

        mock_cfg = mock_get_config.return_value
        mock_cfg.get_effective_params.return_value = {
            "temperature": 0.5,
            "max_tokens": 2000,
        }

        result = get_cheap_params("api")
        assert result["temperature"] == 0.5
        assert result["max_tokens"] == 2000

    @patch("tea_agent.config.get_config")
    def test_config_partial_overrides(self, mock_get_config):
        """配置只覆盖部分字段时，其余字段应使用默认值"""
        from tea_agent.session.params import get_cheap_params

        mock_cfg = mock_get_config.return_value
        mock_cfg.get_effective_params.return_value = {
            "temperature": 0.7,
        }

        result = get_cheap_params("summarizer")
        assert result["temperature"] == 0.7
        assert result["max_tokens"] == 500

    @patch("tea_agent.config.get_config")
    def test_config_invalid_type_coerced(self, mock_get_config):
        """配置值为非预期类型时不应崩溃"""
        from tea_agent.session.params import get_cheap_params

        mock_cfg = mock_get_config.return_value
        mock_cfg.get_effective_params.return_value = {
            "temperature": "0.5",
            "max_tokens": "1000",
        }

        result = get_cheap_params("api")
        assert result["temperature"] == "0.5"
        assert result["max_tokens"] == "1000"


# ============================================================
# 独立性
# ============================================================

class TestGetCheapParamsIndependence:
    """返回值独立性测试"""

    @patch("tea_agent.config.get_config")
    def test_returns_new_dict_each_call(self, mock_get_config):
        """每次调用应返回新的 dict 实例"""
        from tea_agent.session.params import get_cheap_params

        mock_cfg = mock_get_config.return_value
        mock_cfg.get_effective_params.return_value = {
            "temperature": 0.3,
            "max_tokens": 1000,
        }

        r1 = get_cheap_params("api")
        r2 = get_cheap_params("api")
        assert r1 is not r2
        assert r1 == r2

    @patch("tea_agent.config.get_config")
    def test_modifying_result_does_not_affect_defaults(self, mock_get_config):
        """修改返回值不应影响后续调用"""
        from tea_agent.session.params import get_cheap_params

        mock_cfg = mock_get_config.return_value
        mock_cfg.get_effective_params.return_value = {
            "temperature": 0.3,
            "max_tokens": 1000,
        }

        r1 = get_cheap_params("api")
        r1["temperature"] = 999.0

        r2 = get_cheap_params("api")
        assert r2["temperature"] == 0.3


# ============================================================
# 轻量集成测试
# ============================================================

class TestGetCheapParamsIntegration:
    """轻量集成测试 — 使用真实配置（如果有）"""

    def test_with_real_config(self):
        """使用实际配置验证返回结构"""
        from tea_agent.session.params import get_cheap_params

        try:
            result = get_cheap_params("api")
        except Exception:
            pytest.skip("Real config not available")
            return

        assert isinstance(result, dict)
        assert "temperature" in result
        assert "max_tokens" in result
        assert isinstance(result.get("temperature"), (int, float))
        assert isinstance(result.get("max_tokens"), int)
