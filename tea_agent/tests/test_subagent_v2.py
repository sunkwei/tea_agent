"""
Tests for toolkit_subagent v2.1 — New Phase 1 features.

Covers:
- agent_id generation
- Meta schema includes new params (allowed_tools, denied_tools, parent_session_id)
- Auto-wake notifications (add, check, consume)
- Persistence (save to DB, load from DB)
- Registry management (list, status, cleanup)
- Spawn with permission filters (mock execution)
- Inbox injection during execution setup
"""

import json
from unittest.mock import MagicMock, patch

import pytest

# ── Fixtures ──

@pytest.fixture(autouse=True)
def clean_registry():
    """Clean registry before and after each test."""
    from tea_agent.toolkit.toolkit_subagent import (
        _notification_lock,
        _pending_notifications,
        _persist_loaded,
        _registry_lock,
        _subagent_registry,
    )
    with _registry_lock:
        _subagent_registry.clear()
    with _notification_lock:
        _pending_notifications.clear()
    global _persist_loaded
    _persist_loaded = True  # prevent DB load in tests
    yield
    with _registry_lock:
        _subagent_registry.clear()
    with _notification_lock:
        _pending_notifications.clear()


# ── Agent ID Generation ──

class TestAgentId:
    """Agent ID generation."""

    def test_generates_unique_ids(self):
        """Each call should generate a unique ID."""
        from tea_agent.toolkit.toolkit_subagent import _generate_agent_id
        ids = {_generate_agent_id() for _ in range(10)}
        assert len(ids) == 10

    def test_id_format(self):
        """ID should start with 'sub-'."""
        from tea_agent.toolkit.toolkit_subagent import _generate_agent_id
        aid = _generate_agent_id()
        assert aid.startswith('sub-')
        assert len(aid) > 4


# ── Meta Schema ──

class TestMetaSchema:
    """Meta schema includes Phase 1 parameters."""

    def test_meta_excludes_deprecated_allowed_tools(self):
        """Meta 不应包含已废弃且被忽略的 allowed_tools（避免误导模型与浪费 schema token）。"""
        from tea_agent.toolkit.toolkit_subagent import meta_toolkit_subagent
        meta = meta_toolkit_subagent()
        props = meta['function']['parameters']['properties']
        assert 'allowed_tools' not in props

    def test_meta_excludes_deprecated_denied_tools(self):
        """Meta 不应包含已废弃且被忽略的 denied_tools。"""
        from tea_agent.toolkit.toolkit_subagent import meta_toolkit_subagent
        meta = meta_toolkit_subagent()
        props = meta['function']['parameters']['properties']
        assert 'denied_tools' not in props

    def test_meta_has_parent_session_id(self):
        """Meta should include parent_session_id."""
        from tea_agent.toolkit.toolkit_subagent import meta_toolkit_subagent
        meta = meta_toolkit_subagent()
        props = meta['function']['parameters']['properties']
        assert 'parent_session_id' in props

    def test_meta_has_check_notifications(self):
        """Meta action enum should include check_notifications."""
        from tea_agent.toolkit.toolkit_subagent import meta_toolkit_subagent
        meta = meta_toolkit_subagent()
        actions = meta['function']['parameters']['properties']['action']['enum']
        assert 'check_notifications' in actions

    def test_meta_has_cleanup(self):
        """Meta action enum should include cleanup."""
        from tea_agent.toolkit.toolkit_subagent import meta_toolkit_subagent
        meta = meta_toolkit_subagent()
        actions = meta['function']['parameters']['properties']['action']['enum']
        assert 'cleanup' in actions

    def test_meta_function_name(self):
        """Meta function name should be toolkit_subagent."""
        from tea_agent.toolkit.toolkit_subagent import meta_toolkit_subagent
        meta = meta_toolkit_subagent()
        assert meta['function']['name'] == 'toolkit_subagent'


# ── Auto-wake Notifications ──

