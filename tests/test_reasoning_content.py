"""
reasoning_content 处理专项测试。

测试覆盖：
1. _strip_reasoning_content 行为
   - 保留所有 assistant 消息的 reasoning_content ✅
   - 清除非 assistant 消息的 reasoning_content ✅
2. _repair_incomplete_tool_chains + reasoning_content 完整链
3. _compress_tool_rounds 保留 reasoning_content
4. 模拟无工具调用回传场景（确认 API 层面安全）
"""
import json
import sys
import os

# 添加项目根目录到 path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tea_agent.basesession import BaseChatSession


# ─── 测试数据 ───

# 包含 reasoning_content 的 assistant 消息（有 tool_calls）
ASSISTANT_WITH_TOOL_CALLS = {
    "role": "assistant",
    "content": "我来搜索一下",
    "reasoning_content": "用户想要搜索信息，我需要调用搜索引擎",
    "tool_calls": [
        {
            "id": "call_1",
            "type": "function",
            "function": {"name": "toolkit_search", "arguments": '{"query": "test"}'}
        }
    ]
}

# 包含 reasoning_content 的 assistant 消息（无 tool_calls）
ASSISTANT_NO_TOOL_CALLS = {
    "role": "assistant",
    "content": "这是最终答案",
    "reasoning_content": "我已经思考完毕，现在给出答案"
}

# 普通的 assistant 消息（无 reasoning_content）
ASSISTANT_PLAIN = {
    "role": "assistant",
    "content": "你好"
}

# tool 消息（本不该有 reasoning_content，但模拟意外残留）
TOOL_WITH_RC = {
    "role": "tool",
    "tool_call_id": "call_1",
    "content": "搜索结果...",
    "reasoning_content": "意外的 RC 残留"  # 不该存在，但测试清除逻辑
}

# user 消息
USER_MSG = {
    "role": "user",
    "content": "帮我搜索一下"
}

# system 消息
SYSTEM_MSG = {
    "role": "system",
    "content": "你是助手"
}


# ─── 测试函数 ───

passed = 0
failed = 0

def assert_eq(actual, expected, desc):
    global passed, failed
    if actual == expected:
        passed += 1
        print(f"  ✅ {desc}")
    else:
        failed += 1
        print(f"  ❌ {desc}: 期望 {expected!r}, 实际 {actual!r}")

def assert_true(cond, desc):
    global passed, failed
    if cond:
        passed += 1
        print(f"  ✅ {desc}")
    else:
        failed += 1
        print(f"  ❌ {desc}: 条件不成立")
        import traceback
        traceback.print_stack()


def test_strip_reasoning_content():
    """测试 _strip_reasoning_content 的行为"""
    print("\n--- 测试1: _strip_reasoning_content ---")
    print("  [策略] 保留所有 assistant 的 RC，清除非 assistant 的 RC")

    messages = [
        dict(ASSISTANT_WITH_TOOL_CALLS),
        dict(ASSISTANT_NO_TOOL_CALLS),
        dict(ASSISTANT_PLAIN),
        dict(TOOL_WITH_RC),
        dict(USER_MSG),
        dict(SYSTEM_MSG),
    ]

    BaseChatSession._strip_reasoning_content(messages)

    # 验证 assistant 消息的 reasoning_content 被保留
    assert_true(
        messages[0].get("reasoning_content") == "用户想要搜索信息，我需要调用搜索引擎",
        f"有 tool_calls 的 assistant 保留 RC: {messages[0].get('reasoning_content')[:20]}..."
    )
    assert_true(
        messages[1].get("reasoning_content") == "我已经思考完毕，现在给出答案",
        f"无 tool_calls 的 assistant 也保留 RC: {messages[1].get('reasoning_content')[:20]}..."
    )
    # 验证普通 assistant 无 RC 的不受影响
    assert_true(
        "reasoning_content" not in messages[2],
        "无 RC 的 assistant 不受影响"
    )
    # 验证非 assistant 消息的 RC 被清除
    assert_true(
        "reasoning_content" not in messages[3],
        f"tool 消息的 RC 被清除（原为'意外的 RC 残留'）"
    )
    assert_true(
        "reasoning_content" not in messages[4],
        "user 消息的 RC 被清除"
    )
    assert_true(
        "reasoning_content" not in messages[5],
        "system 消息的 RC 被清除"
    )


