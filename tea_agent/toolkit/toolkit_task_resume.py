## llm generated tool func, created Tue Jun  2 07:10:58 2026
# version: 1.0.0

"""自动恢复机制 - 检查并恢复未完成的 TODO/Plan，含 docs/ 产物对照"""

import json
import logging
import os
import re
from datetime import datetime

logger = logging.getLogger("toolkit")

def _get_topic_id() -> str | None:
    """获取当前 topic_id"""
    try:
        from tea_agent.session_ref import get_agent
        agent = get_agent()
        if agent is not None:
            return getattr(agent, 'current_topic_id', None)
    except Exception:
        logger.exception("operation failed")

    return None

def _get_pending_todos() -> list[dict]:
    """获取当前主题未完成的 TODO 项"""
    try:
        from tea_agent.session_ref import get_agent
        agent = get_agent()
        if agent is None or not hasattr(agent, 'db'):
            return []

        db = agent.db
        topic_id = _get_topic_id()
        if not topic_id:
            return []

        c = db.conn.cursor()
        c.execute("""
            SELECT idx, desc, done FROM todo_items
            WHERE topic_id=? AND done=0
            ORDER BY idx ASC
        """, (topic_id,))
        rows = c.fetchall()
        c.close()

        return [{"idx": r[0], "desc": r[1]} for r in rows]
    except Exception as e:
        logger.debug(f"check pending todos failed: {e}")
        return []

def _get_pending_plans() -> list[dict]:
    """获取当前主题未完成的 Plan"""
    try:
        import json
        import os

        plans_dir = ".tea_agent_run/plans"
        if not os.path.exists(plans_dir):
            return []

        topic_id = _get_topic_id()
        if not topic_id:
            return []

        pending = []
        for fname in os.listdir(plans_dir):
            if not fname.endswith(".json"):
                continue
            try:
                path = os.path.join(plans_dir, fname)
                with open(path, encoding="utf-8") as f:
                    plan = json.load(f)

                # 检查是否关联到当前主题
                if plan.get("topic_id") != topic_id:
                    continue

                # 检查是否有未完成的步骤
                total = len(plan.get("steps", []))
                done = sum(1 for s in plan.get("steps", []) if s.get("status") == "done")

                if done < total:
                    pending.append({
                        "plan_id": plan["id"],
                        "goal": plan.get("goal", "")[:60],
                        "progress": f"{done}/{total}",
                        "status": plan.get("status", "unknown"),
                    })
            except Exception:
                continue

        return pending
    except Exception as e:
        logger.debug(f"check pending plans failed: {e}")
        return []

# ── docs/ 产物扫描与对照 ─────────────────────────────────

_DOC_TYPE_FILENAME_MAP = {
    "需求理解.md": "requirement",
    "方案设计.md": "design",
    "代码审查.md": "review",
}


def _scan_docs_dir(cwd: str = ".") -> list[dict]:
    """扫描 docs/ 目录，返回已有落盘产物清单。

    遍历 docs/ 及其子目录（模块目录），统计每个 .md 文件的条目数，
    条目以 '## YYYY-MM-DD' 级标题为分界。

    Returns:
        [{"path": "docs/需求理解.md", "type": "requirement", "module": "",
          "entries": 3, "size": 1024, "updated": "2026-06-06T07:46:00"}, ...]
    """
    docs_dir = os.path.join(cwd, "docs")
    if not os.path.exists(docs_dir):
        return []

    results = []
    for root, _dirs, files in os.walk(docs_dir):
        for fname in files:
            if not fname.endswith(".md"):
                continue
            full = os.path.join(root, fname)
            try:
                with open(full, encoding="utf-8") as fh:
                    content = fh.read()
            except Exception:
                continue

            # 按 ## YYYY-MM-DD 统计条目
            entries = len(re.findall(r'^## \d{4}-\d{2}-\d{2}', content, re.MULTILINE))
            if entries == 0:
                entries = 1  # 至少算 1 条非空文档

            doc_type = _DOC_TYPE_FILENAME_MAP.get(fname, "")
            rel_path = os.path.relpath(full, docs_dir)
            module = os.path.dirname(rel_path) if os.path.dirname(rel_path) else ""

            results.append({
                "path": os.path.relpath(full, cwd).replace("\\", "/"),
                "type": doc_type,
                "module": module or "",
                "entries": entries,
                "size": os.path.getsize(full),
                "updated": datetime.fromtimestamp(os.path.getmtime(full)).strftime("%Y-%m-%d %H:%M"),
            })

    return results


