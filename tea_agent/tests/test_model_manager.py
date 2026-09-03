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
    """隔离的 ProviderService 实例：自定义供应商文件 + 统一模型配置 → tmp_path。"""
    custom_file = tmp_path / "custom_providers.yaml"
    monkeypatch.setattr(mm, "_CUSTOM_FILE", custom_file)
    # 隔离 ModelConfigStore 单例，避免测试读写真实 ~/.tea_agent/model_config.json
    import tea_agent.model_config as mc_mod

    monkeypatch.setenv("TEA_MODEL_CONFIG", str(tmp_path / "model_config.json"))
    monkeypatch.setattr(mc_mod, "_store", None)
    # profile 扫描隔离：空目录（无 config_*.yaml）→ store 回退预置注册表
    monkeypatch.setattr(mc_mod, "CONFIG_DIR", tmp_path / "agent")
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


def test_query_models_refresh_false_cache_hit(svc, monkeypatch):
    """refresh=False 且缓存命中时不触发实时查询，返回 cache 标注。"""
    called = []
    def fake_live(api_url, api_key):
        called.append(api_url)
        return {"ok": True, "models": [{"id": "a"}], "total": 1, "endpoint": ""}
    monkeypatch.setattr(svc, "_query_live", fake_live)
    svc.query_models("DeepSeek", api_key="sk-test", refresh=True)  # 首次实时写缓存
    assert len(called) == 1
    result = svc.query_models("DeepSeek", api_key="sk-test", refresh=False)  # 缓存命中
    assert len(called) == 1  # 未再实时查询
    assert result["source"] == "cache"
    assert result["total"] == 1
    assert "cached_at" in result


def test_query_models_cache_expired(svc, monkeypatch):
    """缓存超过 TTL 后 refresh=False 自动重新实时查询。"""
    called = []
    def fake_live(api_url, api_key):
        called.append(api_url)
        return {"ok": True, "models": [{"id": "a"}], "total": 1, "endpoint": ""}
    monkeypatch.setattr(svc, "_query_live", fake_live)
    svc.query_models("DeepSeek", api_key="sk-test", refresh=True)
    assert len(called) == 1
    # 把缓存时间戳推到过期（TTL=300s 之前）
    import time as _t
    key = "DeepSeek:sk-test"
    ts, _ = svc._models_cache[key]
    svc._models_cache[key] = (ts - svc._models_cache_ttl - 1, _)
    result = svc.query_models("DeepSeek", api_key="sk-test", refresh=False)
    assert len(called) == 2  # 缓存过期 → 重新实时
    assert result["source"] == "live"


def test_query_models_refresh_force(svc, monkeypatch):
    """refresh=True 即使有缓存也强制实时查询并更新缓存。"""
    called = []
    def fake_live(api_url, api_key):
        called.append(api_url)
        return {"ok": True, "models": [{"id": "a"}], "total": 1, "endpoint": ""}
    monkeypatch.setattr(svc, "_query_live", fake_live)
    svc.query_models("DeepSeek", api_key="sk-test", refresh=True)
    svc.query_models("DeepSeek", api_key="sk-test", refresh=True)  # 强制刷新
    assert len(called) == 2


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
    """apply 默认模型 deepseek-chat：能力来自该模型目录条目（思考 ✓ 视觉 ✗）。"""
    captured = {}

    def fake_save(cfg, path):
        captured["options"] = dict(cfg.main_model.options)

    monkeypatch.setattr(mm, "load_config", lambda path: mm._default_cfg())
    monkeypatch.setattr(mm, "save_config", fake_save)
    svc.apply_provider("DeepSeek", api_key="sk-x", role="main")
    # 模型级：deepseek-chat 思考模型，非视觉
    assert captured["options"]["supports_reasoning"] is True
    assert captured["options"]["supports_vision"] is False


# ── 目录驱动切换（供应商 → 模型，窗口/输出自动填充） ────────────

def test_apply_provider_autofills_caps_from_catalog(svc, monkeypatch):
    """apply 未显式传窗口/输出时自动取目录内该模型上限写入配置。"""
    saved = {}

    def fake_save(cfg, path):
        saved["max_context_tokens"] = cfg.main_model.max_context_tokens
        saved["max_tokens"] = cfg.main_model.max_tokens
        saved["model_name"] = cfg.main_model.model_name

    monkeypatch.setattr(mm, "load_config", lambda path: mm._default_cfg())
    monkeypatch.setattr(mm, "save_config", fake_save)
    result = svc.apply_provider("DeepSeek", api_key="sk-x", model="deepseek-chat", role="main")
    assert result["max_context_tokens"] > 0
    assert result["max_tokens"] > 0
    assert saved["max_context_tokens"] == result["max_context_tokens"]
    assert saved["max_tokens"] == result["max_tokens"]


def test_apply_provider_explicit_caps_override_catalog(svc, monkeypatch):
    """显式传入 max_tokens / max_context_tokens 优先于目录默认。"""
    saved = {}

    def fake_save(cfg, path):
        saved["max_tokens"] = cfg.main_model.max_tokens
        saved["max_context_tokens"] = cfg.main_model.max_context_tokens

    monkeypatch.setattr(mm, "load_config", lambda path: mm._default_cfg())
    monkeypatch.setattr(mm, "save_config", fake_save)
    svc.apply_provider(
        "DeepSeek", api_key="sk-x", model="deepseek-chat", role="main",
        max_tokens=4096, max_context_tokens=32768,
    )
    assert saved["max_tokens"] == 4096
    assert saved["max_context_tokens"] == 32768


def test_apply_vision_model_merges_model_level_caps(svc, monkeypatch):
    """选视觉模型条目 → options.supports_vision=True（目录模型级能力）。"""
    captured = {}

    def fake_save(cfg, path):
        captured["options"] = dict(cfg.main_model.options)
        captured["model_name"] = cfg.main_model.model_name

    monkeypatch.setattr(mm, "load_config", lambda path: mm._default_cfg())
    monkeypatch.setattr(mm, "save_config", fake_save)
    svc.apply_provider("DeepSeek", api_key="sk-x", model="deepseek-v4-flash-vision-exp", role="main")
    assert captured["model_name"] == "deepseek-v4-flash-vision-exp"
    assert captured["options"]["supports_vision"] is True


def test_query_models_static_entries_carry_catalog_meta(svc):
    """目录静态列表应带上下文窗口/输出上限/能力，供 UI 两步展示。"""
    result = svc.query_models("DeepSeek", api_key="", refresh=True)
    assert result["source"] == "static"
    by_id = {m["id"]: m for m in result["models"]}
    chat = by_id.get("deepseek-chat")
    assert chat is not None
    assert chat.get("context_window", 0) > 0
    assert chat.get("max_output_tokens", 0) > 0
    assert isinstance(chat.get("supports_vision"), bool)


def test_list_providers_emits_catalog(svc):
    """list_providers 应为每个供应商附 catalog 富目录（含默认模型条目）。"""
    result = svc.list_providers()
    by_name = {p["name"]: p for p in result["providers"]}
    deepseek = by_name["DeepSeek"]
    assert deepseek["default_model"] in deepseek["models"]  # 模型 id 列表兼容旧前端
    cat_ids = {m["id"] for m in deepseek["catalog"]}
    assert deepseek["default_model"] in cat_ids
    assert all(m["id"] in deepseek["models"] for m in deepseek["catalog"])


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
