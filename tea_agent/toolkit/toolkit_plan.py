# @2026-05-19 gen by claude, Plandex风格 Plan→Execute→Verify 工作流引擎
"""
toolkit_plan — 结构化任务规划与执行

三步工作流:
  Plan:    从自然语言目标生成结构化任务树 (JSON)
  Execute: 逐步执行，每步调用 self_evolve/lsp 并记录结果
  Verify:  对已完成步骤运行测试/lint 验证

存储: .tea_agent_run/plans/{plan_id}.json
"""

import json
import os
import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any
import logging

logger = logging.getLogger("toolkit")

PLANS_DIR = ".tea_agent_run/plans"

# ── 数据结构 ────────────────────────────────────────────

def _ensure_plans_dir():
    os.makedirs(PLANS_DIR, exist_ok=True)

def _plan_path(plan_id: str) -> str:
    return os.path.join(PLANS_DIR, f"{plan_id}.json")

def _load_plan(plan_id: str) -> Optional[dict]:
    path = _plan_path(plan_id)
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def _save_plan(plan: dict):
    _ensure_plans_dir()
    plan["updated_at"] = datetime.now().isoformat()
    with open(_plan_path(plan["id"]), "w", encoding="utf-8") as f:
        json.dump(plan, f, indent=2, ensure_ascii=False)

_KNOWN_STEP_META = {"id", "desc", "action", "depends_on", "verify", "params"}

def _new_plan(goal: str, steps: List[dict]) -> dict:
    now = datetime.now().isoformat()
    normalized = []
    for i, s in enumerate(steps):
        meta_keys = _KNOWN_STEP_META & set(s.keys())
        # 显式 params 优先，否则所有非 meta 键自动归入 params
        if "params" in s:
            params = {**s["params"]}
        else:
            params = {k: v for k, v in s.items() if k not in _KNOWN_STEP_META}
        normalized.append({
            "id": s.get("id", str(i + 1)),
            "desc": s["desc"],
            "action": s.get("action", "self_evolve"),
            "params": params,
            "depends_on": s.get("depends_on", []),
            "verify": s.get("verify", "py_compile"),
            "status": "pending",
            "result": None,
            "started_at": None,
            "finished_at": None,
        })
    return {
        "id": uuid.uuid4().hex[:8],
        "goal": goal,
        "status": "created",
        "created_at": now,
        "updated_at": now,
        "current_step": None,
        "steps": normalized,
    }

# ── 核心逻辑 ────────────────────────────────────────────

def _deps_satisfied(step: dict, all_steps: List[dict]) -> bool:
    for dep_id in step.get("depends_on", []):
        dep = next((s for s in all_steps if s["id"] == dep_id), None)
        if not dep or dep["status"] != "done":
            return False
    return True

def _next_pending(plan: dict) -> Optional[dict]:
    for step in plan["steps"]:
        if step["status"] == "pending" and _deps_satisfied(step, plan["steps"]):
            return step
    return None

def _count_status(plan: dict, status: str) -> int:
    return sum(1 for s in plan["steps"] if s["status"] == status)

# ── 工具入口 ────────────────────────────────────────────

def toolkit_plan(
    action: str,
    goal: str = None,
    steps: List[dict] = None,
    plan_id: str = None,
    step_id: str = None,
    cwd: str = None,
) -> dict:
    """Plandex 风格 Plan→Execute→Verify 工作流。"""
    import os as _os
    cwd = cwd or _os.getcwd()

    try:
        if action == "create":
            if not goal or not steps:
                return {"ok": False, "error": "create 需要 goal 和 steps 参数"}
            plan = _new_plan(goal, steps)
            _save_plan(plan)
            return {
                "ok": True, "plan_id": plan["id"], "goal": goal,
                "total_steps": len(plan["steps"]),
                "hint": f"action='run' plan_id='{plan['id']}' 执行全部",
            }

        elif action == "show":
            if not plan_id:
                return {"ok": False, "error": "show 需要 plan_id"}
            plan = _load_plan(plan_id)
            if not plan:
                return {"ok": False, "error": f"计划不存在: {plan_id}"}
            return {
                "ok": True, "plan": plan,
                "progress": f"{_count_status(plan, 'done')}/{len(plan['steps'])} done",
            }

        elif action == "step":
            return _do_step(plan_id, step_id, cwd)

        elif action == "verify":
            return _do_verify(plan_id, step_id, cwd)

        elif action == "run":
            return _do_run(plan_id, cwd)

        elif action == "resume":
            return _do_resume(plan_id, cwd)

        elif action == "list":
            _ensure_plans_dir()
            plans = []
            for fname in sorted(os.listdir(PLANS_DIR), reverse=True):
                if fname.endswith(".json"):
                    p = json.load(open(os.path.join(PLANS_DIR, fname), encoding="utf-8"))
                    plans.append({
                        "id": p["id"], "goal": p["goal"][:80], "status": p["status"],
                        "progress": f"{_count_status(p, 'done')}/{len(p['steps'])}",
                        "updated": p.get("updated_at", "")[:19],
                    })
            return {"ok": True, "plans": plans}

        elif action == "delete":
            if not plan_id:
                return {"ok": False, "error": "delete 需要 plan_id"}
            path = _plan_path(plan_id)
            if os.path.exists(path):
                os.remove(path)
                return {"ok": True, "deleted": plan_id}
            return {"ok": False, "error": f"计划不存在: {plan_id}"}

        else:
            return {"ok": False, "error": f"未知 action: {action}"}

    except Exception as e:
        logger.exception(f"toolkit_plan: {e}")
        return {"ok": False, "error": str(e)[:300]}

