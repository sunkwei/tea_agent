"""
Tests for toolkit_subagent_msg — Sub-agent Message Passing.

Covers:
- Basic send/check_inbox/poll/clear operations
- Multiple messages and unread tracking
- Context injection (inject_messages_into_context)
- Internal API (send_message_as)
- Edge cases (empty fields, unknown actions, etc.)
"""

import pytest

# ── Fixtures ──

@pytest.fixture(autouse=True)
def clean_registry():
    """Clean message registry before and after each test."""
    from tea_agent.toolkit.toolkit_subagent_msg import _message_registry, _registry_lock
    with _registry_lock:
        _message_registry.clear()
    yield
    with _registry_lock:
        _message_registry.clear()


# ── Send / Check Inbox ──

class TestSendAndCheckInbox:
    """Send and check inbox operations."""

    def test_send_basic(self):
        """Send a basic message."""
        from tea_agent.toolkit.toolkit_subagent_msg import toolkit_subagent_msg
        result = toolkit_subagent_msg(action='send', to='agent-a', message='Hello')
        assert result.get('ok') is True
        assert result['to'] == 'agent-a'

    def test_send_and_check(self):
        """Send then check inbox."""
        from tea_agent.toolkit.toolkit_subagent_msg import toolkit_subagent_msg
        toolkit_subagent_msg(action='send', to='agent-b', message='Msg 1')
        result = toolkit_subagent_msg(action='check_inbox', agent_id='agent-b')
        assert result['total'] == 1
        assert result['unread'] == 1  # was unread before check
        assert result['messages'][0]['text'] == 'Msg 1'

    def test_multiple_messages(self):
        """Multiple messages to same recipient."""
        from tea_agent.toolkit.toolkit_subagent_msg import toolkit_subagent_msg
        for i in range(5):
            toolkit_subagent_msg(action='send', to='worker', message=f'Task {i}')
        result = toolkit_subagent_msg(action='check_inbox', agent_id='worker')
        assert result['total'] == 5
        assert len(result['messages']) == 5

    def test_separate_inboxes(self):
        """Different agents have separate inboxes."""
        from tea_agent.toolkit.toolkit_subagent_msg import toolkit_subagent_msg
        toolkit_subagent_msg(action='send', to='alice', message='For Alice')
        toolkit_subagent_msg(action='send', to='bob', message='For Bob')
        assert toolkit_subagent_msg(action='check_inbox', agent_id='alice')['total'] == 1
        assert toolkit_subagent_msg(action='check_inbox', agent_id='bob')['total'] == 1

    def test_check_marks_as_read(self):
        """check_inbox should mark messages as read."""
        from tea_agent.toolkit.toolkit_subagent_msg import toolkit_subagent_msg
        toolkit_subagent_msg(action='send', to='reader', message='Read me')
        # First check: unread > 0
        r1 = toolkit_subagent_msg(action='check_inbox', agent_id='reader')
        assert r1['unread'] == 1
        # Second check: all read now
        r2 = toolkit_subagent_msg(action='check_inbox', agent_id='reader')
        assert r2['unread'] == 0

    def test_limit_parameter(self):
        """limit parameter should cap returned messages."""
        from tea_agent.toolkit.toolkit_subagent_msg import toolkit_subagent_msg
        for i in range(10):
            toolkit_subagent_msg(action='send', to='limited', message=f'M{i}')
        result = toolkit_subagent_msg(action='check_inbox', agent_id='limited', limit=3)
        assert len(result['messages']) == 3


# ── Poll ──

class TestPoll:
    """Poll (parent collects all unread)."""

    def test_poll_empty(self):
        """Poll with no messages returns empty."""
        from tea_agent.toolkit.toolkit_subagent_msg import toolkit_subagent_msg
        result = toolkit_subagent_msg(action='poll')
        assert result['total_unread'] == 0
        assert result['agents_with_messages'] == 0

    def test_poll_unread_only(self):
        """Poll should only count unread messages."""
        from tea_agent.toolkit.toolkit_subagent_msg import toolkit_subagent_msg
        toolkit_subagent_msg(action='send', to='z', message='Unread')
        # check inbox to mark as read
        toolkit_subagent_msg(action='check_inbox', agent_id='z')
        result = toolkit_subagent_msg(action='poll')
        assert result['total_unread'] == 0

    def test_poll_multi_agent_unread(self):
        """Poll across multiple agents with unread."""
        from tea_agent.toolkit.toolkit_subagent_msg import toolkit_subagent_msg
        toolkit_subagent_msg(action='send', to='a1', message='For a1')
        toolkit_subagent_msg(action='send', to='a2', message='For a2')
        result = toolkit_subagent_msg(action='poll')
        assert result['total_unread'] == 2
        assert result['agents_with_messages'] == 2


# ── Clear ──