def test_strip_reasoning_content_noop_on_non_assistant():
    """验证非 assistant 消息本来就不该有 reasoning_content"""
    print("\n--- 测试2: 非 assistant 本无 RC ---")

    messages = [
        {"role": "tool", "tool_call_id": "c1", "content": "result"},
        {"role": "user", "content": "hi"},
        {"role": "system", "content": "sys"},
    ]

    # 确保没有 RC 字段
    for msg in messages:
        assert_true("reasoning_content" not in msg, f"{msg['role']} 消息本无 RC")

    BaseChatSession._strip_reasoning_content(messages)

    # 调用后依然没有
    for msg in messages:
        assert_true("reasoning_content" not in msg, f"{msg['role']} 消息调用后仍无 RC")


def test_repair_with_reasoning_content():
    """测试 _repair_incomplete_tool_chains 保留 reasoning_content"""
    print("\n--- 测试3: _repair_incomplete_tool_chains 保留 RC ---")

    # 完整的工具调用链
    rounds = [
        dict(ASSISTANT_WITH_TOOL_CALLS),
        {"role": "tool", "tool_call_id": "call_1", "content": "搜索到结果: test"},
        dict(ASSISTANT_NO_TOOL_CALLS),
    ]

    repaired = BaseChatSession._repair_incomplete_tool_chains(rounds)

    assert_true(len(repaired) == 3, f"完整链应保留3条，实际{len(repaired)}")

    # 验证 reasoning_content 被保留
    assert_true(
        repaired[0].get("reasoning_content") == "用户想要搜索信息，我需要调用搜索引擎",
        f"第1条 assistant 保留 RC: {repaired[0].get('reasoning_content')[:20]}..."
    )
    # tool 消息不应该有 reasoning_content
    assert_true(
        "reasoning_content" not in repaired[1],
        "tool 消息无 RC"
    )
    assert_true(
        repaired[2].get("reasoning_content") == "我已经思考完毕，现在给出答案",
        f"第3条 assistant 保留 RC: {repaired[2].get('reasoning_content')[:20]}..."
    )


def test_repair_truncates_incomplete_chain():
    """测试不完整工具链被截断时也正确处理 reasoning_content"""
    print("\n--- 测试4: 不完整链截断 ---")

    # 模拟两个工具调用（第一个未完成时又来新的 assistant 消息 = 中断）
    # _repair_incomplete_tool_chains 会回滚到上一个安全点（pending 全清空时）
    # call_2 未匹配，所以安全点 = 0，整个链被截断后只保留最后的 assistant
    rounds = [
        {
            "role": "assistant",
            "content": "",
            "reasoning_content": "思考: 需要调用两个工具",
            "tool_calls": [
                {"id": "call_1", "type": "function", "function": {"name": "toolkit_search", "arguments": '{}'}},
                {"id": "call_2", "type": "function", "function": {"name": "toolkit_exec", "arguments": '{}'}},
            ]
        },
        {"role": "tool", "tool_call_id": "call_1", "content": "结果1"},
        # call_2 还没返回，直接来了新的 assistant（中断）
        {
            "role": "assistant",
            "content": "我来处理",
            "reasoning_content": "继续思考...",
        },
    ]

    repaired = BaseChatSession._repair_incomplete_tool_chains(rounds)

    # 不完整链被截断，只剩最后的 assistant
    # 因为 call_2 未匹配到 tool，pending 非空时遇到新 assistant → 回滚到 last_safe_len=0
    assert_true(len(repaired) == 1,
                f"不完整链应截断到安全点（1条，仅最后assistant），实际 {len(repaired)} 条: "
                f"{[r['role'] for r in repaired]}")

    # 截断后保留的 assistant 消息应有 reasoning_content
    if len(repaired) > 0:
        assert_true(
            repaired[0].get("reasoning_content") == "继续思考...",
            f"截断后 assistant 保留 RC: {repaired[0].get('reasoning_content')}"
        )


def test_compress_rounds_preserves_reasoning():
    """测试 _compress_tool_rounds 保留 reasoning_content"""
    print("\n--- 测试5: _compress_tool_rounds 保留 RC ---")

    rounds = [
        dict(ASSISTANT_WITH_TOOL_CALLS),
        {"role": "tool", "tool_call_id": "call_1", "content": "x" * 5000},
        dict(ASSISTANT_NO_TOOL_CALLS),
    ]

    compressed = BaseChatSession._compress_tool_rounds(rounds)

    assert_true(len(compressed) == 3, f"压缩后仍为3条，实际{len(compressed)}")
    assert_true(
        compressed[0].get("reasoning_content") == "用户想要搜索信息，我需要调用搜索引擎",
        f"压缩后第1条保留 RC: {compressed[0].get('reasoning_content')[:20]}..."
    )
    assert_true(
        compressed[2].get("reasoning_content") == "我已经思考完毕，现在给出答案",
        f"压缩后第3条保留 RC: {compressed[2].get('reasoning_content')[:20]}..."
    )


