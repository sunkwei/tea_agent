# @2026-04-30 gen by deepseek-v4-pro, toolkit_config: Agent 读取/修改运行时配置
"""toolkit_config — 允许 Agent 读取和修改自身运行时配置"""

import json
from tea_agent.config import get_config
from tea_agent.session_ref import get_session


def toolkit_config(action: str = "list", key: str = "", value: str = "") -> str:
    """
    读取或修改 Agent 运行时配置。修改会自动记录到 config_history 表。

    Args:
        action: 'list'=列出所有配置, 'get'=读取单个, 'set'=修改配置, 'history'=查看变更历史
        key: 配置键名
        value: [set] 新值

    可修改的配置项:
        max_history, max_iterations, enable_thinking,
        keep_turns, max_tool_output, max_assistant_content,
        extra_iterations_on_continue, memory_extraction_threshold,
        memory_dedup_threshold, chat_page_size
    """
    cfg = get_config()
    session = get_session()
    storage = getattr(session, 'storage', None) if session else None

    if action == "list":
        data = cfg.to_dict()
        lines = ["📋 当前运行时配置:"]
        for k, v in data.items():
            lines.append(f"  {k} = {v}")
        return "\n".join(lines)

    elif action == "get":
        if not key:
            return "❌ 需要提供 key 参数"
        val = cfg.get(key)
        if val is None:
            return f"❌ 未知配置键: {key}"
        return f"{key} = {val}"

    elif action == "set":
        if not key:
            return "❌ 需要提供 key 参数"
        if not value:
            return "❌ 需要提供 value 参数"

        old_val = str(cfg.get(key, ""))
        ok = cfg.set(key, value)
        if not ok:
            return f"❌ 无法修改 {key}: 键名不在白名单中或值类型错误"

        new_val = str(cfg.get(key, ""))

        # 记录到 config_history
        if storage:
            storage.add_config_change(
                key=key,
                new_value=new_val,
                old_value=old_val,
                reason="Agent 自主调优",
            )

        # 同步到活跃 session
        if session:
            if hasattr(session, key):
                try:
                    setattr(session, key, cfg.get(key))
                except Exception:
                    pass

        return f"✅ {key}: {old_val} → {new_val}"

    elif action == "history":
        if not storage:
            return "❌ Storage 未初始化"
        changes = storage.get_config_history(key=key if key else "", limit=20)
        if not changes:
            return "📝 暂无配置变更记录"
        lines = ["📋 配置变更历史:"]
        for ch in changes:
            lines.append(
                f"  #{ch['id']} [{ch['created_at']}] {ch['key']}: "
                f"{ch.get('old_value', '(无)')} → {ch['new_value']}"
            )
            if ch.get("reason"):
                lines.append(f"    原因: {ch['reason']}")
        return "\n".join(lines)

    else:
        return f"❌ 未知操作: {action}。支持: list, get, set, history"


def meta_toolkit_config() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "toolkit_config",
            "description": "读取或修改 Agent 运行时配置。Agent 可以自主调优自己的参数（如 max_iterations、keep_turns 等）。修改会自动记录历史。",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["list", "get", "set", "history"],
                        "description": "操作: list=全部配置, get=读取单个, set=修改, history=变更历史"
                    },
                    "key": {
                        "type": "string",
                        "description": "配置键名（get/set 时必需）"
                    },
                    "value": {
                        "type": "string",
                        "description": "[set] 新值"
                    }
                },
                "required": ["action"]
            }
        }
    }
