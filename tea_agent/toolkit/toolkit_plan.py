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
    """Internal: ensure plans dir."""
    os.makedirs(PLANS_DIR, exist_ok=True)

def _plan_path(plan_id: str) -> str:
    """Internal: plan path.
    
    Args:
        plan_id: Description.
    """
    return os.path.join(PLANS_DIR, f"{plan_id}.json")

def _load_plan(plan_id: str) -> Optional[dict]:
    """Internal: load plan.
    
    Args:
        plan_id: Description.
    """
    path = _plan_path(plan_id)
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def _save_plan(plan: dict):
    """Internal: save plan.
    
    Args:
        plan: Description.
    """
    _ensure_plans_dir()
    plan["updated_at"] = datetime.now().isoformat()
    with open(_plan_path(plan["id"]), "w", encoding="utf-8") as f:
        json.dump(plan, f, indent=2, ensure_ascii=False)

_KNOWN_STEP_META = {"id", "desc", "action", "depends_on", "verify", "params", "doc_type", "doc_module", "doc_content"}

def _get_topic_id() -> Optional[str]:
    """获取当前 topic_id"""
    try:
        from tea_agent.session_ref import get_agent
        agent = get_agent()
        if agent is not None:
            return getattr(agent, 'current_topic_id', None)
    except Exception:
        pass
    return None

def _new_plan(goal: str, steps: List[dict]) -> dict:
    """Internal: new plan.
    
    Args:
        goal: Description.
        steps: Description.
    """
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
            "doc_type": s.get("doc_type", ""),
            "doc_module": s.get("doc_module", ""),
            "doc_content": s.get("doc_content", ""),
            "status": "pending",
            "result": None,
            "started_at": None,
            "finished_at": None,
        })
    return {
        "id": uuid.uuid4().hex[:8],
        "topic_id": _get_topic_id() or "",
        "goal": goal,
        "status": "created",
        "created_at": now,
        "updated_at": now,
        "current_step": None,
        "steps": normalized,
    }

# ── 核心逻辑 ────────────────────────────────────────────

def _deps_satisfied(step: dict, all_steps: List[dict]) -> bool:
    """Internal: deps satisfied.
    
    Args:
        step: Description.
        all_steps: Description.
    """
    for dep_id in step.get("depends_on", []):
        dep = next((s for s in all_steps if s["id"] == dep_id), None)
        if not dep or dep["status"] != "done":
            return False
    return True

def _next_pending(plan: dict) -> Optional[dict]:
    """Internal: next pending.
    
    Args:
        plan: Description.
    """
    for step in plan["steps"]:
        if step["status"] == "pending" and _deps_satisfied(step, plan["steps"]):
            return step
    return None

