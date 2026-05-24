import logging
import os
import json
import uuid
from typing import Optional, List
from datetime import datetime
from datetime import datetime
from tea_agent.toolkit.toolkit_plan import toolkit_plan

logger = logging.getLogger("toolkit")


_todos = []
_restored = False
_last_topic = None

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
    """
    确保 todo_items 表存在（兼容旧 DB 未迁移的情况）

    Args:
        db: Description.
    """
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
    """
    单条更新 DB

    Args:
        idx: Description.
        done: Description.
    """
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


def _todo_create(items):
    """
    Todo create.

    Args:
        items: Description.
    """
    if not items:
        return {"ok": False, "error": "create needs items"}
    _todos.clear()
    _todos.extend([{"desc": d, "done": False, "idx": i} for i, d in enumerate(items)])
    _sync_to_db()
    return {
        "ok": True, "total": len(_todos), "todo": _fmt(),
        "persisted": _get_topic_id() is not None,
    }


def _todo_check(index):
    """
    Todo check.

    Args:
        index: Description.
    """
    if index is None:
        return {"ok": False, "error": "check needs index"}
    if 0 <= index < len(_todos):
        _todos[index]["done"] = True
        _sync_item(index, True)
        return {
            "ok": True, "checked": _todos[index]["desc"],
            "progress": f"{_done()}/{len(_todos)}", "todo": _fmt(),
        }
    return {"ok": False, "error": f"index {index} out of range (0..{len(_todos)-1})"}


def _todo_show():
    """Todo show"""
    if not _todos:
        topic_id = _get_topic_id()
        return {"ok": True, "todo": "(empty)", "progress": "0/0",
                "topic_id": topic_id[:8] + "..." if topic_id else None}
    return {
        "ok": True, "todo": _fmt(),
        "progress": f"{_done()}/{len(_todos)}",
        "all_done": _done() == len(_todos),
        "topic_id": (_get_topic_id() or "")[:8] + "...",
    }


def _todo_clear():
    """Todo clear"""
    n = len(_todos)
    _todos.clear()
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


def _todo_restore():
    """Todo restore"""
    _restore_from_db()
    return {"ok": True, "todo": _fmt(), "progress": f"{_done()}/{len(_todos)}"}


def toolkit_todo(
    action: str,
    items: list = None,
    index: int = None,
    goal: str = None,
    steps: list = None,
    plan_id: str = None,
    step_id: str = None,
) -> dict:
    """
    TODO + Plan 统一规划工具。

    Args:
        action (str): Description.
        items (list): Description.
        index (int): Description.
        goal (str): Description.
        steps (list): Description.
        plan_id (str): Description.
        step_id (str): Description.

    Returns:
        dict: Description.
    """
    global _todos

    _auto_restore()

    try:
        handlers = {
            "create":       lambda: _todo_create(items),
            "check":        lambda: _todo_check(index),
            "show":         _todo_show,
            "clear":        _todo_clear,
            "restore":      _todo_restore,
            "plan_create":  lambda: _plan_create(items),
            "plan_show":    lambda: _plan_show(index),
            "plan_step":    lambda: _plan_step(index),
            "plan_run":     lambda: _plan_run(index),
            "plan_resume":  lambda: _plan_resume(index),
            "plan_verify":  lambda: _plan_verify(index),
            "plan_list":    _plan_list,
            "plan_delete":  lambda: _plan_delete(index),
        }
        handler = handlers.get(action)
        if handler is None:
            return {"ok": False, "error": f"unknown action: {action}"}
        return handler()

    except Exception as e:
        logger.exception("toolkit_todo")
        return {"ok": False, "error": str(e)[:300]}

def _done():
    """Internal: done"""
    return sum(1 for t in _todos if t["done"])

def _fmt():
    """Internal: fmt"""
    lines = []
    for t in _todos:
        icon = "DONE" if t["done"] else "TODO"
        lines.append(f"[{icon}] [{t['idx']}] {t['desc']}")
    return "\n".join(lines)





def _plan_create(steps_list):
    """
    从 steps 列表创建计划。steps_list[0] 为 goal，其余为步骤描述。

    Args:
        steps_list: Description.
    """
    if not steps_list or len(steps_list) < 2:
        return {"ok": False, "error": "plan_create: items[0]=goal, items[1:]=step descriptions"}
    goal = steps_list[0]
    step_dicts = []
    for i, desc in enumerate(steps_list[1:]):
        step_dicts.append({"id": str(i+1), "desc": desc})
    return _plan_create_inner(goal, step_dicts)

def _plan_show(plan_id):
    """
    Plan show.

    Args:
        plan_id: Description.
    """
    if plan_id is None:
        return {"ok": False, "error": "plan_show needs index (plan_id string)"}
    return _plan_show_inner(str(plan_id))

def _plan_step(plan_id):
    """
    Plan step.

    Args:
        plan_id: Description.
    """
    if plan_id is None:
        return {"ok": False, "error": "plan_step needs index (plan_id string)"}
    cwd = os.getcwd()
    return toolkit_plan("step", plan_id=str(plan_id), cwd=cwd)

def _plan_run(plan_id):
    """
    Plan run.

    Args:
        plan_id: Description.
    """
    if plan_id is None:
        return {"ok": False, "error": "plan_run needs index (plan_id string)"}
    cwd = os.getcwd()
    return toolkit_plan("run", plan_id=str(plan_id), cwd=cwd)

def _plan_resume(plan_id):
    """
    Plan resume.

    Args:
        plan_id: Description.
    """
    if plan_id is None:
        return {"ok": False, "error": "plan_resume needs index (plan_id string)"}
    cwd = os.getcwd()
    return toolkit_plan("resume", plan_id=str(plan_id), cwd=cwd)

def _plan_verify(plan_id):
    """
    Plan verify.

    Args:
        plan_id: Description.
    """
    cwd = os.getcwd()
    pid = str(plan_id) if plan_id else None
    if pid:
        return toolkit_plan("verify", plan_id=pid, cwd=cwd)
    else:
        results = []
        for p in _plan_list_inner():
            r = toolkit_plan("verify", plan_id=p["id"], cwd=cwd)
            results.append(r)
        return {"ok": True, "verified": len(results), "results": results}

def _plan_list():
    """Plan list"""
    return _plan_list_inner()

def _plan_delete(plan_id):
    """
    Plan delete.

    Args:
        plan_id: Description.
    """
    if plan_id is None:
        return {"ok": False, "error": "plan_delete needs index (plan_id string)"}
    return toolkit_plan("delete", plan_id=str(plan_id))

def _plan_create_inner(goal, step_dicts):
    """
    Plan create inner.

    Args:
        goal: Description.
        step_dicts: Description.
    """
    return toolkit_plan("create", goal=goal, steps=step_dicts)

def _plan_show_inner(plan_id):
    """
    Plan show inner.

    Args:
        plan_id: Description.
    """
    return toolkit_plan("show", plan_id=plan_id)

def _plan_list_inner():
    """Plan list inner"""
    result = toolkit_plan("list")
    if result.get("ok"):
        return result.get("plans", [])
    return []


def meta_toolkit_todo():
    """Meta toolkit todo"""
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


