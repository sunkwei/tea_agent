"""toolkit_explr 目录遍历排除集回归测试。

缺陷背景（2026-09-23 实测）：``toolkit_explr.py`` 内曾有 **5 套各不相同**的
内联排除列表，且**每一套都漏掉** ``node_modules`` / ``build_mini_dist``
（其中两处连 ``.venv`` 都没排除）。后果不是性能问题而是**正确性问题**：

``generate_docs`` 会把 ``agent-calendar-viewer/node_modules`` 下第三方捆绑的
Python 当作本项目 API 文档化 —— 实测 ``docs/API参考.md`` 混入 **3610 处**、
``docs/模块概览.md`` 混入 159 处构建产物。这类「新鲜但错误」的文档比
「过期但干净」更有害，因为它看不出污染。

断言钉的是**行为契约**（遍历结果不得含垃圾目录），不是实现细节：

1. 排除集常量必须覆盖全部已知垃圾目录（含 node_modules）
2. ``_prune_dirs`` 必须剔除隐藏目录
3. 真实遍历（在临时工程内构造同名垃圾目录）不得进入产物
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from tea_agent.toolkit.toolkit_explr import _SKIP_DIRS, _prune_dirs

# 实测会污染符号扫描的目录名（node_modules 与 build_mini_dist 是本次缺陷主因）
KNOWN_JUNK = (
    "node_modules", "build_mini_dist", "build", "dist", "__pycache__",
    ".git", ".tea_agent_run", ".venv", "venv", "env", "tmp",
)


@pytest.mark.parametrize("name", KNOWN_JUNK)
def test_skip_dirs_covers_known_junk(name):
    """每个已知垃圾目录都必须在排除集内 —— 少一个就会污染文档产物。"""
    assert name in _SKIP_DIRS, f"{name} 未纳入排除集，会被当成项目源码扫描"


def test_skip_dirs_is_immutable():
    """排除集须为不可变集合，避免被调用点就地改写后再次漂移。"""
    assert isinstance(_SKIP_DIRS, frozenset)


def test_prune_removes_hidden_dirs():
    """隐藏目录一律剔除（.venv / .tea_agent_run / .backup_* 全在内）。"""
    dirs = ["src", ".venv", ".tea_agent_run", ".backup_cache_fix", "tests"]
    _prune_dirs(dirs)
    assert dirs == ["src", "tests"], dirs


def test_prune_removes_junk_and_keeps_real_source():
    """垃圾目录被剔除，真实源码目录必须原样保留（别把防护修成失效）。"""
    dirs = ["tea_agent", "node_modules", "build_mini_dist", "tests", "demo"]
    _prune_dirs(dirs)
    assert dirs == ["tea_agent", "tests", "demo"], dirs


def test_prune_extra_param_is_additive_only():
    """extra 只能「额外排除」，不得影响 _SKIP_DIRS 本体。"""
    before = set(_SKIP_DIRS)
    dirs = ["docs", "src"]
    _prune_dirs(dirs, extra=("docs",))
    assert dirs == ["src"]
    assert set(_SKIP_DIRS) == before, "_prune_dirs 意外改写了全局排除集"


def test_prune_mutates_in_place_and_returns_same_list():
    """必须原地裁剪：os.walk 的 dirs 是就地生效语义，返回新列表等于没排除。"""
    dirs = ["a", "node_modules", "b"]
    out = _prune_dirs(dirs)
    assert out is dirs, "未原地裁剪 → os.walk 仍会进入垃圾目录"
    assert "node_modules" not in dirs


def test_walk_does_not_descend_into_node_modules(tmp_path: Path):
    """端到端：真实 os.walk 遍历中，垃圾目录内的 .py 不得被收集到。

    这是本缺陷的核心契约 —— 用真实目录结构验证，而非只测常量。
    """
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "real.py").write_text("x = 1\n", encoding="utf-8")
    # 构造污染源：node_modules 下第三方捆绑 Python + build 产物
    (tmp_path / "node_modules" / "pkg").mkdir(parents=True)
    (tmp_path / "node_modules" / "pkg" / "vendored.py").write_text("y = 2\n", encoding="utf-8")
    (tmp_path / "build_mini_dist").mkdir()
    (tmp_path / "build_mini_dist" / "copy.py").write_text("z = 3\n", encoding="utf-8")
    (tmp_path / ".venv" / "lib").mkdir(parents=True)
    (tmp_path / ".venv" / "lib" / "site.py").write_text("w = 4\n", encoding="utf-8")

    collected = []
    for root, dirs, files in os.walk(tmp_path):
        _prune_dirs(dirs)
        for f in files:
            if f.endswith(".py"):
                collected.append(os.path.relpath(os.path.join(root, f), tmp_path))

    assert collected == ["src/real.py"] or collected == [os.path.join("src", "real.py")], collected
    for junk in ("vendored.py", "copy.py", "site.py"):
        assert not any(junk in c for c in collected), f"{junk} 泄漏进遍历结果: {collected}"


def test_no_inline_exclusion_lists_remain():
    """元测试：不得再出现内联排除列表（防止各调用点再次各自漂移）。

    唯一允许出现 ``dirs[:] = [d for d in dirs ...`` 的地方是 _prune_dirs 本体。
    """
    src = (Path(__file__).resolve().parents[1] / "toolkit" / "toolkit_explr.py").read_text(encoding="utf-8")
    count = src.count("dirs[:] = [d for d in dirs")
    assert count == 1, (
        f"发现 {count} 处 dirs 裁剪（期望仅 _prune_dirs 本体 1 处）—— "
        f"新增遍历点必须复用 _prune_dirs，不得再写内联排除列表"
    )
