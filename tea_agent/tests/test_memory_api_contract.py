"""记忆创建接口的返回契约（回归测试）。

缺陷背景（2026-09-25 实测复现）：
    记忆管理对话框输入内容点「添加」→ 提示「添加失败」，但记忆**其实已入库**。

    根因是前后端契约不一致，而不是存储失败：
      · 后端 handle_create_memory 只返回裸对象 {"id","content","category"}（HTTP 201）
      · 前端 app.js 的 addMemory 用 `if (d.ok)` 判定成败
      → d.ok 恒为 undefined → 走 else 分支 → toast(d.error || '添加失败')
    且因未进入成功分支，refreshMemoryList() 不被调用，列表不刷新，
    用户更确信「没添加成功」。

    同文件其余 5 处 `d.ok` 判据（deleteMemory / 改标题 / 切模型 / 建配置 /
    测连接）对应的后端**都**返回 ok —— create_memory 是唯一异类。

守卫要点：断言的是**契约**（响应含 ok、失败非 2xx），不是当前实现细节。
"""
from __future__ import annotations

import asyncio
import json
import pathlib

import pytest

from tea_agent.server import route_handlers_basic as rhb


class _Req:
    def __init__(self, payload):
        self._payload = payload

    async def json(self):
        return self._payload


class _Server:
    """替身：返回形态与 StorageModule.create_memory 一致。"""

    def __init__(self, error: str = ""):
        self.error = error
        self.calls: list[tuple] = []

    def create_memory(self, content, category="general", priority=2):
        self.calls.append((content, category, priority))
        if self.error:
            return {"error": self.error}
        return {"id": 42, "content": content, "category": category}


def _post(payload, server):
    rhb.get_server = lambda: server
    resp = asyncio.run(rhb.handle_create_memory(_Req(payload)))
    return resp, json.loads(resp.body.decode())


@pytest.fixture(autouse=True)
def _restore_get_server():
    original = rhb.get_server
    yield
    rhb.get_server = original


def test_success_response_carries_ok_flag():
    """契约：成功响应必须含 ok=True —— 缺了它前端恒报「添加失败」。"""
    resp, body = _post({"content": "这是一条测试记忆"}, _Server())

    assert resp.status_code == 201
    assert body["ok"] is True, f"成功响应缺 ok（前端将误报失败）: {body}"
    assert body["id"] == 42
    assert body["content"] == "这是一条测试记忆"


def test_success_passes_content_and_defaults():
    server = _Server()
    _post({"content": "  带空格  "}, server)
    assert server.calls == [("带空格", "general", 2)], "内容未去空格或默认值漂移"


def test_empty_content_rejected_without_touching_storage():
    server = _Server()
    resp, body = _post({"content": "   "}, server)

    assert resp.status_code == 400
    assert body["ok"] is False
    assert server.calls == [], "空内容不应写库"


def test_storage_unavailable_is_not_reported_as_success():
    """存储未就绪时旧代码仍返回 201 → 按状态码判定的调用方会「假成功」。

    这是本 bug 的镜像：假失败已修，假成功必须一并钉住。
    """
    resp, body = _post({"content": "x"}, _Server(error="Storage not loaded"))

    assert resp.status_code >= 400, "错误却返回 2xx，会被按状态码判定的调用方误判为成功"
    assert body["ok"] is False
    assert "Storage not loaded" in body["error"]


def test_frontend_and_backend_agree_on_ok_field():
    """双向契约：前端以 d.ok 判成败，后端就必须给出 ok。

    只改一侧会让 bug 复发，故把两侧钉在一起。
    """
    js = (pathlib.Path(rhb.__file__).parent / "static" / "app.js").read_text(encoding="utf-8")

    seg = js[js.index("window.addMemory"):]
    seg = seg[: seg.index("async function refreshMemoryList")]
    assert "d.ok" in seg, "前端 addMemory 的判据变了，请同步本测试与后端契约"

    _, body = _post({"content": "x"}, _Server())
    assert "ok" in body, "后端未提供前端所需的 ok 字段"
