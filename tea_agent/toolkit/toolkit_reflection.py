# @2026-04-30 gen by deepseek-v4-pro, toolkit_reflection: Agent主动触发元认知反思
"""toolkit_reflection — 允许 Agent 主动触发自我反思"""

import json
from tea_agent.session_ref import get_session


def toolkit_reflection(action: str = "trigger", limit: int = 5) -> str:
    """
    触发或查看元认知反思。

    Args:
        action: 'trigger'=触发一次反思, 'list'=查看最近反思, 'stats'=查看统计
        limit: list模式下返回的记录数

    Returns:
        格式化的结果字符串
    """
    session = get_session()
    if not session:
        return "❌ 无活跃会话，无法执行反思操作"

    reflection_mgr = getattr(session, 'reflection_manager', None)
    if not reflection_mgr:
        return "❌ ReflectionManager 未初始化"

    if action == "trigger":
        # 强制触发反思
        if not reflection_mgr._pending_traces:
            return "📝 没有待反思的会话追踪数据。反思需要先有对话记录。"
        rid = reflection_mgr.generate_reflection()
        if rid:
            prompt_suggestion = reflection_mgr.last_prompt_suggestion
            result = f"✅ 反思完成 (id={rid})\n"
            if prompt_suggestion:
                result += f"💡 提示词建议: {prompt_suggestion[:200]}..."
            return result
        return "⚠️ 反思生成失败（可能没有便宜模型或数据不足）"

    elif action == "list":
        storage = getattr(session, 'storage', None)
        if not storage:
            return "❌ Storage 未初始化"
        reflections = storage.get_recent_reflections(limit=limit)
        if not reflections:
            return "📝 暂无反思记录"
        lines = []
        for r in reflections:
            suggestions = r.get("suggestions", "[]")
            if isinstance(suggestions, str):
                try:
                    suggestions = json.loads(suggestions)
                except json.JSONDecodeError:
                    suggestions = []
            sugg_text = "; ".join(suggestions[:3]) if suggestions else "无"
            lines.append(
                f"#{r['id']} [{r['created_at']}] {r['summary'][:80]}\n"
                f"  建议: {sugg_text}\n"
                f"  已应用: {'✅' if r.get('is_applied') else '⏳'}"
            )
        return "\n".join(lines)

    elif action == "stats":
        stats = reflection_mgr.get_stats()
        return f"📊 反思统计: 总计 {stats['total']} 条, 未应用 {stats['unapplied']} 条"

    else:
        return f"❌ 未知操作: {action}。支持: trigger, list, stats"


def meta_toolkit_reflection() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "toolkit_reflection",
            "description": "元认知反思工具。trigger=触发自我分析反思，list=查看最近反思，stats=查看统计。Agent 可在任务完成后用此工具反思自己的表现。",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["trigger", "list", "stats"],
                        "description": "操作: trigger=触发反思, list=查看最近反思, stats=统计"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "[list] 返回记录数，默认5"
                    }
                },
                "required": ["action"]
            }
        }
    }
