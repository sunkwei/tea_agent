## llm generated tool func, created Sat May  2 10:20:05 2026
# version: 1.0.1

# @2026-05-02 gen by tea_agent, 自主心跳：Agent自我目标管理系统
# version: 1.0.1

def toolkit_proactive(action: str, content: str = "", priority: int = 2, goal_id: int = None):
    """Agent 自主心跳系统"""
    import json
    
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
            return (1, "", f"未知 action: {action}")
    except Exception as e:
        return (1, "", f"自主心跳出错: {str(e)}")


def _get_memory_manager():
    from tea_agent.memory import MemoryManager
    from tea_agent.store import Storage
    storage = Storage()
    return MemoryManager(storage, extraction_threshold=1, dedup_threshold=0.3)


def _check_proactive():
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
        
        return (0, json.dumps(report, ensure_ascii=False, indent=2), "")
    except Exception as e:
        return (1, "", f"检查失败: {str(e)}")


def _add_goal(content: str, priority: int = 2):
    import json
    if not content or not content.strip():
        return (1, "", "目标内容不能为空")
    try:
        mm = _get_memory_manager()
        mm.storage.add_memory(
            content=content.strip(),
            category="reminder",
            priority=priority,
            importance=4,
            tags="goal,proactive",
        )
        return (0, json.dumps({"status": "已设定", "content": content.strip()}), "")
    except Exception as e:
        return (1, "", f"设定目标失败: {str(e)}")


# NOTE: 2026-05-02, self-evolved by tea_agent --- 修复delete_memory参数错误（无hard参数）
def _complete_goal(goal_id: int):
    import json
    if not goal_id:
        return (1, "", "需要提供 goal_id")
    try:
        mm = _get_memory_manager()
        mm.storage.delete_memory(goal_id)
        return (0, json.dumps({"status": "已完成", "id": goal_id}), "")
    except Exception as e:
        return (1, "", f"完成目标失败: {str(e)}")


def _list_goals():
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
        return (0, json.dumps(goals, ensure_ascii=False, indent=2), "")
    except Exception as e:
        return (1, "", f"列出目标失败: {str(e)}")


def meta_toolkit_proactive() -> dict:
    return {"type": "function", "function": {"name": "toolkit_proactive", "description": "自主心跳：Agent 的自我目标管理系统。action=check 检查待办目标/洞察，action=goal 设置目标，action=done 完成目标。实现 Agent 跨会话的自主行动能力。", "parameters": {"type": "object", "properties": {"action": {"type": "string", "enum": ["check", "goal", "done", "list_goals"], "description": "check=检查待办并返回建议, goal=设定新目标, done=标记目标完成, list_goals=列出所有目标"}, "content": {"type": "string", "description": "[goal] 目标内容"}, "priority": {"type": "integer", "description": "[goal] 优先级 0-3，默认 2", "default": 2}, "goal_id": {"type": "integer", "description": "[done] 目标ID"}}, "required": ["action"]}}}


def meta_toolkit_proactive() -> dict:
    return {"type": "function", "function": {"name": "toolkit_proactive", "description": "自主心跳：Agent 的自我目标管理系统。action=check 检查待办目标/洞察，action=goal 设置目标，action=done 完成目标。实现 Agent 跨会话的自主行动能力。", "parameters": {"type": "object", "properties": {"action": {"type": "string", "enum": ["check", "goal", "done", "list_goals"], "description": "check=检查待办并返回建议, goal=设定新目标, done=标记目标完成, list_goals=列出所有目标"}, "content": {"type": "string", "description": "[goal] 目标内容"}, "priority": {"type": "integer", "description": "[goal] 优先级 0-3，默认 2", "default": 2}, "goal_id": {"type": "integer", "description": "[done] 目标ID"}}, "required": ["action"]}}}
