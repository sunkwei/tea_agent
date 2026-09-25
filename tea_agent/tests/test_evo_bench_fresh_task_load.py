"""EvolutionBench 任务定义加载：必须绕开 sys.modules 缓存（回归测试）。

缺陷背景（2026-09-25 实测）：
    ``load_tasks`` 原先用普通 ``from ... import HARD_TASKS`` 取难度任务集，
    于是任务定义被 ``sys.modules`` 缓存。长期存活的进程（server / 已 import 过
    该模块的 CLI）在**编辑 evo_tasks_hard.py（例如调整棘轮基线）后重跑基准，
    仍会读到旧定义**，得出基于陈旧基线的判定。

    实测后果：把 broad_except 棘轮基线由 789 改为 791 后，长驻进程仍报
    「增至 791（基线 789）」判 FAIL —— 会误导出「改动无效」的结论，
    并把一个**错误的数据点**写进进化曲线（bench_history.jsonl）。

为什么这个缺陷比一般缓存问题更值得防：
    EvolutionBench 是自进化的**裁决器**。裁决器读到陈旧输入时不会报错，
    只会给出一个看起来合理的错误结论 —— 属静默失效，与「检查执行器」
    早已改用子进程规避的那类问题同源（见 evo_bench._check_python 的说明）。
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest


@pytest.fixture()
def bench():
    from tea_agent.evaluation import evo_bench

    return evo_bench


def test_load_tasks_ignores_stale_sys_modules(bench, monkeypatch):
    """核心契约：即便 sys.modules 里躺着旧定义，也必须采用磁盘上的真实定义。"""
    stale = types.ModuleType("tea_agent.evaluation.evo_tasks_hard")
    stale.HARD_TASKS = [{
        "id": "hard-broad-except-ratchet",
        "kind": "quality",
        "title": "STALE-SENTINEL",
        "checks": [{"type": "python", "expr": "assert False, '陈旧基线'"}],
    }]
    monkeypatch.setitem(sys.modules, "tea_agent.evaluation.evo_tasks_hard", stale)

    tasks = {t["id"]: t for t in bench.load_tasks()}
    task = tasks["hard-broad-except-ratchet"]
    assert task["title"] != "STALE-SENTINEL", (
        "load_tasks 吃到了 sys.modules 缓存 —— 编辑任务集后重跑基准仍会用旧定义"
    )


def test_loaded_task_comes_from_disk(bench):
    """载入内容必须与磁盘文件一致（而非任何内存替身）。"""
    tasks = {t["id"]: t for t in bench.load_tasks()}
    task = tasks["hard-broad-except-ratchet"]

    real = Path(bench.__file__).with_name("evo_tasks_hard.py").read_text(encoding="utf-8")
    expr = task["checks"][0]["expr"]
    assert expr in real, "载入的任务表达式不在磁盘文件中，来源可疑"


def test_load_hard_tasks_picks_up_edits(bench, tmp_path, monkeypatch):
    """同一进程内**改文件再读**必须看到新内容（无缓存）。"""
    (tmp_path / "evo_tasks_hard.py").write_text(
        "HARD_TASKS = [{'id': 'probe-v1', 'title': 'V1', 'kind': 'x', 'checks': []}]\n",
        encoding="utf-8",
    )
    # _load_hard_tasks 用 Path(__file__).with_name(...) 定位，故只需改 __file__
    monkeypatch.setattr(bench, "__file__", str(tmp_path / "evo_bench.py"))
    assert [t["id"] for t in bench._load_hard_tasks()] == ["probe-v1"]

    (tmp_path / "evo_tasks_hard.py").write_text(
        "HARD_TASKS = [{'id': 'probe-v2', 'title': 'V2', 'kind': 'x', 'checks': []}]\n",
        encoding="utf-8",
    )
    assert [t["id"] for t in bench._load_hard_tasks()] == ["probe-v2"], (
        "改文件后仍读到旧内容 —— 说明存在缓存"
    )


def test_load_hard_tasks_does_not_pollute_sys_modules(bench, monkeypatch):
    """按路径加载**不得**把模块写回 sys.modules（否则又变回缓存）。"""
    monkeypatch.delitem(sys.modules, "tea_agent.evaluation.evo_tasks_hard", raising=False)
    bench._load_hard_tasks()
    assert "tea_agent.evaluation.evo_tasks_hard" not in sys.modules, (
        "按路径加载污染了 sys.modules，后续读取会重新退化为缓存"
    )


def test_load_hard_tasks_missing_file_is_safe(bench, tmp_path, monkeypatch):
    """任务集文件缺失 → 返回空列表（降级为仅内置任务），不抛异常。"""
    monkeypatch.setattr(bench, "__file__", str(tmp_path / "evo_bench.py"))
    assert bench._load_hard_tasks() == []
