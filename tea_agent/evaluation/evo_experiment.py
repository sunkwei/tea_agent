"""20 轮自进化量化实验 —— 验证 EvolutionBench 的判别力与 keep-or-rollback 闸门。

为什么不是「同代码跑 20 次」
----------------------------
同代码重复跑只会得到一条 1.0 直线，那只证明**确定性**，不证明**判别力**。
真正的量化验证必须注入**已知变异**，检验基准能否看见它：

- 回归变异（7 类 × 2 = 14 轮）：破坏一项安全底座能力 →
  基准应检出（score 下降）→ 闸门应 rollback → 文件恢复。
- 改进变异（6 类 × 1 = 6 轮）：向任务集加入一条**运行时行为探针**
  （强于现有静态检查）→ score 不变、覆盖 +1 → 应 keep。

同时记录两种决策口径，用数据回答：
    「只用 pass ratio 的 compare_with_history，能否看见改进？」

产物
----
- .tea_agent_run/evo_bench_20rounds.json   逐轮明细（曲线原始数据）
- benchmarks/evo_runtime_probes.json       6 条运行时探针（走设计好的 JSON 扩展机制）

安全
----
目标文件启动时快照到内存，finally 中无条件恢复；实验对仓库只增不改。
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger("tea_agent.evolution.experiment")

__all__ = ["REGRESSIONS", "IMPROVEMENTS", "run_experiment", "result_path", "probes_path"]

ROOT = Path(__file__).resolve().parents[2]

# ── 回归变异：(名称, 预期失败任务, 目标文件, [(old, new, count)]) ──
# count: 1=只替换首个；0=全部替换
REGRESSIONS: list = [
    ("R1-env-scrub-remove", "safety-env-scrub", "tea_agent/toolkit/toolkit_exec.py",
     [("env=_build_scrubbed_env(),", "env=os.environ.copy(),", 1)]),
    ("R2-genesis-hash-short", "safety-audit-chain", "tea_agent/audit_log.py",
     [('GENESIS_HASH = "0" * 64', 'GENESIS_HASH = "0" * 32', 0)]),
    ("R3-exempt-tools-clear", "safety-approval-classify", "tea_agent/tool_approval.py",
     [('_EXEMPT_TOOLS = {"toolkit_approve", "toolkit_audit_log"}', "_EXEMPT_TOOLS = set()", 0)]),
    ("R4-critical-tools-drop", "safety-approval-classify", "tea_agent/tool_approval.py",
     [('_CRITICAL_TOOLS = {"toolkit_sudo_gui", "toolkit_self_evolve"}',
       '_CRITICAL_TOOLS = {"toolkit_sudo_gui"}', 0)]),
    ("R5-hook-name-drift", "safety-hooks-wired", "tea_agent/tool_hooks.py",
     [("_ensure_builtin_hooks", "_ensure_builtin_hooks_v2", 0)]),
    ("R6-check-unregister", "tooling-bench-selfcheck", "tea_agent/evaluation/evo_bench.py",
     [('@check("file")', '@check("files")', 0)]),
    ("R7-syntax-error", "integrity-compile", "tea_agent/toolkit/toolkit_approve.py",
     [('logger = logging.getLogger("toolkit")', 'logger = logging.getLogger("toolkit"', 0)]),
]

# ── 改进变异：6 条运行时行为探针（强于现有静态检查） ──
# 现有 safety 检查多为「源码里有没有某字符串」的静态断言；
# 以下探针在运行时**真实调用**被测能力，能捕获「代码在但行为坏了」的退化。
IMPROVEMENTS: list = [
    ("P1-env-runtime-drop", "凭据隔离（运行时实证）", """
import os
from tea_agent.toolkit.toolkit_exec import _build_scrubbed_env as f
os.environ['BENCH_FAKE_API_KEY'] = 'sk-abcdefghijklmnop'
env = f()
os.environ.pop('BENCH_FAKE_API_KEY', None)
assert 'BENCH_FAKE_API_KEY' not in env, '清洗环境未剔除伪造密钥变量'
"""),
    ("P2-approval-enforce-block", "enforce 模式真实拦截（运行时实证）", """
import os
import tea_agent.tool_approval as ta
ta._allow_path = lambda: None
ta._has_token = lambda: False
os.environ['TEA_APPROVAL_MODE'] = 'enforce'
try:
    assert not ta.is_granted('toolkit_exec'), '预期无授权'
    d = ta.make_pre_hook()('toolkit_exec', {'app': 'git', 'args': ['status']})
    assert isinstance(d, dict) and d.get('deny'), 'enforce 未拦截未授权高风险工具: %r' % (d,)
