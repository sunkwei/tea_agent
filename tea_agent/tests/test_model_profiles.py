"""面板默认提供商源：~/.tea_agent/config_*.yaml profile 派生提供商测试。

覆盖：scan 命名/角色元数据/密钥掩码、store 以 profile 为源（预置不再注入）、
profile 文件删除清理与角色重绑、panel 透出、ProviderService get/apply
对 profile 的支持（逐模型 api_url + 密钥内存回读，绝不明文落盘）。

隔离：全部基于 tmp_path 伪造 agent 目录，绝不读写真实 ~/.tea_agent。
"""

from __future__ import annotations

import json

import pytest

import tea_agent.model_config as mc
import tea_agent.model_manager as mm
from tea_agent.model_config import ModelConfigStore, scan_config_profiles

DS_MAIN = "sk-ds-main-key-000111"
DS_CHEAP = "sk-ds-cheap-key-222333"


@pytest.fixture
def agent_dir(tmp_path):
    """伪造 ~/.tea_agent：两个 profile（config.yaml→default、config_ds.yaml→ds）。"""
    d = tmp_path / "agent"
    d.mkdir()
    (d / "config.yaml").write_text(
        "main_model:\n"
        f"  api_key: {DS_MAIN}\n"
        "  api_url: https://api.deepseek.com\n"
        '  model_name: "deepseek-chat"\n',
        encoding="utf-8")
    (d / "config_ds.yaml").write_text(
        "main_model:\n"
        f"  api_key: {DS_MAIN}\n"
        "  api_url: https://api.deepseek.com\n"
        '  model_name: "deepseek-v4-pro"\n'
        "cheap_model:\n"
        f"  api_key: {DS_CHEAP}\n"
        "  api_url: https://opencode.ai/zen/go/v1\n"
        '  model_name: "mimo-v2.5"\n',
        encoding="utf-8")
    return d


@pytest.fixture
def pstore(tmp_path, monkeypatch, agent_dir):
    f = tmp_path / "model_config.json"
    monkeypatch.setenv("TEA_MODEL_CONFIG", str(f))
    # bootstrap 角色绑定读 TEA_CONFIG → 指向伪造 config.yaml，确定化
    monkeypatch.setenv("TEA_CONFIG", str(agent_dir / "config.yaml"))
    import tea_agent.config as cfg_mod
    monkeypatch.setattr(cfg_mod, "_active_config_path", None, raising=False)
    monkeypatch.setattr(cfg_mod, "_last_config_path", None, raising=False)
    monkeypatch.setattr(mc, "_store", None, raising=False)
    s = ModelConfigStore(f, agent_dir=agent_dir)
    yield s
    monkeypatch.setattr(mc, "_store", None, raising=False)


# ── scan_config_profiles ─────────────────────────────────

def test_scan_naming_roles_and_mask(agent_dir):
    profiles = scan_config_profiles(agent_dir)
    assert set(profiles) == {"default", "ds"}
    ds = profiles["ds"]
    assert ds["source"] == "config"
    assert ds["default_model"] == "deepseek-v4-pro"
    assert ds["models"] == ["deepseek-v4-pro", "mimo-v2.5"]
    meta = ds["model_meta"]["mimo-v2.5"]
    assert meta["api_url"] == "https://opencode.ai/zen/go/v1"
    assert meta["roles"] == ["cheap"]
    assert "****" in ds["api_key_masked"]
    assert DS_MAIN not in json.dumps(profiles)       # scan 结果绝不含明文密钥
    assert DS_CHEAP not in json.dumps(profiles)


def test_scan_skips_broken_and_empty(tmp_path):
    d = tmp_path / "a"
    d.mkdir()
    (d / "config_bad.yaml").write_text("main_model: [oops", encoding="utf-8")   # 损坏
    (d / "config_nokey.yaml").write_text("misc: 1\n", encoding="utf-8")          # 无模型
    (d / "config_ok.yaml").write_text(
        "main_model:\n  api_key: k-123456789012ab\n  api_url: https://x.example/v1\n"
        '  model_name: "m-1"\n', encoding="utf-8")
    profiles = scan_config_profiles(d)
    assert set(profiles) == {"ok"}                    # 坏/空文件跳过不抛


# ── store 以 profile 为默认提供商源 ───────────────────────

def test_store_bootstrap_uses_profiles_only(pstore):
    data = pstore.load()
    # 预置表不再注入面板；仅 profile（+custom）
    assert set(data["providers"]) == {"default", "ds"}
    assert data["providers"]["ds"]["config_path"].endswith("config_ds.yaml")
    # 启发能力表对 profile 模型仍生效（deepseek-v4-pro → 1M ctx）
    assert data["providers"]["ds"]["models"]["deepseek-v4-pro"]["max_context_tokens"] == 1_000_000
    # bootstrap 角色绑定：读 TEA_CONFIG（伪造 config.yaml）→ main=deepseek-chat
    assert data["roles"].get("main", {}).get("model") == "deepseek-chat"
    assert data["roles"]["main"]["provider"] == "default"
    assert DS_MAIN not in pstore.file_path.read_text(encoding="utf-8")  # 明文密钥不落盘