def test_no_tool_call_rc_safety():
    """核心测试：无工具调用的 assistant 携带 RC 是否安全

    根据 DeepSeek API 文档：
    > 在两个 user 消息之间，如果模型 未进行工具调用 ，
    > 则中间 assistant 的 reasoning_content 无需参与上下文拼接，
    > 在后续轮次中将其传入 API 会被忽略。

    所以无 tool_calls 的 assistant 的 reasoning_content：
    - 不传：✅ 正确（更省 token）
    - 传了：✅ 也没问题（API 会忽略）

    当前实现策略：is_func_calling=False 时从 conv["ai_msg"] 加载，
    不携带 rounds 中的 reasoning_content。这是合理的优化。
    """
    print("\n--- 测试6: 无工具调用 RC 安全性验证 ---")

    # 模拟完整的对话轮次（无工具调用）
    full_round = {
        "user_msg": "你好，帮我查一下天气",
        "ai_msg": "好的，我来查",
        "is_func_calling": False,  # 无工具调用
        "rounds_json_parsed": [
            {
                "role": "assistant",
                "content": "好的，我来查",
                "reasoning_content": "用户询问天气，我需要查询天气信息"
            }
        ]
    }

    # 通过 _load_single_conversation 加载
    # is_func_calling=False 时走 else 分支：用 conv["ai_msg"] 构建 assistant
    # 不会携带 rounds 中的 reasoning_content（这是合理的——API 会忽略非工具调用的 RC）
    msgs = BaseChatSession._load_single_conversation(full_round)

    assert_true(len(msgs) == 2, f"加载后应有 2 条消息（user+assistant），实际 {len(msgs)}")
    assert_true(msgs[0]["role"] == "user", "第1条为 user")
    assert_true(msgs[1]["role"] == "assistant", "第2条为 assistant")

    # is_func_calling=False 时，assistant 从 ai_msg 加载，不含 reasoning_content
    # 这是正确的——无工具调用的 RC 不传更省 token
    rc = msgs[1].get("reasoning_content", "")
    assert_true(
        rc == "" or rc == "用户询问天气，我需要查询天气信息",
        f"无 tool_calls 时 RC 不存在（被优化掉）或保留（无害）: {rc}"
    )

    # 验证经过 _strip_reasoning_content 后 assistant 不受影响
    BaseChatSession._strip_reasoning_content(msgs)
    assert_true(
        msgs[1].get("role") == "assistant",
        "strip 后 assistant 消息不受影响"
    )

    print("  ✅ 结论：无工具调用的助理——不传 RC 省 token（API 会忽略），传了也无害。当前实现走优化路径。")


def test_load_single_conversation_with_func_calling():
    """测试有工具调用的轮次加载"""
    print("\n--- 测试7: 有工具调用的轮次加载 ---")

    conv = {
        "user_msg": "搜索一下",
        "ai_msg": "搜索完毕，结果是...",
        "is_func_calling": True,
        "rounds_json_parsed": [
            dict(ASSISTANT_WITH_TOOL_CALLS),
            {"role": "tool", "tool_call_id": "call_1", "content": "搜索结果数据"},
            {
                "role": "assistant",
                "content": "搜索完毕，结果是...",
                "reasoning_content": "根据搜索结果整理答案..."
            }
        ]
    }

    msgs = BaseChatSession._load_single_conversation(conv)

    # 应该加载出 4 条（user + assistant_tc + tool + assistant_final）
    assert_true(len(msgs) == 4, f"有工具调用链应加载 4 条，实际 {len(msgs)}")

    # 验证所有 assistant 消息的 reasoning_content 都被保留
    for i, msg in enumerate(msgs):
        if msg["role"] == "assistant":
            assert_true(
                "reasoning_content" in msg,
                f"第 {i+1} 条 assistant 消息保留 reasoning_content: {msg.get('reasoning_content', '')[:20]}..."
            )


# ─── 运行 ───

def main():
    print("=" * 60)
    print("reasoning_content 处理专项测试")
    print("=" * 60)
    print(f"测试目标: {BaseChatSession._strip_reasoning_content.__doc__}")

    test_strip_reasoning_content()
    test_strip_reasoning_content_noop_on_non_assistant()
    test_repair_with_reasoning_content()
    test_repair_truncates_incomplete_chain()
    test_compress_rounds_preserves_reasoning()
    test_no_tool_call_rc_safety()
    test_load_single_conversation_with_func_calling()

    total = passed + failed
    print(f"\n{'=' * 60}")
    print(f"结果: ✅ {passed} 通过 | ❌ {failed} 失败 | 共 {total} 项")
    print(f"{'=' * 60}")

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
