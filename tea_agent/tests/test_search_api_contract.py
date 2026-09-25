"""搜索接口的前后端契约（回归测试）。

缺陷背景（2026-09-25 巡检发现）：前端 `app.js` 读 `d.data`，而后端
`handle_search` 直接返回 `StorageModule.search()` 的
`{"conversations": [...], "memories": [...]}`（无 data 包裹）
→ `d.data` 恒 undefined → 搜索结果**永远显示「没有结果」**（静默假空）。

与「记忆添加失败」同属一类：前端读取的字段后端从不提供。
"""

import asyncio
import json
import pathlib

from tea_agent.server import route_handlers_basic as rhb

APP_JS = pathlib.Path(__file__).resolve().parents[1] / "server" / "static" / "app.js"


class _FakeServer:
    def search(self, query, limit=20):
        return {"conversations": [{"ai_msg": "命中"}], "memories": [{"content": "记忆"}]}


class _Req:
    query_params = {"q": "关键词", "limit": "20"}


def test_handler_returns_plain_entity_dict():
    """后端契约：直接返回 {conversations, memories}，不加 data 包裹。"""
    rhb.get_server = lambda: _FakeServer()
    resp = asyncio.run(rhb.handle_search(_Req()))
    body = json.loads(resp.body.decode())
    assert "conversations" in body and "memories" in body, f"响应形态变了: {body}"


def test_frontend_reads_match_backend_shape():
    """前端读取的字段必须能从后端响应取到（钉行为，不钉写法）。"""
    rhb.get_server = lambda: _FakeServer()
    backend = json.loads(asyncio.run(rhb.handle_search(_Req())).body.decode())

    src = APP_JS.read_text(encoding="utf-8")
    # 取 search 函数体（含 'search-results' 的那段）
    i = src.index("search-results")
    seg = src[i : i + 3000]
    assert "d.data || d || {}" in seg or "d.data || d" in seg, (
        "前端未容忍后端的无 data 包裹形态 → 搜索将恒显示「没有结果」"
    )
    # 模拟前端取值：两种形态都必须拿到结果
    for wrapped in (backend, {"data": backend}):
        results = wrapped.get("data") or wrapped or {}
        assert results.get("conversations") or results.get("memories"), (
            f"前端取不到结果: {wrapped}"
        )
