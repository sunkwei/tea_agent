"""
全局会话引用管理器 — 供 toolkit 工具函数访问当前会话。

设计说明：
- toolkit 函数由 LLM 调用，无法接收额外参数
- 需要一种机制让 toolkit 函数访问当前会话/Agent
- 使用模块级单例是合理的折中方案

安全措施：
- clear() 方法可在 Agent.close() 时调用
- is_active() 检查当前是否有活跃会话
- 记录设置者信息，便于调试

用法:
    from tea_agent import session_ref
    sess = session_ref.get_session()
    agent = session_ref.get_agent()
    info = session_ref.get_session_info()
"""

from __future__ import annotations

import logging
import threading
from typing import Any

logger = logging.getLogger("session_ref")

__all__ = [
    "get_session",
    "set_session",
    "get_agent",
    "set_agent",
    "clear",
    "is_active",
    "get_session_info",
]

_current_session: Any = None
_current_agent: Any = None
_setter_info: str = ""
_session_ref_lock = threading.Lock()


def get_session() -> Any:
    """返回当前会话实例，无活跃会话时返回 None。

    Returns:
        OnlineToolSession 或 LiteSession 实例，或 None
    """
    with _session_ref_lock:
        return _current_session


def set_session(sess: Any, setter: str = "") -> None:
    """设置当前会话引用。通常由 Agent.__init__ 调用。

    Args:
        sess: OnlineToolSession/LiteSession 实例或 None
        setter: 设置者标识字符串（用于调试），如 "Agent(lightweight)"
    """
    global _current_session
    with _session_ref_lock:
        _current_session = sess
    if sess is not None:
        logger.debug(f"会话已设置 | setter={setter or 'unknown'}")
    else:
        logger.debug("会话已清除")


def get_agent() -> Any:
    """返回当前 Agent 实例（GUI/CLI），无活跃 Agent 时返回 None。

    Returns:
        Agent 实例或 None
    """
    with _session_ref_lock:
        return _current_agent


def set_agent(agent: Any, setter: str = "") -> None:
    """设置当前 Agent 引用。通常由 Agent.__init__ 调用。

    Args:
        agent: Agent 实例或 None
        setter: 设置者标识字符串
    """
    global _current_agent
    with _session_ref_lock:
        _current_agent = agent
    if agent is not None:
        logger.debug(
            f"Agent 已设置 | setter={setter or 'unknown'} | "
            f"mode={getattr(agent, 'mode', '?')}"
        )
    else:
        logger.debug("Agent 已清除")


def clear() -> None:
    """清除所有会话和 Agent 引用。Agent.close() 时调用。"""
    global _current_session, _current_agent
    with _session_ref_lock:
        _current_session = None
        _current_agent = None
    logger.debug("所有引用已清除")


def is_active() -> bool:
    """检查当前是否有活跃会话。

    Returns:
        True 表示有活跃会话
    """
    with _session_ref_lock:
        return _current_session is not None


def get_session_info() -> dict[str, Any]:
    """返回当前会话状态信息（用于调试和监控）。

    Returns:
        包含 has_session / has_agent / agent_mode / session_model 的字典
    """
    with _session_ref_lock:
        current_session = _current_session
        current_agent = _current_agent
    return {
        "has_session": current_session is not None,
        "has_agent": current_agent is not None,
        "agent_mode": getattr(current_agent, "mode", None) if current_agent else None,
        "session_model": (
            getattr(getattr(current_session, "context", None), "model", None)
            if current_session else None
        ),
    }
