"""P2 事件溯源（Append-only Session Event Log）回归测试。

覆盖：
- 事件 append（turn/start, user/message, assistant/message, turn/end, tool/*）
- seq 递增 + 只追加（无 UPDATE/DELETE 接口）
- derive_messages 派生视图（Model-visible means logged）
- replay 完整重放
- fork_events 血统复制（payload._fork_source）
- stats 统计
- 与 conversations 表共存（渐进式改造，不破坏现有存储）
"""

import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from tea_agent.store._core import Storage  # noqa: E402


@pytest.fixture
def storage():
    """临时数据库 Storage 实例。"""
    db_path = os.path.join(tempfile.mkdtemp(), "test_events.db")
    st = Storage(db_path)
    yield st
    try:
        st.close()
    except Exception:
        pass


def test_append_and_seq(storage):
    """事件 append：seq 严格递增。"""
    tid = storage.topics.create_topic("ES")
    s1 = storage.events.append_event(tid, "turn/start", {})
    s2 = storage.events.append_event(tid, "user/message", {"content": "hi"})
    s3 = storage.events.append_event(tid, "assistant/message", {"content": "hello"})
    assert s1 == 1 and s2 == 2 and s3 == 3


def test_append_only_no_update_delete(storage):
    """审计约束：事件表无 UPDATE/DELETE 公开接口。"""
    assert not hasattr(storage.events, "update_event")
    assert not hasattr(storage.events, "delete_event")


def test_save_msg_records_turn_events(storage):
    """save_msg + update_msg_rounds 自动记录完整事件链。"""
    tid = storage.topics.create_topic("ES")
    cid = storage.conversations.save_msg(tid, "问题", "", False)
    storage.conversations.update_msg_rounds(
        cid, "答案", True,
        [{"role": "assistant", "content": "答案",
          "tool_calls": [{"function": {"name": "toolkit_search", "arguments": "{}"}}]}],
    )
    events = storage.events.replay(tid)
    types = [e["event_type"] for e in events]
    assert types == ["turn/start", "user/message", "assistant/message", "turn/end"]
    # assistant/message 的 payload 含 tool_calls 概览
    asst = [e for e in events if e["event_type"] == "assistant/message"][0]
    assert asst["payload"]["tool_calls"][0]["name"] == "toolkit_search"


def test_derive_messages(storage):
    """派生视图：从事件流 fold 出消息历史（审计核心能力）。"""
    tid = storage.topics.create_topic("ES")
    cid = storage.conversations.save_msg(tid, "用户问题", "", False)
    storage.conversations.update_msg_rounds(cid, "AI回答", False)
    msgs = storage.events.derive_messages(tid)
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert msgs[0]["content"] == "用户问题"
    assert msgs[1]["content"] == "AI回答"


def test_replay_order(storage):
    """重放保持 seq 顺序。"""
    tid = storage.topics.create_topic("ES")
    for i in range(5):
        storage.events.append_event(tid, "user/message", {"content": f"m{i}"})
    evs = storage.events.replay(tid)
    assert [e["seq"] for e in evs] == list(range(1, 6))
    assert [e["payload"]["content"] for e in evs] == [f"m{i}" for i in range(5)]


def test_fork_events_lineage(storage):
    """fork 事件复制：保留 _fork_source 血统。"""
    src = storage.topics.create_topic("源")
    storage.conversations.save_msg(src, "u", "", False)
    storage.events.append_event(src, "tool/call", {"name": "toolkit_x"})
    storage.topics.create_topic("分支", topic_id="fork1")
    n = storage.events.fork_events(src, "fork1")
    assert n == 3  # turn/start + user/message + tool/call
    evs = storage.events.replay("fork1")
    assert len(evs) == 3
    for e in evs:
        assert e["payload"]["_fork_source"]["topic_id"] == src


def test_stats(storage):
    """事件统计。"""
    tid = storage.topics.create_topic("ES")
    storage.events.append_event(tid, "tool/call", {"name": "a"})
    storage.events.append_event(tid, "tool/call", {"name": "b"})
    storage.events.append_event(tid, "tool/result", {"result": "x"})
    stats = storage.events.stats(tid)
    assert stats["total"] == 3
    assert stats["by_type"]["tool/call"] == 2
    assert stats["by_type"]["tool/result"] == 1


