"""toolkit_approve — 工具审批闸门管理（A3 安全底座的授权入口）。

配合 tea_agent/tool_approval.py 使用。当 `security.approval_mode: enforce` 时，
高风险工具（默认 high 及以上）缺失授权即被拒绝；本工具提供授权/撤销/状态查询。

用法::

    toolkit_approve(action="status")                              # 查看当前闸门状态
    toolkit_approve(action="grant", tool="toolkit_exec")          # 持久授权
    toolkit_approve(action="revoke", tool="toolkit_exec")         # 撤销授权
    toolkit_approve(action="list")                                # 列出已授权工具
"""

import logging

logger = logging.getLogger("toolkit")


def meta_toolkit_approve():
    """Meta toolkit approve."""
    return {
        "type": "function",
        "function": {
            "name": "toolkit_approve",
            "description": (
                "工具审批闸门管理：查看审批状态、持久授权或撤销高风险工具。"
                "当 approval_mode=enforce 时，高风险工具（如 toolkit_exec / toolkit_self_evolve）"
                "必须获得授权才能执行。授权对当前项目持久生效。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["status", "grant", "revoke", "list"],
                        "description": "status=查看闸门状态; grant=授权工具; revoke=撤销授权; list=列出已授权工具",
                    },
                    "tool": {
                        "type": "string",
                        "description": "目标工具名（grant/revoke 时必需），如 toolkit_exec",
                    },
                    "note": {
                        "type": "string",
                        "description": "授权备注（可选，记录授权原因）",
                    },
                },
                "required": ["action"],
            },
        },
    }


def toolkit_approve(action: str = "status", tool: str = "", note: str = "") -> dict:
    """工具审批闸门管理。

    Args:
        action: status / grant / revoke / list
        tool: 目标工具名（grant/revoke 必需）
        note: 授权备注（可选）

    Returns:
        dict：操作结果；失败时含 ``error`` 字段
    """
    logger.info(f"toolkit_approve called: action={action!r}, tool={tool!r}")

    try:
        from tea_agent.tool_approval import (
            RISK_LEVELS,
            approval_status,
            grant,
            grants,
            revoke,
        )
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"审批模块不可用: {e}"}

    act = (action or "status").strip().lower()

    if act == "status":
        st = approval_status()
        st["ok"] = True
        st["risk_levels"] = RISK_LEVELS
        st["hint"] = (
            "mode=off 仅审计高风险动作；mode=advisory 打标不阻断；"
            "mode=enforce 高风险动作缺失授权即拒绝"
        )
        return st

    if act == "list":
        tools = grants().get("tools", [])
        return {"ok": True, "grants": tools, "count": len(tools)}

    if act in ("grant", "revoke"):
        if not tool:
            return {"ok": False, "error": f"action={act} 需要提供 tool 参数"}
        result = grant(tool, note=note) if act == "grant" else revoke(tool)
        if result.get("ok"):
            result["hint"] = (
                f"已{('授权' if act == 'grant' else '撤销')} {tool}；"
                "授权名单存于 .tea_agent_run/approval_allow.json"
            )
        return result

    return {"ok": False, "error": f"未知 action: {action!r}（可选 status/grant/revoke/list）"}
