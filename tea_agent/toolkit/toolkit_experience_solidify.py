## llm generated tool func, created Mon Jun  1 09:41:14 2026
# version: 1.0.2

"""
经验固化机制

任务完成后自动复盘，将经验转化为可复用技能。
- 成功任务 -> 提取模式 -> 固化到技能库 (dynamic_skill)
- 失败任务 -> 分析根因 -> 记录到经验库 (evolution_exp)
"""

import json
import logging
import time
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
) -> str:
    """
    经验固化机制。

    Args:
        action: 操作类型 (analyze/solidify/lesson/auto)
        task: 任务描述
        result: 执行结果摘要
        success: 任务是否成功
        tools_used: 使用的工具列表
        duration: 执行耗时（秒）
        error: 失败原因
        pattern_name: 技能模式名称

    Returns:
        分析结果或固化状态
    """
    logger.info(f"experience_solidify: action={action}, task={task[:50]}...")

    if action == "analyze":
        return _analyze_execution(task, result, success, tools_used, duration, error)
    elif action == "solidify":
        return _solidify_pattern(task, result, tools_used, pattern_name)
    elif action == "lesson":
        return _record_lesson(task, error, tools_used)
    elif action == "auto":
        return _auto_solidify(task, result, success, tools_used, duration, error)
    else:
        return f"未知操作: {action}"


def _analyze_execution(
    task: str,
    result: str,
    success: bool,
    tools_used: list[str],
    duration: float,
    error: str
) -> str:
    """分析任务执行过程。"""
    analysis = {
        "task": task,
        "success": success,
        "duration": duration,
        "tools_used": tools_used or [],
        "timestamp": datetime.now().isoformat()
    }

    if success:
        analysis["status"] = "成功"
        analysis["suggestion"] = "建议固化为可复用技能"
        if tools_used:
            analysis["key_tools"] = tools_used
    else:
        analysis["status"] = "失败"
        analysis["error"] = error
        analysis["suggestion"] = "建议记录教训，避免重复犯错"

    return json.dumps(analysis, ensure_ascii=False, indent=2)


def _solidify_pattern(
    task: str,
    result: str,
    tools_used: list[str],
    pattern_name: str
) -> str:
    """固化成功模式到技能库。"""
    try:
        # 生成模式名称
        if not pattern_name:
            pattern_name = _generate_pattern_name(task)

        # 构建 agent 组合
        agents = _build_agent_config(tools_used)

        # 直接调用 dynamic_skill 函数
        try:
            from tea_agent.toolkit.toolkit_dynamic_skill import toolkit_dynamic_skill
            toolkit_dynamic_skill(
                action="record",
                task=task,
                pattern_name=pattern_name,
                agents=agents
            )
            return f"✅ 已固化技能: {pattern_name}\n任务: {task}\n工具: {', '.join(tools_used or [])}"
        except ImportError:
            return "⚠️ dynamic_skill 工具未加载"
        except Exception as e:
            return f"⚠️ 调用 dynamic_skill 失败: {e}"

    except Exception as e:
        logger.error(f"固化失败: {e}")
        return f"❌ 固化失败: {e}"


def _record_lesson(
    task: str,
    error: str,
    tools_used: list[str]
) -> str:
    """记录失败教训到经验库。"""
    try:
        from tea_agent.toolkit.toolkit_evolution_exp import toolkit_evolution_exp
        toolkit_evolution_exp(
            action="record",
            description=f"任务失败: {task}",
            category="failure",
            outcome="failure",
            notes=f"错误: {error}\n工具: {', '.join(tools_used or [])}",
            tags="failure,lesson"
        )
        return f"✅ 已记录教训\n任务: {task}\n错误: {error}"
    except ImportError:
        return "⚠️ evolution_exp 工具未加载"
    except Exception as e:
        logger.error(f"记录教训失败: {e}")
        return f"❌ 记录失败: {e}"


def _auto_solidify(
    task: str,
    result: str,
    success: bool,
    tools_used: list[str],
    duration: float,
    error: str
) -> str:
    """自动分析并固化。"""
    # 1. 分析执行
    analysis = _analyze_execution(task, result, success, tools_used, duration, error)

    # 2. 根据成功/失败决定操作
    if success:
        solidify_result = _solidify_pattern(task, result, tools_used, "")
        return f"{analysis}\n\n{solidify_result}"
    else:
        lesson_result = _record_lesson(task, error, tools_used)
        return f"{analysis}\n\n{lesson_result}"


def _generate_pattern_name(task: str) -> str:
    """根据任务描述生成模式名称。"""
    # 简单规则：取前20个字符，替换空格为连字符
    name = task[:20].replace(" ", "-").lower()
    # 移除特殊字符
    name = "".join(c for c in name if c.isalnum() or c == "-")
    # 添加时间戳后缀确保唯一性
    timestamp = int(time.time()) % 10000
    return f"{name}-{timestamp}"


def _build_agent_config(tools_used: list[str]) -> list[dict]:
    """根据使用的工具构建 agent 配置。"""
    agents = []

    # 工具到角色的映射
    tool_role_map = {
        "toolkit_exec": "executor",
        "toolkit_file": "file-manager",
        "toolkit_edit": "editor",
        "toolkit_format_code": "formatter",
        "toolkit_lsp": "analyzer",
        "toolkit_explr": "explorer",
        "toolkit_search": "researcher",
        "toolkit_self_evolve": "evolver",
        "toolkit_question": "communicator"
    }

    if tools_used:
        for tool in tools_used:
            role = tool_role_map.get(tool, "general")
            agents.append({
                "role": role,
                "difficulty": "medium",
                "tools": [tool]
            })

    # 如果没有工具，添加默认 agent
    if not agents:
        agents.append({
            "role": "general",
            "difficulty": "medium",
            "tools": []
        })

    return agents


def meta_toolkit_experience_solidify() -> dict:
    return {"type": "function", "function": {"name": "toolkit_experience_solidify", "description": "经验固化机制 - 任务完成后自动复盘，将经验转化为可复用技能。\n\n功能：\n- analyze: 分析任务执行过程\n- solidify: 固化成功模式到技能库\n- lesson: 记录失败教训到经验库\n- auto: 自动分析并固化（成功→技能，失败→教训）\n\n返回：分析结果或固化状态", "parameters": {"type": "object", "properties": {"action": {"type": "string", "enum": ["analyze", "solidify", "lesson", "auto"], "description": "操作类型"}, "task": {"type": "string", "description": "任务描述"}, "result": {"type": "string", "description": "执行结果摘要"}, "success": {"type": "boolean", "description": "任务是否成功"}, "tools_used": {"type": "array", "items": {"type": "string"}, "description": "使用的工具列表"}, "duration": {"type": "number", "description": "执行耗时（秒）"}, "error": {"type": "string", "description": "失败原因（success=false 时）"}, "pattern_name": {"type": "string", "description": "技能模式名称（solidify 时可选）"}}, "required": ["action", "task"]}}}