def test_coexists_with_conversations(storage):
    """渐进式改造：事件日志与 conversations 共存，互不干扰。"""
    tid = storage.topics.create_topic("ES")
    cid = storage.conversations.save_msg(tid, "你好", "", False)
    storage.conversations.update_msg_rounds(cid, "你好！", False)
    convs = storage.conversations.get_conversations(tid, limit=0)
    events = storage.events.replay(tid)
    assert len(convs) == 1
    assert len(events) == 4
    assert convs[0]["user_msg"] is not None


def test_message_fork_boundary(storage):
    """message fork：boundary 截断事件流到指定消息轮。"""
    src = storage.topics.create_topic("源")
    c1 = storage.conversations.save_msg(src, "轮1", "", False)
    storage.conversations.update_msg_rounds(c1, "答1", False)
    c2 = storage.conversations.save_msg(src, "轮2", "", False)
    storage.conversations.update_msg_rounds(c2, "答2", False)
    storage.events.append_event(src, "tool/call", {"name": "toolkit_x"})
    assert storage.events.stats(src)["total"] == 9

    storage.topics.create_topic("分支", topic_id="mf1")
    n = storage.events.fork_events(src, "mf1", boundary_conv_id=c2)
    evs = storage.events.replay("mf1")
    assert n == 8  # 两轮 × 4 事件，tool/call(seq9) 被截断
    assert not any(e["event_type"] == "tool/call" for e in evs)
    assert all(e["payload"]["_fork_source"]["topic_id"] == src for e in evs)

    # 无 boundary → 全量
    storage.topics.create_topic("分支2", topic_id="mf2")
    assert storage.events.fork_events(src, "mf2") == 9


def _mk_ctx_with_level2():
    """构造带 L2 数据 + 一条用户消息的 SessionContext。"""
    from tea_agent.session.context import SessionContext

    ctx = SessionContext()
    ctx._level2 = [
        {"user": "讨论缓存命中率", "assistant": "缓存是前缀命中", "files": []},
        {"user": "天气怎么样", "assistant": "晴天", "files": []},
        {"user": "代码审查", "assistant": "有3个问题", "files": []},
    ]
    ctx.messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "缓存命中率如何优化"},
    ]
    ctx.supports_reasoning = False
    ctx.supports_vision = False
    ctx.disable_summary = False
    ctx.disable_l2 = False
    ctx.disable_l3 = False
    ctx.max_context_tokens = 0
    ctx.model = "deepseek-v4"
    ctx._last_estimate_tokens = 0
    ctx._last_request_prompt_tokens = 0
    return ctx


def test_level2_solidify_stable_in_tool_loop():
    """S1-A: L2 入库定型——工具循环内多轮请求复用同一版本（缓存稳定）。"""
    from tea_agent.session.history_builder import build_api_messages

    ctx = _mk_ctx_with_level2()
    r1 = build_api_messages(ctx, "test")
    l2_1 = [m for m in r1 if str(m.get("content", "")).startswith(("[历史", "[历史相关"))]
    assert ctx._level2_dirty is False  # 首次构建即定型
    assert ctx._level2_selected is not None

    # 工具循环内追加 assistant 消息后再请求 → 必须复用定型版本
    ctx.messages.append({"role": "assistant", "content": "答"})
    r2 = build_api_messages(ctx, "test")
    l2_2 = [m for m in r2 if str(m.get("content", "")).startswith(("[历史", "[历史相关"))]
    assert len(l2_1) == len(l2_2), f"L2 必须稳定: {len(l2_1)} vs {len(l2_2)}"


def test_level2_recompute_on_new_message():
    """S1-A: 新用户消息边界置 dirty → 重算并重新定型。"""
    from tea_agent.session.history_builder import _solidify_level2

    ctx = _mk_ctx_with_level2()
    first = _solidify_level2(ctx)
    assert ctx._level2_dirty is False

    # 新消息到来（add_user_message 会置 dirty）
    ctx.messages.append({"role": "user", "content": "天气怎么样"})
    ctx._level2_dirty = True
    second = _solidify_level2(ctx)
    assert ctx._level2_dirty is False
    assert ctx._level2_selected is second  # 引用更新
    # 新消息聚焦天气 → 选中集合应与首次不同（命中天气条目）
    texts = [str(p.get("user", "") or p.get("content", "")) for p in second]
    assert any("天气" in t for t in texts), f"应命中天气条目: {texts}"


