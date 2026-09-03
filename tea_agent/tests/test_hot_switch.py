"""热生效回归测试：apply 模型后 create_session 必须读到新配置。

回归场景（commit 63dc6d2 修复）：
apply_provider 写入磁盘 config.yaml 后，AgentModule 的 config_cache
仍缓存启动时的旧配置 → create_session 命中缓存 → 聊天会话始终用老模型。
修复：handle_provider_apply 落盘后调用 AgentModule.invalidate_config_cache()。
"""

from __future__ import annotations

import os

import pytest


@pytest.fixture
def hot_switch_env(tmp_path, monkeypatch):
    """临时配置环境：旧模型 deepseek-chat，TEA_CONFIG 指向临时文件。

    同时重置 config.py 模块级全局（_active_config_path/_last_config_path）
    与 config_cache，避免跨测试残留导致读到上一个测试的配置。
    """
    cfg = tmp_path / "hot_switch.yaml"
    cfg.write_text(
        "main_model:\n"
        "  api_key: sk-test\n"
        "  api_url: https://api.deepseek.com\n"
        '  model_name: "deepseek-chat"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("TEA_CONFIG", str(cfg))
    # 隔离统一模型配置中心（apply 会回写 roles），避免污染真实 ~/.tea_agent
    import tea_agent.model_config as mc_mod
    import tea_agent.model_manager as mm_mod
    monkeypatch.setenv("TEA_MODEL_CONFIG", str(tmp_path / "model_config.json"))
    monkeypatch.setattr(mc_mod, "_store", None, raising=False)
    monkeypatch.setattr(mm_mod, "_service", None, raising=False)
    import tea_agent.config as cfg_mod
    from tea_agent.server.modules.agent_module import AgentModule
    from tea_agent.server.modules.state import config_cache

    config_cache.clear()
    cfg_mod._active_config_path = None
    cfg_mod._last_config_path = None
    # AgentModule._config_path 是类属性，create_app 时被设为 TEA_CONFIG 路径，
    # 跨测试残留会导致 create_session 读到上一个测试的配置（已被 apply 改写）
    AgentModule._config_path = ""
    return cfg


def _session_model():
    from tea_agent.server.modules.agent_module import AgentModule

    sess, _ = AgentModule.create_session(None)
    if hasattr(sess.context, "model"):
        return sess.context.model
    return sess.model


def test_apply_invalidates_config_cache(hot_switch_env, monkeypatch):
    """apply 后 create_session 应读到新模型（修复前命中旧缓存）。"""
    from tea_agent.server.modules.agent_module import AgentModule
    from tea_agent.server.server import create_app
    from starlette.testclient import TestClient

    # 保证 config_cache 干净（避免受其他测试/会话污染）
    AgentModule.invalidate_config_cache()

    app = create_app()
    c = TestClient(app)

    # 初始会话用旧模型
    assert "deepseek-chat" in _session_model()

    # apply 新模型（走真实 API 链路）
    r = c.post(
        "/api/providers/DeepSeek/apply",
        json={"model": "deepseek-reasoner", "role": "main", "api_key": "sk-test"},
    )
    assert r.status_code == 200
    assert r.json().get("ok") is True
    assert r.json()["model"] == "deepseek-reasoner"

    # 关键断言：新会话必须读到新模型
    m1 = _session_model()
    assert "deepseek-reasoner" in m1, f"FAIL: session still uses old model: {m1}"

    # 磁盘配置已更新
    import yaml

    disk = yaml.safe_load(hot_switch_env.read_text(encoding="utf-8"))
    assert disk["main_model"]["model_name"] == "deepseek-reasoner"


def test_api_model_switch_persists_and_invalidates(hot_switch_env, monkeypatch):
    """POST /api/model 热切换后：落盘 + 失效缓存 → 新会话读新模型。"""
    from tea_agent.server.modules.agent_module import AgentModule
    from tea_agent.server.server import create_app
    from starlette.testclient import TestClient

    AgentModule.invalidate_config_cache()
    app = create_app()
    c = TestClient(app)

    assert "deepseek-chat" in _session_model()

    r = c.post(
        "/api/model",
        json={
            "api_key": "sk-test",
            "api_url": "https://api.deepseek.com",
            "model_name": "deepseek-reasoner",
        },
    )
    assert r.status_code == 200
    assert r.json().get("ok") is True

    # 磁盘已落盘（修复前 switch_model 只改内存不写磁盘）
    import yaml

    disk = yaml.safe_load(hot_switch_env.read_text(encoding="utf-8"))
    assert disk["main_model"]["model_name"] == "deepseek-reasoner"

    # 新会话读新模型（修复前 config_cache 命中旧配置）
    assert "deepseek-reasoner" in _session_model()


def test_invalidate_config_cache_removes_keys(tmp_path, monkeypatch):
    """invalidate 应清除所有相关缓存 key（默认/显式/实例路径）。"""
    from tea_agent.server.modules import agent_module as am
    from tea_agent.server.modules.state import config_cache

    config_cache.clear()
    cfg_path = str(tmp_path / "x.yaml")
    config_cache["__default__"] = {"dummy": 1}
    config_cache[cfg_path] = {"dummy": 2}
    am.AgentModule._config_path = cfg_path

    am.AgentModule.invalidate_config_cache(cfg_path)

    assert "__default__" not in config_cache
    assert cfg_path not in config_cache
