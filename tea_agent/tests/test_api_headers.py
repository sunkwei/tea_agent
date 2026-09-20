"""出站请求头注入 + 容错 httpx 客户端构建的回归测试。

背景一（OpenCode Go/Zen）：网关要求客户端发送稳定的 ``x-opencode-session``
并建议使用自有 User-Agent，缺失时直接 400::

    {"type":"error","error":{"type":"MissingSessionID","message":"... missing
     x-opencode-session and cannot be routed efficiently."}}

背景二（畸形代理环境变量）：``httpx.Client(proxy=None)`` 仍会读环境代理，
``NO_PROXY`` 含 ``[::1]`` 时构造直接抛 ``InvalidURL``，导致会话无法建立。

覆盖：
- is_opencode_endpoint：命中 Go/Zen，拒绝伪装域名与其它 provider
- 事件钩子：真实请求头被改写、session id 随对话动态变化、非 opencode 端点不注入
- sanitize_headers：头名校验 / CRLF 防护 / ${ENV_VAR} 引用
- resolve_extra_headers：host 匹配优先级与配置驱动注入
- default_headers_for：构造期固定头形式
- build_http_client：代理环境畸形时降级而非崩溃
- OnlineToolSession / LiteSession 集成
"""

from unittest.mock import MagicMock

import httpx
import pytest

from tea_agent.api_headers import (
    OPENCODE_SESSION_HEADER,
    build_http_client,
    default_headers_for,
    is_opencode_endpoint,
    new_session_id,
    request_event_hooks,
    resolve_extra_headers,
    sanitize_headers,
    user_agent,
)

GO_URL = "https://opencode.ai/zen/go/v1"
ZEN_URL = "https://opencode.ai/zen/v1"
OTHER_URL = "https://api.deepseek.com/v1"


def _echo_client(base_url: str, **hook_kwargs) -> httpx.Client:
    """构造一个把收到的请求头回显出来的客户端（MockTransport，不发真实网络）。"""
    return httpx.Client(
        base_url=base_url,
        event_hooks=request_event_hooks(base_url, **hook_kwargs),
        transport=httpx.MockTransport(lambda req: httpx.Response(200, json={"seen": dict(req.headers)})),
    )


def _seen(client: httpx.Client) -> dict:
    return client.post("/chat/completions", json={}).json()["seen"]


class TestIsOpencodeEndpoint:
    """端点识别"""

    def test_go_and_zen_matched(self):
        assert is_opencode_endpoint(GO_URL)
        assert is_opencode_endpoint(ZEN_URL)
        assert is_opencode_endpoint("https://OPENCODE.AI/zen/go/v1")

    def test_other_providers_not_matched(self):
        for url in (OTHER_URL, "https://api.openai.com/v1", "http://127.0.0.1:8000/v1", "", None):
            assert not is_opencode_endpoint(url), url

    def test_lookalike_domain_rejected(self):
        """opencode.ai.evil.com 之类的伪装域名不得拿到会话头。"""
        assert not is_opencode_endpoint("https://opencode.ai.evil.com/v1")
        assert not is_opencode_endpoint("https://notopencode.ai/v1")


class TestUserAgent:
    """自有 User-Agent"""

    def test_identifies_as_tea_agent(self):
        ua = user_agent()
        assert ua.startswith("tea-agent/")
        # 不得是 SDK / HTTP 库的通用名
        assert "openai" not in ua.lower()
        assert "httpx" not in ua.lower()

    def test_stable_across_calls(self):
        assert user_agent() == user_agent()


