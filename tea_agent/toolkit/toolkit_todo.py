import logging
from typing import Optional, List

logger = logging.getLogger("toolkit")


# ── 模块级缓存：快速读写，DB 仅做持久化 ──
_todos = []          # [{"desc":str, "done":bool, "idx":int}, ...]
_restored = False    # 是否已从 DB 恢复
_last_topic = None   # 上次操作的 topic_id, 用于检测主题切换

def _get_db():
    """获取当前 DB 连接（通过 session_ref → agent → db）"""
    try:
        from tea_agent.session_ref import get_agent
        agent = get_agent()
        if agent is not None and hasattr(agent, 'db'):
            return agent.db
    except Exception:
        pass
    return None

def _get_topic_id():
    """获取当前 topic_id"""
    try:
        from tea_agent.session_ref import get_agent
        agent = get_agent()
        if agent is not None:
            return getattr(agent, 'current_topic_id', None)
    except Exception:
        pass
    return None

def _ensure_table(db):
    """确保 todo_items 表存在（兼容旧 DB 未迁移的情况）"""
    try:
        c = db.conn.cursor()
        c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='todo_items'")
        if not c.fetchone():
            c.execute("""CREATE TABLE IF NOT EXISTS todo_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                topic_id TEXT NOT NULL,
                idx INTEGER NOT NULL,
                desc TEXT NOT NULL,
                done INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT (datetime('now', 'localtime')),
                FOREIGN KEY (topic_id) REFERENCES topics(topic_id)
            )""")
            db.conn.commit()
        c.close()
    except Exception as e:
        logger.warning(f"todo ensure_table failed: {e}")

def _sync_to_db():
    """将内存 _todos 全量写入 DB (DELETE + INSERT)"""
    global _last_topic
    topic_id = _get_topic_id()
    if not topic_id:
        return
    db = _get_db()
    if not db:
        return
    _ensure_table(db)
    try:
        c = db.conn.cursor()
        c.execute("DELETE FROM todo_items WHERE topic_id=?", (topic_id,))
        for t in _todos:
            c.execute(
                "INSERT INTO todo_items (topic_id, idx, desc, done) VALUES (?,?,?,?)",
                (topic_id, t["idx"], t["desc"], 1 if t["done"] else 0),
            )
        db.conn.commit()
        c.close()
        _last_topic = topic_id
    except Exception as e:
        logger.warning(f"todo sync to db failed: {e}")

def _sync_item(idx, done):
    """单条更新 DB"""
    topic_id = _get_topic_id()
    if not topic_id:
        return
    db = _get_db()
    if not db:
        return
    _ensure_table(db)
    try:
        c = db.conn.cursor()
        c.execute(
            "UPDATE todo_items SET done=? WHERE topic_id=? AND idx=?",
            (1 if done else 0, topic_id, idx),
        )
        db.conn.commit()
        c.close()
    except Exception as e:
        logger.warning(f"todo sync item failed: {e}")

def _restore_from_db():
    """从 DB 恢复当前 topic 的 TODO"""
    global _todos, _restored, _last_topic
    topic_id = _get_topic_id()
    if not topic_id:
        _restored = True
        return

    db = _get_db()
    if not db:
        _restored = True
        return

    _ensure_table(db)
    try:
        c = db.conn.cursor()
        c.execute(
            "SELECT idx, desc, done FROM todo_items WHERE topic_id=? ORDER BY idx ASC",
            (topic_id,),
        )
        rows = c.fetchall()
        c.close()

        if rows:
            _todos = [{"desc": r[1], "done": bool(r[2]), "idx": r[0]} for r in rows]
            _last_topic = topic_id
            logger.info(f"todo restored {len(_todos)} items for topic {topic_id[:8]}...")
        else:
            _todos = []
    except Exception as e:
        logger.warning(f"todo restore failed: {e}")
        _todos = []
    finally:
        _restored = True

def _auto_restore():
    """自动恢复（首次调用 + 主题切换时）"""
    global _restored, _last_topic, _todos
    topic_id = _get_topic_id()
    if not _restored or (topic_id and topic_id != _last_topic):
        _restore_from_db()

