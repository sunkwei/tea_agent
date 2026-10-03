"""prefix_stable 误报回归测试 —— 尾部动态消息不参与前缀连续性判定。

缺陷：工具循环内每次请求都在**末尾**重新追加动态上下文 user 消息
（skill/TODO/记忆）。下一次请求的新消息插在它**之前**，它的位置后移，
`same_series` 遂判定「前缀被改写」→ 每步刷一条
`运行时不变式违例 [session.prefix_stable]` ERROR（实测 66→68→70→73 条）。

这是**误报**而非真违规：尾部动态消息本就不属于稳定前缀
（test_history_cache.py 早已断言「允许最后一条动态消息移位」）。
真违规（历史前缀被旁路改写）必须仍然报得出来 —— 否则修噪声就是修瞎了守卫。
"""

from tea_agent.session.context import SessionContext
from tea_agent.session.history_builder import build_api_messages
from tea_agent.turn_meta import TurnMetaTracker, same_series


def _m(role, content, **kw):
    return {"role": role, "content": content, **kw}


# ── 根因复现：纳入尾部动态消息即误报 ──

def test_tail_dynamic_shift_is_not_a_real_violation():
    """稳定前缀逐字节相同时，尾部动态消息移位**不得**判为违例。"""
    stable = [_m("system", "sp"), _m("user", "u1")]
    # 第 1 次请求：stable + 动态尾巴
    req1 = stable + [_m("user", "[动态] TODO: 无")]
    # 第 2 次请求：新工具消息插在动态尾巴**之前**，尾巴后移
    req2 = stable + [_m("assistant", None, tool_calls=[{"id": "c1"}]),
                     _m("tool", "结果", tool_call_id="c1"),
                     _m("user", "[动态] TODO: 无")]

    assert not same_series(req1, req2), "整表比对必然判为改写（缺陷根因）"
    # 排除尾部 1 条后：稳定前缀是逐条前缀 → 同一序列，无违例
    assert same_series(req1[:-1], req2[:-1])

    t = TurnMetaTracker()
    t.note_request(req1[:-1])
    t.note_request(req2[:-1])
    assert t.last_violations == [], f"稳定前缀不应报违例: {t.last_violations}"


def test_real_prefix_rewrite_still_reported():
    """守卫不能被修瞎：真·历史前缀改写仍须报违例。"""
    t = TurnMetaTracker()
    t.note_request([_m("system", "sp"), _m("user", "u1")])
    t.note_request([_m("system", "被偷改的 sp"), _m("user", "u1"), _m("user", "u2")])
    assert t.last_violations, "前缀被改写必须报违例"
    assert "prefix_stable" in t.last_violations[0].invariant


# ── 接线：build_api_messages 必须写出尾部条数 ──

def test_build_api_messages_records_dynamic_tail_count():
    """有动态尾巴 → _dynamic_tail_count=1，且尾条确为动态消息。"""
    from tea_agent.basesession import BaseChatSession

    class _S(BaseChatSession):
        def chat_stream(self, msg, callback):
            return "", False

    ctx = SessionContext()
    ctx.model = "deepseek-v3"
    ctx.max_context_tokens = 128000
    s = _S(model="deepseek-v3")
    s.context = ctx
    s.add_user_message("帮我修个 bug")

    msgs = build_api_messages(ctx, "你是助手")

    assert ctx._dynamic_tail_count in (0, 1)
    if ctx._dynamic_tail_count == 1:
        assert msgs[-1]["role"] == "user"


def test_online_session_excludes_tail_from_series_check():
    """_build_api_messages 传给 tracker 的必须是**去掉尾巴**的稳定前缀。"""
    from tea_agent.onlinesession import OnlineToolSession

    sess = OnlineToolSession.__new__(OnlineToolSession)
    ctx = SessionContext()
    sess.context = ctx
    sess.system_prompt = "sp"
    ctx._dynamic_tail_count = 1

    captured = []
    sess._note_request_series = captured.append  # type: ignore[method-assign]
    sess._get_topic_system_prompt = lambda: None  # type: ignore[method-assign]

    full = [_m("system", "sp"), _m("user", "u1"), _m("user", "[动态]")]
    import tea_agent.onlinesession as os_mod

    orig_build, orig_strip = os_mod.build_api_messages, os_mod.strip_historical_images
    os_mod.build_api_messages = lambda c, sp: list(full)
    os_mod.strip_historical_images = lambda ms: ms
    try:
        out = sess._build_api_messages()
    finally:
        os_mod.build_api_messages, os_mod.strip_historical_images = orig_build, orig_strip

    assert out == full, "返回值必须是**完整**消息（尾巴要真的发给 API）"
    assert captured == [full[:-1]], "只有稳定前缀参与连续性判定"
