"""provider.yaml 唯一事实源（ProviderStore）单元测试。

隔离：TEA_PROVIDER_FILE → tmp_path，绝不触碰真实 ~/.tea_agent。
覆盖：
  1. bootstrap：内置目录 ⊕ 显式种入的提供商
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
    """伪造 ~/.tea_agent：放入历史配置文件（不得再派生提供商）。"""
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
        encoding="utf-8",
    )
    (d / "config_ds.yaml").write_text(
        'main_model:\n  api_key: sk-other-key-222333-xyz\n  api_url: https://api.deepseek.com\n  model_name: "deepseek-chat"\n', encoding="utf-8"
    )
    return d


@pytest.fixture
def pstore(tmp_path: pathlib.Path, monkeypatch, agent_dir):
    f = tmp_path / "provider.yaml"
    monkeypatch.setenv("TEA_PROVIDER_FILE", str(f))
    import tea_agent.provider_store as ps

    monkeypatch.setattr(ps, "_store", None, raising=False)
    s = ps.get_provider_store(f, agent_dir=agent_dir)
    # 历史配置文件不再派生提供商 → 显式种入 DeepSeek
    s.ensure_provider(
        "DeepSeek",
        {
            "api_url": "https://api.deepseek.com",
            "api_key": DS_MAIN,
            "default_model": "deepseek-v4-pro",
            "source": "builtin",
            "models": ["deepseek-v4-pro", "deepseek-v4-flash", "deepseek-chat"],
        },
    )
    yield s
    monkeypatch.setattr(ps, "_store", None, raising=False)


def test_prune_unconfigured_builtins(pstore):
    """prune_unconfigured：删除无 key 的内置占位，保留已配置（带 key）条目。"""
    data = pstore.load()
    data["providers"].setdefault("OpenAI", {"api_url": "https://api.openai.com/v1", "api_key": "", "source": "builtin", "models": {}})
    data["providers"]["DeepSeek"]["api_key"] = DS_MAIN
    pstore.save()
    res = pstore.prune_unconfigured()
    assert "OpenAI" in res["removed"]
    provs = pstore.load()["providers"]
    assert "OpenAI" not in provs and "DeepSeek" in provs


def test_list_masks_key(pstore):
    lst = pstore.list_providers()
    ds = next(p for p in lst if p["name"] == "DeepSeek")
    assert "****" in ds["api_key_masked"]
    assert DS_MAIN not in str(ds)


# ── 供应商 CRUD ──────────────────────────────────────────


def test_upsert_and_remove_provider(pstore):
    pstore.upsert_provider(
        "MyGate",
        {
            "api_url": "https://g.example.com/v1",
            "api_key": "sk-live-abcdefghijkl",
            "default_model": "gpt-x",
            "models": ["gpt-x"],
        },
    )
    p = pstore.get_provider("MyGate")
    assert p and p["api_url"] == "https://g.example.com/v1"
    assert pstore.remove_provider("MyGate") is True
    assert pstore.get_provider("MyGate") is None


def test_model_crud_and_sync(pstore):
    pstore.upsert_model(
        "DeepSeek",
        "custom-model",
        {
            "max_context_tokens": 200000,
            "max_output_tokens": 16384,
            "supports_vision": True,
        },
    )
    m = pstore.get_model("DeepSeek", "custom-model")
    assert m and m["max_context_tokens"] == 200000 and m["supports_vision"] is True
    res = pstore.sync_models("DeepSeek", ["deepseek-chat", "brand-new-x"])
    assert "brand-new-x" in res["added"]
    assert pstore.delete_model("DeepSeek", "custom-model") is True


def test_resolve_flat_metadata(pstore):
    # 属性来自 provider.yaml（先显式写入模型条目再 resolve；代码不内置属性）
    pstore.upsert_model(
        "DeepSeek",
        "deepseek-v4-pro",
        {"max_context_tokens": 1_000_000, "max_output_tokens": 384_000, "supports_vision": True, "supports_reasoning": True},
    )
    r = pstore.resolve("DeepSeek", "deepseek-v4-pro")
    assert r and r["provider"] == "DeepSeek"
    assert r["model"] == "deepseek-v4-pro"
    assert r["api_url"] == "https://api.deepseek.com"
    assert r["api_key"] == DS_MAIN  # 主 config key 保留
    assert int(r["max_output_tokens"]) == 384_000  # 属性来自 provider.yaml 显式条目
    assert "supports_vision" in r and "supports_reasoning" in r
