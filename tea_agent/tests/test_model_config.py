"""统一模型配置中心（tea_agent.model_config）单元测试。

覆盖：bootstrap 生成 / 逐模型配置 CRUD 与校验 / 注册表增量同步 /
自定义供应商清理 / 实时模型列表写回 / 角色绑定 / 持久化 roundtrip / 启发式默认。

测试隔离：TEA_MODEL_CONFIG 环境变量 + 单例重置，绝不触碰用户真实 ~/.tea_agent。
"""

from __future__ import annotations

import pytest

from tea_agent import model_config as mc
from tea_agent.model_config import (
    ModelConfigError,
    ModelConfigStore,
    get_model_config_store,
    guess_model_config,
)


@pytest.fixture
def store(tmp_path, monkeypatch):
    """指向 tmp_path 的隔离单例。"""
    f = tmp_path / "model_config.json"
    monkeypatch.setenv("TEA_MODEL_CONFIG", str(f))
    # profile 扫描隔离：空目录（无 config_*.yaml）→ store 回退预置注册表，断言稳定
    monkeypatch.setattr(mc, "CONFIG_DIR", tmp_path / "agent")
    monkeypatch.setattr(mc, "_store", None)
    s = get_model_config_store()
    assert s.file_path == f
    yield s
    monkeypatch.setattr(mc, "_store", None)
    monkeypatch.delenv("TEA_MODEL_CONFIG", raising=False)


# ── bootstrap ─────────────────────────────────────────────

def test_bootstrap_creates_file_with_registry(store, tmp_path):
    data = store.load()
    path = tmp_path / "model_config.json"
    assert path.exists()
    assert data["version"] == mc.SCHEMA_VERSION
    assert len(data["providers"]) >= 10
    assert "DeepSeek" in data["providers"] and "OpenAI" in data["providers"]
    ds_models = data["providers"]["DeepSeek"]["models"]
    assert "deepseek-chat" in ds_models
    # 四个必备能力字段齐全
    for key in ("max_context_tokens", "max_output_tokens", "supports_thinking",
                "supports_vision"):
        assert key in ds_models["deepseek-chat"], key


def test_bootstrap_is_idempotent_and_persisted(store, tmp_path):
    store.upsert_model("DeepSeek", "unit-test-model", {"max_context_tokens": 65536})
    path = tmp_path / "model_config.json"
    # 新建实例（同路径）应读到已持久化的编辑
    s2 = ModelConfigStore(path)
    cfg = s2.get_model_config("DeepSeek", "unit-test-model")
    assert cfg["max_context_tokens"] == 65536
    assert cfg["source"] == "saved"


# ── 逐模型配置 CRUD ───────────────────────────────────────

def test_upsert_partial_update_merges(store):
    store.upsert_model("DeepSeek", "m-a", {"max_context_tokens": 200_000,
                                           "supports_thinking": True})
    entry = store.upsert_model("DeepSeek", "m-a", {"max_output_tokens": 16_000})
    cfg = entry["config"]
    assert cfg["max_context_tokens"] == 200_000      # 保留
    assert cfg["supports_thinking"] is True          # 保留
    assert cfg["max_output_tokens"] == 16_000        # 更新


def test_upsert_rejects_unknown_field(store):
    with pytest.raises(ModelConfigError, match="unknown config field"):
        store.upsert_model("DeepSeek", "m-b", {"temperature": 0.5})


def test_upsert_rejects_out_of_range(store):
    with pytest.raises(ModelConfigError, match="out of range"):
        store.upsert_model("DeepSeek", "m-c", {"max_context_tokens": 10})


def test_upsert_unknown_provider_injects_from_registry(store):
    # provider 名与内置注册表一致（大小写不敏感）→ 自动补齐条目
    entry = store.upsert_model("deepseek", "deepseek-reasoner", {"max_output_tokens": 64_000})
    assert entry["config"]["max_output_tokens"] == 64_000


def test_upsert_truly_unknown_provider_fails(store):
    with pytest.raises(ModelConfigError) as ei:
        store.upsert_model("NoSuchProvider-xyz", "m", {"max_output_tokens": 100})
    assert ei.value.code == "NOT_FOUND"


def test_delete_model(store):
    store.upsert_model("DeepSeek", "to-del", {"max_output_tokens": 1234})
    assert store.delete_model("DeepSeek", "to-del") is True
    assert store.delete_model("DeepSeek", "to-del") is False
    # 删内置注册表中声明的模型 → 允许（store 层面移除条目）
    with pytest.raises(ModelConfigError):
        store.delete_model("NoSuchProvider-xyz", "anything")


def test_update_model_config_on_new_model(store):
    # update_model_config：provider 有、模型从无 → 按默认创建后套用 patch
    entry = store.update_model_config("OpenAI", "gpt-9-ultra",
                                      {"max_context_tokens": 500_000, "note": "新加"})
    assert entry["config"]["max_context_tokens"] == 500_000
    assert entry["config"]["note"] == "新加"


# ── 注册表增量同步 ────────────────────────────────────────

