"""服务端鉴权中间件回归测试。

回归背景：``create_app`` 里的 AuthMiddleware 引用了**未定义**的 ``_SKIP_PATHS``
（局部变量实际叫 ``skip_paths``）。一旦配置了 server api_key，中间件对**每个**
HTTP 请求都会抛 NameError → 全部请求 500，服务彻底不可用。此前无任何测试覆盖
该中间件（已有测试都未启用 api_key，因此走不到这条分支）。
"""

from __future__ import annotations

import pytest

starlette_testclient = pytest.importorskip("starlette.testclient")


def _client(api_key: str):
    from tea_agent.server.server import create_app

    app = create_app(api_key=api_key)
    return starlette_testclient.TestClient(app, raise_server_exceptions=False)


class TestAuthMiddlewareWithApiKey:
    """启用 api_key 时：跳过白名单 + 校验令牌。"""

    def test_health_bypasses_auth(self):
        """白名单路径（/health）无需令牌；若中间件崩了这里会是 500。"""
        r = _client("secret-key").get("/health")
        assert r.status_code != 500, f"鉴权中间件异常（疑似未定义名）: {r.text[:200]}"
        assert r.status_code == 200, r.status_code

    def test_missing_token_rejected(self):
        r = _client("secret-key").get("/api/nonexistent-for-auth-check")
        assert r.status_code == 401, r.status_code

    def test_wrong_token_rejected(self):
        c = _client("secret-key")
        assert c.get("/api/nonexistent-for-auth-check",
                     headers={"Authorization": "Bearer nope"}).status_code == 401
        assert c.get("/api/nonexistent-for-auth-check",
                     headers={"x-api-key": "nope"}).status_code == 401

    @pytest.mark.parametrize("header", [
        {"Authorization": "Bearer secret-key"},
        {"x-api-key": "secret-key"},
    ])
    def test_valid_token_passes_auth(self, header):
        """合法令牌必须放行（403/401 之外的状态码都说明已经越过鉴权）。"""
        r = _client("secret-key").get("/api/nonexistent-for-auth-check", headers=header)
        assert r.status_code not in (401, 500), f"{header} 未通过鉴权: {r.status_code}"


class TestNoApiKeySkipsAuth:
    """未配置 api_key 时不应挂鉴权（回归：白名单变量名写错曾导致全站 500）。"""

    def test_requests_work_without_api_key(self):
        r = _client("").get("/api/nonexistent-for-auth-check")
        assert r.status_code != 401, "未配置 api_key 时不应要求鉴权"
        assert r.status_code != 500, f"未配置 api_key 时服务异常: {r.text[:200]}"
