"""搜索引用「接线」端到端测试 —— 防假绿守卫。

为什么单独一个文件：直接测 ``_record_search_refs`` 函数本身只能证明
「采集函数是对的」，证明不了「工具循环真的调用了它」。历史上这类
「实现正确但没接线」的缺陷正是被单测掩盖的（见 test_tool_trace_events
的替身教训）。故这里走**真实 ToolComponent.execute_tool_call** 全路径。
"""

from types import SimpleNamespace

from tea_agent.session.components.tool import ToolComponent
from tea_agent.session.context import SessionContext


def _ctx():
    ctx = SessionContext()
    ctx.storage = None       # 不落库
    ctx.topic_id = ""        # 不写事件
    ctx.tool_log = None
    return ctx


def _call(name, args_json):
    return SimpleNamespace(
        id="c1",
        function=SimpleNamespace(name=name, arguments=args_json),
    )


def _toolkit(name, ret):
    return SimpleNamespace(
        func_map={name: lambda **kw: ret},
        meta_map={name: {}},
        call_tool=lambda fn, **kw: ret,
    )


def test_execute_tool_call_records_search_refs():
    """真实执行路径：toolkit_search 的 URL 必须落进 ctx._search_refs。"""
    ctx = _ctx()
    ctx.toolkit = _toolkit(
        "toolkit_search",
        {"ok": True, "results": [{"title": "A", "url": "https://a.com"}], "returncode": 0},
    )
    comp = ToolComponent(ctx)

    comp.execute_tool_call(_call("toolkit_search", '{"query": "x", "search_type": "web"}'))

    assert [r["url"] for r in ctx._search_refs] == ["https://a.com"]


def test_execute_tool_call_dedupes_across_calls():
    """同一回合内多次搜索 → 按 URL 去重、保序。"""
    ctx = _ctx()
    ret = {"ok": True, "results": [{"title": "A", "url": "https://a.com"}], "returncode": 0}
    ctx.toolkit = _toolkit("toolkit_search", ret)
    comp = ToolComponent(ctx)

    comp.execute_tool_call(_call("toolkit_search", '{"query": "x"}'))
    comp.execute_tool_call(_call("toolkit_search", '{"query": "y"}'))

    assert [r["url"] for r in ctx._search_refs] == ["https://a.com"]


def test_execute_tool_call_code_search_yields_no_refs():
    """本地代码搜索不算参考链接。"""
    ctx = _ctx()
    ctx.toolkit = _toolkit(
        "toolkit_search",
        {"ok": True, "results": [{"file": "a.py", "line": 1, "content": "x"}], "returncode": 0},
    )
    ToolComponent(ctx).execute_tool_call(
        _call("toolkit_search", '{"query": "def f", "search_type": "code"}')
    )
    assert ctx._search_refs == []


def test_execute_tool_call_other_tool_yields_no_refs():
    """非白名单工具即使输出含 URL 也不列为参考。"""
    ctx = _ctx()
    ctx.toolkit = _toolkit("toolkit_exec", {"ok": True, "stdout": "see https://a.com"})
    ToolComponent(ctx).execute_tool_call(_call("toolkit_exec", '{"app": "ls"}'))
    assert ctx._search_refs == []


def test_execute_tool_call_refs_do_not_break_tool_result():
    """采集是纯旁路：工具结果字符串不受影响。"""
    ctx = _ctx()
    ctx.toolkit = _toolkit(
        "toolkit_search",
        {"ok": True, "results": [{"title": "A", "url": "https://a.com"}], "returncode": 0},
    )
    _, name, result_str = ToolComponent(ctx).execute_tool_call(
        _call("toolkit_search", '{"query": "x"}')
    )
    assert name == "toolkit_search"
    assert "https://a.com" in result_str
    assert "参考链接" not in result_str, "提示只走 callback，不得混进工具结果"


def test_reset_session_state_clears_refs():
    """回合开始清零 → 不会把上一轮的链接重复列出。"""
    import threading

    from tea_agent.onlinesession import OnlineToolSession

    sess = OnlineToolSession.__new__(OnlineToolSession)
    sess.context = SessionContext()
    sess.context._search_refs = [{"url": "https://a.com", "title": "A", "source": "s"}]
    # reset_session_state 还碰这些：用最小真实替身补齐（被测的是 _search_refs 清零）
    noop = lambda *a, **k: None  # noqa: E731
    sess.api = SimpleNamespace(reset_usage=noop, reset_cheap_usage=noop)
    sess._max_iter_wait = threading.Event()
    sess._strip_reasoning_content = noop

    OnlineToolSession.reset_session_state(sess)

    assert sess.context._search_refs == []