def _count_status(plan: dict, status: str) -> int:
    """Internal: count status.
    
    Args:
        plan: Description.
        status: Description.
    """
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

        elif action == "review":
            """画布审阅模式 — 展示计划但绝不修改文件，支持 diff 预览"""
            if not plan_id:
                return {"ok": False, "error": "review 需要 plan_id"}
            plan = _load_plan(plan_id)
            if not plan:
                return {"ok": False, "error": f"计划不存在: {plan_id}"}

            review_sections = []

            # 1. 计划概览
            review_sections.append(f"## 📋 计划审阅: {plan['goal'][:60]}")
            review_sections.append(f"- **状态**: {plan['status']}")
            review_sections.append(f"- **进度**: {_count_status(plan, 'done')}/{len(plan['steps'])} 完成")
            review_sections.append(f"- **创建于**: {plan['created_at'][:19]}")

            # 2. 步骤概览
            review_sections.append("\n### 步骤概览")
            icons = {"done": "✅", "failed": "❌", "running": "▶️", "pending": "⬜", "skipped": "⏭️"}
            for s in plan["steps"]:
                deps = f" (依赖: {', '.join(s['depends_on'])})" if s.get("depends_on") else ""
                status_icon = icons.get(s["status"], "❓")
                review_sections.append(f"  {status_icon} **[{s['id']}]** {s['desc']}{deps}")

            # 3. 依赖关系图 (Mermaid)
            review_sections.append("\n### 依赖关系")
            review_sections.append("```mermaid")
            review_sections.append("graph LR")
            for s in plan["steps"]:
                node_id = s["id"].replace(" ", "_")
                review_sections.append(f"  {node_id}[\"{s['id']}: {s['desc'][:30]}\"]")
                for dep in s.get("depends_on", []):
                    review_sections.append(f"  {dep.replace(' ', '_')} --> {node_id}")
            review_sections.append("```")

            # 4. 文件变更预览
            files_changed = []
            for s in plan["steps"]:
                fp = s.get("params", {}).get("file_path", "")
                if fp and fp not in files_changed:
                    files_changed.append(fp)
            if files_changed:
                review_sections.append(f"\n### 涉及文件 ({len(files_changed)} 个)")
                for fp in files_changed:
                    review_sections.append(f"- `{fp}`")

            # 5. 审阅结论
            has_pending = any(s["status"] == "pending" for s in plan["steps"])
            all_done = all(s["status"] == "done" for s in plan["steps"])
            if all_done:
                review_sections.append("\n✅ **所有步骤已完成，无需执行。**")
            elif has_pending:
                review_sections.append(f"\n🟡 **有待执行步骤，使用 action='run' plan_id='{plan_id}' 执行。**")
            else:
                review_sections.append(f"\n🔵 **计划就绪。**")

            return {
                "ok": True,
                "plan_id": plan_id,
                "review_markdown": "\n".join(review_sections),
                "summary": {
                    "goal": plan["goal"][:80],
                    "status": plan["status"],
                    "total": len(plan["steps"]),
                    "done": _count_status(plan, "done"),
                    "failed": _count_status(plan, "failed"),
                    "pending": _count_status(plan, "pending"),
                    "files_changed": files_changed,
                },
                "hint": "review 仅展示计划，不修改任何文件。使用 action='run' 执行。",
            }

        elif action == "canvas":
            """画布模式 — 创建一个空白画布计划用于 brainstorming"""
            if not goal:
                return {"ok": False, "error": "canvas 需要 goal 参数"}
            plan = _new_plan(goal, steps or [{
                "id": "draft",
                "desc": f"设计实现: {goal[:50]}",
                "action": "verify_only",
                "params": {},
                "verify": "manual",
            }])
            plan["status"] = "draft"
            _save_plan(plan)
            return {
                "ok": True, "plan_id": plan["id"], "goal": goal,
                "mode": "canvas",
                "hint": f"画布已创建 (plan_id='{plan['id']}')。使用 action='review' 查看，action='insert' 添加步骤，确认后 action='run' 执行。",
            }

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

        elif action == "decompose":
            if not goal:
                return {"ok": False, "error": "decompose 需要 goal 参数"}
            return _decompose_goal(goal, cwd)

        # ── 动态规划操作 ──
        elif action == "insert":
            return _insert_step(plan_id, step_id, steps)

        elif action == "replace":
            return _replace_step(plan_id, step_id, steps)

        elif action == "delete_step":
            return _delete_step(plan_id, step_id)

        elif action == "replan":
            return _replan(plan_id, steps, cwd)

        else:
            return {"ok": False, "error": f"未知 action: {action}"}

    except Exception as e:
        logger.exception(f"toolkit_plan: {e}")
        return {"ok": False, "error": str(e)[:300]}

# ── Action 实现 ──────────────────────────────────────────

def _do_step(plan_id, step_id, cwd):
    """Internal: do step.
    
    Args:
        plan_id: Description.
        step_id: Description.
        cwd: Description.
    """
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
    """Internal: do verify.
    
    Args:
        plan_id: Description.
        step_id: Description.
        cwd: Description.
    """
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
    """Internal: do run.
    
    Args:
        plan_id: Description.
        cwd: Description.
    """
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
    """Internal: do resume.
    
    Args:
        plan_id: Description.
        cwd: Description.
    """
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
    """Internal: step summary.
    
    Args:
        plan: Description.
    """
    icons = {"done": "✓", "failed": "✗", "running": "▶", "pending": "○", "skipped": "−"}
    return "\n".join(f"  {icons.get(s['status'],'?')} [{s['id']}] {s['desc']}" for s in plan["steps"])

def _execute_step(plan: dict, step: dict, cwd: str) -> dict:
    """Internal: execute step.
    
    Args:
        plan: Description.
        step: Description.
        cwd: Description.
    """
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

    # 自动落盘：成功完成的步骤若标记了 doc_type，产物写入 docs/
    if step["status"] == "done":
        try:
            doc_path = _auto_save_doc(step, plan, cwd)
            if doc_path:
                step["doc_saved"] = doc_path
                logger.info(f"Plan step doc saved: {doc_path}")
        except Exception as e:
            logger.warning(f"Plan step doc save failed (non-fatal): {e}")

    _save_plan(plan)

    return {"ok": result.get("ok", False), "step_id": step["id"],
            "desc": step["desc"], "result": result,
            "plan_progress": f"{_count_status(plan, 'done')}/{len(plan['steps'])}"}