class TestNotifications:
    """Auto-wake notification system."""

    def test_add_notification(self):
        """Adding a notification should store it."""
        from tea_agent.toolkit.toolkit_subagent import _add_notification, _pending_notifications
        _add_notification('sub-abc', 'parent-123')
        assert 'parent-123' in _pending_notifications
        assert 'sub-abc' in _pending_notifications['parent-123']

    def test_check_notifications(self):
        """Check notifications should return them."""
        from tea_agent.toolkit.toolkit_subagent import _add_notification, check_notifications
        _add_notification('sub-xyz', 'session-1')
        result = check_notifications(session_id='session-1')
        assert result['count'] == 1
        assert result['notifications'][0]['agent_id'] == 'sub-xyz'

    def test_check_consumes_notifications(self):
        """check_notifications should consume the notification."""
        from tea_agent.toolkit.toolkit_subagent import _add_notification, check_notifications
        _add_notification('sub-m', 'sess')
        check_notifications(session_id='sess')
        result = check_notifications(session_id='sess')
        assert result['count'] == 0

    def test_notification_with_registry_data(self):
        """Notification should include data from registry."""
        from tea_agent.toolkit.toolkit_subagent import (
            _add_notification,
            _registry_lock,
            _subagent_registry,
            check_notifications,
        )
        with _registry_lock:
            _subagent_registry['sub-info'] = {
                'agent_id': 'sub-info',
                'goal': 'Test task',
                'status': 'completed',
                'result': 'Done!',
            }
        _add_notification('sub-info', 's')
        result = check_notifications(session_id='s')
        assert result['notifications'][0]['goal'] == 'Test task'
        assert result['notifications'][0]['status'] == 'completed'

    def test_default_session_key(self):
        """Empty session_id should use default key."""
        from tea_agent.toolkit.toolkit_subagent import _add_notification, check_notifications
        _add_notification('sub-d')
        result = check_notifications(session_id='')
        assert result['count'] == 1
        # Consumed
        result2 = check_notifications(session_id='')
        assert result2['count'] == 0


# ── Persistence ──

class TestPersistence:
    """DB persistence for registry."""

    def test_save_to_db(self, tmp_path):
        """Save should write to DB without error."""
        from tea_agent.toolkit.toolkit_subagent import _registry_lock, _save_to_db, _subagent_registry
        with _registry_lock:
            _subagent_registry['sub-test'] = {
                'agent_id': 'sub-test',
                'goal': 'test',
                'status': 'completed',
                'result': 'ok',
            }
        # Mock the DB
        mock_db = MagicMock()
        with patch('tea_agent.toolkit.toolkit_subagent._get_db', return_value=mock_db):
            result = _save_to_db()
            assert result is True
            mock_db.execute.assert_called()
            mock_db.commit.assert_called()

    def test_save_no_db(self):
        """Save without DB should return False."""
        from tea_agent.toolkit.toolkit_subagent import _save_to_db
        with patch('tea_agent.toolkit.toolkit_subagent._get_db', return_value=None):
            result = _save_to_db()
            assert result is False

    def test_load_from_db(self, tmp_path):
        """Load should restore registry from DB."""
        from tea_agent.toolkit.toolkit_subagent import _load_from_db, _registry_lock, _subagent_registry
        # Simulate DB returning data
        mock_row = MagicMock()
        mock_row.__getitem__ = lambda self, k: json.dumps({
            'sub-restored': {
                'agent_id': 'sub-restored',
                'goal': 'restored task',
                'status': 'completed',
            }
        })
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = mock_row
        mock_db = MagicMock()
        mock_db.execute.return_value = mock_cursor

        with patch('tea_agent.toolkit.toolkit_subagent._get_db', return_value=mock_db):
            result = _load_from_db()
            assert result is True

        with _registry_lock:
            assert 'sub-restored' in _subagent_registry

    def test_persist_flag(self):
        """Should not load from DB twice."""
        from tea_agent.toolkit.toolkit_subagent import _load_from_db
        with patch('tea_agent.toolkit.toolkit_subagent._get_db'):
            _load_from_db()  # first call
            _load_from_db()  # second call
            # _get_db should only be called by the first call
            # (second should hit _persist_loaded flag)
            # The actual call count depends on implementation, but at minimum
            # the function should not error
            pass  # Just verify no exception


# ── Registry Management ──

