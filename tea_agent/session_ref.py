"""
全局会话引用管理器 — 供 toolkit 工具函数访问当前会话

设计说明:
- toolkit 函数由 LLM 调用，无法接收额外参数
- 需要一种机制让 toolkit 函数访问当前会话/Agent
- 使用模块级单例是合理的折中方案

安全措施:
- 提供 clear() 方法，Agent.close() 时调用
- 提供 is_active() 检查当前是否有活跃会话
- 记录设置者信息，便于调试
"""

import logging
from typing import Optional, Any

logger = logging.getLogger("session_ref")

_current_session = None
_current_agent = None
_setter_info = ""


def get_session():
    """返回当前会话，无活跃会话时返回 None。"""
    return _current_session


def set_session(sess, setter: str = ""):
    """设置当前会话引用。
    
    Args:
        sess: OnlineToolSession 实例或 None
        setter: 设置者标识（用于调试）
    """
    global _current_session
    _current_session = sess
    if sess:
        logger.debug(f"会话已设置 | setter={setter or 'unknown'}")
    else:
        logger.debug("会话已清除")


def get_agent():
    """返回当前 Agent (GUI/CLI)，无活跃 Agent 时返回 None。"""
    return _current_agent


def set_agent(agent, setter: str = ""):
    """设置当前 Agent 引用。
    
    Args:
        agent: Agent 实例或 None
        setter: 设置者标识（用于调试）
    """
    global _current_agent
    _current_agent = agent
    if agent:
        logger.debug(f"Agent 已设置 | setter={setter or 'unknown'} | mode={getattr(agent, 'mode', '?')}")
    else:
        logger.debug("Agent 已清除")


def clear():
    """清除所有引用。Agent.close() 时调用。"""
    global _current_session, _current_agent
    _current_session = None
    _current_agent = None
    logger.debug("所有引用已清除")


def is_active() -> bool:
    """检查当前是否有活跃会话。"""
    return _current_session is not None


def get_session_info() -> dict:
    """返回当前会话状态信息（用于调试）。"""
    return {
        "has_session": _current_session is not None,
        "has_agent": _current_agent is not None,
        "agent_mode": getattr(_current_agent, "mode", None) if _current_agent else None,
        "session_model": getattr(getattr(_current_session, "context", None), "model", None) if _current_session else None,
    }