def _verify_step(step: dict, cwd: str) -> dict:
    """Internal: verify step.
    
    Args:
        step: Description.
        cwd: Description.
    """
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

# ── 自动落盘（借鉴 best-skills/dev-workflow）────────────────

def _detect_doc_type(step: dict) -> Optional[str]:
    """从步骤描述自动检测落盘文档类型。

    Args:
        step: 步骤字典

    Returns:
        'requirement' | 'design' | 'review' | None
    """
    desc = step.get("desc", "").lower()
    if any(k in desc for k in ["需求", "requirement", "理解需求", "分析需求"]):
        return "requirement"
    if any(k in desc for k in ["设计", "design", "方案", "架构"]):
        return "design"
    if any(k in desc for k in ["审查", "review", "检查代码", "代码检查", "代码审查"]):
        return "review"
    return None


_DOC_NAME_MAP = {
    "requirement": "需求理解.md",
    "design": "方案设计.md",
    "review": "代码审查.md",
}


def _auto_save_doc(step: dict, plan: dict, cwd: str) -> Optional[str]:
    """步骤成功完成后，自动将产物追加写入 docs/ 目录。

    规则（对齐 best-skills/dev-workflow）：
    - 需求理解 → docs/{module}/需求理解.md
    - 方案设计 → docs/{module}/方案设计.md
    - 代码审查 → docs/{module}/代码审查.md
    - 未指定 module 时回退到 docs/ 根目录
    - 文件不存在则创建，存在则追加
    - 每次写入带时间戳标题：## YYYY-MM-DD HH:mm
    - 末尾加分隔线 ---

    Args:
        step: 已完成的步骤字典
        plan: 所属计划字典
        cwd: 工作目录

    Returns:
        写入的文件路径，不适用时返回 None
    """
    import os as _os
    import json as _json
    from datetime import datetime as _datetime

    # 优先用显式 doc_type，否则自动检测
    doc_type = step.get("doc_type") or _detect_doc_type(step)
    if not doc_type:
        return None

    doc_name = _DOC_NAME_MAP.get(doc_type)
    if not doc_name:
        return None

    doc_module = step.get("doc_module", "")
    if doc_module:
        doc_dir = _os.path.join(cwd, "docs", doc_module)
    else:
        doc_dir = _os.path.join(cwd, "docs")

    _os.makedirs(doc_dir, exist_ok=True)
    doc_path = _os.path.join(doc_dir, doc_name)

    # 组装内容
    now = _datetime.now()
    lines = [
        f"## {now.strftime('%Y-%m-%d %H:%M')}",
        "",
        f"**计划**: {plan.get('goal', '')[:120]}",
        f"**步骤**: {step.get('desc', '')}",
        "",
    ]

    # 显式 doc_content 优先，否则提取 result
    doc_content = step.get("doc_content", "")
    if doc_content:
        lines.append(doc_content.strip())
    else:
        result = step.get("result", {})
        if isinstance(result, dict):
            ok_flag = "✅" if result.get("ok") else "❌"
            summary = result.get("summary", result.get("error", _json.dumps(result, indent=2, ensure_ascii=False)))
            lines.append(f"**结果**: {ok_flag} {summary}")
        elif isinstance(result, str):
            lines.append(result)

    lines.append("\n---\n")
    content = "\n".join(lines)

    with open(doc_path, "a", encoding="utf-8") as f:
        f.write(content)

    # 可选：维护模块索引
    if doc_module:
        _update_module_index(cwd, doc_module, doc_type, doc_path)

    return doc_path


def _update_module_index(cwd: str, module: str, doc_type: str, doc_path: str):
    """维护 docs/模块索引.md，记录模块→文档路径映射。

    Args:
        cwd: 工作目录
        module: 模块名
        doc_type: 文档类型
        doc_path: 文档路径
    """
    try:
        import os as _os
        index_path = _os.path.join(cwd, "docs", "模块索引.md")
        entry = f"- **{module}** → [{doc_type}]({_os.path.relpath(doc_path, _os.path.dirname(index_path))})"
        existing = ""
        if _os.path.exists(index_path):
            with open(index_path, "r", encoding="utf-8") as f:
                existing = f.read()
        if entry not in existing:
            with open(index_path, "a", encoding="utf-8") as f:
                f.write(f"{entry}\n")
    except Exception:
        pass  # 索引更新失败不影响主流程


