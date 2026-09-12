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
    # 覆盖 7 → 13，分数保持满值（更强的保证，不是更弱的）
    assert s["coverage_start"] == 7
    assert s["coverage_end"] == 7 + len(IMPROVEMENTS) == 13
    assert s["score_start"] == 1.0 and s["score_end"] == 1.0


def test_pass_ratio_blindspot_is_measured(experiment):
    """核心发现：只用 pass ratio 的 compare_with_history 看不见「同分但覆盖扩大」的改进。

    6 轮改进中 ship 口径全部判 no_change（→ 应回滚），
    而覆盖感知口径判 keep；分歧恰为 6 次。
    """
    s = experiment["summary"]
    assert s["legacy_vs_shipped_disagreements"] == len(IMPROVEMENTS) == 6
    for r in experiment["rounds"]:
        if r["kind"] != "improvement" or r.get("status") != "ok":
            continue
        assert r["score"] == 1.0 and r["total"] > 7
        # 修复前：纯 ratio 口径判 no_change（真实增益会被回滚）
        assert r["legacy_decision"] == "no_change", r
        # 修复后：真实发货的 compare_with_history 覆盖感知 → keep
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
    # 曲线可复现性锚点：baseline 与 summary 一致
    assert data["summary"]["baseline"]["score"] == 1.0
    assert data["summary"]["coverage_start"] == 7


def test_probes_persisted_and_pass(experiment):
    """实验产出的 6 条运行时探针落盘，且真实基准加载后全绿（7+6=13）。"""
    assert experiment["summary"].get("probes_written") == 6
    assert probes_path().exists()
    data = json.loads(probes_path().read_text(encoding="utf-8"))
    assert len(data["tasks"]) == 6
    assert {t["id"] for t in data["tasks"]} == {m[0] for m in IMPROVEMENTS}

    res = _run_bench()
    assert "error" not in res, res.get("error")
    assert res["total"] == 13, res
    assert res["score"] == 1.0 and res["failed"] == []


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
