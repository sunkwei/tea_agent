"""20 轮自进化量化实验的回归驱动（验证 EvolutionBench 的判别力与闸门有效性）。

为什么写成 pytest 而不是脚本：
- 通过 toolkit_run_tests 驱动，不经过 toolkit_exec 链路
- 结论以断言形式固化：判别力/闸门/覆盖三维度任何退化都会让测试红

实验一次约 30-90s（20 轮 × 子进程真实基准），用 module 级 fixture 只跑一次。
"""

from __future__ import annotations

import json

import pytest

from tea_agent.evaluation.evo_experiment import (
    IMPROVEMENTS,
    REGRESSIONS,
    _run_bench,
    probes_path,
    result_path,
    run_experiment,
)


@pytest.fixture(scope="module")
def experiment():
    """跑一次 20 轮实验，全部测试共享结果。"""
    res = run_experiment(write_probes=True)
    assert res.get("ok"), f"实验失败: {res.get('error')}"
    return res


def test_experiment_ran_20_rounds(experiment):
    assert experiment["summary"]["rounds_total"] == 20
    kinds = [r["kind"] for r in experiment["rounds"]]
    assert kinds.count("regression") == 14
    assert kinds.count("improvement") == 6


def test_all_regressions_detected_and_rolled_back(experiment):
    s = experiment["summary"]
    # 判别力：每一类回归变异都必须被基准看见
    assert s["regression_detected"] == s["regression_rounds"] == 14, s["undetected"]
    # 闸门有效性：检出后必须全部回滚，绝不放行
    assert s["regression_rolled_back"] == 14
    assert s["undetected"] == []


def test_each_regression_maps_to_expected_task(experiment):
    """回归变异必须命中「预期的那一条」检查，而不是别的任务顺带失败。"""
    for r in experiment["rounds"]:
        if r["kind"] != "regression" or r.get("status") != "ok":
            continue
        assert r["detected"], f"{r['name']} 未被检出"
        assert r["expect_fail"] in r["failed_ids"], (r["name"], r["failed_ids"])


def test_all_improvements_kept_and_coverage_grows(experiment):
    s = experiment["summary"]
    assert s["improvement_kept"] == s["improvement_rounds"] == 6
    # 覆盖按探针数增长；分数不得下降（难度任务集下基线非满值 → 分数应同步上升）
    assert s["coverage_end"] == s["coverage_start"] + len(IMPROVEMENTS)
    assert s["score_end"] >= s["score_start"]


def test_pass_ratio_blindspot_is_measured(experiment):
    """核心发现：pass-ratio 盲区**只在基线饱和时**出现。

    基线满值（score=1.0）时，加一条通过的探针不改变 ratio → 旧口径误判 no_change；
    难度任务集打破天花板后（基线 ≈0.78），加通过探针同时抬高 ratio → 两口径一致。
    饱和情形的盲区由 test_evo_bench.py::test_compare_coverage_only_improvement_is_keep 直接覆盖。
    """
    s = experiment["summary"]
    if s["score_start"] >= 1.0:  # 饱和：盲区显现，6 轮全部分歧
        assert s["legacy_vs_shipped_disagreements"] == len(IMPROVEMENTS) == 6
    else:  # 非饱和：两口径一致，盲区潜伏
        assert s["legacy_vs_shipped_disagreements"] == 0, s
    for r in experiment["rounds"]:
        if r["kind"] != "improvement" or r.get("status") != "ok":
            continue
        b = s["baseline"]
        assert r["score"] >= b["score"] and r["total"] > b["total"], r
        # 无论饱和与否：真实增益都必须被保留，不得回滚
        assert r["shipped_decision"] == "keep", r
        assert r["coverage_decision"] == "keep"
        assert r["action"] == "keep"


def test_regression_rounds_agree_between_both_metrics(experiment):
    """回归场景两种口径必须一致（score 下降对两者都可见）——盲区只存在于改进侧。"""
    for r in experiment["rounds"]:
        if r["kind"] != "regression" or r.get("status") != "ok":
            continue
        assert r["legacy_decision"] == r["shipped_decision"] == "rollback"
        assert r["disagree"] is False


def test_curve_artifact_written(experiment):
    p = result_path()
    assert p.exists(), f"曲线文件未落盘: {p}"
    data = json.loads(p.read_text(encoding="utf-8"))
    assert len(data["rounds"]) == 20 and data["ok"] is True
    # 曲线可复现性锚点：起始值自洽（与任务集规模解耦，兼容难度任务集）
    assert data["summary"]["baseline"]["score"] == data["summary"]["score_start"]
    assert data["summary"]["coverage_start"] == data["summary"]["baseline"]["total"]


def test_probes_persisted_and_pass(experiment):
    """实验产出的 6 条运行时探针落盘，且在真实基准中全部通过。"""
    assert experiment["summary"].get("probes_written") == 6
    assert probes_path().exists()
    data = json.loads(probes_path().read_text(encoding="utf-8"))
    assert len(data["tasks"]) == 6
    assert {t["id"] for t in data["tasks"]} == {m[0] for m in IMPROVEMENTS}

    res = _run_bench()
    assert "error" not in res, res.get("error")
    probe_ids = {m[0] for m in IMPROVEMENTS}
    # 注意：_run_bench（子进程）的 failed 是 id 字符串列表，与 run_bench 的 dict 列表不同形态
    failed_ids = set(res.get("failed") or [])
    assert not (probe_ids & failed_ids), f"探针未通过: {probe_ids & failed_ids}"
    assert res["total"] >= 7 + len(IMPROVEMENTS), res["total"]


def test_all_regression_targets_restored(experiment):
    """实验结束后仓库必须干净：回归变异不得残留（DEFAULT_TASKS 回到 7 条以内）。"""
    from tea_agent.evaluation.evo_bench import DEFAULT_TASKS

    assert not any("R1-env-scrub-remove" in str(t) for t in DEFAULT_TASKS)
    src = (pytest.importorskip("pathlib").Path(__file__).resolve().parents[2]
           / "tea_agent" / "toolkit" / "toolkit_exec.py").read_text(encoding="utf-8")
    assert src.count("env=_build_scrubbed_env") >= 4, "toolkit_exec 环境清洗接入被实验残留破坏"
    assert "env=os.environ.copy()" not in src, "回归变异 R1 残留未恢复"

    # 内置任务集应恢复原始 7 条（探针走独立 JSON，不改 DEFAULT_TASKS）
    assert len(DEFAULT_TASKS) == 7, len(DEFAULT_TASKS)