# ── 智能分解 ────────────────────────────────────────────

def _decompose_goal(goal: str, cwd: str) -> dict:
    """智能分解目标为可执行步骤。
    
    分析目标，自动生成步骤列表，考虑依赖关系。
    
    Args:
        goal: 目标描述
        cwd: 当前工作目录
        
    Returns:
        分解结果，包含建议的步骤列表
    """
    import re
    
    # 分析目标类型
    goal_lower = goal.lower()
    
    # 检测关键词，确定任务类型
    task_types = []
    if any(k in goal_lower for k in ["修复", "fix", "bug", "错误", "问题"]):
        task_types.append("bugfix")
    if any(k in goal_lower for k in ["添加", "add", "新增", "实现", "implement", "功能"]):
        task_types.append("feature")
    if any(k in goal_lower for k in ["重构", "refactor", "优化", "optimize", "改进"]):
        task_types.append("refactor")
    if any(k in goal_lower for k in ["测试", "test", "验证"]):
        task_types.append("test")
    if any(k in goal_lower for k in ["文档", "doc", "readme", "说明"]):
        task_types.append("docs")
    if any(k in goal_lower for k in ["配置", "config", "设置", "setup"]):
        task_types.append("config")
    
    # 如果没有检测到类型，默认为通用任务
    if not task_types:
        task_types.append("general")
    
    # 根据任务类型生成步骤
    steps = []
    step_id = 1
    
    # 通用步骤：分析和规划
    steps.append({
        "id": str(step_id),
        "desc": "分析需求，理解目标",
        "action": "analyze",
        "params": {"goal": goal},
        "depends_on": [],
        "verify": "manual"
    })
    step_id += 1
    
    # 根据任务类型添加特定步骤
    if "bugfix" in task_types:
        steps.append({
            "id": str(step_id),
            "desc": "定位问题根源",
            "action": "investigate",
            "params": {"goal": goal},
            "depends_on": ["1"],
            "verify": "manual"
        })
        step_id += 1
        
        steps.append({
            "id": str(step_id),
            "desc": "实现修复方案",
            "action": "self_evolve",
            "params": {"goal": goal},
            "depends_on": [str(step_id - 1)],
            "verify": "py_compile"
        })
        step_id += 1
        
        steps.append({
            "id": str(step_id),
            "desc": "验证修复效果",
            "action": "verify",
            "params": {"goal": goal},
            "depends_on": [str(step_id - 1)],
            "verify": "test"
        })
        step_id += 1
    
    elif "feature" in task_types:
        steps.append({
            "id": str(step_id),
            "desc": "设计实现方案",
            "action": "design",
            "params": {"goal": goal},
            "depends_on": ["1"],
            "verify": "manual"
        })
        step_id += 1
        
        steps.append({
            "id": str(step_id),
            "desc": "实现核心功能",
            "action": "self_evolve",
            "params": {"goal": goal},
            "depends_on": [str(step_id - 1)],
            "verify": "py_compile"
        })
        step_id += 1
        
        steps.append({
            "id": str(step_id),
            "desc": "添加测试用例",
            "action": "self_evolve",
            "params": {"goal": f"为 {goal} 添加测试"},
            "depends_on": [str(step_id - 1)],
            "verify": "test"
        })
        step_id += 1
        
        steps.append({
            "id": str(step_id),
            "desc": "更新文档",
            "action": "self_evolve",
            "params": {"goal": f"更新文档：{goal}"},
            "depends_on": [str(step_id - 2)],
            "verify": "manual"
        })
        step_id += 1
    
    elif "refactor" in task_types:
        steps.append({
            "id": str(step_id),
            "desc": "分析现有代码结构",
            "action": "analyze",
            "params": {"goal": f"分析代码结构：{goal}"},
            "depends_on": ["1"],
            "verify": "manual"
        })
        step_id += 1
        
        steps.append({
            "id": str(step_id),
            "desc": "制定重构计划",
            "action": "design",
            "params": {"goal": goal},
            "depends_on": [str(step_id - 1)],
            "verify": "manual"
        })
        step_id += 1
        
        steps.append({
            "id": str(step_id),
            "desc": "执行重构",
            "action": "self_evolve",
            "params": {"goal": goal},
            "depends_on": [str(step_id - 1)],
            "verify": "py_compile"
        })
        step_id += 1
        
        steps.append({
            "id": str(step_id),
            "desc": "运行测试验证",
            "action": "verify",
            "params": {"goal": "验证重构后功能正常"},
            "depends_on": [str(step_id - 1)],
            "verify": "test"
        })
        step_id += 1
    
    elif "test" in task_types:
        steps.append({
            "id": str(step_id),
            "desc": "分析测试需求",
            "action": "analyze",
            "params": {"goal": goal},
            "depends_on": ["1"],
            "verify": "manual"
        })
        step_id += 1
        
        steps.append({
            "id": str(step_id),
            "desc": "编写测试用例",
            "action": "self_evolve",
            "params": {"goal": goal},
            "depends_on": [str(step_id - 1)],
            "verify": "py_compile"
        })
        step_id += 1
        
        steps.append({
            "id": str(step_id),
            "desc": "运行测试验证",
            "action": "verify",
            "params": {"goal": "运行测试"},
            "depends_on": [str(step_id - 1)],
            "verify": "test"
        })
        step_id += 1
    
    elif "docs" in task_types:
        steps.append({
            "id": str(step_id),
            "desc": "分析文档需求",
            "action": "analyze",
            "params": {"goal": goal},
            "depends_on": ["1"],
            "verify": "manual"
        })
        step_id += 1
        
        steps.append({
            "id": str(step_id),
            "desc": "编写文档",
            "action": "self_evolve",
            "params": {"goal": goal},
            "depends_on": [str(step_id - 1)],
            "verify": "manual"
        })
        step_id += 1
    
    elif "config" in task_types:
        steps.append({
            "id": str(step_id),
            "desc": "分析配置需求",
            "action": "analyze",
            "params": {"goal": goal},
            "depends_on": ["1"],
            "verify": "manual"
        })
        step_id += 1
        
        steps.append({
            "id": str(step_id),
            "desc": "修改配置",
            "action": "self_evolve",
            "params": {"goal": goal},
            "depends_on": [str(step_id - 1)],
            "verify": "py_compile"
        })
        step_id += 1
        
        steps.append({
            "id": str(step_id),
            "desc": "验证配置生效",
            "action": "verify",
            "params": {"goal": "验证配置"},
            "depends_on": [str(step_id - 1)],
            "verify": "test"
        })
        step_id += 1
    
    else:  # general
        steps.append({
            "id": str(step_id),
            "desc": "制定实现方案",
            "action": "design",
            "params": {"goal": goal},
            "depends_on": ["1"],
            "verify": "manual"
        })
        step_id += 1
        
        steps.append({
            "id": str(step_id),
            "desc": "执行实现",
            "action": "self_evolve",
            "params": {"goal": goal},
            "depends_on": [str(step_id - 1)],
            "verify": "py_compile"
        })
        step_id += 1
        
        steps.append({
            "id": str(step_id),
            "desc": "验证结果",
            "action": "verify",
            "params": {"goal": "验证实现"},
            "depends_on": [str(step_id - 1)],
            "verify": "test"
        })
        step_id += 1
    
    # 创建计划
    plan = _new_plan(goal, steps)
    _save_plan(plan)
    
    return {
        "ok": True,
        "plan_id": plan["id"],
        "goal": goal,
        "task_types": task_types,
        "total_steps": len(steps),
        "steps": [{"id": s["id"], "desc": s["desc"], "depends_on": s["depends_on"]} for s in steps],
        "hint": f"已创建计划，使用 action='run' plan_id='{plan['id']}' 执行全部步骤",
    }

