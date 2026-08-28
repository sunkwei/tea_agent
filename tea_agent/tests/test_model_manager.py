"""模型管理服务（ProviderService）单元测试。

覆盖：合并注册表 / 自定义供应商 CRUD / 模型查询 fallback / 配置应用 / 端点推断。

测试隔离：通过 monkeypatch 将 custom_providers.yaml 与 config.yaml
重定向到 pytest tmp_path，避免污染用户真实配置。
"""

from __future__ import annotations

import sys
import types
import urllib.error as urllib_err
from pathlib import Path

import pytest

# 使 model_manager 的 _CUSTOM_FILE 可被 monkeypatch（模块级常量）
import tea_agent.model_manager as mm


@pytest.fixture
def svc(tmp_path, monkeypatch):
    """隔离的 ProviderService 实例：自定义供应商文件 → tmp_path。"""
    custom_file = tmp_path / "custom_providers.yaml"
    monkeypatch.setattr(mm, "_CUSTOM_FILE", custom_file)
    svc = mm.ProviderService(config_path="")
    svc._custom_cache = None
    svc._custom_mtime = 0.0
    return svc


def _write_custom(tmp_path, providers: dict) -> Path:
    import yaml

    f = tmp_path / "custom_providers.yaml"
    f.write_text(
        yaml.safe_dump({"version": 1, "providers": providers}, allow_unicode=True),
        encoding="utf-8",
    )
    return f


# ── 端点推断 ─────────────────────────────────────────────────

def test_models_endpoint_variants():
    assert mm._models_endpoint("https://api.openai.com/v1") == "https://api.openai.com/v1/models"
    assert mm._models_endpoint("https://api.deepseek.com") == "https://api.deepseek.com/v1/models"
    assert (
        mm._models_endpoint("https://generativelanguage.googleapis.com/v1beta/openai")
        == "https://generativelanguage.googleapis.com/v1beta/openai/models"
    )
    assert mm._models_endpoint("") == ""


def test_chat_endpoint_variants():
    assert mm._chat_endpoint("https://api.openai.com/v1") == "https://api.openai.com/v1/chat/completions"
    assert mm._chat_endpoint("https://api.deepseek.com") == "https://api.deepseek.com/v1/chat/completions"


# ── 合并注册表 ───────────────────────────────────────────────

def test_list_providers_builtin_only(svc):
    result = svc.list_providers()
    assert result["total"] == len(mm.PROVIDERS)
    assert all(p["source"] == "builtin" for p in result["providers"])
    names = {p["name"] for p in result["providers"]}
    assert "DeepSeek" in names and "OpenAI" in names


def test_list_providers_merges_custom(svc, tmp_path):
    _write_custom(tmp_path, {"My-Gateway": {"api_url": "https://gw.example.com/v1",
                                            "default_model": "gpt-4o-mini"}})
    svc._load_custom(force=True)
    result = svc.list_providers()
    by_name = {p["name"]: p for p in result["providers"]}
    assert "My-Gateway" in by_name
    assert by_name["My-Gateway"]["source"] == "custom"
    assert result["total"] == len(mm.PROVIDERS) + 1
    # 内置 DeepSeek 仍为 builtin
    assert by_name["DeepSeek"]["source"] == "builtin"


def test_get_provider_case_insensitive(svc):
    assert svc.get_provider("deepseek")["name"] == "DeepSeek"
    assert svc.get_provider("DEEPSEEK")["name"] == "DeepSeek"
    assert svc.get_provider("no-such-provider") is None


# ── 自定义供应商 CRUD ────────────────────────────────────────

def test_add_custom_provider_ok(svc, tmp_path):
    provider = svc.add_custom_provider({
        "name": "My-Gateway",
        "api_url": "https://gw.example.com/v1",
        "default_model": "gpt-4o-mini",
        "models": ["gpt-4o", "gpt-4o-mini"],
        "supports_thinking": True,
        "description": "私有中转站",
    })
    assert provider["source"] == "custom"
    assert provider["api_url"] == "https://gw.example.com/v1"
    assert provider["created_at"]
    # 已持久化到文件
    assert (tmp_path / "custom_providers.yaml").exists()
    assert svc.get_provider("my-gateway") is not None


def test_add_custom_provider_duplicate(svc, tmp_path):
    _write_custom(tmp_path, {"My-Gateway": {"api_url": "https://a.com/v1",
                                            "default_model": "m1"}})
    svc._load_custom(force=True)
    with pytest.raises(mm.DuplicateProviderError):
        svc.add_custom_provider({"name": "My-Gateway", "api_url": "https://b.com/v1",
                                 "default_model": "m2"})


