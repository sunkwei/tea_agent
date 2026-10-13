"""渠道 /model 命令 + /v1/chat/completions 路由回归测试。

覆盖两类历史缺陷：
1. `/v1/chat/completions` handler 存在但漏挂路由 → 微信/TG 恒 HTTP 404
2. 命令参数被静默丢弃（`parts[1] if ... else ""` 未赋值）

纯注入 api_get/api_post 假实现，不发真实网络请求，判定确定。
"""

from tea_agent.channel.model_command import VALID_ROLES, build_model_reply, split_role

_PANEL = {
    "active": {
        "main": {"provider": "qwen", "model": "qwen3.8-flash"},
        "cheap": {"provider": "mimo", "model": "mimo-v2.6-flash"},
    },
    "providers": [
        {"name": "qwen", "default_model": "", "models": [{"id": "qwen3.8-flash"}, {"id": "glm-5.2"}]},
        {"name": "mimo", "default_model": "mimo-v2.6-pro", "models": [{"id": "mimo-v2.6-pro"}]},
        {"name": "empty", "default_model": "", "models": []},
    ],
}


class _FakeApi:
    """记录调用并返回预置结果。post_result=None 模拟服务端失败。"""

    def __init__(self, post_result=None):
        self.calls = []
        self._post = post_result if post_result is not None else {"ok": True, "switch": {"mode": "applied"}}

    def get(self, path, timeout=10):
        self.calls.append(("GET", path))
        return dict(_PANEL)

    def post(self, path, json_data=None, timeout=10):
        self.calls.append(("POST", path, json_data))
        return self._post


def test_route_registered_for_chat_completions():
    """回归：/v1/chat/completions 必须挂在路由表上（曾漏挂导致适配器 404）。"""
    from tea_agent.server._routes import _build_routes

    paths = {r.path for r in _build_routes()}
    assert "/v1/chat/completions" in paths


def test_model_no_args_shows_current_and_usage():
    reply = build_model_reply("", _FakeApi().get, _FakeApi().post, "http://x")
    assert "qwen" in reply and "qwen3.8-flash" in reply
    assert "/model list" in reply
    assert not any(c[0] == "POST" for c in _FakeApi().calls)


def test_model_list_marks_current_provider():
    reply = build_model_reply("list", _FakeApi().get, _FakeApi().post, "http://x")
    assert "提供商（3）" in reply.replace("*", "")
    assert "*qwen* ✅" in reply
    assert "*mimo*" in reply and "*mimo* ✅" not in reply


def test_model_switch_passes_provider_and_model():
    api = _FakeApi()
    reply = build_model_reply("qwen glm-5.2", api.get, api.post, "http://x")
    posts = [c for c in api.calls if c[0] == "POST"]
    assert posts, "切换必须真的发出 POST（回归：参数被静默丢弃时此处为空）"
    assert posts[0][2] == {"provider": "qwen", "model": "glm-5.2", "role": "main"}
    assert "已立即生效" in reply


def test_model_provider_name_is_case_insensitive():
    api = _FakeApi()
    build_model_reply("QWEN glm-5.2", api.get, api.post, "http://x")
    assert [c for c in api.calls if c[0] == "POST"][0][2]["provider"] == "qwen"


def test_model_bare_provider_uses_default_model():
    api = _FakeApi()
    reply = build_model_reply("mimo", api.get, api.post, "http://x")
    assert [c for c in api.calls if c[0] == "POST"][0][2]["model"] == "mimo-v2.6-pro"
    assert "mimo-v2.6-pro" in reply


def test_model_bare_provider_without_default_lists_choices():
    api = _FakeApi()
    reply = build_model_reply("qwen", api.get, api.post, "http://x")
    assert "未设默认模型" in reply and "glm-5.2" in reply
    assert not [c for c in api.calls if c[0] == "POST"]


def test_model_unknown_provider_no_switch():
    api = _FakeApi()
    reply = build_model_reply("nope", api.get, api.post, "http://x")
    assert "未找到提供商" in reply
    assert not [c for c in api.calls if c[0] == "POST"]