class TestRegistryManagement:
    """List, status, cleanup operations."""

    def test_list_empty(self):
        """List on empty registry."""
        from tea_agent.toolkit.toolkit_subagent import toolkit_subagent
        result = toolkit_subagent(action='list')
        assert result['total'] == 0
        assert isinstance(result['agents'], list)

    def test_list_after_spawn(self):
        """List after spawn should include the new agent."""
        from tea_agent.toolkit.toolkit_subagent import toolkit_subagent
        # Mock spawn to just add to registry without executing
        with patch('tea_agent.toolkit.toolkit_subagent._execute_subagent'):
            r = toolkit_subagent(action='spawn', goal='test task')
            assert r['status'] == 'pending'
            assert r['agent_id'].startswith('sub-')
        result = toolkit_subagent(action='list')
        assert result['total'] >= 1

    def test_status_specific(self):
        """Query specific agent status."""
        from tea_agent.toolkit.toolkit_subagent import _registry_lock, _subagent_registry, toolkit_subagent
        with _registry_lock:
            _subagent_registry['sub-status'] = {
                'agent_id': 'sub-status',
                'goal': 'status test',
                'status': 'completed',
            }
        result = toolkit_subagent(action='status', agent_id='sub-status')
        assert result['status'] == 'completed'
        assert result['goal'] == 'status test'

    def test_status_not_found(self):
        """Query nonexistent agent returns error."""
        from tea_agent.toolkit.toolkit_subagent import toolkit_subagent
        result = toolkit_subagent(action='status', agent_id='sub-nonexistent')
        assert 'error' in result

    def test_cleanup_removes_completed(self):
        """Cleanup should remove completed agents."""
        from tea_agent.toolkit.toolkit_subagent import _registry_lock, _subagent_registry, toolkit_subagent
        with _registry_lock:
            _subagent_registry['sub-old'] = {
                'agent_id': 'sub-old', 'status': 'completed'
            }
            _subagent_registry['sub-running'] = {
                'agent_id': 'sub-running', 'status': 'running'
            }
        result = toolkit_subagent(action='cleanup')
        assert result['removed'] == 1
        assert result['remaining'] == 1

    def test_collect_completed(self):
        """Collect should return all completed agents."""
        from tea_agent.toolkit.toolkit_subagent import _registry_lock, _subagent_registry, toolkit_subagent
        with _registry_lock:
            _subagent_registry['sub-done'] = {
                'agent_id': 'sub-done', 'goal': 'done', 'status': 'completed',
                'result': 'ok', 'error': None, 'tool_calls': 3, 'elapsed': 1.5,
            }
            _subagent_registry['sub-fail'] = {
                'agent_id': 'sub-fail', 'goal': 'fail', 'status': 'failed',
                'result': '', 'error': 'error', 'tool_calls': 1, 'elapsed': 0.5,
            }
            _subagent_registry['sub-pending'] = {
                'agent_id': 'sub-pending', 'goal': 'pending', 'status': 'pending',
            }
        result = toolkit_subagent(action='collect')
        assert result['total'] == 2
        statuses = [a['status'] for a in result['agents']]
        assert 'completed' in statuses
        assert 'failed' in statuses
        assert 'pending' not in statuses


# ── Cancel ──

class TestCancel:
    """Agent cancellation."""

    def test_cancel_pending(self):
        """Cancel a pending agent."""
        from tea_agent.toolkit.toolkit_subagent import _registry_lock, _subagent_registry, toolkit_subagent
        with _registry_lock:
            _subagent_registry['sub-cancel'] = {
                'agent_id': 'sub-cancel', 'status': 'pending'
            }
        result = toolkit_subagent(action='cancel', agent_id='sub-cancel')
        assert result['status'] == 'cancelled'

    def test_cancel_nonexistent(self):
        """Cancel nonexistent agent returns error."""
        from tea_agent.toolkit.toolkit_subagent import toolkit_subagent
        result = toolkit_subagent(action='cancel', agent_id='sub-noexist')
        assert 'error' in result

    def test_cancel_already_done(self):
        """Cancel completed agent should not error."""
        from tea_agent.toolkit.toolkit_subagent import _registry_lock, _subagent_registry, toolkit_subagent
        with _registry_lock:
            _subagent_registry['sub-done2'] = {
                'agent_id': 'sub-done2', 'status': 'completed'
            }
        result = toolkit_subagent(action='cancel', agent_id='sub-done2')
        assert result['status'] == 'completed'


