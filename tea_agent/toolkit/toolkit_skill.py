"""toolkit_skill — Skill 管理：查看、激活、停用技能"""
# @2026-05-04 gen by tea_agent, Skill系统 — 动态管理Agent的能力模块


def toolkit_skill(action: str = "list", name: str = ""):
    """
    管理 Agent 的技能 (Skill)。Skill 是能力的模块化分组，可动态激活/停用。

    Args:
        action: 操作类型
            - 'list': 列出所有 Skill 及状态
            - 'activate': 激活指定 Skill
            - 'deactivate': 停用指定 Skill
            - 'status': 显示当前 Skill 系统状态
            - 'auto': 根据用户输入自动激活匹配的 Skill
        name: [activate/deactivate] Skill 名称，或 [auto] 用户输入文本

    Returns:
        操作结果描述
    """
    import json
    from tea_agent.skills import SkillManager

    mgr = SkillManager.get_instance()
    mgr.discover_skills()

    if action == "list":
        skills = mgr.list_skills()
        if not skills:
            return "📋 没有发现任何 Skill。"

        lines = ["📋 所有 Skill:"]
        for s in skills:
            status = "🟢 激活" if s["active"] else "⚪ 未激活"
            lines.append(
                f"  {status}  {s['name']} (v{s['version']}) — {s['description']}"
            )
            lines.append(f"         工具({s['tool_count']}): {', '.join(s['tools'][:5])}"
                         + (f" +{s['tool_count']-5}..." if s['tool_count'] > 5 else ""))
        return "\n".join(lines)

    elif action == "activate":
        if not name:
            return "❌ 请指定要激活的 Skill 名称"
        if name not in mgr.skills:
            available = ", ".join(mgr.skills.keys())
            return f"❌ Skill '{name}' 不存在。可用: {available}"
        mgr.activate_skill(name)
        skill = mgr.get_skill(name)
        return f"✅ Skill '{name}' 已激活 ({len(skill.tools)} 个工具)"

    elif action == "deactivate":
        if not name:
            return "❌ 请指定要停用的 Skill 名称"
        if name not in mgr.skills:
            available = ", ".join(mgr.skills.keys())
            return f"❌ Skill '{name}' 不存在。可用: {available}"
        mgr.deactivate_skill(name)
        return f"✅ Skill '{name}' 已停用"

    elif action == "status":
        status = mgr.get_status()
        return json.dumps(status, ensure_ascii=False, indent=2)

    elif action == "auto":
        if not name:
            return "❌ auto 需要提供用户输入文本"
        activated = mgr.auto_activate(name)
        if activated:
            return f"✅ 自动激活了 {len(activated)} 个 Skill: {', '.join(activated)}"
        else:
            return "ℹ️ 没有匹配的 Skill 被自动激活"

    else:
        return f"❌ 未知操作: {action}。支持: list, activate, deactivate, status, auto"


def meta_toolkit_skill():
    return {
        "type": "function",
        "function": {
            "name": "toolkit_skill",
            "description": "管理 Agent 的技能 (Skill) 模块。Skill 是能力的模块化分组（如桌面自动化、文件系统、自我进化等），可动态激活/停用以节省 token。支持 list/activate/deactivate/status/auto 操作。",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["list", "activate", "deactivate", "status", "auto"],
                        "description": "操作: list=列出所有Skill, activate=激活, deactivate=停用, status=状态统计, auto=根据文本自动激活"
                    },
                    "name": {
                        "type": "string",
                        "description": "[activate/deactivate] Skill名称, [auto] 用户输入文本"
                    }
                },
                "required": ["action"]
            }
        }
    }