def test_model_switch_failure_reports_error():
    api = _FakeApi(post_result={"ok": False, "error": "model not found"})
    reply = build_model_reply("qwen nope-model", api.get, api.post, "http://x")
    assert "切换失败" in reply and "model not found" in reply


def test_model_server_down_returns_hint_not_exception():
    def dead_get(path, timeout=10):
        return None

    reply = build_model_reply("list", dead_get, lambda *a, **k: None, "http://127.0.0.1:8282")
    assert "读取模型配置失败" in reply and "http://127.0.0.1:8282" in reply


def test_telegram_registers_model_handler():
    """/model 已注册；曾注册不存在的 _handle_config 导致 start() AttributeError。"""
    import pathlib

    src = pathlib.Path("tea_agent/channel/telegram_adapter.py").read_text(encoding="utf-8")
    assert 'CommandHandler("model"' in src
    assert "_handle_config" not in src, "/config 仍指向不存在的方法"
    assert "async def _handle_model" in src


def test_wechat_command_args_are_bound():
    """回归：args = parts[1]（原写法结果未赋值，命令参数恒丢）。"""
    import pathlib

    src = pathlib.Path("tea_agent/channel/wechat_adapter.py").read_text(encoding="utf-8")
    assert "args = parts[1] if len(parts) > 1 else \"\"" in src


# ── --role 支持 ──

def test_split_role_default_and_extras():
    assert split_role([]) == ([], "main", "")
    assert split_role(["qwen", "glm-5.2"]) == (["qwen", "glm-5.2"], "main", "")
    assert split_role(["mimo", "pro", "--role", "cheap"]) == (["mimo", "pro"], "cheap", "")
    assert split_role(["--role", "cheap", "mimo", "pro"]) == (["mimo", "pro"], "cheap", "")
    assert split_role(["mimo", "-r", "vision"]) == (["mimo"], "vision", "")
    assert split_role(["mimo", "pro", "--cheap"]) == (["mimo", "pro"], "cheap", "")


def test_split_role_errors():
    rest, role, err = split_role(["qwen", "glm-5.2", "--role"])
    assert err and "需要角色名" in err
    rest, role, err = split_role(["qwen", "--role", "nope"])
    assert err and "未知角色" in err and role == "nope"


def test_model_role_cheap_posts_cheap_role():
    api = _FakeApi(post_result={"ok": True, "switch": {"mode": "config_only"}})
    reply = build_model_reply("mimo mimo-v2.6-pro --role cheap", api.get, api.post, "http://x")
    posts = [c for c in api.calls if c[0] == "POST"]
    assert posts[0][2] == {"provider": "mimo", "model": "mimo-v2.6-pro", "role": "cheap"}
    assert "轻量" in reply and "子任务/后台" in reply
    # 非 main 角色不走会话热切 → 不得宣称「已立即生效」
    assert "已立即生效" not in reply


def test_model_role_main_still_uses_session_switch_tip():
    api = _FakeApi()
    reply = build_model_reply("qwen glm-5.2", api.get, api.post, "http://x")
    assert [c for c in api.calls if c[0] == "POST"][0][2]["role"] == "main"
    assert "主力" in reply and "已立即生效" in reply


def test_model_bad_role_does_not_switch():
    api = _FakeApi()
    reply = build_model_reply("qwen glm-5.2 --role foo", api.get, api.post, "http://x")
    assert "未知角色" in reply
    assert not [c for c in api.calls if c[0] == "POST"]


def test_model_view_lists_all_roles_and_usage():
    reply = build_model_reply("", _FakeApi().get, _FakeApi().post, "http://x")
    assert "主力" in reply and "轻量" in reply
    assert "--role cheap" in reply


def test_model_list_marks_each_role():
    reply = build_model_reply("list", _FakeApi().get, _FakeApi().post, "http://x")
    assert "*qwen* ✅" in reply      # main
    assert "*mimo* ⚡" in reply      # cheap


def test_model_valid_roles_exposed():
    assert VALID_ROLES == ("main", "cheap", "vision")