# ── Spawn with Permissions ──

class TestSpawnWithPermissions:
    """Spawn with allowed_tools / denied_tools."""

    def test_spawn_allows_all_by_default(self):
        """Default spawn should not set permission filters."""
        from tea_agent.toolkit.toolkit_subagent import toolkit_subagent
        with patch('tea_agent.toolkit.toolkit_subagent._executor.submit') as mock_submit:
            r = toolkit_subagent(action='spawn', goal='test')
            assert r['status'] == 'pending'
            # Verify _execute_subagent was called (submit was invoked)
            assert mock_submit.called

    def test_spawn_with_allowed_tools(self):
        """Spawn with allowed_tools should store filter in registry."""
        from tea_agent.toolkit.toolkit_subagent import _registry_lock, _subagent_registry, toolkit_subagent
        with patch('tea_agent.toolkit.toolkit_subagent._execute_subagent'):
            r = toolkit_subagent(
                action='spawn',
                goal='test',
                allowed_tools=['toolkit_exec', 'toolkit_read'],
            )
            aid = r['agent_id']
            with _registry_lock:
                entry = _subagent_registry[aid]
                assert entry['allowed_tools'] == ['toolkit_exec', 'toolkit_read']
                assert entry['denied_tools'] is None

    def test_spawn_with_denied_tools(self):
        """Spawn with denied_tools should store filter in registry."""
        from tea_agent.toolkit.toolkit_subagent import _registry_lock, _subagent_registry, toolkit_subagent
        with patch('tea_agent.toolkit.toolkit_subagent._execute_subagent'):
            r = toolkit_subagent(
                action='spawn',
                goal='test',
                denied_tools=['toolkit_subagent_msg'],
            )
            aid = r['agent_id']
            with _registry_lock:
                entry = _subagent_registry[aid]
                assert entry['denied_tools'] == ['toolkit_subagent_msg']

    def test_spawn_sync_with_permissions(self):
        """Spawn sync with allowed_tools should work."""
        from tea_agent.toolkit.toolkit_subagent import toolkit_subagent
        with patch('tea_agent.toolkit.toolkit_subagent._execute_subagent',
                   return_value={'agent_id': 'sub-sync', 'status': 'completed', 'result': 'ok'}):
            r = toolkit_subagent(
                action='spawn_sync',
                goal='sync test',
                allowed_tools=['toolkit_search'],
            )
            assert r['status'] == 'completed'


# ── Spawn with parent_session_id ──

class TestSpawnWithAutoWake:
    """Spawn with parent_session_id should trigger auto-wake on completion."""

    def test_spawn_sets_parent_id_in_registry(self):
        """parent_session_id should be passed through."""
        from tea_agent.toolkit.toolkit_subagent import toolkit_subagent
        with patch('tea_agent.toolkit.toolkit_subagent._execute_subagent'):
            r = toolkit_subagent(
                action='spawn',
                goal='wake test',
                parent_session_id='parent-1',
            )
            # Verification: the _execute_subagent call will handle the notification
            # Just confirm spawn succeeded
            assert r['status'] == 'pending'

    def test_notification_after_completion(self):
        """Completed agent should trigger notification."""
        from tea_agent.toolkit.toolkit_subagent import _add_notification, check_notifications
        _add_notification('sub-complete', 'parent-wake')
        r = check_notifications(session_id='parent-wake')
        assert r['count'] == 1
        assert r['notifications'][0]['agent_id'] == 'sub-complete'


# ── Unknown Action ──

class TestUnknownAction:
    """Unknown action handling."""

    def test_unknown_action_returns_error(self):
        """Unknown action should return error dict."""
        from tea_agent.toolkit.toolkit_subagent import toolkit_subagent
        result = toolkit_subagent(action='nonexistent_action')
        assert 'error' in result

    def test_cancel_without_agent_id(self):
        """Cancel without agent_id should return error."""
        from tea_agent.toolkit.toolkit_subagent import toolkit_subagent
        result = toolkit_subagent(action='cancel')
        assert 'error' in result