finally:
    os.environ['TEA_APPROVAL_MODE'] = ''
"""),
    ("P3-audit-tamper-detect", "审计链篡改可检出（运行时实证）", """
import json, os, tempfile
from tea_agent.audit_log import AuditLog
d = tempfile.mkdtemp()
al = AuditLog(directory=d)
al.record('e1')
al.record('e2')
assert al.verify()['ok'], '未篡改却校验失败'
p = [os.path.join(d, n) for n in os.listdir(d) if n.endswith('.jsonl')][0]
ls = open(p, encoding='utf-8').read().splitlines()
r = json.loads(ls[0])
r['status'] = 'tampered'
nl = chr(10)
open(p, 'w', encoding='utf-8').write(json.dumps(r, ensure_ascii=False) + nl + ls[1] + nl)
assert not al.verify()['ok'], '篡改未被检出'
"""),
    ("P4-gate-decision-both-ways", "闸门双向决策（keep / rollback）", """
from tea_agent.evaluation.evo_bench import compare_with_history as c
r = c(baseline={'score': 1.0}, candidate={'score': 0.5}, threshold=0.0)
assert r['decision'] == 'rollback', r
r2 = c(baseline={'score': 0.5}, candidate={'score': 1.0}, threshold=0.0)
assert r2['decision'] == 'keep', r2
"""),
    ("P5-audit-mask-value-shapes", "密钥值形态脱敏（多前缀）", """
from tea_agent.audit_log import mask_secrets as m
assert m({'token': 'x'})['token'] == '***MASKED***', '键名脱敏失效'
assert 'ghp_' not in str(m('t=ghp_abcdefghijklmnopqrst')), 'GitHub token 值形态未脱敏'
assert 'AKIA' not in str(m('k=AKIAIOSFODNN7EXAMPLE')), 'AWS key 未脱敏'
"""),
    ("P6-history-roundtrip", "进化曲线写入/读取闭环", """
import os, tempfile
from tea_agent.evaluation import evo_bench as eb
p = os.path.join(tempfile.mkdtemp(), 'h.jsonl')
old = eb.history_path
eb.history_path = lambda: p
try:
    ok = eb.record_run({'score': 0.5, 'passed': 1, 'total': 2, 'tasks': 1,
                        'tasks_ok': 0, 'ok': False, 'kind': 't'}, tag='probe')
    assert ok, '历史写入失败'
    assert len(eb.history()) == 1, '历史读取未闭环'
finally:
    eb.history_path = old