def _get_all_plans_for_topic() -> list[dict]:
    """获取当前主题的所有 Plan（含已完成和未完成）。

    Returns:
        [{"plan_id": "...", "goal": "...", "status": "...",
          "progress": "2/3", "steps": [...]}, ...]
    """
    plans_dir = ".tea_agent_run/plans"
    if not os.path.exists(plans_dir):
        return []

    topic_id = _get_topic_id()
    results = []
    for fname in sorted(os.listdir(plans_dir)):
        if not fname.endswith(".json"):
            continue
        try:
            path = os.path.join(plans_dir, fname)
            with open(path, encoding="utf-8") as f:
                plan = json.load(f)
            if topic_id and plan.get("topic_id") != topic_id:
                continue
            steps = plan.get("steps", [])
            total = len(steps)
            done = sum(1 for s in steps if s.get("status") == "done")
            results.append({
                "plan_id": plan["id"],
                "goal": plan.get("goal", "")[:80],
                "status": plan.get("status", "unknown"),
                "progress": f"{done}/{total}",
                "steps": [
                    {
                        "id": s["id"],
                        "desc": s.get("desc", ""),
                        "status": s.get("status", "pending"),
                        "doc_type": s.get("doc_type", ""),
                        "doc_saved": s.get("doc_saved", ""),
                    }
                    for s in steps
                ],
            })
        except Exception:
            continue
    return results


def _cross_check_docs_plans(cwd: str = ".") -> dict:
    """交叉对照 docs/ 产物与 Plan 状态。

    双向检查：
      1. 计划步骤有 doc_type 但 docs/ 无对应条目 → "未落实"
      2. docs/ 有产物但找不到关联计划 → "孤儿文档"
      3. 计划未完成但 docs/ 已有部分产物 → "部分落实"

    Returns:
        {
            "docs_count": 3,
            "plans_count": 2,
            "pending_plans": [...],
            "orphan_docs": [...],
            "unfulfilled_steps": [...],
            "healthy": True/False,
        }
    """
    docs = _scan_docs_dir(cwd)
    plans = _get_all_plans_for_topic()

    # 1. 未完成的 Plan
    pending_plans = [p for p in plans if p["status"] not in ("done",)]

    # 2. 计划步骤中标记了 doc_saved 但文件不存在的 → 未落实
    unfulfilled = []
    doc_paths_set = {d["path"] for d in docs}
    for p in plans:
        for s in p["steps"]:
            saved = s.get("doc_saved", "")
            if saved:
                saved_rel = os.path.relpath(saved, cwd).replace("\\", "/")
                if saved_rel not in doc_paths_set and s["status"] == "done":
                    unfulfilled.append({
                        "plan_id": p["plan_id"],
                        "step_id": s["id"],
                        "step_desc": s["desc"],
                        "doc_type": s.get("doc_type", ""),
                        "expected_path": saved_rel,
                    })

    # 3. 计划步骤有 doc_type 但未设置 doc_saved → 计划未执行到落盘
    doc_planned_steps = []
    for p in plans:
        for s in p["steps"]:
            if s.get("doc_type") and not s.get("doc_saved") and s["status"] == "pending":
                doc_planned_steps.append({
                    "plan_id": p["plan_id"],
                    "step_id": s["id"],
                    "step_desc": s["desc"],
                    "doc_type": s["doc_type"],
                })

    # 4. docs/ 有产物但无关联计划 → 孤儿文档
    orphan_docs = []
    all_doc_saved = set()
    for p in plans:
        for s in p["steps"]:
            saved = s.get("doc_saved", "")
            if saved:
                all_doc_saved.add(os.path.relpath(saved, cwd).replace("\\", "/"))

    for d in docs:
        if d["path"] not in all_doc_saved:
            orphan_docs.append(d)

    healthy = not pending_plans and not unfulfilled and not orphan_docs and not doc_planned_steps

    return {
        "docs_count": len(docs),
        "plans_count": len(plans),
        "pending_plans": pending_plans,
        "orphan_docs": orphan_docs,
        "unfulfilled_steps": unfulfilled,
        "doc_planned_steps": doc_planned_steps,
        "healthy": healthy,
    }


