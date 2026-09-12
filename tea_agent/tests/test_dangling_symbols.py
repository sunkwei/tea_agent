"""悬空符号引用检测（含合成阳性对照）。

「引用了不存在的符号」是静默死路径的高发形态：真实实例是 agent.py 曾
`from ...toolkit_experience_solidify import ExperienceSolidifier` 而该类并不存在，
被 `except ImportError` 吞掉 → 功能长期死亡且无人察觉。

本测试两层：
1. **阳性对照**：合成缺陷包必须被准确检出（防检测器空转/假绿，也防符号表
   收集逻辑退化 —— 曾因 `_module_level_nodes` 漏产出顶层 def/class，
   导致函数名不进符号表、虚报 427 处悬空）。
2. **真实仓库**：当前应为 0 处悬空导入符号、0 个悬空 __all__ 名称。
"""

from __future__ import annotations

import ast
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _write_control_pkg(base: Path, pkg: str = "pkg") -> None:
    """合成包：含 2 处悬空符号导入 + 1 个悬空 __all__ 名 + 1 个悬空模块。"""
    p = base / pkg
    (p / "sub").mkdir(parents=True)
    (p / "__init__.py").write_text(
        'from .core import Foo\n__all__ = ["Foo", "Bar"]\n', encoding="utf-8")
    (p / "core.py").write_text("def Foo():\n    return 1\n", encoding="utf-8")
    (p / "sub" / "__init__.py").write_text("", encoding="utf-8")
    (p / "mod.py").write_text(
        "from . import sub\n"             # 合法：子模块
        "from . import missing_mod\n"     # 悬空：无此子模块
        "from .core import Foo\n"         # 合法
        "from .core import NoSuchSym\n"   # 悬空：符号不存在
        "from .nope import Anything\n",   # 悬空：目标模块不存在
        encoding="utf-8")


def test_control_detects_known_dangling_symbols():
    """阳性对照：检测器必须报出合成缺陷（防空转假绿）。"""
    from tea_agent.evaluation.evo_bench import _dangling_symbol_stats

    with tempfile.TemporaryDirectory() as d:
        base = Path(d)
        (base / "tea_agent").mkdir()
        # 复用合成包内容，但置于 tea_agent/ 下以适配扫描入口
        p = base / "tea_agent"
        (p / "sub").mkdir()
        (p / "__init__.py").write_text(
            'from .core import Foo\n__all__ = ["Foo", "Bar"]\n', encoding="utf-8")
        (p / "core.py").write_text("def Foo():\n    return 1\n", encoding="utf-8")
        (p / "sub" / "__init__.py").write_text("", encoding="utf-8")
        (p / "mod.py").write_text(
            "from . import sub\n"
            "from . import missing_mod\n"
            "from .core import Foo\n"
            "from .core import NoSuchSym\n"
            "from .nope import Anything\n", encoding="utf-8")
        n_import, n_all = _dangling_symbol_stats(str(base))

    assert n_import == 2, f"应对 2 处悬空符号（missing_mod/NoSuchSym），实得 {n_import}"
    assert n_all == 1, f"应对 1 个悬空 __all__ 名（Bar），实得 {n_all}"


def test_module_level_nodes_includes_toplevel_defs():
    """回归：顶层 def/class 必须出现在「模块级节点」中（符号表依赖此点）。"""
    from tea_agent.evaluation.evo_bench import _module_level_nodes

    tree = ast.parse("def f():\n    pass\n\n\nclass C:\n    pass\n")
    kinds = {type(n).__name__ for n in _module_level_nodes(tree)}
    assert "FunctionDef" in kinds and "ClassDef" in kinds, kinds


def test_repo_has_no_dangling_symbols():
    """真实仓库不变量：无悬空符号导入、无悬空 __all__ 声明。"""
    from tea_agent.evaluation.evo_bench import _dangling_symbol_stats

    n_import, n_all = _dangling_symbol_stats(str(ROOT))
    assert n_import == 0, f"悬空符号导入 {n_import} 处（引用不存在的符号 = 静默死路径）"
    assert n_all == 0, f"悬空 __all__ 名 {n_all} 个（公开承诺未兑现）"


def test_lazy_getattr_exports_not_flagged():
    """PEP 562 惰性导出（模块级 __getattr__）不得被判为悬空 __all__。

    tea_agent/__init__.py 用 __getattr__ + _LAZY_EXPORTS 兑现 __all__ 承诺，
    静态符号表看不到这些名字；若照报，就会产出与运行时事实相反的假阳性
    （实测曾因此虚报 6 个）。
    """
    from tea_agent.evaluation.evo_bench import _dangling_symbol_stats

    with tempfile.TemporaryDirectory() as d:
        base = Path(d)
        p = base / "tea_agent"
        p.mkdir()
        (p / "lazy.py").write_text("def Lazy():\n    return 1\n", encoding="utf-8")
        (p / "__init__.py").write_text(
            "def Real():\n    return 1\n"
            "_LAZY = {'Lazy': '.lazy'}\n"
            "__all__ = ['Real', 'Lazy']\n"
            "\n"
            "def __getattr__(name):\n"
            "    return getattr(__import__('tea_agent.lazy'), name)\n",
            encoding="utf-8")
        n_import, n_all = _dangling_symbol_stats(str(base))

    assert n_all == 0, f"惰性导出的 __all__ 被误报 {n_all} 个"
    assert n_import == 0, f"误报悬空导入 {n_import} 处"
