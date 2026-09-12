"""EvolutionBench + 安全底座（A2/A3/B1/B2）回归测试。

覆盖：
- evo_bench 引擎：check 注册 / 任务执行 / 失败隔离 / 环境清洗
- 内置 safety 任务集全绿（自证：基准同时是安全底座的回归网络）
- 审批分级：critical/high/medium 判定与豁免，含 rm -rf / 漏判回归
- 审计日志：脱敏、hash 链可复算、篡改可检出、链路校验
- 进化闸门：模式解析、钩子幂等挂载、.bak 自动恢复
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tea_agent.evaluation.evo_bench import (  # noqa: E402
    CHECKS,
    DEFAULT_TASKS,
    _scrubbed_env,
    compare_with_history,
    history,
    history_path,
    load_tasks,
    record_run,
    run_bench,
    run_task,
)


@pytest.fixture()
def temp_history(tmp_path, monkeypatch):
    """把进化曲线重定向到临时文件，避免污染项目历史。"""
    p = tmp_path / "bench_history.jsonl"
    monkeypatch.setenv("TEA_BENCH_HISTORY", str(p))
    return p


# ── 引擎：check 注册与执行 ────────────────────────────────────────

def test_checks_registered():
    assert {"command", "file", "python"} <= set(CHECKS)


def test_builtin_tasks_have_ids():
    ids = [t.get("id") for t in DEFAULT_TASKS]
    assert all(ids), "内置任务必须都有 id"
    assert len(ids) == len(set(ids)), "任务 id 不可重复"


def test_run_task_python_check_pass(tmp_path):
    r = run_task({"id": "t1", "checks": [{"type": "python", "expr": "assert 1 + 1 == 2"}]}, root=tmp_path)
    assert r["ok"] and r["score"] == 1.0 and r["passed"] == 1


def test_run_task_failure_isolated(tmp_path):
    """单个 check 失败不影响其他 check（失败隔离）。"""
    r = run_task({"id": "t2", "checks": [
        {"type": "python", "expr": "assert False, 'boom'"},
        {"type": "python", "expr": "assert True"},
    ]}, root=tmp_path)
    assert r["score"] == 0.5 and not r["ok"]
    assert "boom" in r["checks"][0]["detail"]


def test_run_task_unknown_check_type_fails_closed(tmp_path):
    r = run_task({"id": "t3", "checks": [{"type": "nope"}]}, root=tmp_path)
    assert not r["ok"] and "未知" in r["checks"][0]["detail"]


def test_run_task_no_checks_scores_zero(tmp_path):
    r = run_task({"id": "t4", "checks": []}, root=tmp_path)
    assert r["score"] == 0.0 and not r["ok"]


def test_file_check_pass_and_missing(tmp_path):
    (tmp_path / "a.txt").write_text("hello world", encoding="utf-8")
    ok = run_task({"id": "f1", "checks": [{"type": "file", "path": "a.txt", "contains": "hello"}]}, root=tmp_path)
    bad = run_task({"id": "f2", "checks": [{"type": "file", "path": "missing.txt"}]}, root=tmp_path)
    assert ok["ok"] and not bad["ok"]


def test_scrubbed_env_drops_secret_keys(monkeypatch):
    """基准命令同样隔离凭据（与 toolkit_exec 一致的 env 清洗）。"""
    monkeypatch.setenv("MY_SUPER_TOKEN", "leak-me")
    monkeypatch.setenv("MY_PLAIN_VAR", "keep-me")
    env = _scrubbed_env()
    assert "MY_SUPER_TOKEN" not in env
    assert env.get("MY_PLAIN_VAR") == "keep-me"


# ── 内置任务集：安全底座自证 ──────────────────────────────────────

def test_builtin_safety_tasks_all_pass(temp_history):
    """A 部分（env 清洗 / 审计链 / 审批闸门）必须全绿。"""
    agg = run_bench(root=str(REPO_ROOT), kind="safety")
    assert agg["ok"], f"安全底座任务失败: {json.dumps(agg['failed'], ensure_ascii=False)}"
    assert agg["total"] >= 5


def test_env_scrub_task_detects_regression():
    """safety-env-scrub 必须真的检查 4 处 Popen 接入（而非只查函数名存在）。"""
    task = next(t for t in DEFAULT_TASKS if t["id"] == "safety-env-scrub")
    assert run_task(task, root=REPO_ROOT)["ok"]


def test_load_tasks_kind_filter():
    assert all(t["kind"] == "safety" for t in load_tasks(kind="safety"))
    assert len(load_tasks(kind="safety")) < len(load_tasks())


# ── 进化曲线：记录与 keep-or-rollback ────────────────────────────

def test_record_and_history_roundtrip(temp_history):
    agg = {"score": 1.0, "passed": 7, "total": 7, "tasks": 3, "tasks_ok": 3,
           "ok": True, "kind": "safety"}
    assert record_run(agg, tag="snap-1")
    pts = history()
    assert len(pts) == 1
    assert pts[0]["score"] == 1.0 and pts[0]["tag"] == "snap-1"
    assert history_path() == str(temp_history)


def test_compare_decisions(temp_history):
    temp_history.write_text(
        json.dumps({"ts": "1", "score": 0.5}) + "\n", encoding="utf-8")
    assert compare_with_history(baseline=0.5, candidate=0.6)["decision"] == "keep"
    assert compare_with_history(baseline=0.5, candidate=0.4)["decision"] == "rollback"
    assert compare_with_history(baseline=0.5, candidate=0.5)["decision"] == "no_change"
    # 阈值高于 delta → 不算提升
    assert compare_with_history(baseline=0.5, candidate=0.6, threshold=0.2)["decision"] == "no_change"


def test_compare_uses_last_history_point_as_baseline(temp_history):
    temp_history.write_text(
        json.dumps({"ts": "1", "score": 0.3}) + "\n", encoding="utf-8")
    r = compare_with_history(candidate={"score": 0.9})
    assert r["ok"] and r["baseline"] == 0.3 and r["delta"] == 0.6


def test_compare_without_candidate_errors(temp_history):
    assert not compare_with_history(candidate=None)["ok"]


def test_run_bench_records_snapshot(temp_history):
    agg = run_bench(root=str(REPO_ROOT), kind="safety", record=True, tag="t-snap")
    assert agg["snapshot"] and agg["snapshot"]["tag"] == "t-snap"
    assert len(history()) == 1


# ── 审批分级（A3）────────────────────────────────────────────────

def test_classify_risk_levels():
    from tea_agent.tool_approval import classify_risk as cr
    assert cr("toolkit_self_evolve")[0] == "critical"
    assert cr("toolkit_exec", {"app": "sudo", "args": ["ls"]})[0] == "critical"
    assert cr("toolkit_exec", {"app": "git", "args": ["status"]})[0] == "high"
    assert cr("toolkit_file", {"action": "read"})[0] is None
    assert cr("toolkit_file", {"action": "write"})[0] == "medium"
    assert cr("toolkit_unknown_xyz")[0] is None


def test_classify_risk_destructive_command_regression():
    """回归：仅扫描 args 会漏判 `rm -rf /`（app 自身须参与匹配）。"""
    from tea_agent.tool_approval import classify_risk as cr
    assert cr("toolkit_exec", {"app": "rm", "args": ["-rf", "/"]})[0] == "critical"
    assert cr("toolkit_exec", {"app": "mkfs", "args": ["-t", "ext4", "/dev/sda1"]})[0] == "critical"


def test_exempt_tools_are_not_classified():
    from tea_agent.tool_approval import classify_risk as cr
    assert cr("toolkit_approve")[0] is None
    assert cr("toolkit_audit_log")[0] is None


def test_approval_mode_env_override(monkeypatch):
    from tea_agent.tool_approval import approval_mode
    monkeypatch.setenv("TEA_APPROVAL_MODE", "enforce")
    assert approval_mode() == "enforce"
    monkeypatch.setenv("TEA_APPROVAL_MODE", "advisory")
    assert approval_mode() == "advisory"
    monkeypatch.setenv("TEA_APPROVAL_MODE", "bogus")
    assert approval_mode() in ("off", "advisory", "enforce")


# ── 审计日志（A2）────────────────────────────────────────────────

def test_mask_secrets_key_and_value_form():
    from tea_agent.audit_log import mask_secrets
    assert mask_secrets({"api_key": "anything"})["api_key"] == "***MASKED***"
    masked = str(mask_secrets("token=sk-abcdefghijklmnop"))
    assert "sk-abcdefghijklmnop" not in masked


def test_audit_hash_chain_is_recomputable(tmp_path):
    from tea_agent.audit_log import GENESIS_HASH, AuditLog, _canonical
    al = AuditLog(directory=str(tmp_path))
    al.record("e1", tool="toolkit_x", status="ok")
    al.record("e2", tool="toolkit_x", status="ok")
    recs = [json.loads(l) for l in Path(al.files()[0]).read_text(encoding="utf-8").splitlines() if l.strip()]
    assert recs[0]["prev"] == GENESIS_HASH
    assert recs[1]["prev"] == recs[0]["h"]
    for r in recs:
        body = {k: v for k, v in r.items() if k != "h"}
        expect = hashlib.sha256((r["prev"] + _canonical(body)).encode("utf-8")).hexdigest()
        assert r["h"] == expect, "记录哈希应可由 prev + 内容独立复算"


def test_audit_tamper_detected(tmp_path):
    from tea_agent.audit_log import AuditLog
    al = AuditLog(directory=str(tmp_path))
    al.record("e", tool="t", status="ok")
    al.record("e", tool="t", status="ok")
    p = Path(al.files()[0])
    lines = p.read_text(encoding="utf-8").splitlines()
    rec = json.loads(lines[0])
    rec["status"] = "tampered"
    lines[0] = json.dumps(rec, ensure_ascii=False, sort_keys=True)
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    v = AuditLog(directory=str(tmp_path)).verify()
    assert not v["ok"] and "篡改" in v["reason"]


def test_audit_verify_intact_chain(tmp_path):
    from tea_agent.audit_log import AuditLog
    al = AuditLog(directory=str(tmp_path))
    al.record("a", tool="t", status="ok")
    al.record("b", tool="t", status="err")
    v = AuditLog(directory=str(tmp_path)).verify()
    assert v["ok"] and v["records"] == 2


def test_audit_disabled_writes_nothing(tmp_path):
    from tea_agent.audit_log import AuditLog
    al = AuditLog(directory=str(tmp_path), enabled=False)
    assert al.record("e", tool="t") is None
    assert al.files() == []


# ── 进化闸门（B2）────────────────────────────────────────────────

def test_gate_mode_env_override(monkeypatch):
    from tea_agent.evolution_gate import gate_mode
    monkeypatch.setenv("TEA_EVOLVE_GATE", "enforce")
    assert gate_mode() == "enforce"
    monkeypatch.setenv("TEA_EVOLVE_GATE", "off")
    assert gate_mode() == "off"
    monkeypatch.setenv("TEA_EVOLVE_GATE", "nonsense")
    assert gate_mode() in ("off", "advisory", "enforce")


def test_gate_threshold_parsing(monkeypatch):
    from tea_agent.evolution_gate import gate_threshold
    monkeypatch.setenv("TEA_EVOLVE_GATE_THRESHOLD", "0.25")
    assert gate_threshold() == 0.25
    monkeypatch.setenv("TEA_EVOLVE_GATE_THRESHOLD", "not-a-number")
    assert gate_threshold() >= 0.0


def test_install_gate_is_idempotent():
    from tea_agent.evolution_gate import install_evolution_gate
    from tea_agent.tool_hooks import ToolHookRegistry
    reg = ToolHookRegistry()
    install_evolution_gate(reg)
    install_evolution_gate(reg)
    # stats() 的 post_hooks 值是「计数」而非列表
    assert reg.stats()["post_hooks"].get("toolkit_self_evolve") == 1


def test_restore_latest_backup(tmp_path):
    from tea_agent.evolution_gate import _restore_latest_backup
    target = tmp_path / "mod.py"
    target.write_text("NEW = 1\n", encoding="utf-8")
    (tmp_path / "mod.py.bak.20260101_000000").write_text("OLD = 1\n", encoding="utf-8")
    (tmp_path / "mod.py.bak.20260202_000000").write_text("OLDER = 2\n", encoding="utf-8")
    res = _restore_latest_backup(str(target))
    assert res["ok"]
    assert target.read_text(encoding="utf-8") == "OLDER = 2\n"  # 取最新备份


def test_restore_without_backup_reports_error(tmp_path):
    from tea_agent.evolution_gate import _restore_latest_backup
    target = tmp_path / "nobak.py"
    target.write_text("x = 1\n", encoding="utf-8")
    res = _restore_latest_backup(str(target))
    assert not res["ok"] and "备份" in res["error"]


def test_builtin_hooks_installed_lazily():
    """run_pre 应自动挂载内建审批/审计钩子（无需手工初始化）。"""
    from tea_agent.tool_hooks import ToolHookRegistry
    reg = ToolHookRegistry()
    assert reg._pre_hooks == {}
    reg.run_pre("toolkit_noop", {})
    assert reg._pre_hooks, "pre-hook 应已自动挂载"


def test_toolkit_evo_bench_tool_actions(temp_history):
    """工具层接口：run / history / compare 三动作闭环。"""
    from tea_agent.toolkit.toolkit_evo_bench import toolkit_evo_bench
    run1 = toolkit_evo_bench(action="run", kind="safety", root=str(REPO_ROOT),
                             record=True, tag="r1", verbose=False)
    assert run1["ok"] and "results" not in run1
    run2 = toolkit_evo_bench(action="run", kind="safety", root=str(REPO_ROOT),
                             record=True, tag="r2", verbose=False)
    assert run2["ok"]
    hist = toolkit_evo_bench(action="history")
    assert hist["ok"] and hist["points"] == 2
    cmp_ = toolkit_evo_bench(action="compare")
    assert cmp_["ok"] and cmp_["decision"] == "no_change"


# ── 覆盖感知决策（20 轮实验发现的 pass-ratio 盲区修复） ──────────────

def test_compare_coverage_only_improvement_is_keep(temp_history):
    """同分但覆盖扩大 → keep。

    纯 ratio 口径会判 no_change 并回滚掉真实增益（实验实证：6/6 分歧）。
    """
    from tea_agent.evaluation.evo_bench import compare_with_history

    r = compare_with_history(baseline={"score": 1.0, "total": 7},
                             candidate={"score": 1.0, "total": 13})
    assert r["decision"] == "keep", r
    assert r["basis"] == "coverage", r
    assert r["coverage_delta"] == 6
    assert r["delta"] == 0.0


def test_compare_coverage_shrink_is_rollback(temp_history):
    """同分但覆盖收缩 → rollback（不能因为分数没掉就放过）。"""
    from tea_agent.evaluation.evo_bench import compare_with_history

    r = compare_with_history(baseline={"score": 1.0, "total": 13},
                             candidate={"score": 1.0, "total": 7})
    assert r["decision"] == "rollback" and r["basis"] == "coverage", r


def test_compare_score_takes_priority_over_coverage(temp_history):
    """分数变化优先于覆盖变化（两个方向都要）。"""
    from tea_agent.evaluation.evo_bench import compare_with_history

    up = compare_with_history(baseline={"score": 0.5, "total": 10},
                              candidate={"score": 0.9, "total": 5})
    assert up["decision"] == "keep" and up["basis"] == "score", up

    down = compare_with_history(baseline={"score": 0.9, "total": 5},
                                candidate={"score": 0.5, "total": 20})
    assert down["decision"] == "rollback" and down["basis"] == "score", down


def test_compare_backward_compatible_with_numeric(temp_history):
    """纯数字入参（无 total）保持旧行为，不引入回退风险。"""
    from tea_agent.evaluation.evo_bench import compare_with_history

    r = compare_with_history(baseline=0.8, candidate=0.8)
    assert r["decision"] == "no_change" and r["basis"] == "none", r
    assert r["coverage_delta"] is None

    keep = compare_with_history(baseline=0.5, candidate=0.9)
    assert keep["decision"] == "keep" and keep["basis"] == "score"


def test_compare_coverage_threshold_respected(temp_history):
    """覆盖增量未超阈值 → 不保留（阈值可调）。"""
    from tea_agent.evaluation.evo_bench import compare_with_history

    r = compare_with_history(baseline={"score": 1.0, "total": 7},
                             candidate={"score": 1.0, "total": 8},
                             coverage_threshold=2)
    assert r["decision"] == "no_change", r
