"""配置对话框语义回归（POST /api/model）：

1. url/key/模型名只读 —— 不提交时缺省兑底当前值，身份三元组不被清空/改动；
2. 参数（temperature/max_tokens/top_p/max_context/能力/effort）更新落盘并热切，
   便宜模型参数兑底 url/name 后同样生效；
3. 参数写回 provider.yaml（模型属性唯一事实源），含 cheap 角色与
   supports_vision=False（旧 upsert 过滤会把 False/0.0 当空值丢弃）；
4. provider_store.upsert_model：0.0/False 可写入，未显式提供的键不被 blank 覆盖。

隔离：TEA_CONFIG + TEA_MODEL_CONFIG + TEA_PROVIDER_FILE → tmp_path，
绝不触碰真实用户配置。
"""

from __future__ import annotations

import pytest


@pytest.fixture
def env(tmp_path, monkeypatch):
    import yaml

    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "main_model:\n"
        "  api_key: sk-main-1234567890\n"
        "  api_url: https://api.deepseek.com\n"
        '  model_name: "deepseek-chat"\n'
        "cheap_model:\n"
        "  api_key: sk-cheap-1234567890\n"
        "  api_url: https://api.deepseek.com\n"
        '  model_name: "deepseek-flash"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("TEA_CONFIG", str(cfg))
    monkeypatch.setenv("TEA_MODEL_CONFIG", str(tmp_path / "model_config.json"))
    provider_file = tmp_path / "provider.yaml"
    provider_file.write_text(yaml.safe_dump({
        "version": 1,
        "providers": {
            "DeepSeek": {
                "api_url": "https://api.deepseek.com",
                "api_key": "sk-main-1234567890",
                "default_model": "deepseek-chat",
                "source": "builtin",
                "models": {
                    "deepseek-chat": {
                        "max_context_tokens": 131072,
                        "max_output_tokens": 8192,
                        "supports_reasoning": True,
                        "supports_vision": False,
                        "temperature": 0.7,
                        "top_p": 0.9,
                    },
                    # 初始 supports_vision=True → POST False 后断言翻转，
                    # 钉住「False 可写回」契约（旧过滤会静默丢弃）。
                    "deepseek-flash": {
                        "max_context_tokens": 65536,
                        "max_output_tokens": 4096,
                        "supports_reasoning": False,
                        "supports_vision": True,
                        "temperature": 0.7,
                        "top_p": 0.9,
                    },
                },
            },
        },
    }, allow_unicode=True, sort_keys=False), encoding="utf-8")
    monkeypatch.setenv("TEA_PROVIDER_FILE", str(provider_file))

    import tea_agent.config as cfg_mod
    import tea_agent.model_config as mc_mod
    import tea_agent.model_manager as mm_mod
    import tea_agent.provider_store as ps_mod
    from tea_agent.server.modules import state
    from tea_agent.server.modules.agent_module import AgentModule

    monkeypatch.setattr(mc_mod, "_store", None)
    monkeypatch.setattr(mm_mod, "_service", None)
    monkeypatch.setattr(ps_mod, "_store", None)
    state.config_cache.clear()
    state.active_sessions.clear()
    state.background_sessions.clear()
    cfg_mod._active_config_path = None
    cfg_mod._last_config_path = None
    AgentModule._config_path = ""
    monkeypatch.setattr(AgentModule, "_pending_switch", None, raising=False)

    from starlette.testclient import TestClient
    from tea_agent.server.server import create_app

    client = TestClient(create_app(config_path=str(cfg)))
    yield client, cfg, provider_file, AgentModule
    state.active_sessions.clear()
    state.background_sessions.clear()


def _dialog_payload() -> dict:
    """配置对话框实际提交体：无 api_url/api_key/model_name（只读语义）。"""
    return {
        "temperature": 0.3,
        "max_tokens": 5555,
        "top_p": 0.8,
        "max_context_tokens": 100000,
        "options": {"supports_vision": True, "supports_reasoning": True,
                    "reasoning_effort": "high"},
        "cheap_temperature": 0.1,
        "cheap_max_tokens": 2222,
        "cheap_top_p": 0.6,
        "cheap_max_context_tokens": 32768,
        "cheap_options": {"supports_vision": False, "supports_reasoning": False,
                          "reasoning_effort": "low"},
    }


