# version: 2.1.0 — merged toolkit_evolution_exp（经验库 list/record/search 内联，删除独立工具）

"""
经验固化机制
成功任务→固化技能，失败任务→记录教训。
同时内联进化经验库（原 toolkit_evolution_exp）：list/record/search 经验条目。
"""

import json
import logging
import os
from datetime import datetime

logger = logging.getLogger("toolkit.experience_solidify")


def toolkit_experience_solidify(
    action: str = "auto",
    task: str = "",
    result: str = "",
    success: bool = True,
    tools_used: list[str] = None,
    duration: float = 0,
    error: str = "",
    pattern_name: str = "",
    description: str = "",
    category: str = "",
    tags: str = "",
    outcome: str = "success",
    notes: str = "",
    query: str = "",
    limit: int = 10
) -> dict:
    """
    经验固化机制。

    - action=analyze: 分析执行过程
    - action=solidify: 固化成功模式到技能库
    - action=lesson: 记录失败教训
    - action=auto: 分析+自动固化/记录
    - action=record: 记录一条进化经验（原 toolkit_evolution_exp）
    - action=list: 列出最近经验
    - action=search: 按关键词搜索经验
    """
    if action == "analyze":
        return _analyze_execution(task, result, success, tools_used, duration, error)
    elif action == "solidify":
        return _solidify_pattern(task, result, tools_used, pattern_name)
    elif action == "lesson":
        return _record_lesson(task, error, tools_used)
    elif action == "auto":
        if success:
            return _solidify_pattern(task, result, tools_used, pattern_name)
        else:
            return _record_lesson(task, error, tools_used)
    elif action == "record":
        return _exp_record(description, category, tags, outcome, notes)
    elif action == "list":
        return _exp_list(limit)
    elif action == "search":
        return _exp_search(query, limit)
    else:
        return {"ok": False, "error": f"unknown_action:{action}"}


def _analyze_execution(task: str, result: str, success: bool, tools_used: list[str], duration: float, error: str) -> dict:
    return {
        "ok": True,
        "task": task,
        "success": success,
        "duration": duration,
        "tools_used": tools_used or [],
        "timestamp": datetime.now().isoformat(),
        "suggestion": "solidify" if success else "lesson"
    }


def _solidify_pattern(task: str, result: str, tools_used: list[str], pattern_name: str) -> dict:
    try:
        from tea_agent.toolkit.toolkit_dynamic_skill import toolkit_dynamic_skill
        return toolkit_dynamic_skill(
            action="record",
            task=task,
            pattern_name=pattern_name or f"skill_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            agents=[{"role": "general", "tools": tools_used or []}]
        )
    except Exception as e:
        logger.exception(f"solidify_failed:{task[:50]}")
        return {"ok": False, "error": f"solidify_failed:{e}"}


def _record_lesson(task: str, error: str, tools_used: list[str]) -> dict:
    try:
        return _exp_record(
            description=f"task_failed:{task[:100]}",
            category="failure",
            notes=f"error:{error}"
        )
    except Exception as e:
        logger.exception(f"lesson_record_failed:{task[:50]}")
        return {"ok": False, "error": f"lesson_record_failed:{e}"}


# ── 进化经验库（原 toolkit_evolution_exp，内联） ──

def _get_exp_path() -> str:
    return os.path.join(os.path.expanduser("~"), ".tea_agent", "evolution_exp.json")


def _load_exp_db() -> list[dict]:
    path = _get_exp_path()
    if os.path.exists(path):
        try:
            with open(path, encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.exception(f"load_exp_failed:{e}")
    return []


def _save_exp_db(data: list[dict]):
    path = _get_exp_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _exp_record(description: str, category: str = "", tags: str = "", outcome: str = "success", notes: str = "") -> dict:
    if not description:
        return {"ok": False, "error": "missing_description"}
    db = _load_exp_db()
    exp = {
        "timestamp": datetime.now().isoformat(),
        "description": description,
        "category": category or "general",
        "tags": [t.strip() for t in tags.split(",") if t.strip()] if tags else [],
        "outcome": outcome,
        "notes": notes
    }
    db.append(exp)
    _save_exp_db(db)
    return {"ok": True, "message": f"recorded:{description[:60]}"}


def _exp_list(limit: int) -> dict:
    db = _load_exp_db()
    if not db:
        return {"ok": True, "experiences": [], "total": 0}
    result = []
    for exp in db[-limit:]:
        result.append({
            "description": exp.get("description", ""),
            "category": exp.get("category", ""),
            "outcome": exp.get("outcome", ""),
            "date": exp.get("timestamp", "")[:10]
        })
    return {"ok": True, "experiences": result, "total": len(db)}


def _exp_search(query: str, limit: int) -> dict:
    if not query:
        return {"ok": False, "error": "missing_query"}
    db = _load_exp_db()
    q = query.lower()
    results = [exp for exp in db if q in json.dumps(exp, ensure_ascii=False).lower()]
    return {"ok": True, "query": query, "results": results[-limit:], "total": len(results)}


def meta_toolkit_experience_solidify() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "toolkit_experience_solidify",
            "description": "经验固化 + 进化经验库（合并原 toolkit_evolution_exp）。solidify=成功→技能库, lesson=失败→教训库, auto=按成功与否自动固化/记录, record=记录经验条目, list=列出经验, search=搜索经验, analyze=分析执行过程",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["analyze", "solidify", "lesson", "auto", "record", "list", "search"], "description": "操作类型"},
                    "task": {"type": "string", "description": "任务描述（analyze/solidify/lesson/auto 使用）"},
                    "result": {"type": "string", "description": "执行结果"},
                    "success": {"type": "boolean", "description": "是否成功"},
                    "tools_used": {"type": "array", "items": {"type": "string"}, "description": "使用工具列表"},
                    "duration": {"type": "number", "description": "耗时秒数"},
                    "error": {"type": "string", "description": "失败原因"},
                    "pattern_name": {"type": "string", "description": "技能模式名称"},
                    "description": {"type": "string", "description": "经验描述（record 时必需）"},
                    "category": {"type": "string", "description": "经验分类（record）"},
                    "tags": {"type": "string", "description": "逗号分隔标签（record）"},
                    "outcome": {"type": "string", "description": "success/failure/partial（record）"},
                    "notes": {"type": "string", "description": "备注（record）"},
                    "query": {"type": "string", "description": "搜索关键词（search）"},
                    "limit": {"type": "integer", "description": "返回上限（list/search）"}
                },
                "required": ["action"]
            }
        }
    }