# ── Action 实现 ──────────────────────────────────────────

def _do_step(plan_id, step_id, cwd):
    if not plan_id:
        return {"ok": False, "error": "step 需要 plan_id"}
    plan = _load_plan(plan_id)
    if not plan:
        return {"ok": False, "error": f"计划不存在: {plan_id}"}

    if step_id:
        step = next((s for s in plan["steps"] if s["id"] == step_id), None)
        if not step:
            return {"ok": False, "error": f"步骤不存在: {step_id}"}
    else:
        step = _next_pending(plan)
        if not step:
            all_done = all(s["status"] in ("done", "skipped") for s in plan["steps"])
            plan["status"] = "done" if all_done else "failed"
            _save_plan(plan)
            return {"ok": True, "done": all_done, "plan_status": plan["status"],
                    "summary": _step_summary(plan)}

    if not _deps_satisfied(step, plan["steps"]):
        return {"ok": False, "error": f"步骤 {step['id']} 依赖未满足: {step['depends_on']}"}

    return _execute_step(plan, step, cwd)

def _do_verify(plan_id, step_id, cwd):
    if not plan_id:
        return {"ok": False, "error": "verify 需要 plan_id"}
    plan = _load_plan(plan_id)
    if not plan:
        return {"ok": False, "error": f"计划不存在: {plan_id}"}
    if step_id:
        step = next((s for s in plan["steps"] if s["id"] == step_id), None)
        if not step:
            return {"ok": False, "error": f"步骤不存在: {step_id}"}
        return _verify_step(step, cwd)
    results = [_verify_step(s, cwd) for s in plan["steps"] if s["status"] == "done"]
    return {"ok": True, "verified": len(results), "results": results}

def _do_run(plan_id, cwd):
    if not plan_id:
        return {"ok": False, "error": "run 需要 plan_id"}
    plan = _load_plan(plan_id)
    if not plan:
        return {"ok": False, "error": f"计划不存在: {plan_id}"}
    plan["status"] = "running"
    _save_plan(plan)
    executed = []
    while True:
        step = _next_pending(plan)
        if not step:
            break
        result = _execute_step(plan, step, cwd)
        executed.append({"step": step["id"], "ok": result.get("ok"), "desc": step["desc"]})
        if not result.get("ok"):
            plan["status"] = "failed"
            _save_plan(plan)
            return {"ok": False, "error": f"步骤 {step['id']} 失败: {result.get('error','')}",
                    "executed": executed, "plan_id": plan_id}
    plan["status"] = "done"
    _save_plan(plan)
    return {"ok": True, "executed": executed, "plan_id": plan_id, "summary": _step_summary(plan)}

def _do_resume(plan_id, cwd):
    if not plan_id:
        return {"ok": False, "error": "resume 需要 plan_id"}
    plan = _load_plan(plan_id)
    if not plan:
        return {"ok": False, "error": f"计划不存在: {plan_id}"}
    for s in plan["steps"]:
        if s["status"] == "running":
            s["status"] = "pending"
    plan["status"] = "running"
    _save_plan(plan)
    return _do_run(plan_id, cwd)

# ── 内部辅助 ────────────────────────────────────────────

def _step_summary(plan: dict) -> str:
    icons = {"done": "✓", "failed": "✗", "running": "▶", "pending": "○", "skipped": "−"}
    return "\n".join(f"  {icons.get(s['status'],'?')} [{s['id']}] {s['desc']}" for s in plan["steps"])

