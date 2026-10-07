"""状态栏「主模型: <provider> · <model>」显示契约。

回归背景一（provider 永久陈旧）：
    状态栏那行由 ``static/app.js::_usageBarHtml`` 渲染 ``usage.model_provider``
    与 ``usage.model``。二者必须**同源**，但早期实现里：

      - ``model``         ← 会话 context（随切换刷新）
      - ``model_provider`` ← 长驻 Agent 的 ``config.main_model.provider``

    而 ``switch_model`` 只更新 api_url / api_key /
    model_name，**从不更新 provider / ref_model**。于是 provider 永久停留在
    进程首次加载配置文件时的值，状态栏出现「qwen · deepseek-v4-flash」这类
    明显错配（provider 与 model 分属两个不同来源）。
"""

from __future__ import annotations

import types
from unittest.mock import MagicMock

import pytest

# ═══════════════════════════════════════════════════════════════
# 背景一：provider 必须与会话 model 同源
# ═══════════════════════════════════════════════════════════════


class TestProviderFollowsSession:
    """usage.model_provider 与会话 context.provider 同源。"""

    def _fake_session(self, model: str, provider: str):
        sess = MagicMock()
        sess.context.model = model
        sess.context.provider = provider
        sess.context.cheap_model = "cheap-m"
        sess._last_usage = {"total_tokens": 10, "prompt_tokens": 8, "completion_tokens": 2}
        sess._last_cheap_usage = {}
        return sess

    def test_usage_data_provider_matches_model_source(self):
        """同一 session 的 provider 与 model 必须成对出现（不得跨对象取值）。"""
        from tea_agent.server.modules.agent_module import _build_usage_data

        ud = _build_usage_data(self._fake_session("deepseek-v4-flash", "qwen"))
        assert ud["model"] == "deepseek-v4-flash"
        assert ud["model_provider"] == "qwen"

    def test_provider_name_prefers_session_over_stale_instance(self, monkeypatch):
        """有会话时以会话为准，忽略可能陈旧的长驻 Agent config。"""
        from tea_agent.server.modules import agent_module as am

        stale = MagicMock()
        stale.config.main_model.provider = "stale-provider"
        monkeypatch.setattr(am.AgentModule, "_instance", stale, raising=False)

        assert am._get_main_provider_name(self._fake_session("m", "fresh-provider")) == "fresh-provider"

    def test_provider_name_falls_back_to_instance_without_session(self, monkeypatch):
        """无会话（或会话未带 provider）时退回实例 config。"""
        from tea_agent.server.modules import agent_module as am

        inst = MagicMock()
        inst.config.main_model.provider = "deepseek"
        monkeypatch.setattr(am.AgentModule, "_instance", inst, raising=False)

        assert am._get_main_provider_name() == "deepseek"
        no_prov = self._fake_session("m", "")
        assert am._get_main_provider_name(no_prov) == "deepseek"

    def test_provider_name_empty_when_unknown(self, monkeypatch):
        """全未知时返回空串 —— 前端据此省略 Provider 段而不是显示错的。"""
        from tea_agent.server.modules import agent_module as am

        monkeypatch.setattr(am.AgentModule, "_instance", None, raising=False)
        assert am._get_main_provider_name() == ""
        assert am._get_main_provider_name(self._fake_session("m", "")) == ""


class TestSessionContextCarriesProvider:
    """SessionContext 必须自带 provider（与 model 同生命周期）。"""

    def test_default_empty(self):
        from tea_agent.session.context import SessionContext

        assert SessionContext().provider == ""

    def test_online_session_wires_provider_into_context(self):
        from tea_agent.onlinesession import OnlineToolSession

        tk = MagicMock()
        tk.meta_map = {}
        sess = OnlineToolSession(
            toolkit=tk,
            api_key="sk-test",
            api_url="https://api.test.com/v1",
            model="test-model",
            provider="deepseek",
            enable_thinking=False,
            no_stream_chunk=True,
        )
        try:
            assert sess.context.provider == "deepseek"
            assert sess.context.model == "test-model"
        finally:
            sess.close()


class TestSwitchModelUpdatesProvider:
    """switch_model 必须同时更新 provider / ref_model（否则状态栏永久陈旧）。"""

    def _install_fake_agent(self, monkeypatch):
        from tea_agent.server.modules import agent_module as am

        cfg = types.SimpleNamespace(
            main_model=types.SimpleNamespace(
                api_key="old",
                api_url="http://old",
                model_name="old",
                provider="old-provider",
                ref_model="old-ref",
                temperature=None,
                max_tokens=None,
                top_p=None,
                max_context_tokens=None,
                options=None,
            ),
            cheap_model=types.SimpleNamespace(api_key="", api_url="", model_name=""),
        )
        agent = MagicMock()
        agent._cfg = cfg
        agent.current_topic_id = ""
        agent.sess = None
        monkeypatch.setattr(am.AgentModule, "_instance", agent, raising=False)
        return am, cfg

    def test_provider_and_ref_updated(self, monkeypatch):
        am, cfg = self._install_fake_agent(monkeypatch)
        am.AgentModule.switch_model(
            "sk-new",
            "https://api.deepseek.com",
            "deepseek-v4-flash",
            provider="deepseek",
            ref_model="deepseek-v4-flash",
        )
        assert cfg.main_model.provider == "deepseek"
        assert cfg.main_model.ref_model == "deepseek-v4-flash"
        assert cfg.main_model.model_name == "deepseek-v4-flash"

    def test_none_provider_keeps_existing(self, monkeypatch):
        """未提供 provider（None）时不得用空值覆盖已知的 provider。"""
        am, cfg = self._install_fake_agent(monkeypatch)
        am.AgentModule.switch_model("sk-new", "https://api.x.com", "m2")
        assert cfg.main_model.provider == "old-provider"
        assert cfg.main_model.ref_model == "old-ref"

    def test_explicit_empty_clears(self, monkeypatch):
        """显式传空串才是清空（与 None 语义区分）。"""
        am, cfg = self._install_fake_agent(monkeypatch)
        am.AgentModule.switch_model("sk", "https://api.x.com", "m", provider="", ref_model="")
        assert cfg.main_model.provider == ""
        assert cfg.main_model.ref_model == ""


@pytest.mark.parametrize("role", ["main_model", "cheap_model"])
def test_provider_field_exists_on_model_config(role):
    """两种角色都应有 provider 字段（热切换依赖它透传）。"""
    from tea_agent.config import AgentConfig

    cfg = AgentConfig()
    assert hasattr(getattr(cfg, role), "provider")