def test_add_custom_provider_duplicate_builtin(svc):
    with pytest.raises(mm.DuplicateProviderError):
        svc.add_custom_provider({"name": "DeepSeek", "api_url": "https://x.com/v1",
                                 "default_model": "m"})


@pytest.mark.parametrize("name", ["a", "ab c", "", "x" * 33, "bad/name"])
def test_add_custom_provider_invalid_name(svc, name):
    with pytest.raises(mm.ProviderError):
        svc.add_custom_provider({"name": name, "api_url": "https://a.com/v1",
                                 "default_model": "m"})


def test_add_custom_provider_requires_fields(svc):
    with pytest.raises(mm.ProviderError, match="api_url"):
        svc.add_custom_provider({"name": "X" * 3, "default_model": "m"})
    with pytest.raises(mm.ProviderError, match="default_model"):
        svc.add_custom_provider({"name": "X" * 3, "api_url": "https://a.com/v1"})


def test_add_custom_provider_invalid_url(svc):
    with pytest.raises(mm.ProviderError, match="api_url"):
        svc.add_custom_provider({"name": "X" * 3, "api_url": "ftp://a.com",
                                 "default_model": "m"})


def test_update_custom_provider_partial(svc, tmp_path):
    _write_custom(tmp_path, {"My-Gateway": {"api_url": "https://a.com/v1",
                                            "default_model": "m1", "models": ["m1"]}})
    svc._load_custom(force=True)
    updated = svc.update_custom_provider("my-gateway", {"default_model": "m2"})
    assert updated["default_model"] == "m2"
    assert updated["api_url"] == "https://a.com/v1"  # 未提供的字段保持
    assert updated["updated_at"]


def test_update_builtin_rejected(svc):
    with pytest.raises(mm.BuiltinProviderError):
        svc.update_custom_provider("DeepSeek", {"default_model": "x"})


def test_update_not_found(svc):
    with pytest.raises(mm.ProviderNotFoundError):
        svc.update_custom_provider("Ghost", {"default_model": "x"})


def test_delete_custom_provider(svc, tmp_path):
    _write_custom(tmp_path, {"My-Gateway": {"api_url": "https://a.com/v1",
                                            "default_model": "m1"}})
    svc._load_custom(force=True)
    result = svc.delete_custom_provider("My-Gateway")
    assert result["ok"] is True
    assert svc.get_provider("My-Gateway") is None


def test_delete_builtin_rejected(svc):
    with pytest.raises(mm.BuiltinProviderError):
        svc.delete_custom_provider("OpenAI")


def test_delete_not_found(svc):
    with pytest.raises(mm.ProviderNotFoundError):
        svc.delete_custom_provider("Ghost")


# ── 模型查询 fallback ────────────────────────────────────────

def test_query_models_static_without_key(svc):
    result = svc.query_models("DeepSeek", api_key="", refresh=True)
    assert result["source"] == "static"
    assert result["total"] >= 1
    assert result["needs_key"] is False
    ids = {m["id"] for m in result["models"]}
    assert "deepseek-chat" in ids


def test_query_models_custom_needs_key(svc, tmp_path):
    _write_custom(tmp_path, {"My-Gateway": {"api_url": "https://gw.example.com/v1",
                                            "default_model": "gpt-4o-mini"}})
    svc._load_custom(force=True)
    result = svc.query_models("My-Gateway", api_key="", refresh=True)
    assert result["needs_key"] is True
    assert result["source"] == "static"


def test_query_models_live_fallback_to_static(svc, monkeypatch):
    """实时查询失败（网络/401）→ 自动 fallback 到静态列表。"""
    def fake_live(api_url, api_key):
        return {"ok": False, "error": "HTTP 401: Unauthorized"}
    monkeypatch.setattr(svc, "_query_live", fake_live)
    result = svc.query_models("DeepSeek", api_key="sk-test", refresh=True)
    assert result["source"] == "static"
    assert "error_hint" in result
    assert result["total"] >= 1


def test_query_models_live_success(svc, monkeypatch):
    def fake_live(api_url, api_key):
        return {"ok": True,
                "models": [{"id": "a", "owned_by": "x"}, {"id": "b"}],
                "total": 2, "endpoint": "https://x/v1/models"}
    monkeypatch.setattr(svc, "_query_live", fake_live)
    result = svc.query_models("DeepSeek", api_key="sk-test", refresh=True)
    assert result["source"] == "live"
    assert result["total"] == 2
    assert "error_hint" not in result


def test_query_models_refresh_false(svc, monkeypatch):
    called = []
    def fake_live(api_url, api_key):
        called.append(api_url)
        return {"ok": True, "models": [], "total": 0, "endpoint": ""}
    monkeypatch.setattr(svc, "_query_live", fake_live)
    svc.query_models("DeepSeek", api_key="sk-test", refresh=False)
    assert called == []  # refresh=False 不触发实时查询