def toolkit_todo(
    action: str,
    items: list = None,
    index: int = None,
    goal: str = None,
    steps: list = None,
    plan_id: str = None,
    step_id: str = None,
) -> dict:
    """TODO + Plan 统一规划工具。
    Simple TODO: create/check/show/clear/restore (DB持久化 per-topic)。
    Plan 工作流: plan_create/plan_step/plan_run/plan_resume/plan_verify/plan_show/plan_list/plan_delete。
    """
    global _todos

    _auto_restore()

    try:
        if action == "create":
            if not items:
                return {"ok": False, "error": "create needs items"}
            _todos.clear()
            _todos.extend([{"desc": d, "done": False, "idx": i} for i, d in enumerate(items)])
            _sync_to_db()
            return {
                "ok": True,
                "total": len(_todos),
                "todo": _fmt(),
                "persisted": _get_topic_id() is not None,
            }

        elif action == "check":
            if index is None:
                return {"ok": False, "error": "check needs index"}
            if 0 <= index < len(_todos):
                _todos[index]["done"] = True
                _sync_item(index, True)
                return {
                    "ok": True,
                    "checked": _todos[index]["desc"],
                    "progress": f"{_done()}/{len(_todos)}",
                    "todo": _fmt(),
                }
            return {"ok": False, "error": f"index {index} out of range (0..{len(_todos)-1})"}

        elif action == "show":
            if not _todos:
                topic_id = _get_topic_id()
                return {
                    "ok": True,
                    "todo": "(empty)",
                    "progress": "0/0",
                    "topic_id": topic_id[:8] + "..." if topic_id else None,
                }
            all_done = _done() == len(_todos)
            topic_id = _get_topic_id()
            return {
                "ok": True,
                "todo": _fmt(),
                "progress": f"{_done()}/{len(_todos)}",
                "all_done": all_done,
                "topic_id": topic_id[:8] + "..." if topic_id else None,
            }

        elif action == "clear":
            n = len(_todos)
            _todos.clear()
            # 清除 DB 中当前 topic 的记录
            topic_id = _get_topic_id()
            if topic_id:
                db = _get_db()
                if db:
                    _ensure_table(db)
                    try:
                        c = db.conn.cursor()
                        c.execute("DELETE FROM todo_items WHERE topic_id=?", (topic_id,))
                        db.conn.commit()
                        c.close()
                    except Exception as e:
                        logger.warning(f"todo clear db failed: {e}")
            return {"ok": True, "msg": f"cleared {n} items"}

        elif action == "restore":
            _restore_from_db()
            return {"ok": True, "todo": _fmt(), "progress": f"{_done()}/{len(_todos)}"}

        # ── Plan 工作流 actions ──
        elif action == "plan_create":
            return _plan_create(items)
        elif action == "plan_show":
            return _plan_show(index)
        elif action == "plan_step":
            return _plan_step(index)
        elif action == "plan_run":
            return _plan_run(index)
        elif action == "plan_resume":
            return _plan_resume(index)
        elif action == "plan_verify":
            return _plan_verify(index)
        elif action == "plan_list":
            return _plan_list()
        elif action == "plan_delete":
            return _plan_delete(index)

        else:
            return {"ok": False, "error": f"unknown action: {action}"}

    except Exception as e:
        logger.exception("toolkit_todo")
        return {"ok": False, "error": str(e)[:300]}

def _done():
    """Internal: done."""
    return sum(1 for t in _todos if t["done"])

def _fmt():
    """Internal: fmt."""
    lines = []
    for t in _todos:
        icon = "DONE" if t["done"] else "TODO"
        lines.append(f"[{icon}] [{t['idx']}] {t['desc']}")
    return "\n".join(lines)



# ═══════════════════════════════════════════════════════════
# Plan 工作流 wrapper — 复用 toolkit_plan 的核心逻辑
# ═══════════════════════════════════════════════════════════

import os as _os_plan

