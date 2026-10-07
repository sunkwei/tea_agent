"""配置向导测试（provider.yaml 唯一事实源）。"""

import os

import pytest
import yaml


def _fake_input(answers: list[str]):
    it = iter(answers)

    def fn(prompt: str = "") -> str:
        try:
            return next(it)
        except StopIteration:
            raise AssertionError(f"输入耗尽，仍在询问: {prompt!r}") from None

    return fn


@pytest.fixture
def isolated_store(tmp_path, monkeypatch):
    """隔离 provider.yaml 单例，返回路径。"""
    from tea_agent import provider_store as ps

    path = tmp_path / "provider.yaml"
    monkeypatch.setenv("TEA_PROVIDER_FILE", str(path))
    monkeypatch.setattr(ps, "_store", None, raising=False)
    return path


class TestRunProviderSetupWizard:
    """run_setup_wizard（兼容别名）→ 写 provider.yaml。"""

    def test_wizard_deepseek_basic(self, isolated_store):
        from tea_agent.setup_wizard import run_setup_wizard

        # 1=DeepSeek, ""=默认模型, key, n=不再添加
        saved = run_setup_wizard(input_fn=_fake_input(["1", "", "sk-test-123", "n"]))

        assert saved == str(isolated_store)
        data = yaml.safe_load(isolated_store.read_text(encoding="utf-8"))
        p = data["providers"]["DeepSeek"]
        assert p["api_url"] == "https://api.deepseek.com"
        assert p["api_key"] == "sk-test-123"
        assert p["default_model"], "应写入所选默认模型"

    def test_wizard_custom_provider(self, isolated_store):
        from tea_agent.setup_wizard import run_setup_wizard

        # 10=custom, url, model, key, n
        saved = run_setup_wizard(input_fn=_fake_input(["10", "https://my-api.example.com/v1", "my-model", "sk-custom", "n"]))

        assert saved == str(isolated_store)
        data = yaml.safe_load(isolated_store.read_text(encoding="utf-8"))
        p = data["providers"]["custom"]
        assert p["api_url"] == "https://my-api.example.com/v1"
        assert p["api_key"] == "sk-custom"
        assert "my-model" in p["models"]

    def test_wizard_cancel_returns_none(self, isolated_store):
        from tea_agent.setup_wizard import run_setup_wizard

        assert run_setup_wizard(input_fn=_fake_input(["q"])) is None
        assert not isolated_store.exists()

    def test_wizard_writes_only_provider_yaml(self, isolated_store, tmp_path):
        """向导只写 provider.yaml，不产生任何其他配置文件。"""
        from tea_agent.setup_wizard import run_setup_wizard

        saved = run_setup_wizard(input_fn=_fake_input(["1", "", "sk-x", "n"]))

        assert saved == str(isolated_store)
        # provider.yaml 本身即目标产物：目录中不得出现任何**其他**配置文件
        written = sorted(q.name for q in tmp_path.glob("*.yaml"))
        assert written == [isolated_store.name], written

    def test_end_to_end_via_provider_wizard(self, isolated_store):
        """provider 向导直连入口同样写 provider.yaml。"""
        from tea_agent.setup_wizard import run_provider_setup_wizard

        assert run_provider_setup_wizard(input_fn=_fake_input(["1", "", "sk-e2e", "n"]))
        data = yaml.safe_load(isolated_store.read_text(encoding="utf-8"))
        assert data["providers"]["DeepSeek"]["api_key"] == "sk-e2e"


def test_build_config_removed():
    """_build_config / _collect_answers 属历史配置文件机制，已随其删除。"""
    import tea_agent.setup_wizard as w

    assert not hasattr(w, "_build_config")
    assert not hasattr(w, "_collect_answers")
    assert not [p for p in os.listdir(os.path.dirname(w.__file__)) if p.endswith(".yaml")]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
