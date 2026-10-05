"""provider.yaml 唯一事实源：config*.yaml profile 派生已停用。

历史：本文件曾测试「扫描 config_*.yaml 派生提供商」的整套机制
（scan_config_profiles / profile 密钥内存回读 / profile 删除后角色重绑）。
该机制已整体移除 —— provider.yaml 是供应商、逐模型能力与角色绑定的唯一来源。

本文件改为钉住「已停用」契约：存在 config.yaml 也不再产生任何提供商。
隔离：TEA_PROVIDER_FILE + tmp 目录，绝不触碰真实 ~/.tea_agent。
"""

from __future__ import annotations

import pytest
import yaml

import tea_agent.model_config as mc
import tea_agent.provider_store as ps
from tea_agent.model_config import scan_config_profiles
from tea_agent.provider_store import ProviderStore


@pytest.fixture
def agent_dir(tmp_path):
    """伪造 ~/.tea_agent：放两份 config*.yaml（旧机制会据此派生提供商）。"""
    d = tmp_path / "agent"
    d.mkdir()
    (d / "config.yaml").write_text(
        "main_model:\n"
        "  api_key: sk-should-be-ignored\n"
        "  api_url: https://api.deepseek.com\n"
        '  model_name: "deepseek-chat"\n',
        encoding="utf-8")
    (d / "config_ds.yaml").write_text(
        "main_model:\n"
        "  api_key: sk-also-ignored\n"
        "  api_url: https://api.deepseek.com\n"
        '  model_name: "deepseek-v4-pro"\n',
        encoding="utf-8")
    return d


@pytest.fixture
def pstore(tmp_path, monkeypatch, agent_dir):
    f = tmp_path / "provider.yaml"
    monkeypatch.setenv("TEA_PROVIDER_FILE", str(f))
    monkeypatch.setattr(ps, "_store", None, raising=False)
    monkeypatch.setattr(mc, "_store", None, raising=False)
    s = ProviderStore(f, agent_dir=agent_dir)
    yield s
    monkeypatch.setattr(ps, "_store", None, raising=False)
    monkeypatch.delenv("TEA_PROVIDER_FILE", raising=False)


# ── 已停用契约 ────────────────────────────────────────────

def test_scan_config_profiles_is_disabled(agent_dir):
    """即便 config*.yaml 存在，也不再派生任何提供商。"""
    assert scan_config_profiles(agent_dir) == {}


def test_config_profiles_do_not_seed_providers(pstore, agent_dir):
    """bootstrap 不得把 config*.yaml 里的供应商/密钥并进 provider.yaml。"""
    data = pstore.load()
    api_urls = {p.get("api_url") for p in data.get("providers", {}).values()}
    assert "https://api.deepseek.com" not in api_urls
    dumped = pstore.file_path.read_text(encoding="utf-8") if pstore.file_path.exists() else ""
    assert "sk-should-be-ignored" not in dumped
    assert "sk-also-ignored" not in dumped


def test_provider_yaml_is_single_source(pstore, tmp_path):
    """写入只落 provider.yaml，不生成 model_config.json。"""
    pstore.upsert_provider("MyProv", {"api_url": "https://x.example/v1",
                                      "api_key": "sk-x"})
    pstore.save()
    assert pstore.file_path.exists()
    assert not (tmp_path / "model_config.json").exists()
    assert "MyProv" in pstore.load()["providers"]


def test_roles_live_in_provider_yaml(pstore):
    pstore.upsert_model("DeepSeek", "m-1", {"max_context_tokens": 1000})
    pstore.set_role("main", "DeepSeek", "m-1")
    raw = yaml.safe_load(pstore.file_path.read_text(encoding="utf-8"))
    assert raw["roles"]["main"]["model"] == "m-1"