def _plan_create(steps_list):
    """从 steps 列表创建计划。steps_list[0] 为 goal，其余为步骤描述。"""
    if not steps_list or len(steps_list) < 2:
        return {"ok": False, "error": "plan_create: items[0]=goal, items[1:]=step descriptions"}
    goal = steps_list[0]
    step_dicts = []
    for i, desc in enumerate(steps_list[1:]):
        step_dicts.append({"id": str(i+1), "desc": desc})
    return _plan_create_inner(goal, step_dicts)

def _plan_show(plan_id):
    if plan_id is None:
        return {"ok": False, "error": "plan_show needs index (plan_id string)"}
    return _plan_show_inner(str(plan_id))

def _plan_step(plan_id):
    if plan_id is None:
        return {"ok": False, "error": "plan_step needs index (plan_id string)"}
    cwd = _os_plan.getcwd()
    return toolkit_plan("step", plan_id=str(plan_id), cwd=cwd)

def _plan_run(plan_id):
    if plan_id is None:
        return {"ok": False, "error": "plan_run needs index (plan_id string)"}
    cwd = _os_plan.getcwd()
    return toolkit_plan("run", plan_id=str(plan_id), cwd=cwd)

def _plan_resume(plan_id):
    if plan_id is None:
        return {"ok": False, "error": "plan_resume needs index (plan_id string)"}
    cwd = _os_plan.getcwd()
    return toolkit_plan("resume", plan_id=str(plan_id), cwd=cwd)

def _plan_verify(plan_id):
    cwd = _os_plan.getcwd()
    pid = str(plan_id) if plan_id else None
    if pid:
        return toolkit_plan("verify", plan_id=pid, cwd=cwd)
    else:
        # verify all done plans
        results = []
        for p in _plan_list_inner():
            r = toolkit_plan("verify", plan_id=p["id"], cwd=cwd)
            results.append(r)
        return {"ok": True, "verified": len(results), "results": results}

def _plan_list():
    return _plan_list_inner()

def _plan_delete(plan_id):
    if plan_id is None:
        return {"ok": False, "error": "plan_delete needs index (plan_id string)"}
    return toolkit_plan("delete", plan_id=str(plan_id))

def _plan_create_inner(goal, step_dicts):
    return toolkit_plan("create", goal=goal, steps=step_dicts)

def _plan_show_inner(plan_id):
    return toolkit_plan("show", plan_id=plan_id)

def _plan_list_inner():
    result = toolkit_plan("list")
    if result.get("ok"):
        return result.get("plans", [])
    return []


def meta_toolkit_todo():
    """Meta toolkit todo."""
    return {
        "type": "function",
        "function": {
            "name": "toolkit_todo",
            "description": (
                "TODO + Plan 统一规划工具。Simple TODO: create/check/show/clear/restore。"
                "Plan工作流: plan_create/plan_step/plan_run/plan_resume/plan_verify/plan_show/plan_list/plan_delete。"
                "Plan 持久化到 .tea_agent_run/plans/，支持依赖、验证、断点续跑。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["create", "check", "show", "clear", "restore",
                                 "plan_create", "plan_show", "plan_step", "plan_run",
                                 "plan_verify", "plan_resume", "plan_list", "plan_delete"],
                        "description": "create/check/show/clear/restore=简易TODO; plan_*=Plan工作流",
                    },
                    "items": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "[create] 任务列表; [plan_create] goal+步骤描述",
                    },
                    "index": {
                        "type": "integer",
                        "description": "[check] 任务序号; [plan_show/step/run/resume/delete] plan_id",
                    },
                    "goal": {
                        "type": "string",
                        "description": "[plan_create] 计划目标（也可用 items[0] 传入）",
                    },
                    "steps": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": "[plan_create] 步骤列表 [{desc, action, depends_on, verify}]",
                    },
                    "plan_id": {
                        "type": "string",
                        "description": "[plan_show/step/run/resume/delete] 计划ID",
                    },
                    "step_id": {
                        "type": "string",
                        "description": "[plan_step/verify] 指定步骤ID",
                    },
                },
                "required": ["action"],
            },
        },
    }


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

_KNOWN_STEP_META = {"id", "desc", "action", "depends_on", "verify", "params"}

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
