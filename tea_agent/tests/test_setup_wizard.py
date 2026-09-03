"""
Setup Wizard 测试套件 — 首次运行配置向导。

覆盖：完整流程生成 yaml、自定义 Provider、必填校验重试、
便宜模型/视觉模型可选配置、用户取消路径。
"""

import os

import pytest
import yaml


def _fake_input(values: list[str]):
    """构造测试用 input_fn：依次返回给定输入，耗尽时抛 AssertionError。"""
    it = iter(values)

    def fn(prompt: str) -> str:
        try:
            return next(it)
        except StopIteration:
            raise AssertionError(f"输入耗尽，仍在询问: {prompt!r}")

    return fn


class TestRunSetupWizard:
    """run_setup_wizard 端到端测试"""

    def test_wizard_deepseek_basic(self, tmp_path):
        """选择 DeepSeek + 默认模型 + 输入 key → 生成正确 yaml"""
        from tea_agent.setup_wizard import run_setup_wizard

        target = str(tmp_path / "config.yaml")
        inputs = _fake_input(["1", "", "sk-test-123", "n", "n"])
        saved = run_setup_wizard(target, input_fn=inputs)

        assert saved == target
        assert os.path.isfile(target)
        with open(target, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        assert data["main_model"]["api_url"] == "https://api.deepseek.com"
        assert data["main_model"]["api_key"] == "sk-test-123"
        assert data["main_model"]["model_name"] == "deepseek-chat"
        # 未配置的模型不应写入
        assert "cheap_model" not in data
        assert "vision_model" not in data

    def test_wizard_custom_provider(self, tmp_path):
        """自定义 URL + 模型名"""
        from tea_agent.setup_wizard import run_setup_wizard

        target = str(tmp_path / "config.yaml")
        # 选项编号 10 = custom（QUICK_PROVIDERS 9 个 + custom）
        inputs = _fake_input(
            ["10", "https://my-api.example.com/v1", "my-model", "sk-custom", "n", "n"]
        )
        saved = run_setup_wizard(target, input_fn=inputs)

        assert saved == target
        with open(target, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        assert data["main_model"]["api_url"] == "https://my-api.example.com/v1"
        assert data["main_model"]["model_name"] == "my-model"
        assert data["main_model"]["api_key"] == "sk-custom"

    def test_wizard_required_key_retry(self, tmp_path):
        """API Key 必填：第一次空输入重试，第二次有效"""
        from tea_agent.setup_wizard import run_setup_wizard

        target = str(tmp_path / "config.yaml")
        inputs = _fake_input(["1", "", "", "sk-retry", "n", "n"])
        saved = run_setup_wizard(target, input_fn=inputs)

        assert saved == target
        with open(target, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        assert data["main_model"]["api_key"] == "sk-retry"

    def test_wizard_cheap_and_vision(self, tmp_path):
        """配置便宜模型(Ollama) + 视觉模型(Gemini)"""
        from tea_agent.setup_wizard import run_setup_wizard

        target = str(tmp_path / "config.yaml")
        inputs = _fake_input(
            [
                "1",          # DeepSeek
                "",           # 主模型名默认 deepseek-chat
                "sk-main",    # 主 key
                "y",          # 配置便宜模型
                "Ollama",     # 便宜服务商
                "",           # 便宜模型默认 llama3.1
                "",           # 便宜 key 复用 sk-main
                "y",          # 配置视觉模型
                "Gemini",     # 视觉服务商
                "",           # 视觉模型默认
                "",           # 视觉 key 复用 sk-main
            ]
        )
        saved = run_setup_wizard(target, input_fn=inputs)

        assert saved == target
        with open(target, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        assert data["main_model"]["api_url"] == "https://api.deepseek.com"
        assert data["cheap_model"]["api_url"] == "http://127.0.0.1:11434/v1"
        assert data["cheap_model"]["model_name"] == "llama3.1"
        assert data["cheap_model"]["api_key"] == "sk-main"
        assert (
            data["vision_model"]["api_url"]
            == "https://generativelanguage.googleapis.com/v1beta/openai"
        )
        assert data["vision_model"]["model_name"] == "gemini-2.5-pro"
        assert data["vision_model"]["api_key"] == "sk-main"

    def test_wizard_cancel_returns_none(self, tmp_path):
        """输入 q 取消 → 返回 None 且不生成文件"""
        from tea_agent.setup_wizard import run_setup_wizard

        target = str(tmp_path / "config.yaml")
        inputs = _fake_input(["q"])
        saved = run_setup_wizard(target, input_fn=inputs)

        assert saved is None
        assert not os.path.isfile(target)

    def test_wizard_invalid_choice_retry(self, tmp_path):
        """无效选项编号后重试"""
        from tea_agent.setup_wizard import run_setup_wizard

        target = str(tmp_path / "config.yaml")
        inputs = _fake_input(["99", "1", "", "sk-choice", "n", "n"])
        saved = run_setup_wizard(target, input_fn=inputs)

        assert saved == target
        with open(target, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        assert data["main_model"]["api_key"] == "sk-choice"


class TestBuildConfig:
    """_build_config 单元测试"""

    def test_build_config_main_only(self):
        from tea_agent.setup_wizard import _build_config

        cfg = _build_config(
            {
                "provider_name": "DeepSeek",
                "api_url": "https://api.deepseek.com",
                "api_key": "sk-x",
                "model_name": "deepseek-chat",
                "supports_vision": False,
                "cheap": {},
                "vision": {},
            }
        )
        assert cfg.main_model.is_configured
        assert not cfg.cheap_model.is_configured
        assert not cfg.vision_model.is_configured
        assert cfg.main_model.options["supports_vision"] == "false"

    def test_build_config_with_optional(self):
        from tea_agent.setup_wizard import _build_config

        cfg = _build_config(
            {
                "provider_name": "DeepSeek",
                "api_url": "https://api.deepseek.com",
                "api_key": "sk-main",
                "model_name": "deepseek-chat",
                "supports_vision": True,
                "cheap": {
                    "api_url": "http://127.0.0.1:11434/v1",
                    "model_name": "llama3.1",
                    "api_key": "",
                    "temperature": 0.3,
                },
                "vision": {
                    "api_url": "https://api.openai.com/v1",
                    "model_name": "gpt-4o",
                    "api_key": "",
                },
            }
        )
        assert cfg.cheap_model.is_configured
        assert cfg.cheap_model.api_key == "sk-main"  # 复用主模型 key
        assert cfg.vision_model.is_configured
        assert cfg.vision_model.options["supports_vision"] == "true"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