# ── Meta ────────────────────────────────────────────────

def meta_toolkit_plan():
    """Meta toolkit plan."""
    return {
        "type": "function",
        "function": {
            "name": "toolkit_plan",
            "description": "Plandex 风格 Plan→Execute→Verify 三步工作流。create=创建计划, decompose=智能分解目标, show=查看, review=画布审阅(不修改文件), canvas=创建空白画布, step=执行下一步, verify=验证, run=全量执行, resume=恢复, list=列表, delete=删除。动态规划: insert=插入步骤, replace=替换步骤, delete_step=删除步骤, replan=重新规划。",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["create", "decompose", "show", "review", "canvas", "step", "verify", "run", "resume", "list", "delete", "insert", "replace", "delete_step", "replan"]},
                    "goal": {"type": "string", "description": "[create] 计划目标"},
                    "steps": {"type": "array", "items": {"type": "object"}, "description": "[create] 步骤列表"},
                    "plan_id": {"type": "string", "description": "[show/step/verify/run/resume/delete] 计划ID"},
                    "step_id": {"type": "string", "description": "[step/verify] 指定步骤ID"},
                },
                "required": ["action"],
            },
        },
    }


# ── 动态规划操作 ──────────────────────────────────────────

def _insert_step(plan_id: str, after_step_id: str, new_steps: list) -> dict:
    """在指定步骤后插入新步骤。
    
    Args:
        plan_id: 计划ID
        after_step_id: 在此步骤后插入，None 则插入到开头
        new_steps: 要插入的步骤列表
        
    Returns:
        操作结果
    """
    if not plan_id or not new_steps:
        return {"ok": False, "error": "insert 需要 plan_id 和 steps 参数"}
    
    plan = _load_plan(plan_id)
    if not plan:
        return {"ok": False, "error": f"计划不存在: {plan_id}"}
    
    # 找到插入位置
    insert_idx = 0
    if after_step_id:
        for i, s in enumerate(plan["steps"]):
            if s["id"] == after_step_id:
                insert_idx = i + 1
                break
        else:
            return {"ok": False, "error": f"步骤不存在: {after_step_id}"}
    
    # 生成新步骤ID
    existing_ids = {s["id"] for s in plan["steps"]}
    next_id = max(int(s["id"]) for s in plan["steps"]) + 1 if plan["steps"] else 1
    
    # 构建新步骤
    normalized = []
    for ns in new_steps:
        while str(next_id) in existing_ids:
            next_id += 1
        step = {
            "id": ns.get("id", str(next_id)),
            "desc": ns["desc"],
            "action": ns.get("action", "self_evolve"),
            "params": ns.get("params", {}),
            "depends_on": ns.get("depends_on", []),
            "verify": ns.get("verify", "py_compile"),
            "status": "pending",
            "result": None,
            "started_at": None,
            "finished_at": None,
        }
        normalized.append(step)
        existing_ids.add(step["id"])
        next_id += 1
    
    # 插入
    plan["steps"] = plan["steps"][:insert_idx] + normalized + plan["steps"][insert_idx:]
    _save_plan(plan)
    
    return {
        "ok": True,
        "plan_id": plan_id,
        "inserted": [s["id"] for s in normalized],
        "total_steps": len(plan["steps"]),
        "progress": f"{_count_status(plan, 'done')}/{len(plan['steps'])}",
    }