class TestClear:
    """Clear inbox."""

    def test_clear_existing(self):
        """Clear inbox with messages."""
        from tea_agent.toolkit.toolkit_subagent_msg import toolkit_subagent_msg
        toolkit_subagent_msg(action='send', to='clean-me', message='X')
        result = toolkit_subagent_msg(action='clear', agent_id='clean-me')
        assert result['cleared'] == 1
        inbox = toolkit_subagent_msg(action='check_inbox', agent_id='clean-me')
        assert inbox['total'] == 0

    def test_clear_empty(self):
        """Clear empty inbox should not error."""
        from tea_agent.toolkit.toolkit_subagent_msg import toolkit_subagent_msg
        result = toolkit_subagent_msg(action='clear', agent_id='nonexistent')
        assert result['cleared'] == 0


# ── Context Injection ──

class TestContextInjection:
    """Context injection from inbox."""

    def test_inject_with_messages(self):
        """Inject messages into context dict."""
        from tea_agent.toolkit.toolkit_subagent_msg import inject_messages_into_context, toolkit_subagent_msg
        toolkit_subagent_msg(action='send', to='ctx-agent', message='Important data')
        result = inject_messages_into_context('ctx-agent', {'existing_key': 'value'})
        assert '## Incoming Messages' in result
        assert 'existing_key' in result
        assert 'Important data' in result.get('## Incoming Messages', '')

    def test_inject_no_messages(self):
        """Inject without messages returns original context."""
        from tea_agent.toolkit.toolkit_subagent_msg import inject_messages_into_context
        result = inject_messages_into_context('no-msgs', {'key': 'val'})
        assert result == {'key': 'val'}

    def test_inject_none_context(self):
        """Inject with None context returns empty dict when no msgs."""
        from tea_agent.toolkit.toolkit_subagent_msg import inject_messages_into_context
        result = inject_messages_into_context('none-ctx')
        assert result == {}

    def test_inject_none_context_with_msgs(self):
        """Inject with None context returns inbox dict."""
        from tea_agent.toolkit.toolkit_subagent_msg import inject_messages_into_context, toolkit_subagent_msg
        toolkit_subagent_msg(action='send', to='n', message='Msg')
        result = inject_messages_into_context('n')
        assert '## Incoming Messages' in result

    def test_inject_marks_as_read(self):
        """Injection should mark messages as read."""
        from tea_agent.toolkit.toolkit_subagent_msg import inject_messages_into_context, toolkit_subagent_msg
        toolkit_subagent_msg(action='send', to='read-me', message='Msg')
        inject_messages_into_context('read-me')
        r = toolkit_subagent_msg(action='check_inbox', agent_id='read-me')
        assert r['unread'] == 0


# ── Internal API ──

class TestInternalAPI:
    """Internal send_message_as API."""

    def test_send_message_as(self):
        """Send message as a specific agent."""
        from tea_agent.toolkit.toolkit_subagent_msg import send_message_as, toolkit_subagent_msg
        ok = send_message_as(from_agent='agent-alpha', to='agent-beta', text='From alpha')
        assert ok is True
        inbox = toolkit_subagent_msg(action='check_inbox', agent_id='agent-beta')
        assert inbox['total'] == 1
        assert inbox['messages'][0]['from'] == 'agent-alpha'

    def test_send_message_as_empty_to(self):
        """Send to empty recipient returns False."""
        from tea_agent.toolkit.toolkit_subagent_msg import send_message_as
        ok = send_message_as(from_agent='a', to='', text='test')
        assert ok is False

    def test_get_message_stats(self):
        """get_message_stats returns correct counts."""
        from tea_agent.toolkit.toolkit_subagent_msg import get_message_stats, toolkit_subagent_msg
        toolkit_subagent_msg(action='send', to='a', message='1')
        toolkit_subagent_msg(action='send', to='b', message='2')
        stats = get_message_stats()
        assert stats.get('a') == 1
        assert stats.get('b') == 1


# ── Edge Cases ──

class TestEdgeCases:
    """Edge cases and error handling."""

    def test_unknown_action(self):
        """Unknown action returns error."""
        from tea_agent.toolkit.toolkit_subagent_msg import toolkit_subagent_msg
        result = toolkit_subagent_msg(action='nonexistent')
        assert 'error' in result

    def test_send_no_recipient(self):
        """Send without 'to' returns error."""
        from tea_agent.toolkit.toolkit_subagent_msg import toolkit_subagent_msg
        result = toolkit_subagent_msg(action='send', message='No target')
        assert 'error' in result

    def test_send_no_message(self):
        """Send without message returns error."""
        from tea_agent.toolkit.toolkit_subagent_msg import toolkit_subagent_msg
        result = toolkit_subagent_msg(action='send', to='nobody')
        assert 'error' in result

    def test_check_inbox_no_agent_id(self):
        """check_inbox without agent_id returns error."""
        from tea_agent.toolkit.toolkit_subagent_msg import toolkit_subagent_msg
        result = toolkit_subagent_msg(action='check_inbox')
        assert 'error' in result

    def test_meta_registration(self):
        """Meta function returns valid schema."""
        from tea_agent.toolkit.toolkit_subagent_msg import meta_toolkit_subagent_msg
        meta = meta_toolkit_subagent_msg()
        assert meta['type'] == 'function'
        assert meta['function']['name'] == 'toolkit_subagent_msg'
        assert 'action' in meta['function']['parameters']['properties']
        assert meta['function']['parameters']['required'] == ['action']
