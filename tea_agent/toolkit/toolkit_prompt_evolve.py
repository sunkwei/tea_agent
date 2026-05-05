# @2026-04-30 gen by deepseek-v4-pro, toolkit_prompt_evolve: Agent 自主进化系统提示词
"""toolkit_prompt_evolve — 允许 Agent 管理自己的系统提示词版本"""

from tea_agent.session_ref import get_session


def toolkit_prompt_evolve(action: str = "current", version: str = "", content: str = "") -> str:
    """
    管理系统提示词的多版本进化。

    Args:
        action: 操作类型
            - 'current': 查看当前版本
            - 'evolve': 基于反思和记忆自动生成新版本
            - 'list': 列出所有版本历史
            - 'rollback': 回滚到指定版本（需 version 参数）
            - 'set': 手动设置新版本（需 content 参数）
            - 'stats': 查看统计

        version: [rollback] 目标版本号（如 "1", "2"）
        content: [set] 新的完整系统提示词文本
    """
    session = get_session()
    if not session:
        return "❌ 无活跃会话"

    pm = getattr(session, 'prompt_manager', None)
    if not pm:
        return "❌ SystemPromptManager 未初始化"

    if action == "current":
        return (
            f"📋 当前系统提示词版本: v{pm.current_version} (id={pm.current_prompt_id})\n\n"
            f"---\n{pm.current_prompt}\n---"
        )

    elif action == "evolve":
        # 获取最近的反思建议
        reflection_mgr = getattr(session, 'reflection_manager', None)
        suggestion = None
        if reflection_mgr:
            suggestion = reflection_mgr.last_prompt_suggestion

        new_id = pm.evolve(reflection_suggestion=suggestion)
        if new_id:
            return f"✅ 系统提示词已进化到 v{pm.current_version} (id={new_id})"
        return "⚠️ 提示词进化未产生新版本（可能无变化或 LLM 调用失败）"

    elif action == "list":
        versions = pm.list_versions()
        if not versions:
            return "📝 暂无历史版本"
        lines = ["📋 系统提示词版本历史:"]
        for v in versions:
            status = "✅ 活跃" if v.get("is_active") else "⏸️ 停用"
            lines.append(
                f"  v{v['version']} (id={v['id']}) {status}\n"
                f"    创建: {v['created_at']}\n"
                f"    原因: {v.get('reason', '无')[:80]}\n"
                f"    内容预览: {v['content'][:100]}..."
            )
        return "\n".join(lines)

    elif action == "rollback":
        if not version:
            return "❌ 需要提供 version 参数（如 '1'）"
        ok = pm.rollback(version)
        if ok:
            return f"✅ 已回滚到 v{version}"
        return f"❌ 回滚失败: 版本 {version} 不存在"

    elif action == "set":
        if not content:
            return "❌ 需要提供 content 参数（完整提示词文本）"
        if len(content) < 20:
            return "❌ 提示词太短，至少需要 20 个字符"
        new_id = pm.manual_set(content, reason="Agent 手动设置")
        return f"✅ 已创建新版本 v{pm.current_version} (id={new_id})"

    elif action == "stats":
        stats = pm.get_stats()
        return (
            f"📊 系统提示词统计:\n"
            f"  总版本数: {stats['total_versions']}\n"
            f"  当前版本: v{stats['current_version']}\n"
            f"  当前 ID: {stats['current_id']}"
        )

    else:
        return f"❌ 未知操作: {action}。支持: current, evolve, list, rollback, set, stats"


def meta_toolkit_prompt_evolve() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "toolkit_prompt_evolve",
            "description": "管理系统提示词的多版本进化。evolve=基于反思自动优化提示词, rollback=回滚到历史版本, list=查看版本历史。Agent 可以自主改进自己的核心指令。",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["current", "evolve", "list", "rollback", "set", "stats"],
                        "description": "操作类型"
                    },
                    "version": {
                        "type": "string",
                        "description": "[rollback] 目标版本号"
                    },
                    "content": {
                        "type": "string",
                        "description": "[set] 新的完整系统提示词"
                    }
                },
                "required": ["action"]
            }
        }
    }
