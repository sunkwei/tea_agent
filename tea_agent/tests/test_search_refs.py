"""搜索引用收集与回合末列出 — 回归测试。

契约：
1. 仅网络来源工具（toolkit_search web/github、toolkit_js_fetch）产出引用
2. 本地代码/符号搜索**不得**产出引用（那不是"参考链接"）
3. 按 URL 去重、顺序稳定
4. 回合收尾经 callback 列出，且 **full_reply 逐字不变**（不入库）
"""

from tea_agent.search_refs import (
    MAX_DISPLAY_REFS,
    extract_refs,
    format_refs_text,
    merge_refs,
)


def _search_result(items):
    return {"ok": True, "results": items, "returncode": 0}


# ── 提取 ──

def test_extract_web_search_urls():
    refs = extract_refs(
        "toolkit_search",
        {"query": "x", "search_type": "web"},
        _search_result([
            {"title": "Python 教程", "url": "https://docs.python.org/3/"},
            {"title": "Blog", "url": "http://example.com/a"},
        ]),
    )
    assert [r["url"] for r in refs] == [
        "https://docs.python.org/3/", "http://example.com/a",
    ]
    assert refs[0]["title"] == "Python 教程"


def test_extract_default_search_type_is_web():
    """search_type 缺省（模型常不传）时按 web 处理，不得漏采。"""
    refs = extract_refs(
        "toolkit_search", {"query": "x"},
        _search_result([{"title": "t", "url": "https://a.com"}]),
    )
    assert len(refs) == 1


def test_extract_github_search_urls():
    refs = extract_refs(
        "toolkit_search", {"query": "x", "search_type": "github"},
        _search_result([{"title": "repo", "url": "https://github.com/a/b"}]),
    )
    assert refs and refs[0]["url"] == "https://github.com/a/b"


def test_no_refs_for_local_code_search():
    """代码搜索命中的是本地文件，不是参考链接。"""
    assert extract_refs(
        "toolkit_search", {"query": "def f", "search_type": "code"},
        {"ok": True, "results": [{"file": "a.py", "line": 1}]},
    ) == []
    assert extract_refs(
        "toolkit_search", {"query": "C", "search_type": "symbol"},
        {"ok": True, "results": [{"file": "a.py", "name": "C"}]},
    ) == []


def test_no_refs_for_unlisted_tools():
    """非白名单工具（exec 的 stdout 里常含 URL）不得被当引用。"""
    assert extract_refs("toolkit_exec", {}, {"stdout": "see https://a.com"}) == []


def test_no_refs_on_search_failure():
    assert extract_refs(
        "toolkit_search", {"search_type": "web"},
        {"ok": False, "error": "超时", "returncode": 1},
    ) == []


def test_extract_skips_non_http_and_bad_entries():
    refs = extract_refs(
        "toolkit_search", {"search_type": "web"},
        _search_result([
            {"title": "本地", "url": "file:///tmp/a"},
            {"title": "空", "url": ""},
            {"title": None, "url": None},
            "非 dict",
            {"title": "好", "url": "https://ok.com/"},
        ]),
    )
    assert [r["url"] for r in refs] == ["https://ok.com/"]


def test_extract_js_fetch_uses_arg_url():
    refs = extract_refs(
        "toolkit_js_fetch", {"url": "https://spa.example.com/page"},
        {"ok": True, "title": "动态页标题"},
    )
    assert refs == [{
        "url": "https://spa.example.com/page",
        "title": "动态页标题",
        "source": "toolkit_js_fetch",
    }]


def test_extract_js_fetch_without_url():
    assert extract_refs("toolkit_js_fetch", {}, {"ok": True}) == []


def test_extract_never_raises():
    """旁路采集：畸形输入只能返回空，不能抛。"""
    class _Boom(dict):
        def get(self, *a, **k):
            raise RuntimeError("boom")

    assert extract_refs("toolkit_search", {"search_type": "web"}, _Boom()) == []


# ── 合并去重 ──

def test_merge_dedupes_by_url_keeps_order():
    merged = merge_refs(
        [{"url": "https://a.com", "title": "A", "source": "s"}],
        [
            {"url": "https://a.com", "title": "A2", "source": "s"},
            {"url": "https://b.com", "title": "B", "source": "s"},
        ],
    )
    assert [r["url"] for r in merged] == ["https://a.com", "https://b.com"]
    assert merged[0]["title"] == "A", "重复 URL 保留首次标题"


def test_merge_tolerates_none_and_junk():
    assert merge_refs(None, None) == []
    assert merge_refs([], ["junk", None, {"no": "url"}]) == []


# ── 渲染 ──

def test_format_empty_returns_empty_string():
    assert format_refs_text([]) == ""
    assert format_refs_text(None) == ""
    assert format_refs_text([{"title": "无 url"}]) == ""


