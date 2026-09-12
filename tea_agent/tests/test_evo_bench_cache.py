"""EvolutionBench 指标缓存新鲜度回归。

背景：``_bench_metrics`` 使用进程内缓存 ``_BENCH_METRIC_CACHE``（同一轮基准内
多次 ``metrics()`` 复用一次全量扫描，是必要的性能优化）。但若该缓存**跨
``run_bench`` 调用**复用，同一 Agent 会话内「改前 vs 改后」两次测量会返回相同
分数 —— keep-or-rollback（分数未提升则回滚）的前提即被破坏：进化曲线在会话内
永远是平线。

本测试固化不变量：``run_bench`` 每次调用都必须基于**当前磁盘状态**重新扫描。
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
_TMP_NAME = "_zz_bench_cache_probe.py"


@pytest.fixture()
def tmp_source():
    """在 tea_agent/ 下临时创建源码文件（影响 print_calls 指标），用后必删。"""
    p = ROOT / "tea_agent" / _TMP_NAME
    try:
        yield p
    finally:
        try:
            p.unlink()
        except OSError:
            pass


def _baseline_print_calls() -> int:
    """清缓存后读取当前 print_calls 基线（不假设为 0，仓库可能已有真实 print）。"""
    from tea_agent.evaluation import evo_bench as eb

    eb._BENCH_METRIC_CACHE.clear()
    return eb._bench_metrics(str(ROOT))["print_calls"]


def test_run_bench_recomputes_metrics_across_calls(tmp_source):
    """预热缓存后改变源码，run_bench 必须反映新状态（不得返回陈旧指标）。"""
    from tea_agent.evaluation import evo_bench as eb

    n0 = _baseline_print_calls()
    tmp_source.write_text("print(1)\n", encoding="utf-8")
    n1 = n0 + 1

    expr = ("m = metrics(); assert m['print_calls'] == %d, "
            "'期望 print_calls=%d，实际 %%d（指标缓存陈旧）' %% m['print_calls']" % (n1, n1))
    task = {"id": "cache-probe", "kind": "probe", "title": "指标新鲜度",
            "checks": [{"type": "python", "expr": expr}]}

    agg = eb.run_bench(tasks=[task], root=str(ROOT))
    assert agg["score"] == 1.0, f"run_bench 使用了陈旧指标: {agg['failed']}"


def test_run_bench_detects_regression_within_same_process(tmp_source):
    """同一进程内：指标恶化后二次 run_bench 必须反映（否则门禁形同虚设）。"""
    from tea_agent.evaluation import evo_bench as eb

    n0 = _baseline_print_calls()
    expr = "m = metrics(); assert m['print_calls'] == %d, 'print_calls 已变化'" % n0
    task = {"id": "cache-regression", "kind": "probe", "title": "回归可检测",
            "checks": [{"type": "python", "expr": expr}]}

    before = eb.run_bench(tasks=[task], root=str(ROOT))["score"]
    assert before == 1.0, f"基线应通过: {eb.run_bench(tasks=[task], root=str(ROOT))['failed']}"

    tmp_source.write_text("print(1)\n", encoding="utf-8")
    after = eb.run_bench(tasks=[task], root=str(ROOT))["score"]

    assert after == 0.0, (
        f"同进程内指标恶化未被检测（before={before} after={after}）—— 缓存跨运行复用"
    )
