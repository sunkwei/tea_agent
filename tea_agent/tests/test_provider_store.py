"""provider.yaml 唯一事实源（ProviderStore）单元测试。

隔离：TEA_PROVIDER_FILE → tmp_path，绝不触碰真实 ~/.tea_agent。
覆盖：
  1. bootstrap：内置目录 ⊕ config*.yaml 迁移（同 url 多 key 保留一个，主 config 优先）
  2. 供应商 CRUD（upsert/remove/掩码/list/get）
  3. 模型目录 CRUD（upsert_model/delete_model/sync_models 启发式默认）
  4. resolve：p_name + m_name → ModelConfig 可直接套用的扁平元数据
  5. config 引用式解析：main_model: {provider, model} 由 provider.yaml resolve
"""

from __future__ import annotations

import pathlib

import pytest

DS_MAIN = "sk-main-key-000111-abcdef"


@pytest.fixture
def agent_dir(tmp_path: pathlib.Path):
    """伪造 ~/.tea_agent：config.yaml（DeepSeek 主）+ config_ds.yaml（同 url 不同 key）。"""
    d = tmp_path / "agent"
    d.mkdir()
    (d / "config.yaml").write_text(
        "main_model:\n"
        f"  api_key: {DS_MAIN}\n"
        "  api_url: https://api.deepseek.com\n"
        '  model_name: "deepseek-v4-pro"\n'
        "cheap_model:\n"
        f"  api_key: {DS_MAIN}\n"
        "  api_url: https://api.deepseek.com\n"
        '  model_name: "deepseek-v4-flash"\n',
        encoding="utf-8")
    (d / "config_ds.yaml").write_text(
        "main_model:\n"
        "  api_key: sk-other-key-222333-xyz\n"
        "  api_url: https://api.deepseek.com\n"
        '  model_name: "deepseek-chat"\n',
        encoding="utf-8")
    return d


@pytest.fixture
def pstore(tmp_path: pathlib.Path, monkeypatch, agent_dir):
    f = tmp_path / "provider.yaml"
    monkeypatch.setenv("TEA_PROVIDER_FILE", str(f))
    import tea_agent.provider_store as ps
    monkeypatch.setattr(ps, "_store", None, raising=False)
    s = ps.get_provider_store(f, agent_dir=agent_dir)
    yield s
    monkeypatch.setattr(ps, "_store", None, raising=False)


# ── bootstrap / 迁移 ─────────────────────────────────────

def test_bootstrap_builtins_plus_profiles(pstore):
    data = pstore.load()
    provs = data["providers"]
    assert "DeepSeek" in provs
    assert "OpenAI" in provs  # 内置目录 bootstrap
    # config_ds 的模型并入 DeepSeek（同 url）；key 保留主 config 的（同 url 多 key 保留一个）
    assert "deepseek-chat" in provs["DeepSeek"]["models"]
    assert provs["DeepSeek"]["api_key"] == DS_MAIN


def test_list_masks_key(pstore):
    lst = pstore.list_providers()
    ds = next(p for p in lst if p["name"] == "DeepSeek")
    assert "****" in ds["api_key_masked"]
    assert DS_MAIN not in str(ds)


# ── 供应商 CRUD ──────────────────────────────────────────

def test_upsert_and_remove_provider(pstore):
    pstore.upsert_provider("MyGate", {
        "api_url": "https://g.example.com/v1",
        "api_key": "sk-live-abcdefghijkl",
        "default_model": "gpt-x",
        "models": ["gpt-x"],
    })
    p = pstore.get_provider("MyGate")
    assert p and p["api_url"] == "https://g.example.com/v1"
    assert pstore.remove_provider("MyGate") is True
    assert pstore.get_provider("MyGate") is None


def test_model_crud_and_sync(pstore):
    pstore.upsert_model("DeepSeek", "custom-model", {
        "max_context_tokens": 200000,
        "max_output_tokens": 16384,
        "supports_vision": True,
    })
    m = pstore.get_model("DeepSeek", "custom-model")
    assert m and m["max_context_tokens"] == 200000 and m["supports_vision"] is True
    res = pstore.sync_models("DeepSeek", ["deepseek-chat", "brand-new-x"])
    assert "brand-new-x" in res["added"]
    assert pstore.delete_model("DeepSeek", "custom-model") is True


def test_resolve_flat_metadata(pstore):
    r = pstore.resolve("DeepSeek", "deepseek-v4-pro")
    assert r and r["provider"] == "DeepSeek"
    assert r["model"] == "deepseek-v4-pro"
    assert r["api_url"] == "https://api.deepseek.com"
    assert r["api_key"] == DS_MAIN  # 主 config key 保留
    assert int(r["max_output_tokens"]) > 0
    assert "supports_vision" in r and "supports_reasoning" in r


# ── config 引用式加载（TODO[3] 集成验证） ─────────────────

def test_config_reference_load(tmp_path: pathlib.Path, monkeypatch, agent_dir):
    import tea_agent.config as cfg_mod
    import tea_agent.provider_store as ps_mod

    pfile = tmp_path / "provider.yaml"
    monkeypatch.setenv("TEA_PROVIDER_FILE", str(pfile))
    monkeypatch.setattr(ps_mod, "_store", None, raising=False)
    ps_mod.migrate_from_configs(config_dir=agent_dir, target=pfile)
    store = ps_mod.get_provider_store(pfile, agent_dir=agent_dir)

    # 引用式 config：main=provider+model
    ref_cfg = tmp_path / "config_ref.yaml"
    ref_cfg.write_text(
        "main_model:\n"
        "  provider: DeepSeek\n"
        "  model: deepseek-v4-flash\n"
        "cheap_model:\n"
        "  provider: DeepSeek\n"
        "  model: deepseek-chat\n",
        encoding="utf-8")
    monkeypatch.setattr(cfg_mod, "_active_config_path", None, raising=False)
    monkeypatch.setattr(cfg_mod, "_last_config_path", None, raising=False)

    import tea_agent.config as C
    orig = C._resolve_ref_model
    C._resolve_ref_model = lambda p, m: store.resolve(p, m)
    try:
        cfg = C.load_config(str(ref_cfg))
        assert cfg.main_model.model_name == "deepseek-v4-flash"
        assert cfg.main_model.api_url == "https://api.deepseek.com"
        assert cfg.main_model.api_key == DS_MAIN
        assert cfg.main_model.provider == "DeepSeek"
        assert cfg.main_model.ref_model == "deepseek-v4-flash"
        # 保存回写为引用式（不展开密钥）
        out = tmp_path / "config_out.yaml"
        C.save_config(cfg, str(out))
        text = out.read_text(encoding="utf-8")
        assert "provider: DeepSeek" in text and "model: deepseek-v4-flash" in text
        assert DS_MAIN not in text  # 密钥不落 config
    finally:
        C._resolve_ref_model = orig