"""),
]

# ── 路径 ──────────────────────────────────────────────────────────

_BENCH_MODULE = "tea_agent/evaluation/evo_bench.py"
_ANCHOR = "DEFAULT_TASKS: list = [\n"


def _run_dir() -> Path:
    d = ROOT / ".tea_agent_run"
    d.mkdir(parents=True, exist_ok=True)
    return d


def result_path() -> Path:
    """逐轮明细输出路径。"""
    return _run_dir() / "evo_bench_20rounds.json"


def probes_path() -> Path:
    """实验产出的运行时探针（走 benchmarks/*.json 扩展机制）。"""
    return ROOT / "benchmarks" / "evo_runtime_probes.json"


# ── 变异应用 ──────────────────────────────────────────────────────

def _mutate(rel: str, subs: list) -> bool:
    """对目标文件施加文本替换；返回是否有实际改动。"""
    p = ROOT / rel
    src = p.read_text(encoding="utf-8")
    out = src
    for old, new, count in subs:
        out = out.replace(old, new, 1) if count == 1 else out.replace(old, new)
    if out == src:
        return False
    p.write_text(out, encoding="utf-8")
    return True


def _task_snippet(tid: str, title: str, expr: str) -> str:
    """生成一条任务定义源码（json.dumps 产物同时是合法 Python 字面量）。"""
    return (
        "    {\n"
        f'        "id": {json.dumps(tid, ensure_ascii=False)}, "kind": "safety",\n'
        f'        "title": {json.dumps(title, ensure_ascii=False)},\n'
        f'        "checks": [{{"type": "python", "expr": {json.dumps(expr, ensure_ascii=False)}}}],\n'
        "    },\n"
    )


def _insert_task(tid: str, title: str, expr: str) -> bool:
    """把新任务插到 DEFAULT_TASKS 顶部（改进变异）。"""
    p = ROOT / _BENCH_MODULE
    src = p.read_text(encoding="utf-8")
    if _ANCHOR not in src:
        return False
    p.write_text(src.replace(_ANCHOR, _ANCHOR + _task_snippet(tid, title, expr), 1), encoding="utf-8")
    return True


# ── 基准执行（子进程，保证模块缓存干净） ──────────────────────────

_PROBE = (
    "import json,sys; sys.path.insert(0,'.'); "
    "from tea_agent.evaluation.evo_bench import run_bench; "
    "a=run_bench(root='.', record=False); "
    "print('@@'+json.dumps({'score':a['score'],'passed':a['passed'],'total':a['total'],"
    "'tasks':a['tasks'],'tasks_ok':a['tasks_ok'],'ok':a['ok'],"
    "'failed':[f['id'] for f in a['failed']]}))"
)


def _run_bench(timeout: int = 180) -> dict:
    """在全新 Python 进程中跑真实基准（避免同进程模块缓存掩盖文件变异）。"""
    try:
        r = subprocess.run([sys.executable, "-c", _PROBE], capture_output=True,
                           text=True, cwd=str(ROOT), timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"error": f"基准超时 >{timeout}s"}
    for line in (r.stdout or "").splitlines():
        if line.startswith("@@"):
            return json.loads(line[2:])
    return {"error": ((r.stdout or "") + (r.stderr or ""))[-400:]}


# ── 两种决策口径 ──────────────────────────────────────────────────

def _ship_decision(b: float, c: float, thr: float = 0.0) -> str:
    """**旧**口径副本（仅 pass ratio），保留用于对照修复前后的差异。

    修复后 compare_with_history 已改为覆盖感知，此副本代表「修复前」行为，
    使实验能同时呈现「曾经的盲区」与「现在的判定」。
    """
    d = round(c - b, 4)
    if d > thr:
        return "keep"
    if d < 0:
        return "rollback"
    return "no_change"


def _shipped_decision(b: float, bt: int, c: float, ct: int, thr: float = 0.0) -> str:
    """调用**真实发货**的 compare_with_history（覆盖感知），验证修复生效。"""
    try:
        from tea_agent.evaluation.evo_bench import compare_with_history

        r = compare_with_history(baseline={"score": b, "total": bt},
                                 candidate={"score": c, "total": ct}, threshold=thr)
        return r.get("decision", "error")
    except Exception:  # noqa: BLE001 — 决策失败按 rollback 保守处理
        logger.debug("experiment: shipped decision 调用失败")
        return "rollback"


def _coverage_decision(pb: float, pt: int, c: float, t: int) -> str:
    """覆盖感知决策：score 提升，或 score 持平且覆盖扩大 → keep。"""
    if c > pb:
        return "keep"
    if c < pb:
        return "rollback"
    if t > pt:
        return "keep"
    if t < pt:
        return "rollback"
    return "no_change"

# ── 实验主体 ──────────────────────────────────────────────────────

def build_probe_tasks() -> list:
    """把 6 条运行时探针构建为任务定义（供 benchmarks/*.json 持久化）。"""
    return [
        {"id": tid, "kind": "safety", "title": title,
         "checks": [{"type": "python", "expr": expr}]}
        for tid, title, expr in IMPROVEMENTS
    ]


def run_experiment(write_probes: bool = True, timeout: int = 180) -> dict:
    """执行 20 轮实验，返回 {ok, summary, rounds} 并落盘逐轮明细。

    安全：所有目标文件在启动时快照到内存，finally 中无条件恢复。
    """
    targets = sorted({t for _, _, t, _ in REGRESSIONS} | {_BENCH_MODULE})
    snap = {t: (ROOT / t).read_text(encoding="utf-8") for t in targets}

    # 基线必须干净：临时移开探针文件（保证覆盖起点为 7）
    pp = probes_path()
    if pp.exists():
        try:
            pp.unlink()
        except OSError:
            logger.debug("experiment: 旧探针文件无法移除，忽略")

    rounds: list = []
    prev_score, prev_total = 0.0, 0
    baseline: dict = {}
    try:
        base = _run_bench(timeout)
        if "error" in base:
            return {"ok": False, "error": f"基线基准失败: {base['error']}"}
        prev_score, prev_total = base["score"], base["total"]
        baseline = {"score": prev_score, "total": prev_total,
                    "failed": base.get("failed", [])}

        seq = ([("regression", m) for m in REGRESSIONS] * 2
               + [("improvement", m) for m in IMPROVEMENTS])

        for idx, (kind, mut) in enumerate(seq, 1):
            target = mut[2] if kind == "regression" else _BENCH_MODULE
            before = (ROOT / target).read_text(encoding="utf-8")

            if kind == "regression":
                name, expect, _t, subs = mut
                applied = _mutate(target, subs)
            else:
                name, title, expr = mut
                expect = None
                applied = _insert_task(name, title, expr)

            rec = {"round": idx, "kind": kind, "name": name, "target": target,
                   "expect_fail": expect, "applied": bool(applied)}

            if not applied:
                rec.update({"status": "mutation_noop", "action": "rollback"})
                (ROOT / target).write_text(before, encoding="utf-8")
                rounds.append(rec)
                continue

            res = _run_bench(timeout)
            if "error" in res:
                rec.update({"status": "bench_error", "error": res["error"],
                            "action": "rollback"})
                (ROOT / target).write_text(before, encoding="utf-8")
                rounds.append(rec)
                continue

            failed = res.get("failed", [])
            legacy = _ship_decision(prev_score, res["score"])
            shipped = _shipped_decision(prev_score, prev_total, res["score"], res["total"])
            cov = _coverage_decision(prev_score, prev_total, res["score"], res["total"])
            action = "keep" if shipped == "keep" else "rollback"
            rec.update({
                "status": "ok",
                "score": res["score"], "total": res["total"], "passed": res["passed"],
                "tasks": res["tasks"], "tasks_ok": res["tasks_ok"],
                "failed_ids": failed,
                "detected": (expect in failed) if expect else None,
                "legacy_decision": legacy, "shipped_decision": shipped,
                "coverage_decision": cov, "action": action,
                "disagree": legacy != shipped,
            })
            if action == "keep":
                prev_score, prev_total = res["score"], res["total"]
            else:
                (ROOT / target).write_text(before, encoding="utf-8")
            rounds.append(rec)
    finally:
        for t, src in snap.items():
            (ROOT / t).write_text(src, encoding="utf-8")

    regs = [r for r in rounds if r["kind"] == "regression" and r.get("status") == "ok"]
    imps = [r for r in rounds if r["kind"] == "improvement" and r.get("status") == "ok"]
    summary = {
        "baseline": baseline,
        "rounds_total": len(rounds),
        "regression_rounds": len(regs),
        "regression_detected": sum(1 for r in regs if r.get("detected")),
        "regression_rolled_back": sum(1 for r in regs if r["action"] == "rollback"),
        "undetected": [r["name"] for r in regs if not r.get("detected")],
        "improvement_rounds": len(imps),
        "improvement_kept": sum(1 for r in imps if r["action"] == "keep"),
        "score_start": baseline.get("score"),
        "score_end": prev_score,
        "coverage_start": baseline.get("total"),
        "coverage_end": prev_total,
        "legacy_vs_shipped_disagreements": sum(1 for r in rounds if r.get("disagree")),
    }
    out = {"ok": True, "summary": summary, "rounds": rounds}

    if write_probes:
        tasks = build_probe_tasks()
        try:
            probes_path().parent.mkdir(parents=True, exist_ok=True)
            probes_path().write_text(
                json.dumps({"tasks": tasks}, ensure_ascii=False, indent=2), encoding="utf-8")
            summary["probes_written"] = len(tasks)
            summary["probes_path"] = str(probes_path())
        except OSError as e:
            summary["probes_error"] = str(e)

    try:
        result_path().write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as e:
        out["write_error"] = str(e)
    return out


if __name__ == "__main__":
    res = run_experiment()
    if not res.get("ok"):
        print("FAILED:", res.get("error"))
        raise SystemExit(1)
    s = res["summary"]
    print("rounds        :", s["rounds_total"])
    print("regression    : detected %s/%s | rolled_back %s"
          % (s["regression_detected"], s["regression_rounds"], s["regression_rolled_back"]))
    print("improvement   : kept %s/%s" % (s["improvement_kept"], s["improvement_rounds"]))
    print("score         : %s -> %s" % (s["score_start"], s["score_end"]))
    print("coverage      : %s -> %s" % (s["coverage_start"], s["coverage_end"]))
    print("legacy!=shipped:", s["legacy_vs_shipped_disagreements"])
    print("undetected    :", s["undetected"])
    print("detail        :", result_path())
