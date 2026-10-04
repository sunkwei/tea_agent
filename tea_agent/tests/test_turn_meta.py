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

    def test_reasoning_blanking_is_not_violation(self):
        """RC 治理性置空（_blank_stale_reasoning 跨块边界）不构成历史改写违例。

        缺陷形态：工具循环每 rc_keep_steps 步跨块边界时，框架有意把旧
        assistant 的 reasoning_content 置空以治理上下文填充。旧实现把它
        当作「历史被旁路改写」刷 ERROR（实测 prev=123→current=125 噪声）。
        """
        def _asst(content, rc, cid):
            return {"role": "assistant", "content": content,
                    "reasoning_content": rc, "tool_calls": [{"id": cid}]}

        prev = [_msg("system", "sp"), _msg("user", "u1"),
                _asst("a0", "THINK-0", "c0"),
                {"role": "tool", "content": "r0", "tool_call_id": "c0"}]
        import copy
        cur = copy.deepcopy(prev)
        cur.append(_asst("a1", "THINK-1", "c1"))
        cur.append({"role": "tool", "content": "r1", "tool_call_id": "c1"})
        # 治理性置空旧 assistant 的 RC
        for m in cur:
            if m["role"] == "assistant" and m.get("reasoning_content"):
                m["reasoning_content"] = ""

        t = TurnMetaTracker()
        t.note_request(prev)
        t.note_request(cur)
        assert t.last_violations == [], f"RC 置空是治理，不应报违例: {t.last_violations}"

    def test_real_rewrite_with_rc_field_still_violation(self):
        """对话内容被偷改（即使消息携带 RC）仍须报违例 —— 守卫不能被修瞎。"""
        t = TurnMetaTracker()
        t.note_request([_msg("system", "sp"), _msg("user", "u1"),
                        {"role": "assistant", "content": "a0",
                         "reasoning_content": "THINK"}])
        t.note_request([_msg("system", "sp"), _msg("user", "被偷改"),
                        {"role": "assistant", "content": "a0",
                         "reasoning_content": "THINK"}])
        assert t.last_violations, "对话内容改写必须报违例"
        assert "prefix_stable" in t.last_violations[0].invariant

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