def test_format_renders_markdown_links():
    text = format_refs_text([
        {"url": "https://a.com", "title": "A"},
        {"url": "https://b.com", "title": "B"},
    ])
    assert text.startswith("🔗 本回合参考链接（2）")
    assert "1. [A](https://a.com)" in text
    assert "2. [B](https://b.com)" in text


def test_format_escapes_markdown_breakers_in_title():
    """标题含 [] 会破坏 Markdown 链接语法 → 必须中和。"""
    text = format_refs_text([{"url": "https://a.com", "title": "bad [x] (y)"}])
    assert "[bad" in text and "](https://a.com)" in text
    assert "[x]" not in text


def test_format_caps_at_max_items():
    refs = [{"url": f"https://a.com/{i}", "title": f"t{i}"} for i in range(MAX_DISPLAY_REFS + 5)]
    text = format_refs_text(refs)
    assert f"（{MAX_DISPLAY_REFS + 5}）" in text
    assert f"{MAX_DISPLAY_REFS}. " in text
    assert f"{MAX_DISPLAY_REFS + 1}. " not in text
    assert "… 等 5 条" in text


# ── 接线：ToolComponent 采集 ──

def test_tool_component_records_refs_into_ctx():
    from tea_agent.session.components.tool import _record_search_refs

    class _Ctx:
        _search_refs = []

    ctx = _Ctx()
    _record_search_refs(
        ctx, "toolkit_search", {"search_type": "web"},
        _search_result([{"title": "T", "url": "https://a.com"}]),
    )
    _record_search_refs(
        ctx, "toolkit_search", {"search_type": "web"},
        _search_result([{"title": "T", "url": "https://a.com"},
                        {"title": "U", "url": "https://b.com"}]),
    )
    assert [r["url"] for r in ctx._search_refs] == ["https://a.com", "https://b.com"]


def test_tool_component_ignores_non_ref_tools():
    from tea_agent.session.components.tool import _record_search_refs

    class _Ctx:
        _search_refs = []

    ctx = _Ctx()
    _record_search_refs(ctx, "toolkit_exec", {}, {"stdout": "https://a.com"})
    assert ctx._search_refs == []


def test_record_search_refs_never_raises_on_bad_ctx():
    """ctx 没有该字段 / 属性查找抛错 → 静默，不影响工具执行。"""
    from tea_agent.session.components.tool import _record_search_refs

    class _Boom:
        @property
        def _search_refs(self):
            raise RuntimeError("boom")

        @_search_refs.setter
        def _search_refs(self, v):
            raise RuntimeError("boom")

    _record_search_refs(
        _Boom(), "toolkit_search", {"search_type": "web"},
        _search_result([{"title": "T", "url": "https://a.com"}]),
    )


# ── 接线：回合收尾 ──

def _make_session(refs, db_path=""):
    """真实 OnlineToolSession 实例（绕过重量级 __init__），只注入所需字段。"""
    from tea_agent.onlinesession import OnlineToolSession

    sess = OnlineToolSession.__new__(OnlineToolSession)
    sess.context = type("C", (), {"_search_refs": refs})()

    class _S:
        pass

    s = _S()
    s.db_path = db_path
    sess.storage = s
    return sess


def test_finalize_lists_refs_via_callback_only():
    """关键契约：引用经 callback 送达，full_reply 逐字不变（不入库）。"""
    from tea_agent.onlinesession import OnlineToolSession

    sess = _make_session([{"url": "https://a.com", "title": "A", "source": "toolkit_search"}])
    got = []
    reply, used = OnlineToolSession._finalize_turn_reply(sess, "原始回复", True, got.append)

    assert reply == "原始回复", "引用不得混入回复（会被持久化污染历史）"
    assert used is True
    assert any("https://a.com" in t for t in got), "引用须经 callback 送达 UI"


def test_finalize_silent_without_search():
    """没搜索过的回合不得输出空标题噪声。"""
    from tea_agent.onlinesession import OnlineToolSession

    sess = _make_session([])
    got = []
    OnlineToolSession._finalize_turn_reply(sess, "回复", False, got.append)
    assert not any("参考链接" in t for t in got)


def test_emit_search_refs_never_raises():
    from tea_agent.onlinesession import OnlineToolSession

    class _BoomCtx:
        @property
        def _search_refs(self):
            raise RuntimeError("boom")

    sess = OnlineToolSession.__new__(OnlineToolSession)
    sess.context = _BoomCtx()
    sess._emit_search_refs(lambda t: None)  # 不抛即通过

    # context 属性完全缺失（__new__ 裸实例）同样不得抛
    OnlineToolSession._emit_search_refs(
        OnlineToolSession.__new__(OnlineToolSession), lambda t: None
    )