def test_profile_file_removed_purges_and_rebinds(pstore, agent_dir):
    data = pstore.load()
    assert "default" in data["providers"]
    (agent_dir / "config.yaml").unlink()              # 用户删除 profile 文件
    data2 = pstore.load(force=True)
    assert "default" not in data2["providers"]
    assert "ds" in data2["providers"]
    # 悬空角色按 api_url 重绑到同网关的 ds profile
    assert data2["roles"]["main"]["provider"] == "ds"


def test_profile_file_added_incremental(pstore, agent_dir):
    pstore.load()
    (agent_dir / "config_qwen.yaml").write_text(
        "main_model:\n  api_key: kq-1234567890ab\n  api_url: https://q.example/v1\n"
        '  model_name: "qwen3.8-flash"\n', encoding="utf-8")
    data = pstore.load(force=True)
    assert "qwen" in data["providers"]                # 新 profile 自动发现
    assert "qwen3.8-flash" in data["providers"]["qwen"]["models"]
    assert set(data["providers"]) == {"default", "ds", "qwen"}   # 原有 profile 保留


def test_panel_exposes_profile_meta(pstore):
    p = pstore.panel()
    ds = next(x for x in p["providers"] if x["name"] == "ds")
    assert ds["source"] == "config" and ds["config_path"] and ds["api_key_masked"]
    m = next(x for x in ds["models"] if x["id"] == "mimo-v2.5")
    assert m["roles"] == ["cheap"]
    assert m["api_url"] == "https://opencode.ai/zen/go/v1"
    assert DS_MAIN not in json.dumps(p) and DS_CHEAP not in json.dumps(p)


# ── ProviderService 对 profile 的支持 ─────────────────────

def test_manager_profile_secret_reads_by_model(agent_dir):
    svc = mm.ProviderService(config_path="")
    f = str(agent_dir / "config_ds.yaml")
    assert svc._profile_secret(f, "mimo-v2.5") == DS_CHEAP
    assert svc._profile_secret(f, "deepseek-v4-pro") == DS_MAIN
    assert svc._profile_secret(f) == DS_MAIN          # 无 model → main 块
    assert svc._profile_secret("") == ""
    assert svc._profile_secret("nonexistent.yaml") == ""


def test_manager_get_provider_falls_back_to_profile(tmp_path, monkeypatch, agent_dir):
    monkeypatch.setattr(mc, "CONFIG_DIR", agent_dir)
    monkeypatch.setattr(mm, "_CUSTOM_FILE", tmp_path / "none.yaml")
    svc = mm.ProviderService(config_path="")
    p = svc.get_provider("DS")                        # 大小写不敏感
    assert p and p["source"] == "config" and p["config_path"]
    assert p["models"] == ["deepseek-v4-pro", "mimo-v2.5"]
    assert svc.get_provider("ghost-xyz") is None


def test_manager_apply_profile_endpoint_and_key(tmp_path, monkeypatch, agent_dir):
    monkeypatch.setattr(mc, "CONFIG_DIR", agent_dir)
    monkeypatch.setattr(mm, "_CUSTOM_FILE", tmp_path / "none.yaml")
    monkeypatch.setenv("TEA_MODEL_CONFIG", str(tmp_path / "mc.json"))
    monkeypatch.setattr(mc, "_store", None)
    svc = mm.ProviderService(config_path="")
    cfg = mm._default_cfg()
    cfg.main_model.api_key = "sk-old-role-key-9999"
    monkeypatch.setattr(mm, "load_config", lambda path: cfg)
    monkeypatch.setattr(mm, "save_config", lambda c, p: None)

    res = svc.apply_provider("ds", model="mimo-v2.5", role="main")
    assert res["ok"]
    # 逐模型 api_url：mimo 在 cheap 块 → opencode 网关（而非 profile main 的 deepseek）
    assert cfg.main_model.api_url == "https://opencode.ai/zen/go/v1"
    assert res["api_url"] == "https://opencode.ai/zen/go/v1"
    # key 回读优先级：profile 文件对应块 > 该角色现有旧 key
    assert cfg.main_model.api_key == DS_CHEAP
    # 显式传参最高优先
    res2 = svc.apply_provider("ds", model="deepseek-v4-pro", role="main", api_key="sk-explicit-9")
    assert cfg.main_model.api_key == "sk-explicit-9"
    assert cfg.main_model.api_url == "https://api.deepseek.com"
