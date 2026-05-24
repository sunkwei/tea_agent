"""Holds a reference to the current OnlineToolSession for toolkit functions to access."""

_current_session = None
_current_agent = None

def get_session():
    """Return the current session, or None"""
    return _current_session

def set_session(sess):
    """
    Set the current session reference

    Args:
        sess: Description.
    """
    global _current_session
    _current_session = sess

def get_agent():
    """Return the current agent (GUI/CLI), or None"""
    return _current_agent

def set_agent(agent):
    """
    Set the current agent reference

    Args:
        agent: Description.
    """
    global _current_agent
    _current_agent = agent
