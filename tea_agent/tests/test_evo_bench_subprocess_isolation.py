"""回归：evo_bench 的 python 检查必须读**磁盘**，而不是父进程 sys.modules 里的旧模块。

缺陷背景（2026-09-19）：``_check_python`` 原先在**父进程内** exec，检查里的
``from tea_agent.x import y`` 会命中 ``sys.modules`` 缓存。长期存活的 server 若已
加载过该模块，检查读到的就是**加载那一刻**的代码 —— 对职责是「判定新鲜改动好坏」
的进化闸门，这等于拿旧代码给新代码打分：磁盘上真实的回归（例如 GENESIS_HASH 被
改短）会被判「未检出」，闸门照样报绿。

修复：一次基准运行 = 一个全新解释器（``python_check_session``），检查在子进程内
执行，模块从磁盘重建。

本文件第一个用例是**元验证用**的：把 ``_check_python`` 改回进程内 exec，它会立刻
变红 —— 否则这个测试就是假的。
"""

from __future__ import annotations

import importlib
import os
import sys

from tea_agent.evaluation.evo_bench import run_bench

_PROBE_PKG = "_evo_stale_probe"


def _run(expr: str, root, timeout: int = 30) -> dict:
    """跑一个只含单条 python 检查的任务，返回该 check 的结果。"""
    task = {"id": "probe", "kind": "safety", "checks": [{"type": "python", "expr": expr}]}
    res = run_bench(tasks=[task], root=str(root), timeout=timeout)
    return res["results"][0]["checks"][0]


def test_python_check_reads_disk_not_stale_parent_module(tmp_path, monkeypatch):
    """父进程已缓存旧模块时，检查仍须读磁盘现值（子进程隔离）。

    旧实现（进程内 exec）下此用例必然失败：断言会读到父进程缓存的 64。
    """
    pkg = tmp_path / _PROBE_PKG
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    mod = pkg / "stale_mod.py"
    mod.write_text("VALUE = 64\n", encoding="utf-8")

    monkeypatch.syspath_prepend(str(tmp_path))
    had_pkg = _PROBE_PKG in sys.modules
    had_mod = f"{_PROBE_PKG}.stale_mod" in sys.modules
    try:
        # 先让**父进程**加载并缓存该模块（VALUE=64）
        loaded = importlib.import_module(f"{_PROBE_PKG}.stale_mod")
        assert loaded.VALUE == 64
        # 前置条件：父进程此刻确实揣着一份旧模块（修复要对抗的正是它）
        assert f"{_PROBE_PKG}.stale_mod" in sys.modules

        # 磁盘上把值改掉：只有「读磁盘」的实现才能看到 32
        mod.write_text("VALUE = 32\n", encoding="utf-8")

        expr = (
            f"from {_PROBE_PKG}.stale_mod import VALUE\n"
            "assert VALUE == 32, '读到的是父进程旧值 %r（检查未隔离 sys.modules）' % VALUE\n"
        )
        check = _run(expr, tmp_path)
        assert check["ok"] is True, f"python 检查未读磁盘：{check['detail']}"
    finally:
        # 清理，避免污染其它用例（monkeypatch.delitem 会立即删除，此处不能提前用）
        if not had_mod:
            sys.modules.pop(f"{_PROBE_PKG}.stale_mod", None)
        if not had_pkg:
            sys.modules.pop(_PROBE_PKG, None)


def test_python_check_runs_in_a_different_process(tmp_path):
    """检查必须在独立进程内执行（直接钉住机制，而非间接现象）。"""
    expr = f"import os\nassert os.getpid() != {os.getpid()}, '检查仍在父进程内执行（pid 相同）'\n"
    check = _run(expr, tmp_path)
    assert check["ok"] is True, check["detail"]


def test_python_check_hard_exit_fails_closed_and_recovers(tmp_path):
    """执行器硬退出 → 该检查判失败（fail-closed），且后续检查能重启执行器继续。"""
    task = {
        "id": "probe-exit", "kind": "safety",
        "checks": [
            {"type": "python", "expr": "import os\nos._exit(0)\n"},
            {"type": "python", "expr": "assert 1 + 1 == 2"},
        ],
    }
    res = run_bench(tasks=[task], root=str(tmp_path), timeout=30)
    checks = res["results"][0]["checks"]
    assert checks[0]["ok"] is False, "执行器硬退出必须判失败（不得静默通过）"
    assert checks[1]["ok"] is True, f"应能重启执行器继续后续检查：{checks[1]['detail']}"


def test_python_check_assertion_failure_is_reported(tmp_path):
    """普通断言失败仍照常归因（子进程化不得吞掉失败原因）。"""
    check = _run("assert 1 == 2, '意图失败'", tmp_path)
    assert check["ok"] is False
    assert "意图失败" in check["detail"]
