## llm generated tool func, created Tue Jun  2 07:10:58 2026
# version: 1.0.0

"""自动恢复机制 - 检查并恢复未完成的 TODO/Plan"""

import logging
from typing import Dict, Optional, List

logger = logging.getLogger("toolkit")

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

def _get_pending_todos() -> List[Dict]:
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

def _get_pending_plans() -> List[Dict]:
    """获取当前主题未完成的 Plan"""
    try:
        import os
        import json
        
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
                with open(path, "r", encoding="utf-8") as f:
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

def toolkit_task_resume(action: str = "check", plan_id: str = None) -> dict:
    """检查当前主题未完成的 TODO 和 Plan，返回恢复提示。
    
    对话开始时自动调用，或用户主动询问时调用。
    """
    try:
        if action == "check":
            todos = _get_pending_todos()
            plans = _get_pending_plans()
            
            if not todos and not plans:
                return {
                    "ok": True,
                    "has_pending": False,
                    "message": "当前主题没有未完成的任务"
                }
            
            result = {
                "ok": True,
                "has_pending": True,
                "pending_todos": todos,
                "pending_plans": plans,
            }
            
            # 生成恢复提示
            hints = []
            if todos:
                hints.append(f"有 {len(todos)} 个未完成的 TODO 项")
            if plans:
                hints.append(f"有 {len(plans)} 个未完成的 Plan")
            
            result["hint"] = "；".join(hints) + "。是否继续执行？"
            
            return result
        
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
            "description": "检查当前主题未完成的 TODO 和 Plan，返回恢复提示。对话开始时自动调用。",
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


def meta_toolkit_task_resume() -> dict:
    return {"type": "function", "function": {"name": "toolkit_task_resume", "description": "检查当前主题未完成的 TODO 和 Plan，返回恢复提示。对话开始时自动调用。", "parameters": {"type": "object", "properties": {"action": {"type": "string", "enum": ["check", "resume_todo", "resume_plan"], "description": "check=检查未完成任务, resume_todo=恢复TODO执行, resume_plan=恢复Plan执行"}, "plan_id": {"type": "string", "description": "[resume_plan] 计划ID"}}, "required": ["action"]}}}