def toolkit_task_resume(action: str = "check", plan_id: str = None) -> dict:
    """检查当前主题未完成的 TODO 和 Plan，返回恢复提示。

    对话开始时自动调用，或用户主动询问时调用。
    """
    try:
        if action == "check":
            todos = _get_pending_todos()
            plans = _get_pending_plans()
            cross = _cross_check_docs_plans()

            # 构建提示
            hints = []

            if todos:
                hints.append(f"有 {len(todos)} 个未完成的 TODO 项")
            if plans:
                hints.append(f"有 {len(plans)} 个未完成的 Plan")

            if cross["docs_count"] > 0:
                hints.append(f"docs/ 有 {cross['docs_count']} 个落盘文档")
            if cross["orphan_docs"]:
                hints.append(f"{len(cross['orphan_docs'])} 个孤儿文档（有文档无计划）")
            if cross["unfulfilled_steps"]:
                hints.append(f"{len(cross['unfulfilled_steps'])} 个步骤标记落盘但文件缺失")
            if cross["doc_planned_steps"]:
                hints.append(f"{len(cross['doc_planned_steps'])} 个步骤有待落盘")

            # 无任何任务
            if not todos and not plans and cross["docs_count"] == 0:
                return {
                    "ok": True,
                    "has_pending": False,
                    "docs": {"count": 0, "files": []},
                    "cross_check": cross,
                    "message": "当前主题没有未完成的任务，docs/ 也无产物",
                }

            has_pending = bool(todos) or bool(plans) or bool(cross["orphan_docs"]) or bool(cross["unfulfilled_steps"])

            return {
                "ok": True,
                "has_pending": has_pending,
                "pending_todos": todos,
                "pending_plans": plans,
                "docs": {
                    "count": cross["docs_count"],
                    "files": _scan_docs_dir(),
                },
                "cross_check": cross,
                "hint": "；".join(hints) + ("。" if hints else ""),
            }

        elif action == "resume_todo":
            # 恢复 TODO 执行
            from tea_agent.toolkit.toolkit_todo import toolkit_todo
            return toolkit_todo(action="show")

        elif action == "resume_plan":
            if not plan_id:
                return {"ok": False, "error": "resume_plan 需要 plan_id"}
            from tea_agent.toolkit.toolkit_plan import toolkit_plan
            return toolkit_plan(action="show", plan_id=plan_id)

        else:
            return {"ok": False, "error": f"未知 action: {action}"}

    except Exception as e:
        logger.exception("toolkit_task_resume")
        return {"ok": False, "error": str(e)[:200]}


def meta_toolkit_task_resume() -> dict:
    """Meta toolkit task resume."""
    return {
        "type": "function",
        "function": {
            "name": "toolkit_task_resume",
            "description": "检查当前主题未完成的 TODO 和 Plan，扫描 docs/ 产物并进行交叉对照（孤儿文档/未落实步骤/待落盘步骤），返回恢复提示。对话开始时自动调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["check", "resume_todo", "resume_plan"],
                        "description": "check=检查未完成任务, resume_todo=恢复TODO执行, resume_plan=恢复Plan执行"
                    },
                    "plan_id": {
                        "type": "string",
                        "description": "[resume_plan] 计划ID"
                    }
                },
                "required": ["action"]
            }
        }
    }