def _execute_step(plan: dict, step: dict, cwd: str) -> dict:
    step["status"] = "running"
    step["started_at"] = datetime.now().isoformat()
    plan["current_step"] = step["id"]
    _save_plan(plan)

    result = {"ok": False, "error": "未执行"}
    try:
        action = step.get("action", "self_evolve")
        params = step.get("params", {})

        if action == "self_evolve":
            from tea_agent.toolkit.toolkit_self_evolve import toolkit_self_evolve
            result = toolkit_self_evolve(
                file_path=params["file_path"],
                description=step["desc"],
                old_code=params["old_code"],
                new_code=params["new_code"],
                verify=params.get("verify", True),
                backup=params.get("backup", True),
                git_snapshot=params.get("git_snapshot", False),
                run_tests=params.get("run_tests", False),
                symbol=params.get("symbol"),
                lsp_checks=params.get("lsp_checks", True),
            )

        elif action == "create_file":
            path = params["file_path"]
            full = os.path.join(cwd, path)
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "w", encoding="utf-8") as f:
                f.write(params["content"])
            result = {"ok": True, "file": path}

        elif action == "exec":
            import subprocess
            r = subprocess.run(params.get("cmd", []), capture_output=True,
                               text=True, timeout=120, cwd=cwd)
            result = {"ok": r.returncode == 0, "stdout": r.stdout, "stderr": r.stderr}
        elif action == "verify_only":
            result = _verify_step(step, cwd)

        else:
            result = {"ok": False, "error": f"未知 action: {action}"}

    except Exception as e:
        result = {"ok": False, "error": str(e)[:300]}

    step["result"] = result
    step["status"] = "done" if result.get("ok") else "failed"
    step["finished_at"] = datetime.now().isoformat()
    _save_plan(plan)

    return {"ok": result.get("ok", False), "step_id": step["id"],
            "desc": step["desc"], "result": result,
            "plan_progress": f"{_count_status(plan, 'done')}/{len(plan['steps'])}"}

def _verify_step(step: dict, cwd: str) -> dict:
    verify_type = step.get("verify", "py_compile")
    results = {}
    try:
        import py_compile
        import subprocess as sp
        params = step.get("params", {})
        fp = params.get("file_path", "")

        if any(k in verify_type for k in ("py_compile", "compile")):
            if fp and fp.endswith(".py"):
                try:
                    py_compile.compile(os.path.join(cwd, fp), doraise=True)
                    results["compile"] = "ok"
                except py_compile.PyCompileError as e:
                    results["compile"] = f"FAIL: {e}"

        if any(k in verify_type for k in ("lint", "ruff")):
            if fp:
                r = sp.run(["ruff", "check", "--output-format", "json", os.path.join(cwd, fp)],
                           capture_output=True, text=True, timeout=15, cwd=cwd)
                diags = json.loads(r.stdout) if r.stdout.strip() else []
                results["lint"] = "ok" if not diags else f"{len(diags)} issues"

        if any(k in verify_type for k in ("test", "pytest")):
            r = sp.run([os.sys.executable, "-m", "pytest", "test_*.py", "-q", "--tb=short"],
                       capture_output=True, text=True, timeout=60, cwd=cwd)
            results["test"] = (r.stdout + r.stderr)[-300:]

    except Exception as e:
        results["error"] = str(e)[:200]

    all_ok = all(not str(v).startswith("FAIL") for v in results.values())
    return {"ok": all_ok, "step_id": step.get("id"), "verify": results}

# ── Meta ────────────────────────────────────────────────

def meta_toolkit_plan():
    return {
        "type": "function",
        "function": {
            "name": "toolkit_plan",
            "description": "Plandex 风格 Plan→Execute→Verify 三步工作流。create=创建计划, show=查看, step=执行下一步, verify=验证, run=全量执行, resume=恢复, list=列表, delete=删除。",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["create", "show", "step", "verify", "run", "resume", "list", "delete"]},
                    "goal": {"type": "string", "description": "[create] 计划目标"},
                    "steps": {"type": "array", "items": {"type": "object"}, "description": "[create] 步骤列表"},
                    "plan_id": {"type": "string", "description": "[show/step/verify/run/resume/delete] 计划ID"},
                    "step_id": {"type": "string", "description": "[step/verify] 指定步骤ID"},
                },
                "required": ["action"],
            },
        },
    }
