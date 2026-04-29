# @2026-04-29 gen by deepseek-v4-pro, 全局会话引用供 toolkit 工具访问
"""Holds a reference to the current OnlineToolSession for toolkit functions to access."""

_current_session = None


def get_session():
    """Return the current session, or None."""
    return _current_session


def set_session(sess):
    """Set the current session reference."""
    global _current_session
    _current_session = sess