class TestEventHookInjection:
    """httpx 事件钩子：请求头注入"""

    def test_header_and_user_agent_injected(self):
        seen = _seen(_echo_client(GO_URL, session_id="topic-1"))
        assert seen[OPENCODE_SESSION_HEADER] == "topic-1"
        assert seen["user-agent"] == user_agent()

    def test_session_id_follows_conversation(self):
        """同一个客户端服务多个对话时，session id 必须随对话切换。"""
        current = {"topic": "topic-A"}
        client = _echo_client(GO_URL, session_id_provider=lambda: current["topic"])

        assert _seen(client)[OPENCODE_SESSION_HEADER] == "topic-A"
        current["topic"] = "topic-B"
        assert _seen(client)[OPENCODE_SESSION_HEADER] == "topic-B"

    def test_no_injection_for_other_providers(self):
        seen = _seen(_echo_client(OTHER_URL, session_id="topic-1", extra_headers={}))
        assert OPENCODE_SESSION_HEADER not in seen
        assert seen.get("user-agent") != user_agent()

    def test_empty_hooks_when_nothing_to_inject(self):
        assert request_event_hooks(OTHER_URL, extra_headers={}) == {}

    def test_missing_session_id_falls_back_to_user_agent_only(self):
        """provider 返回空值时只发 UA，不得发出空 session 头。"""
        seen = _seen(_echo_client(GO_URL, session_id_provider=lambda: ""))
        assert not seen.get(OPENCODE_SESSION_HEADER)


class TestSanitizeHeaders:
    """请求头校验（含头注入防护）"""

    def test_valid_headers_kept(self):
        assert sanitize_headers({"X-A": "1", "X-B": "two"}) == {"X-A": "1", "X-B": "two"}

    def test_non_string_values_stringified(self):
        assert sanitize_headers({"X-Num": 42}) == {"X-Num": "42"}

    def test_illegal_name_dropped(self):
        """含空格的头名非法，必须丢弃。"""
        assert sanitize_headers({"Bad Name": "1", "X-Ok": "2"}) == {"X-Ok": "2"}

    def test_crlf_in_value_dropped(self):
        """值里的 CR/LF 可用于请求拆分，必须丢弃。"""
        assert sanitize_headers({"X-A": "v\r\nX-Evil: 1"}) == {}

    def test_env_ref_expanded(self, monkeypatch):
        monkeypatch.setenv("MY_GW_TOKEN", "secret-token")
        assert sanitize_headers({"X-Token": "${MY_GW_TOKEN}"}) == {"X-Token": "secret-token"}

    def test_missing_env_ref_dropped(self, monkeypatch):
        """引用的环境变量不存在时丢弃，避免发出空密钥。"""
        monkeypatch.delenv("MY_MISSING_TOKEN", raising=False)
        assert sanitize_headers({"X-Token": "${MY_MISSING_TOKEN}"}) == {}

    def test_non_dict_returns_empty(self):
        assert sanitize_headers(None) == {}
        assert sanitize_headers("nope") == {}


class TestResolveExtraHeaders:
    """配置驱动附加头：host 匹配优先级"""

    TABLE = {
        "*": {"X-Scope": "all", "X-Common": "base"},
        "example.com": {"X-Scope": "suffix", "X-Suffix": "1"},
        "*.example.com": {"X-Wild": "1", "X-Scope": "wild"},
        "api.example.com": {"X-Scope": "exact"},
    }

    def test_all_scope(self):
        assert resolve_extra_headers("https://other.net/v1", table=self.TABLE) == {
            "X-Scope": "all",
            "X-Common": "base",
        }

    def test_suffix_match(self):
        headers = resolve_extra_headers("https://example.com/v1", table=self.TABLE)
        assert headers["X-Scope"] == "suffix"
        assert headers["X-Suffix"] == "1"

    def test_wildcard_and_exact_priority(self):
        headers = resolve_extra_headers("https://api.example.com/v1", table=self.TABLE)
        # 精确 host 优先级最高
        assert headers["X-Scope"] == "exact"
        # 通配与后缀的其它头也合并进来
        assert headers["X-Wild"] == "1"
        assert headers["X-Suffix"] == "1"
        assert headers["X-Common"] == "base"

    def test_empty_table_returns_empty(self):
        assert resolve_extra_headers(GO_URL, table={}) == {}

    def test_invalid_entries_ignored(self):
        table = {"example.com": {"Good": "1", "Bad Name": "2"}}
        assert resolve_extra_headers("https://example.com", table=table) == {"Good": "1"}


