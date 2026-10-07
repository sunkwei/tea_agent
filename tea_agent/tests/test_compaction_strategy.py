"""压缩策略可插拔回归测试。"""

from __future__ import annotations

from tea_agent import auto_compact as ac


def _msgs(n=20):
    return [{"role": "user" if i % 2 == 0 else "assistant", "content": f"m{i}"} for i in range(n)]


def test_default_is_truncate_strategy():
    assert ac.get_compaction_strategy() is ac.truncate_compact_messages


def test_compact_messages_delegates_to_registered_strategy():
    calls = {}

    def fake(messages, keep_recent=5, summary="", max_summary_length=1500):
        calls["hit"] = True
        return [], "S"

    ac.register_compaction_strategy(fake)
    try:
        out, s = ac.compact_messages(_msgs())
        assert calls.get("hit") is True
        assert out == [] and s == "S"
    finally:
        ac.register_compaction_strategy(None)


def test_truncate_strategy_contract():
    msgs = [{"role": "system", "content": "SP"}] + _msgs(20)
    out, summary = ac.truncate_compact_messages(msgs, keep_recent=2)
    assert out[0]["role"] == "system" and out[0]["content"] == "SP"
    assert out[1]["role"] == "system" and "历史摘要" in out[1]["content"]
    assert len(out) == 2 + 4  # sys + 摘要 + 2*2 recent
    assert summary


def test_truncate_strategy_empty_and_short():
    assert ac.truncate_compact_messages([], 5, "") == ([], "")
    msgs = _msgs(3)
    out, s = ac.truncate_compact_messages(msgs, keep_recent=5)
    assert out == msgs and s == ""
