"""
@2026-07-09 gen by tea_agent, 主题级 System Prompt 管理工具

允许 LLM 在对话中获取/设置/清除当前主题的自定义系统提示词。
优先级：主题级 > 全局进化版。

使用方式：
  toolkit_topic_prompt(action='get') → 查看当前主题的自定义 system prompt
  toolkit_topic_prompt(action='set', content='...') → 设置当前主题的 system prompt
  toolkit_topic_prompt(action='clear') → 清除当前主题的自定义 system prompt
  toolkit_topic_prompt(action='status') → 查看当前使用的 system prompt 来源
"""

import logging

logger = logging.getLogger("toolkit.topic_prompt")


def _get_agent():
    """获取当前 Agent 实例"""
    try:
        from tea_agent.session_ref import get_agent
        return get_agent()
    except Exception:
        logger.exception("获取 Agent 失败")
        return None


def meta_toolkit_topic_prompt() -> dict:
    """返回工具的 OpenAI function calling schema。"""
    return {
        "type": "function",
        "function": {
            "name": "toolkit_topic_prompt",
            "description": "管理当前主题的自定义系统提示词（system prompt）。可获取/设置/清除/查看状态。设置后该主题的后续对话将使用自定义提示词，清除后恢复使用全局进化版本。",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["get", "set", "clear", "status"],
                        "description": "操作类型：get=获取当前设置, set=设置新提示词, clear=清除自定义, status=查看来源",
                        "default": "get"
                    },
                    "content": {
                        "type": "string",
                        "description": "[set 操作时] 要设置的系统提示词内容"
                    }
                },
                "required": ["action"]
            }
        }
    }


def toolkit_topic_prompt(action: str = "get", content: str = "") -> str:
    """管理当前主题的自定义系统提示词。

    Args:
        action: 操作类型
            - 'get': 获取当前主题的自定义 system prompt（若无自定义则返回提示）
            - 'set': 设置当前主题的 system prompt（使用 content 参数）
            - 'clear': 清除当前主题的自定义 system prompt，恢复使用默认进化版
            - 'status': 查看当前 system prompt 的来源（主题级 vs 全局进化版）
        content: [set 操作时] 要设置的 system prompt 内容

    Returns:
        操作结果描述文本
    """
    agent = _get_agent()
    if agent is None:
        return "❌ 无法获取当前 Agent 实例"

    storage = getattr(agent, 'storage', None)
    topic_id = getattr(agent, 'current_topic_id', None)

    if not storage:
        return "❌ 当前会话无存储支持，无法管理主题级 system prompt"
    if not topic_id:
        return "❌ 当前无活跃主题"

    try:
        if action == "get":
            current = storage.get_topic_system_prompt(topic_id)
            if current:
                title = storage.get_topic(topic_id).get("title", topic_id)
                return f"📋 当前主题「{title}」的自定义系统提示词：\n\n{current}"
            else:
                title = storage.get_topic(topic_id).get("title", topic_id)
                return f"ℹ️ 当前主题「{title}」没有自定义系统提示词，使用全局进化版。"

        elif action == "set":
            if not content or not content.strip():
                return "❌ content 参数不能为空。用法：toolkit_topic_prompt(action='set', content='你的系统提示词')"
            content = content.strip()
            storage.set_topic_system_prompt(topic_id, content)
            title = storage.get_topic(topic_id).get("title", topic_id)
            prompt_len = len(content)
            return f"✅ 已设置主题「{title}」的自定义系统提示词（{prompt_len} 字符）。\n接下来的对话将使用此提示词。"

        elif action == "clear":
            storage.set_topic_system_prompt(topic_id, None)
            title = storage.get_topic(topic_id).get("title", topic_id)
            return f"✅ 已清除主题「{title}」的自定义系统提示词，恢复使用全局进化版本。"

        elif action == "status":
            topic_sp = storage.get_topic_system_prompt(topic_id)
            title = storage.get_topic(topic_id).get("title", topic_id)

            # 获取全局进化版本信息
            global_info = "（无 prompt_manager）"
            pm = getattr(agent, 'prompt_manager', None)
            if pm:
                global_info = f"v{pm.current_version} (id={pm.current_prompt_id})"

            if topic_sp:
                return (
                    f"📊 System Prompt 状态 (主题: {title})\n"
                    f"┌─────────────────────────────────────\n"
                    f"│ 来源: 主题级自定义 ✨\n"
                    f"│ 长度: {len(topic_sp)} 字符\n"
                    f"│ 全局进化版: {global_info}\n"
                    f"└─────────────────────────────────────"
                )
            else:
                return (
                    f"📊 System Prompt 状态 (主题: {title})\n"
                    f"┌─────────────────────────────────────\n"
                    f"│ 来源: 全局进化版\n"
                    f"│ 版本: {global_info}\n"
                    f"│ 说明: 使用 toolkit_topic_prompt(action='set', content=...) 设置主题自定义提示词\n"
                    f"└─────────────────────────────────────"
                )

        else:
            return f"❌ 未知操作: {action}。支持: get, set, clear, status"

    except Exception as e:
        logger.exception(f"操作失败: {e}")
        return f"❌ 操作失败: {e}"
