"""架构不变量回归：包内导入规范 + 跨层无循环导入。

对应 AGENTS.md「不得循环导入」约定，把两条结构约束固化为可执行断言：

1. agent.py 的包内导入统一使用相对形式（``from .`` / ``from .x``）——绝对形式
   ``from tea_agent.x`` 会把「同包模块」与「外部消费者」混为一谈，且在包部分
   初始化期间更易与导入环纠缠。
2. 工具层不得在**模块级**反向导入 ``tea_agent.agent``：``tlk`` 会在 agent 导入
   期间 exec 全部 ``toolkit_*.py``，模块级反向导入会立刻成环。函数内惰性导入
   （如 ``toolkit_parallel_subtasks``）是允许的。
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PKG = ROOT / "tea_agent"


def _parse(p: Path) -> ast.Module:
    return ast.parse(p.read_text(encoding="utf-8", errors="replace"))


def test_agent_uses_relative_intra_package_imports():
    """agent.py 不得出现 `from tea_agent.xxx import ...`（应为相对导入）。"""
    tree = _parse(PKG / "agent.py")
    bad = [
        (n.lineno, n.module)
        for n in ast.walk(tree)
        if isinstance(n, ast.ImportFrom)
        and n.level == 0
        and (n.module or "").startswith("tea_agent")
    ]
    assert bad == [], f"agent.py 仍存在包内绝对导入: {bad}"


def test_toolkit_layer_has_no_module_level_import_of_agent():
    """工具层模块级反向导入 agent 会成环；只允许函数内惰性导入。"""
    bad = []
    for p in sorted((PKG / "toolkit").glob("*.py")):
        if p.name == "__init__.py":
            continue
        for node in ast.iter_child_nodes(_parse(p)):  # 仅顶层语句
            if isinstance(node, ast.ImportFrom) and (node.module or "") == "tea_agent.agent":
                bad.append((p.name, node.lineno))
            elif isinstance(node, ast.Import):
                for a in node.names:
                    if a.name == "tea_agent.agent":
                        bad.append((p.name, node.lineno))
    assert bad == [], f"工具层模块级反向导入 agent: {bad}"


def test_agent_module_imports_cleanly_in_fresh_process():
    """独立进程导入 tea_agent.agent 必须成功（冒烟验证无真实导入环）。"""
    r = subprocess.run(
        [sys.executable, "-c", "import tea_agent.agent as m; assert hasattr(m, 'Agent')"],
        cwd=str(ROOT), capture_output=True, text=True, timeout=180,
    )
    assert r.returncode == 0, f"导入 tea_agent.agent 失败:\n{r.stderr[-800:]}"


# ── 导入环检测（Tarjan SCC）──────────────────────────────────────
def test_cycle_detector_finds_synthetic_cycle():
    """算法正确性：合成 A⇄B 环必须被检出，无环图为 0。"""
    from tea_agent.evaluation.evo_bench import _count_import_cycles

    assert _count_import_cycles({"a": {"b"}, "b": {"a"}, "c": set()})[0] == 1
    assert _count_import_cycles({"a": {"b"}, "b": {"c"}, "c": set()})[0] == 0
    # 3 模块环 + 自引用（自环不计入 size>1 的强连通分量）
    assert _count_import_cycles({"a": {"b"}, "b": {"c"}, "c": {"a"}, "d": {"d"}})[0] == 1


def test_no_new_import_cycles_at_package_level():
    """不变量：包内**导入期**不得存在导入环（当前 0，判据已修正）。

    判据要点：只计模块级（导入期）执行的导入边 —— 函数内惰性导入是合法的
    破环手段，`if TYPE_CHECKING:` 块运行时不执行；相对导入按 ``__package__``
    语义解析（包的 ``__init__`` 其 ``__package__`` 即自身）。
    """
    from tea_agent.evaluation.evo_bench import _bench_metrics

    n = _bench_metrics(str(ROOT))["import_cycles"]
    assert n == 0, f"包内检测到 {n} 个导入环（期望 0）"
