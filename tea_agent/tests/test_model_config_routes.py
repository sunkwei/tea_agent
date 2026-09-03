"""统一模型配置面板 API（/api/model-config*）集成测试。

隔离：TEA_CONFIG + TEA_MODEL_CONFIG → tmp_path，绝不触碰真实用户配置。
覆盖：
  1. 面板全量视图（providers→models→逐模型配置 + roles + active 掩码）
  2. 模型配置保存（PUT）/新增（POST）/删除（DELETE）+ 校验 400
  3. 在线模型同步入库（sync，新模型启发式默认）
  4. 切换并继续会话：落盘 config.yaml + roles 绑定 + 逐模型注入 options
  5. 会话进行中：挂起切换（pending_next_turn）→ 本轮结束自动应用
"""

from __future__ import annotations

import pytest


@pytest.fixture
def env(tmp_path, monkeypatch):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "main_model:\n"
        "  api_key: sk-test1234567890\n"
        "  api_url: https://api.deepseek.com\n"
        '  model_name: "deepseek-chat"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("TEA_CONFIG", str(cfg))
    monkeypatch.setenv("TEA_MODEL_CONFIG", str(tmp_path / "model_config.json"))

    import tea_agent.config as cfg_mod
    import tea_agent.model_config as mc_mod
    import tea_agent.model_manager as mm_mod
    from tea_agent.server.modules import state
    from tea_agent.server.modules.agent_module import AgentModule

    monkeypatch.setattr(mc_mod, "_store", None)
    monkeypatch.setattr(mm_mod, "_service", None)
    state.config_cache.clear()
    state.active_sessions.clear()
    state.background_sessions.clear()
    cfg_mod._active_config_path = None
    cfg_mod._last_config_path = None
    monkeypatch.setattr(AgentModule, "_pending_switch", None, raising=False)

    from tea_agent.server.server import create_app
    from starlette.testclient import TestClient

    # 显式传 config_path：避免 create_app 默认空路径导致 apply/save 走
    # config.py 模块级粘滞全局（_last_config_path），跨测试互相污染
    client = TestClient(create_app(config_path=str(cfg)))
    yield client, cfg, state, AgentModule
    state.active_sessions.clear()
    state.background_sessions.clear()


# ── 1. 面板全量视图 ───────────────────────────────────────

def test_panel_full_view(env):
    client, _cfg, _state, _am = env
    r = client.get("/api/model-config")
    assert r.status_code == 200
    d = r.json()
    assert d["ok"] and d["total_providers"] >= 10 and d["file"]
    ds = next(p for p in d["providers"] if p["name"] == "DeepSeek")
    assert ds["source"] == "builtin" and ds["api_url"] == "https://api.deepseek.com"
    m = next(x for x in ds["models"] if x["id"] == "deepseek-chat")
    cfgm = m["config"]
    for key in ("max_context_tokens", "max_output_tokens",
                "supports_thinking", "supports_vision"):
        assert key in cfgm, key
    # active：读 config.yaml 实时值；api_key 必须掩码
    assert d["active"]["main"]["model"] == "deepseek-chat"
    assert "sk-test1234567890" not in r.text
    assert d["pending_switch"] is None


# ── 2. 模型配置 CRUD ──────────────────────────────────────

def test_put_model_config(env):
    client, _cfg, _state, _am = env
    r = client.put("/api/model-config/model", json={
        "provider": "DeepSeek", "model": "deepseek-chat",
        "config": {"max_context_tokens": 200000, "max_output_tokens": 128000,
                   "supports_thinking": True, "supports_vision": False,
                   "supports_tools": True, "note": "测试编辑"},
    })
    assert r.status_code == 200 and r.json()["ok"]
    d = client.get("/api/model-config").json()
    ds = next(p for p in d["providers"] if p["name"] == "DeepSeek")
    m = next(x for x in ds["models"] if x["id"] == "deepseek-chat")
    assert m["config"]["max_context_tokens"] == 200000
    assert m["config"]["note"] == "测试编辑"


def test_put_model_config_validation(env):
    client, _cfg, _state, _am = env
    r = client.put("/api/model-config/model", json={
        "provider": "DeepSeek", "model": "whatever",
        "config": {"temperature": 1}})          # 未知字段
    assert r.status_code == 400
    assert r.json()["ok"] is False
    # 校验失败不得产生副作用条目
    d = client.get("/api/model-config").json()
    ds = next(p for p in d["providers"] if p["name"] == "DeepSeek")
    assert all(x["id"] != "whatever" for x in ds["models"])


