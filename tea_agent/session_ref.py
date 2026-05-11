# @2026-04-29 gen by deepseek-v4-pro, 全局会话引用供 toolkit 工具访问
"""Holds a reference to the current OnlineToolSession for toolkit functions to access."""

_current_session = None
_current_agent = None

# NOTE: 2026-05-08 09:19:44, self-evolved by tea_agent --- 增加 agent 引用，供 toolkit 函数访问 current_topic_id / db

def get_session():
    """Return the current session, or None."""
    return _current_session


def set_session(sess):
    """Set the current session reference."""
    global _current_session
    _current_session = sess


def get_agent():
    """Return the current agent (GUI/CLI), or None."""
    return _current_agent


def set_agent(agent):
    """Set the current agent reference."""
    global _current_agent
    _current_agent = agent