# ── 配置应用 ─────────────────────────────────────────────────

def test_apply_provider_main(svc, tmp_path, monkeypatch):
    cfg_file = tmp_path / "config.yaml"
    monkeypatch.setattr(mm, "load_config", lambda path: mm._default_cfg())
    monkeypatch.setattr(mm, "save_config", lambda cfg, path: cfg_file.write_text("saved", encoding="utf-8"))
    result = svc.apply_provider(
        "DeepSeek", api_key="sk-1234567890123", model="deepseek-chat",
        role="main", config_path=str(cfg_file), temperature=0.3,
    )
    assert result["ok"] is True
    assert result["role"] == "main"
    assert result["model"] == "deepseek-chat"
    assert result["api_url"] == "https://api.deepseek.com"
    assert cfg_file.exists()  # 已落盘


def test_apply_provider_default_model(svc, monkeypatch):
    monkeypatch.setattr(mm, "load_config", lambda path: mm._default_cfg())
    monkeypatch.setattr(mm, "save_config", lambda cfg, path: None)
    result = svc.apply_provider("DeepSeek", api_key="sk-x", role="main")
    assert result["model"] == "deepseek-chat"  # 使用 default_model


def test_apply_provider_invalid_role(svc):
    with pytest.raises(mm.ProviderError, match="role"):
        svc.apply_provider("DeepSeek", api_key="sk-x", role="turbo")


def test_apply_provider_unknown_provider(svc):
    with pytest.raises(mm.ProviderNotFoundError):
        svc.apply_provider("Ghost", api_key="sk-x", role="main")


def test_apply_provider_merges_capabilities(svc, monkeypatch):
    captured = {}

    def fake_save(cfg, path):
        captured["options"] = dict(cfg.main_model.options)

    monkeypatch.setattr(mm, "load_config", lambda path: mm._default_cfg())
    monkeypatch.setattr(mm, "save_config", fake_save)
    svc.apply_provider("DeepSeek", api_key="sk-x", role="main")
    assert captured["options"]["supports_vision"] is True
    assert captured["options"]["supports_reasoning"] is True


def test_apply_provider_reuses_existing_key(svc, monkeypatch):
    cfg = mm._default_cfg()
    cfg.main_model.api_key = "sk-existing-key-123"
    monkeypatch.setattr(mm, "load_config", lambda path: cfg)
    saved = {}
    monkeypatch.setattr(mm, "save_config", lambda c, p: saved.update(api_key=c.main_model.api_key))
    result = svc.apply_provider("DeepSeek", api_key="", role="main")
    assert result["ok"] is True
    assert saved["api_key"] == "sk-existing-key-123"


def test_apply_provider_vision_role(svc, monkeypatch):
    cfg = mm._default_cfg()
    monkeypatch.setattr(mm, "load_config", lambda path: cfg)
    monkeypatch.setattr(mm, "save_config", lambda c, p: None)
    result = svc.apply_provider("DeepSeek", api_key="sk-x", role="vision")
    assert result["role"] == "vision"
    assert cfg.vision_model.model_name == "deepseek-chat"
    assert cfg.vision_model.api_url == "https://api.deepseek.com"


# ── 连接测试 ─────────────────────────────────────────────────

def test_test_connection_requires_fields(svc):
    with pytest.raises(mm.ProviderError, match="api_url"):
        svc.test_connection("", "sk-x", "m")
    with pytest.raises(mm.ProviderError, match="api_key"):
        svc.test_connection("https://api.deepseek.com", "", "m")


def test_test_connection_http_error(svc, monkeypatch):
    class FakeHTTPError(urllib_err.HTTPError):
        def __init__(self):
            super().__init__("https://x/v1/chat/completions", 401, "Unauthorized", None, None)

    def fake_urlopen(req, timeout):
        raise FakeHTTPError()

    monkeypatch.setattr(mm.urllib_req, "urlopen", fake_urlopen)
    result = svc.test_connection("https://api.deepseek.com", "sk-bad", "deepseek-chat")
    assert result["ok"] is False
    assert "401" in result["error"]


# ── 单例 ────────────────────────────────────────────────────

def test_get_provider_service_singleton(tmp_path, monkeypatch):
    monkeypatch.setattr(mm, "_service", None)
    a = mm.get_provider_service()
    b = mm.get_provider_service()
    assert a is b


def test_default_cfg_helper():
    cfg = mm._default_cfg()
    assert cfg.main_model.api_key == ""
    assert cfg.main_model.model_name == ""
