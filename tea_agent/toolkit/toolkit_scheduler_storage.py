## llm generated tool func, created Wed Jun  3 07:59:03 2026
# version: 1.0.0

def toolkit_scheduler_storage(action: str, **kwargs):
    """调度器存储管理 — 脚本与任务的统一管理。"""
    from tea_agent.scheduler_storage import SchedulerStorage, save_evolve_script

    storage = SchedulerStorage()

    if action == "save_script":
        script_id = kwargs.get("script_id")
        name = kwargs.get("name")
        content = kwargs.get("content")
        description = kwargs.get("description", "")
        if not all([script_id, name, content]):
            return {"error": "需要 script_id, name, content"}
        return storage.save_script(script_id, name, content, description)

    elif action == "get_script":
        script_id = kwargs.get("script_id")
        if not script_id:
            return {"error": "需要 script_id"}
        return storage.get_script(script_id)

    elif action == "list_scripts":
        return {"scripts": storage.list_scripts()}

    elif action == "delete_script":
        script_id = kwargs.get("script_id")
        if not script_id:
            return {"error": "需要 script_id"}
        return {"deleted": storage.delete_script(script_id)}

    elif action == "save_evolve_script":
        return save_evolve_script()

    elif action == "prepare_script":
        script_id = kwargs.get("script_id")
        if not script_id:
            return {"error": "需要 script_id"}
        path = storage.prepare_script_for_execution(script_id)
        return {"path": path}

    else:
        return {"error": f"未知操作: {action}"}


def meta_toolkit_scheduler_storage() -> dict:
    return {"type": "function", "function": {"name": "toolkit_scheduler_storage", "description": "调度器存储管理 — 脚本与任务的统一管理。支持脚本存储在数据库中，便于备份、迁移。", "parameters": {"type": "object", "properties": {"action": {"type": "string", "enum": ["save_script", "get_script", "list_scripts", "delete_script", "save_evolve_script", "prepare_script"], "description": "操作类型"}}, "required": ["action"]}}}
