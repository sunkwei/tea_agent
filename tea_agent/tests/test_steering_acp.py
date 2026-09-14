"""ACP 插话（steering）回归测试。

背景：ACP 回合跑在**独立进程**里，插话队列（``state.message_queue``）与 HTTP 服务端
同源但不共享；此前 ACP 既没有入队接口、也没挂插话来源，于是"ACP 会话进行中插话"
完全不可用。现在：

- ``POST /v1/sessions/{session_id}/steering`` 入队；
- ACP 的 ``_run_stream`` 在 chat_stream 前挂上 providers，工具循环在轮边界注入。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

starlette_testclient = pytest.importorskip("starlette.testclient")


@pytest.fixture(autouse=True)
def _hermetic_queue(tmp_path, monkeypatch):
    """排队字典是进程级全局，用例前后清空并隔离落盘路径。"""
    from tea_agent.server.modules import state

    monkeypatch.setattr(state, "_queue_store_path", lambda: str(tmp_path / "q.json"))
    with state.message_queue_lock:
        state.message_queue.clear()
    yield
    with state.message_queue_lock:
        state.message_queue.clear()


class TestSteeringEndpoint:
    """POST /v1/sessions/{session_id}/steering"""

    @staticmethod
    def _client():
        from tea_agent.protocol.acp_server import create_app

        return starlette_testclient.TestClient(create_app(), raise_server_exceptions=False)

    def test_queues_message(self):
        c = self._client()
        r = c.post("/v1/sessions/sess-1/steering", json={"message": "先停下手头工作"})
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["ok"] is True and data["item_id"]
        assert data["position"] == 1

        from tea_agent.server.modules.state import queue_list

        items = queue_list("sess-1")
        assert [i["message"] for i in items] == ["先停下手头工作"]
        assert items[0]["id"] == data["item_id"]

    def test_missing_message_rejected(self):
        c = self._client()
        assert c.post("/v1/sessions/sess-1/steering", json={"message": "  "}).status_code == 400
        assert c.post("/v1/sessions/sess-1/steering", json={}).status_code == 400

    def test_unknown_session_path_requires_session_id(self):
        """/v1/sessions//steering 这类空 id 不应入队。"""
        c = self._client()
        r = c.post("/v1/sessions/%20/steering", json={"message": "x"})
        assert r.status_code in (400, 404), r.status_code


class TestAcpTurnWiring:
    """ACP 回合必须挂上插话来源，且能消费本会话排队的插话。"""

    def test_wire_steering_sets_providers(self):
        from tea_agent.protocol.acp_server import ACPProtocolServer

        sess = SimpleNamespace(current_topic_id="sess-x", context=SimpleNamespace(messages=[]))
        ACPProtocolServer._wire_steering(sess)

        assert callable(getattr(sess, "_steering_provider", None)), "未挂插话来源"
        assert callable(getattr(sess, "_followup_provider", None)), "未挂后续任务来源"

    def test_wired_provider_drains_endpoint_queue(self):
        """端到端：接口入队 → ACP 回合的 provider 能取到（同一 topic）。"""
        from tea_agent.protocol.acp_server import ACPProtocolServer

        self._client_post("sess-y", "插话内容")
        sess = SimpleNamespace(current_topic_id="sess-y", context=SimpleNamespace(messages=[]))
        ACPProtocolServer._wire_steering(sess)

        items = sess._steering_provider()
        assert [i["message"] for i in items] == ["插话内容"]
        # 消费式：再次取为空
        assert sess._steering_provider() == []

    @staticmethod
    def _client_post(session_id: str, message: str):
        from tea_agent.protocol.acp_server import create_app

        c = starlette_testclient.TestClient(create_app(), raise_server_exceptions=False)
        assert c.post(f"/v1/sessions/{session_id}/steering", json={"message": message}).status_code == 200

    def test_run_stream_wires_before_chat(self):
        """真实 _run_stream 路径：chat_stream 被调用前 provider 已经挂好。"""
        from tea_agent.protocol.acp_server import ACPProtocolServer

        srv = ACPProtocolServer()
        observed = {}

        def _fake_chat_stream(user_msg, callback=None, topic_id=""):
            observed["has_provider"] = callable(getattr(sess, "_steering_provider", None))
            observed["topic"] = topic_id
            return "回答", False

        sess = SimpleNamespace(current_topic_id="sess-z", chat_stream=_fake_chat_stream)
        agent = SimpleNamespace(sess=sess, current_topic_id="sess-z")
        srv._init_agent = lambda session_id="": agent   # type: ignore[method-assign]

        events: list = []
        srv._run_stream("hi", "sess-z", lambda t: None, events.append)

        assert observed.get("has_provider") is True, "_run_stream 未在 chat_stream 前挂插话来源"
        assert observed.get("topic") == "sess-z"
        assert events and events[-1]["type"] == "done"

    def test_wiring_failure_does_not_break_turn(self, monkeypatch):
        """挂接失败不能影响正常对话（容错）。"""
        from tea_agent.protocol import acp_server

        def _boom(*a, **k):
            raise RuntimeError("registry down")

        monkeypatch.setattr("tea_agent.server.module.get_registry", _boom, raising=False)
        monkeypatch.setattr(acp_server, "logger", acp_server.logger)

        srv = acp_server.ACPProtocolServer()
        sess = SimpleNamespace(current_topic_id="s1", chat_stream=lambda *a, **k: ("ok", False))
        agent = SimpleNamespace(sess=sess, current_topic_id="s1")
        srv._init_agent = lambda session_id="": agent   # type: ignore[method-assign]

        events: list = []
        srv._run_stream("hi", "s1", lambda t: None, events.append)
        assert events[-1]["type"] == "done"
