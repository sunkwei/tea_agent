# @2026-04-29 gen by deepseek-v4-pro, 内置工具: 切换/查询 reasoning/thinking 状态
def toolkit_toggle_reasoning(enable: bool = None) -> dict:
    """
    切换或查询推理（thinking/reasoning）状态。
    不传参数则返回当前状态；传入 True/False 则开启/关闭。

    Args:
        enable: True=开启, False=关闭, None=仅查询
    """
    try:
        from tea_agent.session_ref import get_session
    except ImportError:
        return {"error": "session_ref 模块不可用"}

    sess = get_session()
    if sess is None:
        return {"error": "当前无活跃会话"}

    if enable is None:
        return {"enable_thinking": sess.enable_thinking}

    sess.enable_thinking = bool(enable)
    state = "开启" if enable else "关闭"
    return {"enable_thinking": sess.enable_thinking, "changed": True, "message": f"Reasoning 已{state}"}


def meta_toolkit_toggle_reasoning():
    return {
        "type": "function",
        "function": {
            "name": "toolkit_toggle_reasoning",
            "description": "切换或查询推理（thinking/reasoning）状态。不传参数则返回当前状态；传入 True/False 则开启/关闭。",
            "parameters": {
                "type": "object",
                "properties": {
                    "enable": {
                        "type": "boolean",
                        "description": "True=开启, False=关闭, None=仅查询当前状态"
                    }
                },
                "required": []
            }
        }
    }