class TestConfigDrivenInjection:
    """config.yaml 的 api_headers / opencode_session_header"""

    def _patch_config(self, monkeypatch, **attrs):
        cfg = MagicMock()
        for key, value in attrs.items():
            setattr(cfg, key, value)
        monkeypatch.setattr("tea_agent.config.get_config", lambda *a, **k: cfg)
        return cfg

    def test_config_headers_applied_to_other_provider(self, monkeypatch):
        self._patch_config(
            monkeypatch,
            api_headers={"api.deepseek.com": {"X-Gateway-Token": "t0k"}},
            opencode_session_header=True,
        )
        seen = _seen(_echo_client(OTHER_URL))
        assert seen["x-gateway-token"] == "t0k"
        assert OPENCODE_SESSION_HEADER not in seen

    def test_config_headers_applied_to_opencode(self, monkeypatch):
        self._patch_config(monkeypatch, api_headers={"*": {"X-Trace": "tea"}}, opencode_session_header=True)
        seen = _seen(_echo_client(GO_URL, session_id="topic-7"))
        assert seen["x-trace"] == "tea"
        assert seen[OPENCODE_SESSION_HEADER] == "topic-7"

    def test_toggle_disables_session_header(self, monkeypatch):
        self._patch_config(monkeypatch, api_headers={}, opencode_session_header=False)
        seen = _seen(_echo_client(GO_URL, session_id="topic-7"))
        assert OPENCODE_SESSION_HEADER not in seen
        # UA 仍应标识自身
        assert seen["user-agent"] == user_agent()


class TestDefaultHeaders:
    """构造期固定头的形式"""

    def test_opencode_gets_session_and_ua(self):
        headers = default_headers_for(GO_URL)
        assert headers[OPENCODE_SESSION_HEADER]
        assert headers["User-Agent"] == user_agent()

    def test_explicit_session_id_kept(self):
        assert default_headers_for(GO_URL, session_id="topic-9")[OPENCODE_SESSION_HEADER] == "topic-9"

    def test_generated_ids_are_unique(self):
        assert new_session_id() != new_session_id()

    def test_other_provider_empty(self):
        assert default_headers_for(OTHER_URL, extra_headers={}) == {}

    def test_explicit_extra_headers_for_other_provider(self):
        headers = default_headers_for(OTHER_URL, extra_headers={"X-A": "1"})
        assert headers == {"X-A": "1"}


class TestBuildHttpClient:
    """畸形代理环境变量下的降级容错"""

    def test_normal_construction_works(self):
        client = build_http_client(5.0)
        assert isinstance(client, httpx.Client)
        client.close()

    def test_event_hooks_attached(self):
        client = build_http_client(5.0, request_event_hooks(GO_URL, session_id="t"))
        assert client.event_hooks["request"]
        client.close()

    def test_falls_back_when_env_proxy_broken(self, monkeypatch):
        """构造失败（模拟 NO_PROXY 含 [::1]）时应回退 trust_env=False，而不是崩溃。"""
        calls = {"n": 0}
        real_client = httpx.Client

        def _fake_client(**kwargs):
            calls["n"] += 1
            if kwargs.get("trust_env") is not False:
                raise ValueError("Invalid port: ':1]'")
            return real_client(trust_env=False, timeout=kwargs.get("timeout", 5.0))

        monkeypatch.setattr("httpx.Client", _fake_client)
        client = build_http_client(5.0)
        assert calls["n"] == 2, "应先原样尝试一次，失败后再降级"
        assert isinstance(client, real_client)
        client.close()

    def test_propagates_when_both_attempts_fail(self, monkeypatch):
        def _always_fail(**kwargs):
            raise RuntimeError("boom")

        monkeypatch.setattr("httpx.Client", _always_fail)
        with pytest.raises(RuntimeError):
            build_http_client(5.0)