def test_registry_increment_sync(store, tmp_path, monkeypatch):
    import copy

    store.load()  # 确保 bootstrap 完成
    fake = {
        "ZzzFake": {"api_url": "https://fake.example.com/v1",
                    "default_model": "fm-1",
                    "models": ["fm-1", "fm-2"],
                    "supports_vision": True},
    }
    real = copy.deepcopy(mc.__dict__.get("_PROVIDERS_CACHE", None))  # 防呆：无缓存属性则忽略
    import tea_agent.providers as prov
    monkeypatch.setitem(prov.PROVIDERS, "ZzzFake", fake["ZzzFake"])
    # 用户先编辑一个既有模型的配置，增量同步不得覆盖
    store.upsert_model("DeepSeek", "deepseek-chat", {"max_context_tokens": 999_999})
    data = store.load(force=True)
    assert "ZzzFake" in data["providers"]
    assert set(data["providers"]["ZzzFake"]["models"]) == {"fm-1", "fm-2"}
    assert data["providers"]["ZzzFake"]["supports_vision"] is True
    assert data["providers"]["DeepSeek"]["models"]["deepseek-chat"]["max_context_tokens"] \
        == 999_999
    # 新模型按 provider 能力播种
    assert data["providers"]["ZzzFake"]["models"]["fm-2"]["supports_vision"] is True


def test_removed_custom_provider_purged(store, tmp_path, monkeypatch):
    import yaml

    custom_dir = tmp_path / "tea_home"
    custom_dir.mkdir()
    monkeypatch.setattr(mc, "CONFIG_DIR", custom_dir)
    f = custom_dir / "custom_providers.yaml"
    f.write_text(yaml.safe_dump({"version": 1, "providers": {
        "GhostGW": {"api_url": "https://ghost.example/v1", "default_model": "gm"}}}),
        encoding="utf-8")
    data = store.load(force=True)
    assert "GhostGW" in data["providers"]
    store.set_role("cheap", "GhostGW", "gm")
    assert store.roles().get("cheap", {}).get("provider") == "GhostGW"
    f.unlink()  # 模拟删除自定义供应商
    data = store.load(force=True)
    assert "GhostGW" not in data["providers"]
    assert "cheap" not in store.roles()


# ── 实时模型列表写回 ──────────────────────────────────────

def test_sync_live_models_preserves_user_edits(store):
    store.upsert_model("DeepSeek", "deepseek-chat", {"max_context_tokens": 777_777})
    r = store.sync_live_models("DeepSeek",
                               ["deepseek-chat", "brand-new-live", "deepseek-reasoner"])
    assert "brand-new-live" in r["added"]
    assert "deepseek-chat" in r["kept"]
    assert r["total"] >= len(r["added"]) + len(r["kept"])
    # 用户编辑未被覆盖
    assert store.get_model_config("DeepSeek", "deepseek-chat")["max_context_tokens"] == 777_777
    # 新模型获得启发式配置
    assert store.get_model_config("DeepSeek", "brand-new-live")["max_context_tokens"] > 0


# ── 角色绑定 ──────────────────────────────────────────────

def test_set_role_validates(store):
    store.set_role("main", "DeepSeek", "deepseek-chat", api_url="https://api.deepseek.com")
    r = store.roles()["main"]
    assert r["provider"] == "DeepSeek" and r["model"] == "deepseek-chat"
    with pytest.raises(ModelConfigError):
        store.set_role("bad-role", "DeepSeek", "m")
    with pytest.raises(ModelConfigError):
        store.set_role("main", "DeepSeek", "")


# ── panel 视图 ────────────────────────────────────────────

def test_panel_shape(store):
    store.upsert_model("OpenAI", "gpt-4o", {"max_output_tokens": 4096})
    p = store.panel()
    assert p["ok"] is True and p["version"] == mc.SCHEMA_VERSION
    assert p["total_providers"] == len(p["providers"])
    names = {x["name"] for x in p["providers"]}
    assert {"DeepSeek", "OpenAI"} <= names
    for prov in p["providers"]:
        assert {"name", "source", "api_url", "models", "model_count"} <= set(prov)
        for m in prov["models"]:
            assert {"id", "config", "is_default"} <= set(m)
            cfg = m["config"]
            for key in ("max_context_tokens", "max_output_tokens",
                        "supports_thinking", "supports_vision"):
                assert key in cfg
    assert "active" in p and "roles" in p


# ── 启发式 ────────────────────────────────────────────────

@pytest.mark.parametrize("mid,expect", [
    ("deepseek-reasoner", {"supports_thinking": True}),
    ("gpt-4o", {"supports_vision": True}),
    ("gemini-2.5-pro", {"supports_thinking": True, "supports_vision": True}),
    ("qwen3-32b", {"supports_thinking": True}),
    ("moonshot-v1-32k", {"max_context_tokens": 32 * 1024}),
    ("llama-suffix-1m", {"max_context_tokens": 1_048_576}),
])
def test_guess_heuristics(mid, expect):
    cfg = guess_model_config(mid)
    for k, v in expect.items():
        assert cfg[k] == v, (mid, k)


def test_guess_family_ctx():
    assert guess_model_config("gemini-turbo-x")["max_context_tokens"] == 1_048_576
    assert guess_model_config("claude-new-thing")["max_context_tokens"] == 200_000
    # 已知条目优先于家族规则
    assert guess_model_config("deepseek-reasoner")["max_context_tokens"] == 128_000


# ── 备份 ──────────────────────────────────────────────────

def test_bak_created_on_second_save(store, tmp_path):
    store.upsert_model("DeepSeek", "m-x", {"max_output_tokens": 4321})
    store.upsert_model("DeepSeek", "m-y", {"max_output_tokens": 4321})
    baks = list(tmp_path.glob("model_config.json.bak.*"))
    assert baks, "第二次保存应生成 .bak 备份"