def test_trim_reasoning_solidified():
    """S2: 策略3 清空 reasoning 时回写 context 定型，预算波动不翻转。"""
    from tea_agent.session.context import SessionContext
    from tea_agent.session.history_builder import _progressive_trim

    ctx = SessionContext()
    rc = "思考" * 300
    ctx.messages = [
        {"role": "system", "content": "s"},
        {"role": "assistant", "content": "a" * 200, "reasoning_content": rc},
        {"role": "user", "content": "再来"},
    ]

    def build(start_idx=1):
        out = []
        for i in range(start_idx, len(ctx.messages)):
            mc = dict(ctx.messages[i])
            mc["_src_idx"] = i
            out.append(mc)
        return out

    # 预算宽松 → 完整 reasoning 发送
    r1 = _progressive_trim(build(), 5000, ctx, tool_prune_threshold=100)
    assert [m["reasoning_content"] for m in r1 if m.get("reasoning_content")][0] == rc
    assert ctx.messages[1]["reasoning_content"] == rc  # 源不被误清空

    # 预算紧张 → 清空 + 回写 context 定型
    _progressive_trim(build(), 200, ctx, tool_prune_threshold=100)
    assert not [m for m in ctx.messages if m.get("reasoning_content")]

    # 预算恢复宽松 → 读到的已是空，形态收敛（不发完整版）
    r3 = _progressive_trim(build(), 5000, ctx, tool_prune_threshold=100)
    assert not [m for m in r3 if m.get("reasoning_content")]

    # 已定型截断版 reasoning 不被清空
    ctx2 = SessionContext()
    rc2 = "x" * 9000 + "\n... [已截断: 原长 10000 字符]"
    ctx2.messages = [
        {"role": "system", "content": "s"},
        {"role": "assistant", "content": "a", "reasoning_content": rc2},
        {"role": "user", "content": "再来"},
    ]
    r4 = _progressive_trim(
        [dict(ctx2.messages[i], **{"_src_idx": i}) for i in range(1, len(ctx2.messages))],
        200, ctx2, tool_prune_threshold=100,
    )
    assert [m["reasoning_content"] for m in r4 if m.get("reasoning_content")][0] == rc2


def test_emergency_trim_solidified():
    """S2-B: 最终保护紧急截断回写 context 定型，预算波动不翻转。"""
    from tea_agent.session.context import SessionContext
    from tea_agent.session.history_builder import _progressive_trim

    ctx = SessionContext()
    long_user = "字" * 3000  # 超长最后一条消息(如粘贴代码)
    ctx.messages = [{"role": "system", "content": "s"}, {"role": "user", "content": long_user}]

    def _build_result():
        return [dict(ctx.messages[i], **{"_src_idx": i}) for i in range(1, len(ctx.messages))]

    # 请求1: 极小预算 → 触发最终保护紧急截断 + 回写
    _progressive_trim(_build_result(), 50, ctx, tool_prune_threshold=100)
    ctx_c = ctx.messages[1]["content"]
    assert "[紧急截断" in ctx_c, "紧急截断必须回写 context"

    # 请求2: 预算恢复 → 必须读截断版, 不再从完整版重来
    r2 = _progressive_trim(_build_result(), 50000, ctx, tool_prune_threshold=100)
    r2_c = [m["content"] for m in r2 if m.get("role") == "user"][0]
    assert "[紧急截断" in r2_c and len(r2_c) < 1500, "回写后不得恢复完整版"

    # 请求3: 仍紧张 → 幂等守卫不再二次截断
    r3 = _progressive_trim(_build_result(), 50, ctx, tool_prune_threshold=100)
    r3_c = [m["content"] for m in r3 if m.get("role") == "user"][0]
    assert r3_c == r2_c, "幂等守卫失败: 截断版被二次改写"
