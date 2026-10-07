"""model_config 兼容层测试（provider.yaml 唯一事实源）。

历史：本模块曾把供应商/逐模型能力/角色绑定持久化到 model_config.json，
与 provider.yaml 等形成多份互相覆盖的事实源。现已收敛到 provider.yaml，
本模块只做 API 名转发，**不再读写任何 JSON 文件**。

本文件钉住该契约：转发不落盘、scan_config_profiles 已停用、roles 存 provider.yaml。
隔离：TEA_PROVIDER_FILE + tmp 目录，绝不触碰真实 ~/.tea_agent。
"""

from __future__ import annotations

import pytest

from tea_agent.model_config import (
    ModelConfigError,
    clean_model_config,
    get_model_config_store,
    guess_model_config,
    scan_config_profiles,
)


@pytest.fixture
def store(tmp_path, monkeypatch):
    """隔离的 ProviderStore 转发单例（无 JSON 文件）。"""
    import tea_agent.provider_store as ps

    f = tmp_path / "provider.yaml"
    monkeypatch.setenv("TEA_PROVIDER_FILE", str(f))
    monkeypatch.setattr(ps, "_store", None, raising=False)
    s = get_model_config_store()
    yield s
    monkeypatch.setattr(ps, "_store", None, raising=False)
    monkeypatch.delenv("TEA_PROVIDER_FILE", raising=False)


# ── 转发契约 ──────────────────────────────────────────────


def test_get_model_config_store_returns_provider_store():
    """兼容名 get_model_config_store 返回 ProviderStore（不存在第二个存储）。"""
    from tea_agent.provider_store import ProviderStore

    assert isinstance(get_model_config_store(), ProviderStore)


def test_no_json_file_is_written(store, tmp_path):
    """任何写操作都不得生成 model_config.json（单一事实源契约）。"""
    store.upsert_model("DeepSeek", "m-x", {"max_context_tokens": 65536})
    store.set_role("main", "DeepSeek", "m-x", api_url="https://api.deepseek.com")
    assert not (tmp_path / "model_config.json").exists()
    assert store.file_path.name == "provider.yaml"
    assert store.file_path.exists()


def test_model_config_roundtrip_persists(store):
    """逐模型配置经 provider.yaml 持久化（新实例可读回）。"""
    from tea_agent.provider_store import ProviderStore

    store.upsert_model("DeepSeek", "m-rt", {"max_context_tokens": 32_768})
    cfg = ProviderStore(store.file_path).get_model_config("DeepSeek", "m-rt")
    assert cfg["max_context_tokens"] == 32_768


def test_roles_persist_to_provider_yaml(store):
    """角色绑定存 provider.yaml 的 roles 段，而非独立 JSON。"""
    import yaml

    store.set_role("cheap", "DeepSeek", "m-cheap")
    raw = yaml.safe_load(store.file_path.read_text(encoding="utf-8"))
    assert raw["roles"]["cheap"]["model"] == "m-cheap"
    assert store.roles()["cheap"]["model"] == "m-cheap"


def test_set_role_rejects_vision_role(store):
    """vision 角色已随独立视觉模型槽位一并移除。"""
    from tea_agent.provider_store import ProviderStoreError

    with pytest.raises(ProviderStoreError):
        store.set_role("vision", "DeepSeek", "m-v")


def test_panel_shape(store):
    """面板视图：providers 含逐模型配置 + roles/active。"""
    store.upsert_model("DeepSeek", "m-p", {"supports_vision": True})
    panel = store.panel()
    assert panel["ok"] is True
    assert panel["file"].endswith("provider.yaml")
    assert isinstance(panel["providers"], list)
    assert "roles" in panel and "active" in panel


# ── 已停用能力 ────────────────────────────────────────────


def test_scan_config_profiles_disabled():
    """config*.yaml 不再是提供商来源：恒返回空。"""
    assert scan_config_profiles() == {}
    assert scan_config_profiles("/tmp") == {}


# ── 纯函数 ────────────────────────────────────────────────


def test_guess_model_config_neutral_without_caps():
    """无能力声明时给出中性默认（不做模型名启发）。"""
    cfg = guess_model_config("some-unknown-model")
    assert cfg["max_context_tokens"] == 0
    assert cfg["supports_vision"] is False


def test_guess_model_config_inherits_provider_caps():
    """供应商级显式能力可补足模型能力。"""
    cfg = guess_model_config("m", {"supports_vision": True, "supports_thinking": True})
    assert cfg["supports_vision"] is True
    assert cfg["supports_reasoning"] is True


def test_clean_model_config_rejects_unknown_field():
    with pytest.raises(ModelConfigError):
        clean_model_config({"nope": 1})


def test_clean_model_config_partial_keeps_only_given():
    out = clean_model_config({"max_context_tokens": 1024}, partial=True)
    assert out["max_context_tokens"] == 1024


def test_clean_model_config_full_fills_blank():
    out = clean_model_config({"max_context_tokens": 1024}, partial=False)
    assert "supports_vision" in out and "note" in out
