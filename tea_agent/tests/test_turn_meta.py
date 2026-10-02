"""turn_meta — turn/step 生命周期与前缀缓存重置点回归测试。

核心契约：历史只允许尾部追加；前缀被改写（压缩/回滚/系统提示词变化）必须
被判为「新请求序列」—— 否则前缀缓存治理、审计回放都会失去事实依据。
"""

from __future__ import annotations

import logging

from tea_agent.turn_meta import TurnMetaTracker, same_series


def _msg(role: str, content: str) -> dict:
    return {"role": role, "content": content}


BASE = [_msg("system", "s"), _msg("user", "u1"), _msg("assistant", "a1")]


class TestSameSeries:
    def test_append_keeps_series(self):
        assert same_series(BASE, BASE + [_msg("user", "u2")]) is True

    def test_rewrite_breaks_series(self):
        changed = list(BASE[:-1]) + [_msg("assistant", "改写过的历史")]
        assert same_series(BASE, changed) is False

    def test_truncation_breaks_series(self):
        assert same_series(BASE, BASE[:2]) is False

    def test_empty_prev_is_new_series(self):
        assert same_series(None, BASE) is False
        assert same_series([], BASE) is False

    def test_field_order_is_irrelevant(self):
        a = [{"role": "user", "content": "x", "name": "n"}]
        b = [{"name": "n", "content": "x", "role": "user"}]
        assert same_series(a, b) is True


class TestTurnMetaTracker:
    def test_first_request_is_new_series(self):
        t = TurnMetaTracker()
        assert t.note_request(BASE) is True

    def test_append_continues_series(self):
        t = TurnMetaTracker()
        t.note_request(BASE)
        assert t.note_request(BASE + [_msg("user", "u2")]) is False

    def test_declared_new_series(self):
        t = TurnMetaTracker()
        t.note_request(BASE)
        assert t.note_request(BASE, declared=True) is True

    def test_summary_counts_resets(self):
        t = TurnMetaTracker()
        t.begin_turn()
        t.note_request(BASE)
        t.note_request(BASE + [_msg("user", "u2")])
        t.note_request([_msg("system", "换提示词了"), _msg("user", "u2")])
        assert t.summary() == {"turns": 1, "steps": 3, "request_series_resets": 2}

    def test_begin_turn_clears_steps(self):
        t = TurnMetaTracker()
        t.note_request(BASE)
        t.begin_turn()
        assert t.summary()["steps"] == 0
        # 跨 turn 请求序列可延续（同一话题继续追问）
        assert t.note_request(BASE + [_msg("user", "u2")]) is False


class TestPrefixStableInvariant:
    def test_rewrite_without_declaration_is_violation(self, caplog):
        t = TurnMetaTracker()
        t.note_request(BASE)
        with caplog.at_level(logging.DEBUG, logger="turn_meta"):
            t.note_request([_msg("system", "被偷改了"), _msg("user", "u1")])
        assert t.last_violations, "前缀被改写却未声明新序列，应产生违例"
        assert "startsRequestSeries" in t.last_violations[0].detail

    def test_append_is_not_violation(self):
        t = TurnMetaTracker()
        t.note_request(BASE)
        t.note_request(BASE + [_msg("user", "u2")])
        assert t.last_violations == []

    def test_declared_rewrite_is_not_violation(self):
        t = TurnMetaTracker()
        t.note_request(BASE)
        t.note_request([_msg("system", "压缩后的新前缀")], declared=True)
        assert t.last_violations == []

    def test_broken_check_never_breaks_request(self):
        from tea_agent.invariants import registry

        registry.install("test.crash", "session.request", lambda **_: 1 / 0)
        try:
            t = TurnMetaTracker()
            assert t.note_request(BASE) is True  # 不抛
            assert t.last_violations  # 检查器异常按违例记录
        finally:
            registry.uninstall("test.crash")
            assert "session.prefix_stable" in registry.names("session.request")