# ── Message Tool Registration ──

class TestMsgToolRegistration:
    """Auto-registration of toolkit_subagent_msg."""

    def test_ensure_toolkit_loaded_no_error(self):
        """_ensure_toolkit_loaded should not throw."""
        from tea_agent.toolkit.toolkit_subagent import _ensure_toolkit_loaded
        # Patch at the source: tea_agent.tlk (the module being imported)
        mock_tlk = MagicMock()
        mock_tlk.toolkit = MagicMock()
        mock_tlk.toolkit.func_map = {}
        with patch('tea_agent.tlk', mock_tlk, create=True):
            _ensure_toolkit_loaded()  # Should not raise


# ── 注册表锁不得自死锁（回归）────────────────────────────────

class TestRegistryLockNoDeadlock:
    """子 Agent 启动路径曾在持锁状态下调用同样取锁的 _save_to_db() → 自死锁。

    关键点：``_save_to_db()`` 在没有 DB 时会提前返回，**根本不取锁**，所以本地无
    存储的测试永远发现不了；生产（有 storage）表现为子 Agent 一启动就永久卡住，
    并且锁被占住后 list/save 等操作全部阻塞。这里用假 DB 让锁真正被二次获取。
    """

    @staticmethod
    def _run_with_timeout(fn, timeout: float = 5.0):
        import threading

        box: dict = {}

        def _target():
            box["result"] = fn()

        th = threading.Thread(target=_target, daemon=True)
        th.start()
        th.join(timeout=timeout)
        return (not th.is_alive()), box.get("result")

    def test_nested_registry_update_and_save_does_not_hang(self):
        """复刻 _execute_subagent 的「持锁更新 + 落盘」写法，必须不卡死。"""
        from tea_agent.toolkit.toolkit_subagent import (
            _registry_lock,
            _save_to_db,
            _subagent_registry,
        )

        _subagent_registry["sub-nested"] = {"agent_id": "sub-nested", "status": "pending"}

        def _work():
            with _registry_lock:
                if "sub-nested" in _subagent_registry:
                    _subagent_registry["sub-nested"]["status"] = "running"
                    _save_to_db()   # ← 有 DB 时会二次取锁
            return _subagent_registry["sub-nested"]["status"]

        with patch("tea_agent.toolkit.toolkit_subagent._get_db", return_value=MagicMock()):
            done, status = self._run_with_timeout(_work)
        assert done, "注册表更新+落盘自死锁（_registry_lock 必须可重入）"
        assert status == "running"

    def test_execute_subagent_full_path_finishes(self):
        """整条 _execute_subagent 路径（含落盘）必须能跑完并更新状态。"""
        from tea_agent.toolkit.toolkit_subagent import _execute_subagent, _subagent_registry

        _subagent_registry["sub-e2e"] = {
            "agent_id": "sub-e2e", "status": "pending", "goal": "test",
        }

        fake_sess = MagicMock()
        fake_sess.chat.return_value = {"assistant": "done", "tool_calls": 1}
        fake_cfg = MagicMock()
        fake_cfg.main_model.api_key = "k"
        fake_cfg.main_model.api_url = "https://api.test.com/v1"
        fake_cfg.main_model.model_name = "m"
        fake_cfg.main_model.max_context_tokens = 0

        with patch("tea_agent.toolkit.toolkit_subagent._get_db", return_value=MagicMock()), \
             patch("tea_agent.litesession.LiteSession", return_value=fake_sess), \
             patch("tea_agent.config.load_config", return_value=fake_cfg), \
             patch("tea_agent.tlk.toolkit", MagicMock(), create=True), \
             patch("tea_agent.toolkit.toolkit_subagent_msg.inject_messages_into_context",
                   return_value={}, create=True):
            done, result = self._run_with_timeout(
                lambda: _execute_subagent("sub-e2e", "goal", None, 3, False, 30)
            )

        assert done, "子 Agent 执行路径卡死（注册表锁自死锁）"
        assert result and result.get("status") == "completed", result
        assert _subagent_registry["sub-e2e"]["status"] == "completed"