def test_apply_without_url_key_keeps_identity(env):
    """不提交 url/key/模型名 → 兑底当前值，身份三元组不变；参数全部生效。"""
    import yaml
    client, cfg, _pf, _am = env

    r = client.post("/api/model", json=_dialog_payload())
    assert r.status_code == 200, r.text
    assert r.json().get("ok") is True, r.json()

    disk = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    main = disk["main_model"]
    # 身份三元组保持（兑底当前值，不清空不改动）
    assert main["api_url"] == "https://api.deepseek.com"
    assert main["api_key"] == "sk-main-1234567890"
    assert main["model_name"] == "deepseek-chat"
    # 主模型参数生效
    assert float(main["temperature"]) == 0.3
    assert int(main["max_tokens"]) == 5555
    assert float(main["top_p"]) == 0.8
    assert int(main["max_context_tokens"]) == 100000
    assert main["options"]["reasoning_effort"] == "high"
    assert main["options"]["supports_vision"] is True
    # cheap 参数（后端兑底 cheap url/name 后 switch_model 才应用 cheap 分支）
    cheap = disk["cheap_model"]
    assert cheap["model_name"] == "deepseek-flash"
    assert cheap["api_key"] == "sk-cheap-1234567890"
    assert cheap["api_url"] == "https://api.deepseek.com"
    assert float(cheap["temperature"]) == 0.1
    assert int(cheap["max_tokens"]) == 2222
    assert float(cheap["top_p"]) == 0.6
    assert int(cheap["max_context_tokens"]) == 32768
    assert cheap["options"]["reasoning_effort"] == "low"


def test_apply_writes_back_provider_yaml(env):
    """参数写回 provider.yaml：main + cheap 条目（窗口/输出/采样/能力/effort）。"""
    import yaml
    client, _cfg, pf, _am = env

    r = client.post("/api/model", json=_dialog_payload())
    assert r.status_code == 200, r.text
    assert r.json().get("ok") is True, r.json()

    pdata = yaml.safe_load(pf.read_text(encoding="utf-8"))
    models = pdata["providers"]["DeepSeek"]["models"]
    dm = models["deepseek-chat"]
    assert int(dm["max_context_tokens"]) == 100000
    assert int(dm["max_output_tokens"]) == 5555
    assert float(dm["temperature"]) == 0.3
    assert float(dm["top_p"]) == 0.8
    assert dm["supports_vision"] is True      # False → True 翻转
    assert dm["reasoning_effort"] == "high"
    # cheap 按 api_url 反查到同 provider，写到 deepseek-flash 条目
    cf = models["deepseek-flash"]
    assert int(cf["max_context_tokens"]) == 32768
    assert int(cf["max_output_tokens"]) == 2222
    assert float(cf["temperature"]) == 0.1
    assert float(cf["top_p"]) == 0.6
    assert cf["supports_vision"] is False     # True → False 翻转（0.0/False 可写契约）
    assert cf["reasoning_effort"] == "low"


def test_upsert_model_zero_false_and_unspecified(env):
    """upsert_model：0.0/False 是有效值可写；未显式提供的键不被 blank 覆盖。"""
    from tea_agent.provider_store import get_provider_store
    client, _cfg, _pf, _am = env
    store = get_provider_store()

    store.upsert_model("DeepSeek", "deepseek-chat",
                       {"max_context_tokens": 131072, "supports_vision": True,
                        "temperature": 0.7})
    store.upsert_model("DeepSeek", "deepseek-chat",
                       {"temperature": 0.0, "top_p": 0.0, "supports_vision": False})
    entry = store.providers()["DeepSeek"]["models"]["deepseek-chat"]
    assert float(entry["temperature"]) == 0.0   # 旧过滤：0.0 被当空值丢弃 → 红
    assert float(entry["top_p"]) == 0.0
    assert entry["supports_vision"] is False    # 旧过滤：False 被丢弃 → 红
    assert int(entry["max_context_tokens"]) == 131072  # 未提供的键保持既有值