def test_add_and_delete_model(env):
    client, _cfg, _state, _am = env
    r = client.post("/api/model-config/model", json={
        "provider": "DeepSeek", "model": "brand-new-m",
        "config": {"max_context_tokens": 65536}})
    assert r.status_code == 200 and r.json()["ok"]
    r4 = client.delete("/api/model-config/model?provider=DeepSeek&model=brand-new-m")
    assert r4.status_code == 200 and r4.json()["ok"]
    d = client.get("/api/model-config").json()
    ds = next(p for p in d["providers"] if p["name"] == "DeepSeek")
    assert all(x["id"] != "brand-new-m" for x in ds["models"])
    assert client.delete("/api/model-config/model?provider=DeepSeek&model=no-such").status_code == 404


# ── 3. 同步入库 ───────────────────────────────────────────

def test_sync_live_models_into_store(env, monkeypatch):
    client, _cfg, _state, _am = env
    import tea_agent.model_manager as mm_mod

    svc = mm_mod.get_provider_service()

    def fake_live(api_url, api_key):
        return {"ok": True,
                "models": [{"id": "deepseek-chat"}, {"id": "gw-only-model"}],
                "total": 2, "endpoint": "https://api.deepseek.com/v1/models"}
    monkeypatch.setattr(svc, "_query_live", fake_live)
    r = client.post("/api/model-config/sync",
                    json={"provider": "DeepSeek", "api_key": "sk-test1234567890"})
    assert r.status_code == 200
    d = r.json()
    assert d["ok"] and d["query_source"] == "live"
    assert "gw-only-model" in d["added"] and "deepseek-chat" in d["kept"]
    d2 = client.get("/api/model-config").json()
    ds = next(p for p in d2["providers"] if p["name"] == "DeepSeek")
    new = next(x for x in ds["models"] if x["id"] == "gw-only-model")
    assert new["config"]["max_context_tokens"] > 0  # 启发式默认已补齐


# ── 4. 切换并继续会话（空闲路径） ─────────────────────────

def test_switch_persists_and_binds_role(env):
    client, cfg, _state, _am = env
    import yaml
    r = client.post("/api/model-config/switch", json={
        "provider": "DeepSeek", "model": "deepseek-reasoner",
        "role": "main", "api_key": "sk-new123456789012", "continue_session": True,
    })
    assert r.status_code == 200
    d = r.json()
    assert d["ok"] and d["model"] == "deepseek-reasoner"
    # 1) config.yaml 落盘
    disk = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    assert disk["main_model"]["model_name"] == "deepseek-reasoner"
    # 2) 逐模型配置注入 options（reasoner 支持思考）
    assert disk["main_model"]["options"]["supports_reasoning"] is True
    # 3) roles 绑定写回 model_config.json（面板单一事实源）
    mc = client.get("/api/model-config").json()
    assert mc["roles"]["main"]["model"] == "deepseek-reasoner"
    # 4) 会话续用：无长驻 Agent/空闲 → applied 或 next_message
    assert d["switch"]["mode"] in ("applied", "next_message")
    # 5) 下一条消息读到新模型（config_cache 已失效）
    from tea_agent.server.modules.agent_module import AgentModule
    sess, _ = AgentModule.create_session(str(cfg))
    model = getattr(sess.context, "model", None) or getattr(sess, "model", "")
    assert "deepseek-reasoner" in str(model)


# ── 5. 会话进行中：挂起 → 本轮结束自动应用 ────────────────

def test_session_continue_deferred_switch(env, monkeypatch):
    client, _cfg, state, AgentModule = env
    # 模拟一个正在流式输出的回合
    state.active_sessions["t-busy"] = object()
    r = client.post("/api/model-config/switch", json={
        "provider": "DeepSeek", "model": "deepseek-v4-flash",
        "role": "main", "api_key": "sk-k1234567890ab", "continue_session": True,
    })
    d = r.json()
    assert d["ok"] and d["switch"]["mode"] == "pending_next_turn"
    assert AgentModule.get_pending_switch()["model_name"] == "deepseek-v4-flash"
    # 面板可见排队状态（前端横幅数据源）
    assert client.get("/api/model-config").json()["pending_switch"]["model_name"] \
        == "deepseek-v4-flash"
    # 挂起期间，其他会话仍在进行 → 不应用
    state.active_sessions["t-other"] = object()
    assert AgentModule.try_apply_pending_switch() is None
    # 本轮结束（全部空闲）→ 自动应用，继续同一会话
    state.active_sessions.clear()

    class _FakeAgent:
        sess = None
        _cfg = None
        current_topic_id = ""

    calls = []
    monkeypatch.setattr(AgentModule, "_instance", _FakeAgent())
    monkeypatch.setattr(
        AgentModule, "switch_model",
        classmethod(lambda cls, *a, **k: calls.append((a, k))))
    out = AgentModule.try_apply_pending_switch()
    assert out and out["mode"] == "applied_after_turn"
    assert calls and calls[0][0][2] == "deepseek-v4-flash"  # 新模型名
    assert AgentModule.get_pending_switch() is None