class TestOnlineSessionIntegration:
    """OnlineToolSession 三个客户端都应挂上钩子"""

    def _make_session(self, **kwargs):
        from tea_agent.onlinesession import OnlineToolSession

        mock_tk = MagicMock()
        mock_tk.meta_map = {}
        defaults = {
            "toolkit": mock_tk,
            "api_key": "sk-test",
            "api_url": GO_URL,
            "model": "deepseek-v4.1-flash",
            "enable_thinking": False,
            "storage": None,
        }
        defaults.update(kwargs)
        return OnlineToolSession(**defaults)

    def test_opencode_clients_have_request_hooks(self):
        sess = self._make_session(
            cheap_api_key="sk-cheap",
            cheap_api_url=GO_URL,
            cheap_model="cheap-model",
            vision_api_key="sk-vis",
            vision_api_url=ZEN_URL,
            vision_model="vision-model",
        )
        try:
            assert sess._http_clients, "未登记 httpx 客户端"
            for client in sess._http_clients:
                hooks = getattr(client, "event_hooks", {}).get("request") or []
                assert hooks, "opencode 端点缺少请求头钩子"
        finally:
            sess.close()

    def test_session_id_prefers_topic_id(self):
        """有 topic id 时用它做 session id（跨重启稳定 → 缓存可复用）。"""
        sess = self._make_session()
        try:
            sess.current_topic_id = "topic-xyz"
            req = httpx.Request("POST", GO_URL + "/chat/completions")
            for hook in sess._http_clients[0].event_hooks["request"]:
                hook(req)
            assert dict(req.headers)[OPENCODE_SESSION_HEADER] == "topic-xyz"
        finally:
            sess.close()

    def test_session_id_falls_back_when_no_topic(self):
        """没有 topic id 时使用稳定的会话内 id（同一 session 不变）。"""
        sess = self._make_session()
        try:
            sess.current_topic_id = None
            ids = []
            for _ in range(2):
                req = httpx.Request("POST", GO_URL + "/chat/completions")
                for hook in sess._http_clients[0].event_hooks["request"]:
                    hook(req)
                ids.append(dict(req.headers)[OPENCODE_SESSION_HEADER])
            assert ids[0] and ids[0] == ids[1]
        finally:
            sess.close()

    def test_non_opencode_session_has_no_hooks(self, monkeypatch):
        """无附加头配置时，非 opencode 端点不应挂任何钩子。"""
        cfg = MagicMock()
        cfg.api_headers = {}
        cfg.opencode_session_header = True
        monkeypatch.setattr("tea_agent.config.get_config", lambda *a, **k: cfg)
        sess = self._make_session(api_url=OTHER_URL)
        try:
            for client in sess._http_clients:
                hooks = getattr(client, "event_hooks", {}).get("request") or []
                assert not hooks, "非 opencode 端点不应注入请求头"
        finally:
            sess.close()

    def test_litesession_gets_default_headers(self):
        from tea_agent.litesession import LiteSession

        lite = LiteSession(
            api_key="sk-test",
            api_url=GO_URL,
            model="deepseek-v4.1-flash",
            system_prompt="x",
            toolkit=MagicMock(),
            max_iterations=1,
        )
        headers = lite.api.default_headers
        assert headers and headers.get(OPENCODE_SESSION_HEADER)


@pytest.mark.parametrize("url", [GO_URL, ZEN_URL])
def test_hooks_not_shared_between_clients(url):
    """每个客户端独立钩子，不得复用同一份可变字典。"""
    a = request_event_hooks(url, session_id="a")
    b = request_event_hooks(url, session_id="b")
    assert a is not b
    assert a["request"] is not b["request"]