def _replace_step(plan_id: str, step_id: str, new_steps: list) -> dict:
    """替换指定步骤。
    
    Args:
        plan_id: 计划ID
        step_id: 要替换的步骤ID
        new_steps: 替换后的步骤列表（1个或多个）
        
    Returns:
        操作结果
    """
    if not plan_id or not step_id or not new_steps:
        return {"ok": False, "error": "replace 需要 plan_id, step_id 和 steps 参数"}
    
    plan = _load_plan(plan_id)
    if not plan:
        return {"ok": False, "error": f"计划不存在: {plan_id}"}
    
    # 找到要替换的步骤
    replace_idx = None
    old_step = None
    for i, s in enumerate(plan["steps"]):
        if s["id"] == step_id:
            replace_idx = i
            old_step = s
            break
    
    if replace_idx is None:
        return {"ok": False, "error": f"步骤不存在: {step_id}"}
    
    # 检查是否已完成
    if old_step["status"] == "done":
        return {"ok": False, "error": f"步骤已完成，不能替换: {step_id}"}
    
    # 生成新步骤
    existing_ids = {s["id"] for s in plan["steps"]}
    next_id = max(int(s["id"]) for s in plan["steps"]) + 1
    
    normalized = []
    for ns in new_steps:
        while str(next_id) in existing_ids:
            next_id += 1
        step = {
            "id": ns.get("id", str(next_id)),
            "desc": ns["desc"],
            "action": ns.get("action", "self_evolve"),
            "params": ns.get("params", {}),
            "depends_on": ns.get("depends_on", old_step.get("depends_on", [])),
            "verify": ns.get("verify", "py_compile"),
            "status": "pending",
            "result": None,
            "started_at": None,
            "finished_at": None,
        }
        normalized.append(step)
        existing_ids.add(step["id"])
        next_id += 1
    
    # 替换
    plan["steps"] = plan["steps"][:replace_idx] + normalized + plan["steps"][replace_idx+1:]
    
    # 更新依赖：将其他步骤对旧步骤的依赖改为新步骤
    new_ids = [s["id"] for s in normalized]
    for s in plan["steps"]:
        if step_id in s.get("depends_on", []):
            s["depends_on"] = [new_ids[0] if d == step_id else d for d in s["depends_on"]]
    
    _save_plan(plan)
    
    return {
        "ok": True,
        "plan_id": plan_id,
        "replaced": step_id,
        "with": new_ids,
        "total_steps": len(plan["steps"]),
        "progress": f"{_count_status(plan, 'done')}/{len(plan['steps'])}",
    }


