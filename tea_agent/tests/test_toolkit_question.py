"""toolkit_question 交互路径回归测试。

背景：该工具原支持 4 条交互路径（Web 回调 / 静默兜底 / GUI 的 tkinter 弹窗 /
CLI 的终端 ``input()``），却**从未有测试覆盖** —— 缺口本身就是风险。

GUI / CLI 接口废弃后，GUI 与 CLI 两条路径已移除，剩余两条必须被钉住：

1. **有 Web handler 时必须用它** —— 否则退化成默认值，用户永远答不上来；
2. **Web handler 抛错时必须安全降级** —— 旁路失败不得把异常抛给调用方；
3. **无交互通道时必须返回 default，绝不阻塞在 stdin 上** —— 旧 CLI 路径会
   在 main thread 上等 ``input()``，在 server 场景等于挂死（这是移除它的主因，
   故用 monkeypatch 把 ``input`` 换成「一调用就失败」来防止回归）。
"""

from __future__ import annotations

import pathlib
from unittest.mock import patch

from tea_agent.toolkit import toolkit_question as tq


def _no_handler():
    """模拟「无 Web handler」（非 server 环境）。"""
    return None


def _handler_returning(value):
    """构造一个固定返回 value 的 Web handler。"""
    def _h(title, question, options, default, timeout):
        return value

    return lambda: _h


# ── 路径 1：Web 回调 ──

def test_web_handler_takes_priority():
    """有 Web handler 时必须走 handler，而不是直接返回默认值。"""
    with patch.object(tq, "_get_web_handler", _handler_returning("USER_PICKED")):
        assert tq.toolkit_question("标题", "问题", default="FALLBACK") == "USER_PICKED"


def test_web_handler_receives_all_arguments():
    """handler 必须收到完整 5 参数（早期签名漂移会让 options/timeout 静默丢失）。"""
    seen = {}

    def _h(title, question, options, default, timeout):
        seen.update(
            title=title, question=question, options=options,
            default=default, timeout=timeout,
        )
        return "ok"

    with patch.object(tq, "_get_web_handler", lambda: _h):
        tq.toolkit_question("T", "Q", options=["a", "b"], default="a", timeout=7)

    assert seen == {"title": "T", "question": "Q", "options": ["a", "b"],
                    "default": "a", "timeout": 7}


def test_web_handler_failure_falls_back_to_default():
    """handler 抛错时必须降级为 default，不得把异常抛给调用方。"""
    def _boom(*args, **kwargs):
        raise RuntimeError("handler down")

    with patch.object(tq, "_get_web_handler", lambda: _boom):
        assert tq.toolkit_question("T", "Q", default="D") == "D"


# ── 路径 2：无交互通道 ──

def test_no_handler_returns_default_and_never_reads_stdin(monkeypatch):
    """无 Web handler 时返回 default，且**绝不读取 stdin**。

    把 ``input`` 换成「一调用即失败」：若有人重新引入 CLI 交互路径且未加
    headless 守卫，本用例会立刻变红（而不是让 server 静默挂死）。
    """
    def _forbidden(*args, **kwargs):
        raise AssertionError("无交互通道时不得读取 stdin —— 会让 server 挂死")

    monkeypatch.setattr("builtins.input", _forbidden)
    with patch.object(tq, "_get_web_handler", _no_handler):
        assert tq.toolkit_question("T", "Q", default="D") == "D"


def test_headless_returns_default(monkeypatch):
    """显式 headless 环境返回 default（与无 handler 同一条路径）。"""
    monkeypatch.setenv("TEA_HEADLESS", "1")
    with patch.object(tq, "_get_web_handler", _no_handler):
        assert tq.toolkit_question("T", "Q", default="D") == "D"


def test_no_default_returns_empty_string():
    """default 为空时返回空串（而非 None）——调用方按 str 消费。"""
    with patch.object(tq, "_get_web_handler", _no_handler):
        result = tq.toolkit_question("T", "Q")
    assert result == ""
    assert isinstance(result, str)


def test_headless_check_never_raises():
    """_is_headless_context 在任何环境下都必须返回 bool，不得抛错。"""
    assert isinstance(tq._is_headless_context(), bool)


# ── 元测试：钉住 GUI/CLI 路径的移除 ──

def test_gui_and_cli_paths_removed():
    """GUI(tkinter) 与 CLI(input) 交互路径必须已移除。

    钉住删除本身 —— 只删断言会让这段代码在将来被无意重新引入而无人察觉。
    tkinter 不在 pyproject 依赖中，重新引入会让精简版 Python 直接 ImportError。
    """
    src = pathlib.Path(tq.__file__).read_text(encoding="utf-8")
    for forbidden in ("import tkinter", "from tkinter", "_ask_gui", "_ask_cli",
                      "_is_gui_running", "import threading"):
        assert forbidden not in src, f"toolkit_question 仍引用已废弃路径: {forbidden}"


def test_meta_is_valid_and_unchanged():
    """工具元信息仍可产出合法 schema（重构不得破坏注册契约）。"""
    meta = tq.meta_toolkit_question()
    assert meta["type"] == "function"
    fn = meta["function"]
    assert fn["name"] == "toolkit_question"
    assert set(fn["parameters"]["required"]) == {"title", "question"}
