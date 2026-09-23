"""path_filters —— 项目树遍历排除集（唯一事实源）的回归测试。

背景（2026-09-23 实测）：本项目历史上在多个扫描器里**各自维护内联排除列表**，
且普遍漏掉 ``node_modules`` / ``build_mini_dist``。后果不是「慢一点」而是
**正确性事故**：

- ``toolkit_explr`` 把 ``agent-calendar-viewer/node_modules`` 下第三方捆绑的
  Python 当本项目 API 文档化（``docs/API参考.md`` 混入 344 条伪路径，
  ``symbol_index.json`` 1.9 MB → 48 MB）
- ``auto_fix`` / ``toolkit_format_code`` 会**改写文件**，扫进第三方代码就会去
  「修复 / 格式化」别人的实现
- ``toolkit_code_review`` / ``toolkit_batch_process`` 的报告与批量替换同样被污染

本测试钉住三件事：
1. 已知垃圾目录**全部**在排除集内（漏一个就会复发）
2. ``prune_dirs`` 必须**原地**生效（``os.walk`` 依赖就地裁剪语义）
3. 真实源码目录**必须保留**（别把防护修成「什么都扫不到」）
"""

from __future__ import annotations

import os

import pytest

from tea_agent.path_filters import (
    PRUNE_DIRS,
    is_junk_path,
    iter_files,
    prune_dirs,
)

#: 实测会污染本项目的目录（任何新增扫描器都必须排除它们）
KNOWN_JUNK = [
    "node_modules",
    "build_mini_dist",
    "build",
    "dist",
    ".venv",
    "venv",
    "__pycache__",
    ".git",
    ".tea_agent_run",
    "site-packages",
]

#: 真实源码目录 —— 绝不能被排除
REAL_SOURCE = ["tea_agent", "tests", "docs", "src", "lib", "demo", "scripts"]


@pytest.mark.parametrize("name", KNOWN_JUNK)
def test_prune_dirs_covers_known_junk(name):
    """每个已知垃圾目录都必须在排除集内 —— 少一个就会污染产物。"""
    assert name in PRUNE_DIRS, f"{name} 未纳入排除集，会被当成项目源码扫描"


@pytest.mark.parametrize("name", REAL_SOURCE)
def test_real_source_not_excluded(name):
    """防「防护修成失效」：真实源码目录不得被排除。"""
    assert name not in PRUNE_DIRS, f"{name} 被误排除，项目源码将扫不到"


def test_prune_dirs_mutates_in_place():
    """必须原地裁剪 —— os.walk 的 dirs 是就地生效语义，返回新列表等于没排除。"""
    dirs = ["tea_agent", "node_modules", "tests", "build_mini_dist", "demo"]
    out = prune_dirs(dirs)
    assert out is None or out is dirs, "应原地修改传入的列表"
    assert dirs == ["tea_agent", "tests", "demo"], dirs


def test_prune_dirs_drops_hidden():
    """隐藏目录一律排除（实测其中的 .py 全为 ``_probe_*`` / 已删模块备份）。"""
    dirs = [".backup_cache_fix", ".tea_agent", "src"]
    prune_dirs(dirs)
    assert dirs == ["src"], dirs


def test_prune_dirs_extra_param():
    """extra= 用于局部追加排除，且不得污染全局排除集。"""
    dirs = ["src", "vendor", "node_modules"]
    prune_dirs(dirs, extra=("vendor",))
    assert dirs == ["src"], dirs
    assert "vendor" not in PRUNE_DIRS, "extra 不得写入全局排除集"


@pytest.mark.parametrize("junk", KNOWN_JUNK)
def test_is_junk_path_detects(junk):
    assert is_junk_path(os.path.join("agent-calendar-viewer", junk, "pkg", "v.py"))
    assert is_junk_path(f"/abs/{junk}/x.py")
    assert is_junk_path(f"a\\{junk}\\x.py".replace("\\", "/"))


def test_is_junk_path_allows_real_source():
    assert not is_junk_path("tea_agent/toolkit/toolkit_explr.py")
    assert not is_junk_path("/abs/tea_agent/server/server.py")
    assert not is_junk_path("tea_agent/node_modules_notes.py"), \
        "仅按目录段匹配，文件名的子串不算命中"


def test_iter_files_skips_junk(tmp_path):
    """端到端：真实目录结构下，垃圾目录内的 .py 不得被收集到。"""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "real.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "node_modules" / "pkg").mkdir(parents=True)
    (tmp_path / "node_modules" / "pkg" / "vendored.py").write_text("y = 2\n", encoding="utf-8")
    (tmp_path / ".venv" / "lib").mkdir(parents=True)
    (tmp_path / ".venv" / "lib" / "site.py").write_text("z = 3\n", encoding="utf-8")
    (tmp_path / "build_mini_dist").mkdir()
    (tmp_path / "build_mini_dist" / "copy.py").write_text("w = 4\n", encoding="utf-8")

    got = sorted(
        os.path.relpath(p, tmp_path).replace("\\", "/")
        for p in iter_files(str(tmp_path), "*.py")
    )
    assert got == ["src/real.py"], got


def test_iter_files_accepts_single_file(tmp_path):
    """传单个文件路径时应直接产出（供显式指定文件的调用方使用）。"""
    f = tmp_path / "solo.py"
    f.write_text("", encoding="utf-8")
    got = list(iter_files(str(f), "*.py"))
    assert got == [str(f)]


def test_iter_files_respects_pattern(tmp_path):
    (tmp_path / "a.py").write_text("", encoding="utf-8")
    (tmp_path / "b.txt").write_text("", encoding="utf-8")
    got = sorted(os.path.basename(p) for p in iter_files(str(tmp_path), "*.py"))
    assert got == ["a.py"]


def test_no_scanner_reintroduces_inline_exclude_lists():
    """元测试：禁止扫描器再出现内联排除列表（本缺陷的根因是「各自维护」）。

    允许 ``path_filters`` 自身实现裁剪（它就是那份唯一事实源）。
    """
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parents[1]  # tea_agent/
    offenders = []
    pattern = re.compile(r"d(?:irs)?\[:\]\s*=\s*\[.*(?:node_modules|__pycache__)")
    for f in sorted(root.rglob("*.py")):
        if "__pycache__" in f.parts or f.name == "path_filters.py":
            continue
        text = f.read_text(encoding="utf-8", errors="ignore")
        for i, line in enumerate(text.splitlines(), 1):
            if pattern.search(line):
                offenders.append(f"{f.relative_to(root.parent).as_posix()}:{i}")
    assert not offenders, (
        "以下位置又出现了内联目录排除列表，请改用 tea_agent.path_filters：\n  "
        + "\n  ".join(offenders)
    )
