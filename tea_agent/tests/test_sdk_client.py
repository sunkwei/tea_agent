"""SDK 客户端回归测试。

背景：sdk/client.py 的 ``Request(method, url, headers=..., data=...)`` 位置写反
（正确签名为 ``Request(url, data=None, headers={}, method=None)``），令**每一个**
SDK 方法都抛 ``TypeError: got multiple values for argument 'data'``；叠加 chat()
里 ``{messages: ...}`` 把键名当裸变量，SDK 自引入（9ea22a9）起从未可用。
全项目 1663 个测试无一触达该文件，故长期无人发现。

本测试用真实 HTTP 服务器打全链路，而不是 mock——mock 恰恰会放过这次的参数错位。
"""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from sdk import AgentSDK
from sdk.client import assemble_sse


class _Handler(BaseHTTPRequestHandler):
    """回显收到的请求，并按路由返回不同形态的响应。"""

    def log_message(self, *args):  # 静音
        pass

    def _respond(self, code, body, content_type="application/json"):
        # 记录请求头，供断言鉴权头/Content-Type 是否真的送达
        self.server.last_headers = {k.lower(): v for k, v in self.headers.items()}
        raw = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path == "/health":
            self._respond(200, json.dumps({"status": "ok"}))
        elif self.path.startswith("/v1/sessions/"):
            topic = self.path.rsplit("/", 1)[-1]
            if topic == "ERR":
                # get_session 的错误分支：非 200 必须返回 None
                self._respond(500, json.dumps({"error": "no such topic"}))
            else:
                self._respond(200, json.dumps({"id": topic, "title": "t"}))
        elif self.path == "/v1/empty":
            self._respond(200, "")
        elif self.path == "/v1/html404":
            self._respond(404, "<html>not found</html>", "text/html")
        elif self.path == "/v1/session_err":
            self._respond(500, json.dumps({"error": "no such topic"}))
        elif self.path == "/v1/unauthorized":
            self._respond(401, json.dumps({"error": "bad key"}))
        elif self.path.startswith("/v1/tools"):
            self._respond(200, json.dumps({"object": "list",
                                           "data": [{"name": "toolkit_exec"}]}))
        elif self.path.startswith("/v1/sessions"):
            self._respond(200, json.dumps({"object": "list",
                                           "data": [{"id": "topic-1"}]}))
        else:
            self._respond(404, json.dumps({"error": "no route"}))

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length).decode("utf-8") if length else ""
        received = json.loads(raw) if raw else {}
        self.server.last_body = received

        if self.path == "/v1/chat/completions":
            if received.get("stream"):
                sse = (
                    'data: {"choices":[{"delta":{"role":"assistant"}}]}\n\n'
                    'data: {"choices":[{"delta":{"content":"Hel"}}]}\n\n'
                    'data: {"choices":[{"delta":{"content":"lo!"}}]}\n\n'
                    'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n'
                    "data: [DONE]\n\n"
                )
                self._respond(200, sse, "text/event-stream")
            else:
                self._respond(200, json.dumps(
                    {"choices": [{"message": {"role": "assistant",
                                              "content": "Hello!"}}]}))
        elif self.path.endswith("/run"):
            self._respond(200, json.dumps({"ok": True, "echo": received}))
        elif self.path == "/v1/sessions":
            self._respond(201, json.dumps({"id": "new-topic",
                                           "title": received.get("title", "")}))
        else:
            self._respond(404, json.dumps({"error": "no route"}))

    def do_DELETE(self):
        self._respond(200, json.dumps({"ok": True}))


@pytest.fixture(scope="module")
def server():
    srv = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield srv
    srv.shutdown()


@pytest.fixture
def sdk(server):
    return AgentSDK(f"127.0.0.1:{server.server_address[1]}", api_key="k", timeout=10)


class TestRequestIsWellFormed:
    """核心回归：Request 参数位置不得再写反。"""

    def test_get_returns_json_not_typeerror(self, sdk):
        # 旧代码在此抛 TypeError: multiple values for argument 'data'
        assert sdk.health().get("status") == "ok"

    def test_list_tools(self, sdk):
        assert sdk.list_tools() == [{"name": "toolkit_exec"}]

    def test_list_sessions(self, sdk):
        assert sdk.list_sessions(limit=5) == [{"id": "topic-1"}]

    def test_get_session(self, sdk):
        assert sdk.get_session("abc")["id"] == "abc"

    def test_delete_session(self, sdk):
        assert sdk.delete_session("abc") is True

    def test_api_key_header_actually_sent(self, server):
        """鉴权头必须真的出现在请求里 —— 否则调用方永远拿到 401 却不知为何。"""
        sdk = AgentSDK(f"127.0.0.1:{server.server_address[1]}", api_key="secret-k", timeout=10)
        server.last_headers = {}
        sdk.health()
        # handler 已把键统一小写（HTTP 头名大小写不敏感）
        assert server.last_headers.get("x-api-key") == "secret-k", server.last_headers

    def test_content_type_json_on_post(self, sdk, server):
        """带 body 的请求必须声明 application/json。"""
        sdk.chat("hi")
        assert server.last_headers.get("content-type") == "application/json", server.last_headers

    def test_no_content_type_on_get(self, sdk, server):
        server.last_headers = {}
        sdk.health()
        assert "content-type" not in server.last_headers, server.last_headers

    def test_no_header_when_no_api_key(self, server):
        sdk = AgentSDK(f"127.0.0.1:{server.server_address[1]}", timeout=10)
        server.last_headers = {}
        sdk.health()
        assert "x-api-key" not in server.last_headers, server.last_headers