def _delete_step(plan_id: str, step_id: str) -> dict:
    """删除指定步骤。
    
    Args:
        plan_id: 计划ID
        step_id: 要删除的步骤ID
        
    Returns:
        操作结果
    """
    if not plan_id or not step_id:
        return {"ok": False, "error": "delete_step 需要 plan_id 和 step_id"}
    
    plan = _load_plan(plan_id)
    if not plan:
        return {"ok": False, "error": f"计划不存在: {plan_id}"}
    
    # 找到要删除的步骤
    target = None
    for s in plan["steps"]:
        if s["id"] == step_id:
            target = s
            break
    
    if not target:
        return {"ok": False, "error": f"步骤不存在: {step_id}"}
    
    # 检查是否已完成
    if target["status"] == "done":
        return {"ok": False, "error": f"步骤已完成，不能删除: {step_id}"}
    
    # 检查是否有其他步骤依赖此步骤
    dependents = [s["id"] for s in plan["steps"] if step_id in s.get("depends_on", [])]
    if dependents:
        return {"ok": False, "error": f"步骤 {step_id} 被依赖: {dependents}，请先修改依赖关系"}
    
    # 删除
    plan["steps"] = [s for s in plan["steps"] if s["id"] != step_id]
    _save_plan(plan)
    
    return {
        "ok": True,
        "plan_id": plan_id,
        "deleted": step_id,
        "total_steps": len(plan["steps"]),
        "progress": f"{_count_status(plan, 'done')}/{len(plan['steps'])}",
    }


def _replan(plan_id: str, new_steps: list, cwd: str) -> dict:
    """基于当前状态重新规划。
    
    保留已完成的步骤，用新步骤替换未完成的步骤。
    
    Args:
        plan_id: 计划ID
        new_steps: 新的步骤列表
        cwd: 当前工作目录
        
    Returns:
        操作结果
    """
    if not plan_id or not new_steps:
        return {"ok": False, "error": "replan 需要 plan_id 和 steps 参数"}
    
    plan = _load_plan(plan_id)
    if not plan:
        return {"ok": False, "error": f"计划不存在: {plan_id}"}
    
    # 保留已完成的步骤
    done_steps = [s for s in plan["steps"] if s["status"] == "done"]
    
    # 生成新步骤
    existing_ids = {s["id"] for s in done_steps}
    next_id = max(int(s["id"]) for s in done_steps) + 1 if done_steps else 1
    
    normalized = []
    for ns in new_steps:
        while str(next_id) in existing_ids:
            next_id += 1
        step = {
            "id": ns.get("id", str(next_id)),
            "desc": ns["desc"],
            "action": ns.get("action", "self_evolve"),
            "params": ns.get("params", {}),
            "depends_on": ns.get("depends_on", []),
            "verify": ns.get("verify", "py_compile"),
            "status": "pending",
            "result": None,
            "started_at": None,
            "finished_at": None,
        }
        normalized.append(step)
        existing_ids.add(step["id"])
        next_id += 1
    
    # 更新计划
    plan["steps"] = done_steps + normalized
    plan["status"] = "running"
    _save_plan(plan)
    
    return {
        "ok": True,
        "plan_id": plan_id,
        "kept_done": len(done_steps),
        "added_new": len(normalized),
        "total_steps": len(plan["steps"]),
        "progress": f"{_count_status(plan, 'done')}/{len(plan['steps'])}",
    }
