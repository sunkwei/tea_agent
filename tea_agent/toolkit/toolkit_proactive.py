# version: 1.0.1

# version: 1.0.1

import logging

logger = logging.getLogger("toolkit")

def toolkit_proactive(action: str, content: str = "", priority: int = 2, goal_id: int = None):
    """Agent 自主心跳系统"""
    logger.info(f"toolkit_proactive called: action={action!r}, content={repr(content)[:80]}, priority={priority!r}, goal_id={goal_id!r}")


    try:
        if action == "check":
            return _check_proactive()
        elif action == "goal":
            return _add_goal(content, priority)
        elif action == "done":
            return _complete_goal(goal_id)
        elif action == "list_goals":
            return _list_goals()
        else:
            return {"ok": False, "error": f"未知 action: {action}", "returncode": 1}
    except Exception as e:
        return {"ok": False, "error": f"自主心跳出错: {e}", "returncode": 1}

def _get_memory_manager():
    """Internal: get the memory manager."""
    from tea_agent.memory import MemoryManager
    from tea_agent.store import Storage
    storage = Storage()
    return MemoryManager(storage, extraction_threshold=1, dedup_threshold=0.3)

def _check_proactive():
    """Internal: check proactive."""
    import json
    try:
        mm = _get_memory_manager()
        all_mems = mm.storage.get_active_memories(limit=100)

        goals = []
        insights = []
        for m in all_mems:
            tags = (m.get("tags") or "").lower()
            cat = (m.get("category") or "")
            if "goal" in tags or cat == "reminder":
                goals.append(m)
            elif "insight" in tags:
                insights.append(m)

        report = {
            "pending_goals": len(goals),
            "pending_insights": len(insights),
            "goals": [],
            "insights": [],
            "suggestion": "",
        }

        for g in sorted(goals, key=lambda x: x.get("priority", 2))[:5]:
            report["goals"].append({
                "id": g["id"],
                "content": g["content"],
                "priority": g.get("priority", 2),
                "category": g.get("category", ""),
            })

        for ins in insights[:3]:
            report["insights"].append({
                "id": ins["id"],
                "content": ins["content"][:120],
            })

        if not goals and not insights:
            report["suggestion"] = "无待办目标。建议：反思当前会话，设定下一步进化方向。"
        elif goals:
            top = goals[0]
            report["suggestion"] = f"最高优先级待办: {top['content'][:80]}"

        return {"ok": True, "report": report, "returncode": 0}
    except Exception as e:
        return {"ok": False, "error": f"检查失败: {e}", "returncode": 1}

def _add_goal(content: str, priority: int = 2):
    """Internal: add goal.

    Args:
        content: Description.
        priority: Description.
    """
    import json
    if not content or not content.strip():
        return {"ok": False, "error": "目标内容不能为空", "returncode": 1}
    priority = max(0, min(3, priority))
    try:
        mm = _get_memory_manager()
        mm.storage.add_memory(
            content=content.strip(),
            category="reminder",
            priority=priority,
            importance=4,
            tags="goal,proactive",
        )
        return {"ok": True, "status": "已设定", "content": content.strip(), "returncode": 0}
    except Exception as e:
        return {"ok": False, "error": f"设定目标失败: {e}", "returncode": 1}

def _complete_goal(goal_id: int):
    """Internal: complete goal.

    Args:
        goal_id: Description.
    """
    import json
    if not goal_id:
        return {"ok": False, "error": "需要提供 goal_id", "returncode": 1}
    try:
        mm = _get_memory_manager()
        mm.storage.delete_memory(goal_id)
        return {"ok": True, "status": "已完成", "id": goal_id, "returncode": 0}
    except Exception as e:
        return {"ok": False, "error": f"完成目标失败: {e}", "returncode": 1}

def _list_goals():
    """Internal: list goals."""
    import json
    try:
        mm = _get_memory_manager()
        all_mems = mm.storage.get_active_memories(limit=100)
        goals = []
        for m in all_mems:
            tags = (m.get("tags") or "").lower()
            cat = (m.get("category") or "")
            if "goal" in tags or cat == "reminder":
                goals.append({
                    "id": m["id"],
                    "content": m["content"],
                    "priority": m.get("priority", 2),
                    "importance": m.get("importance", 3),
                    "created": m.get("created_at", ""),
                })
        goals.sort(key=lambda x: x["priority"])
        return {"ok": True, "goals": goals, "returncode": 0}
    except Exception as e:
        return {"ok": False, "error": f"列出目标失败: {e}", "returncode": 1}

def meta_toolkit_proactive() -> dict:
    return {"type": "function", "function": {"name": "toolkit_proactive", "description": "自主心跳：Agent 的自我目标管理系统。action=check/goal/done/list_goals。", "parameters": {"type": "object", "properties": {"action": {"type": "string", "enum": ["check", "goal", "done", "list_goals"], "description": "check/goal/done/list_goals"}, "content": {"type": "string", "description": "目标内容"}, "priority": {"type": "integer", "description": "优先级 0-3", "default": 2}, "goal_id": {"type": "integer", "description": "目标ID"}}, "required": ["action"]}}}