class TestChat:
    def test_chat_payload_shape(self, sdk, server):
        assert sdk.chat("hi") == "Hello!"
        body = server.last_body
        assert body["messages"] == [{"role": "user", "content": "hi"}]
        assert "stream" in body and "model" in body

    def test_chat_sends_json_content_type(self, sdk):
        """POST 必须带 Content-Type，否则多数服务端按纯文本拒收。"""
        assert sdk.chat("x") == "Hello!"

    def test_chat_topic_id_forwarded(self, sdk, server):
        sdk.chat("hi", topic_id="t-9")
        assert server.last_body["topic_id"] == "t-9"

    def test_chat_omits_topic_id_when_empty(self, sdk, server):
        sdk.chat("hi")
        assert "topic_id" not in server.last_body

    def test_chat_stream_true_assembles_sse(self, sdk, server):
        """stream=True 必须真正以流式发出，并把 SSE 分帧拼回完整文本。

        旧代码在构造 payload 时就因裸变量 messages 抛 NameError，流式路径从未走通。
        """
        assert sdk.chat("hi", stream=True) == "Hello!"
        assert server.last_body["stream"] is True

    def test_chat_sends_json_content_type(self, sdk):
        """POST 必须带 Content-Type，否则多数服务端按纯文本拒收。"""
        assert sdk.chat("x") == "Hello!"

    def test_stream_false_is_not_sent_as_true(self, sdk, server):
        """非流式必须确实是非流式（默认值不得被翻转）。"""
        sdk.chat("hi")
        assert server.last_body["stream"] is False

    def test_chat_error_surfaces_message(self, sdk):
        assert sdk.chat(None)  # 不得抛异常

    def test_http_error_code_preserved(self, server):
        """4xx 不得被伪装成 500（旧实现让 json.loads 异常穿透，状态码丢失）。"""
        sdk = AgentSDK(f"127.0.0.1:{server.server_address[1]}", timeout=10)
        code, data = sdk._request("GET", "/v1/unauthorized")
        assert code == 401, f"HTTP 状态码被吞: {code}"
        assert data.get("error") == "bad key"

    def test_non_json_body_does_not_clobber_status(self, server):
        sdk = AgentSDK(f"127.0.0.1:{server.server_address[1]}", timeout=10)
        code, data = sdk._request("GET", "/v1/html404")
        assert code == 404, f"HTML 错误页让状态码退化成 500: {code}"

    def test_empty_body_is_not_error(self, server):
        sdk = AgentSDK(f"127.0.0.1:{server.server_address[1]}", timeout=10)
        code, data = sdk._request("GET", "/v1/empty")
        assert code == 200
        assert data == {}

    def test_connection_refused_is_readable(self, monkeypatch):
        """本机地址必须绕开系统代理。

        Windows 下 urlopen 默认读取注册表代理；若走代理，服务未启动时拿到的是
        代理返回的 502（真实原因「连不上」被吞），且请求从未到达本地服务。
        """
        import urllib.request as ur

        called = {"proxy": False}
        real_build = ur.build_opener

        def spy(*args, **kw):
            if any(isinstance(h, ur.ProxyHandler) for h in args):
                called["proxy"] = True
            return real_build(*args, **kw)

        monkeypatch.setattr(ur, "build_opener", spy)
        dead = AgentSDK("127.0.0.1:1", timeout=5)
        code, data = dead._request("GET", "/health")
        assert code == 500, f"状态码来自代理而非本地服务: {code} {data}"
        assert "无法连接" in data.get("error", ""), data
        assert called["proxy"], "本机地址未绕开系统代理"


class TestRunToolAndSession:
    def test_run_tool_sends_arguments(self, sdk, server):
        out = sdk.run_tool("toolkit_notify", {"title": "t"})
        assert server.last_body == {"arguments": {"title": "t"}}
        assert out["ok"] is True

    def test_run_tool_with_empty_arguments_still_posts_body(self, sdk, server):
        """arguments={} 是合法入参，不得被 `if data` 判空后丢掉 body 变成 GET。"""
        sdk.run_tool("toolkit_notify", {})
        assert server.last_body == {"arguments": {}}

    def test_create_session(self, sdk):
        assert sdk.create_session("my title") == "new-topic"

    def test_get_session_returns_none_on_error(self, sdk):
        """非 200 必须返回 None —— 旧代码会把解析异常抛给调用方。"""
        assert sdk.get_session("ERR") is None


class TestAssembleSse:
    """纯函数：SSE 拼装。"""

    def test_concatenates_deltas(self):
        raw = (
            'data: {"choices":[{"delta":{"content":"a"}}]}\n\n'
            'data: {"choices":[{"delta":{"content":"b"}}]}\n\n'
            "data: [DONE]\n\n"
        )
        assert assemble_sse(raw) == "ab"

    def test_ignores_role_only_and_done(self):
        raw = (
            'data: {"choices":[{"delta":{"role":"assistant"}}]}\n\n'
            'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n'
            "data: [DONE]\n\n"
        )
        assert assemble_sse(raw) == ""

    def test_tolerates_garbage_frames(self):
        raw = "data: not-json\n\ndata: {\"choices\":[{\"delta\":{\"content\":\"x\"}}]}\n\n"
        assert assemble_sse(raw) == "x"

    def test_empty_and_none_input(self):
        assert assemble_sse("") == ""
        assert assemble_sse(None) == ""

    def test_utf8_multibyte_preserved(self):
        raw = 'data: {"choices":[{"delta":{"content":"你好，世界"}}]}\n\ndata: [DONE]\n\n'
        assert assemble_sse(raw) == "你好，世界"

    def test_message_form_supported(self):
        raw = 'data: {"choices":[{"message":{"content":"m"}}]}\n\n'
        assert assemble_sse(raw) == "m"