class TestSharedSslContext:
    """进程级共享 SSLContext —— 启动性能优化，且**不得**改变校验语义。

    回归背景：httpx 每构造一个 Client 都要为 sync/async/proxy 各建一个
    SSLContext，Windows OpenSSL 下单次 ``load_verify_locations(certifi CA)``
    ≈ 0.5s。冷启动建 main+cheap 两个 client = 6 次 ≈ 3.0s，是那次 8.25s 冷启动
    中唯一的 CPU 热点（cProfile 实测 2.997s，占 36%）。修复：进程级复用一份。
    """

    @pytest.fixture
    def fresh(self, monkeypatch):
        """清空共享缓存 —— 模块级 dict 必须隔离，否则用例互相串扰。"""
        import tea_agent.api_headers as ah

        monkeypatch.setattr(ah, "_SSL_CTX_CACHE", {})
        return ah

    @staticmethod
    def _spy_client(monkeypatch) -> dict:
        """记录传给 httpx.Client 的构造参数。"""
        seen: dict = {}
        real = httpx.Client

        def _spy(**kwargs):
            seen.update(kwargs)
            return real(**kwargs)

        monkeypatch.setattr("httpx.Client", _spy)
        return seen

    def test_two_clients_build_context_once(self, fresh, monkeypatch):
        """核心契约：N 个 client 只应构造 1 次 SSLContext（省下的就是那 2.5s）。"""
        calls: list = []
        real = fresh._create_ssl_context

        def _counting(http2=False):
            calls.append(http2)
            return real(http2)

        monkeypatch.setattr(fresh, "_create_ssl_context", _counting)
        c1 = build_http_client(5.0)
        c2 = build_http_client(5.0)
        try:
            assert len(calls) == 1, f"两个 client 应只建一次 SSLContext，实际 {len(calls)} 次"
        finally:
            c1.close()
            c2.close()

    def test_verify_is_the_shared_context(self, fresh, monkeypatch):
        """契约：共享 context 确实作为 verify 传给了 httpx（否则优化并未生效）。"""
        seen = self._spy_client(monkeypatch)
        ctx = fresh.shared_ssl_context()
        assert ctx is not None, "本机应能构造 SSLContext"
        c = build_http_client(5.0)
        try:
            assert seen.get("verify") is ctx
        finally:
            c.close()

    def test_shared_context_still_verifies(self, fresh):
        """安全契约：共享 context 必须仍是「校验证书 + 校验主机名」。

        防止未来某次「优化」把它换成不校验的 context —— 那会让所有出站请求
        静默失去 TLS 保护，且不会有任何测试变红。
        """
        import ssl as _ssl

        ctx = fresh.shared_ssl_context()
        assert ctx is not None
        assert ctx.verify_mode == _ssl.CERT_REQUIRED
        assert ctx.check_hostname is True

    @pytest.mark.parametrize("explicit", [
        {"verify": False},
        {"cert": ("/nonexistent/cli.pem", "/nonexistent/cli.key")},
        {"trust_env": True},
    ])
    def test_explicit_tls_kwargs_are_not_overridden(self, fresh, monkeypatch, explicit):
        """显式 TLS 参数必须原样透传，不得被共享 context 顶掉。

        cert 尤其重要：httpx 会把客户端证书写进 context，共享出去等于把私钥
        串给其它连接。
        """
        seen = self._spy_client(monkeypatch)
        try:
            build_http_client(5.0, **explicit)
        except Exception:
            pass  # cert 指向不存在的文件时 httpx 会报错，此处只关心 verify 是否被注入
        if "verify" in explicit:
            assert seen.get("verify") is False
        else:
            assert "verify" not in seen, f"显式 {list(explicit)} 时不应注入共享 context"

    def test_fail_open_when_context_unavailable(self, fresh, monkeypatch):
        """取不到共享 context 时必须 fail-open，绝不能阻断开会话。"""

        def _boom(http2=False):
            raise RuntimeError("boom")

        monkeypatch.setattr(fresh, "_create_ssl_context", _boom)
        seen = self._spy_client(monkeypatch)
        c = build_http_client(5.0)
        try:
            assert "verify" not in seen, "优化失败应退回 httpx 默认 verify 路径"
        finally:
            c.close()

    def test_construction_failure_is_cached(self, fresh, monkeypatch):
        """失败的结论也要缓存，避免每次建 client 重试昂贵的失败路径。"""
        calls: list = []

        def _boom(http2=False):
            calls.append(http2)
            raise RuntimeError("boom")

        monkeypatch.setattr(fresh, "_create_ssl_context", _boom)
        assert fresh.shared_ssl_context() is None
        assert fresh.shared_ssl_context() is None
        assert len(calls) == 1, f"失败结论应缓存，实际重试 {len(calls)} 次"
