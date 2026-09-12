"""公共 API 契约：`__all__` 声明的名字必须**运行时**可用。

背景（真实缺陷，由运行时实证发现）：
`tea_agent/__init__.py` 的 `__all__` 声明了 8 个公开名，但文件只绑定了
Agent / TeaAgent，其余 6 个（BaseChatSession / OnlineToolSession / Storage /
load_config / get_config / save_config）从未导入 —— 于是
`from tea_agent import Storage` 直接 ImportError，`from tea_agent import *`
也会因 AttributeError 失败。__all__ 是显式公开契约，声明了就必须兑现。

为什么用运行时而非静态断言：静态扫描曾报「悬空 __all__ 6 处」，但同类静态
判据此前多次出现假阳性/假绿（环检测 4 例、委托漂移 8 例）。此处直接以
hasattr / 真实 import 为准，杜绝判据与事实脱节。
"""

from __future__ import annotations

import importlib

import tea_agent


def test_all_declared_names_resolve_at_runtime():
    """`__all__` 中每个名字都必须能通过属性访问拿到。"""
    mod = importlib.import_module("tea_agent")
    missing = [n for n in mod.__all__ if not hasattr(mod, n)]
    assert missing == [], f"__all__ 声明但运行时不可用: {missing}"


def test_star_import_exposes_all_declared_names():
    """`from tea_agent import *` 必须导出 __all__ 全部名字。"""
    ns: dict = {}
    exec("from tea_agent import *", ns)  # noqa: S102 — 校验公开契约
    missing = [n for n in tea_agent.__all__ if n not in ns]
    assert missing == [], f"star import 缺失: {missing}"


def test_from_import_works_for_each_declared_name():
    """逐个名字验证 `from tea_agent import X` 形式可用。"""
    for name in tea_agent.__all__:
        ns: dict = {}
        exec(f"from tea_agent import {name}", ns)  # noqa: S102
        assert name in ns, f"from tea_agent import {name} 失败"


def test_lazy_export_map_matches_all():
    """惰性导出表与 __all__ 保持一致（防新增公开名时漏配）。"""
    declared = set(tea_agent.__all__)
    strictly_bound = {"Agent", "TeaAgent"}  # 末尾显式导入，不走 __getattr__
    covered = set(tea_agent._LAZY_EXPORTS) | strictly_bound
    assert declared <= covered, f"__all__ 中未覆盖: {sorted(declared - covered)}"
