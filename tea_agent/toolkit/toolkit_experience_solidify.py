# version: 2.0.0 — refactored: unified dict return, removed string-return anti-pattern

"""
经验固化机制
成功任务→固化技能，失败任务→记录教训。
"""

import json
import logging
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
    pattern_name: str = ""
) -> dict:
    """
    经验固化机制。

    - action=analyze: 分析执行过程
    - action=solidify: 固化成功模式到技能库
    - action=lesson: 记录失败教训
    - action=auto: 分析+自动固化/记录
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
        from tea_agent.toolkit.toolkit_evolution_exp import toolkit_evolution_exp
        return toolkit_evolution_exp(
            action="record",
            description=f"task_failed:{task[:100]}",
            category="failure",
            notes=f"error:{error}"
        )
    except Exception as e:
        logger.exception(f"lesson_record_failed:{task[:50]}")
        return {"ok": False, "error": f"lesson_record_failed:{e}"}


def meta_toolkit_experience_solidify() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "toolkit_experience_solidify",
            "description": "经验固化。成功→技能库，失败→教训库。action=analyze/solidify/lesson/auto",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["analyze", "solidify", "lesson", "auto"], "description": "操作类型"},
                    "task": {"type": "string", "description": "任务描述"},
                    "result": {"type": "string", "description": "执行结果"},
                    "success": {"type": "boolean", "description": "是否成功"},
                    "tools_used": {"type": "array", "items": {"type": "string"}, "description": "使用工具列表"},
                    "duration": {"type": "number", "description": "耗时秒数"},
                    "error": {"type": "string", "description": "失败原因"},
                    "pattern_name": {"type": "string", "description": "技能模式名称"}
                },
                "required": ["action", "task"]
            }
        }
    }
