"""
测试 reasoning_content 统一保留策略

验证所有模型的 reasoning_content 均被保留，不做移除处理。
"""
from tea_agent.onlinesession import OnlineToolSession


class MockToolkit:
    """模拟工具库"""
    def __init__(self):
        self.meta_map = {}
    
    def get_all_tools(self):
        return []
    
    def reload(self):
        pass


def test_no_deepseek_special_detection():
    """验证不再有 DeepSeek 特殊检测属性"""
    session = OnlineToolSession(
        toolkit=MockToolkit(),
        api_key="test",
        api_url="http://test",
        model="deepseek-r1"
    )
    
    # 不应再存在 _is_deepseek_reasoning 属性
    assert not hasattr(session, '_is_deepseek_reasoning'), \
        "已移除 _is_deepseek_reasoning 属性，不应存在"
    
    # 不应再存在 _handle_deepseek_reasoning_content 方法
    assert not hasattr(session, '_handle_deepseek_reasoning_content'), \
        "已移除 _handle_deepseek_reasoning_content 方法，不应存在"
    
    # 不应再存在 _check_deepseek_reasoning_model 方法
    assert not hasattr(session, '_check_deepseek_reasoning_model'), \
        "已移除 _check_deepseek_reasoning_model 方法，不应存在"
    
    print("✓ 已移除所有 DeepSeek 特殊检测逻辑")


def test_reasoning_content_always_preserved():
    """测试所有 reasoning_content 始终被保留"""
    session = OnlineToolSession(
        toolkit=MockToolkit(),
        api_key="test",
        api_url="http://test",
        model="deepseek-r1"
    )
    
    # 直接测试 _build_api_messages：消息中的 reasoning_content 应全部保留
    
    # 场景1: 有 tool_calls 的 assistant 消息，reasoning_content 应保留
    session.messages = [
        {"role": "system", "content": "test"},
        {"role": "user", "content": "hello"},
        {
            "role": "assistant",
            "content": "thinking...",
            "reasoning_content": "deep thought",
            "tool_calls": [
                {"id": "call_1", "type": "function", "function": {"name": "test", "arguments": "{}"}}
            ]
        },
        {"role": "tool", "tool_call_id": "call_1", "content": "result"},
        {"role": "user", "content": "next question"}
    ]
    
    api_msgs = session._build_api_messages()
    # 找到有 tool_calls 的 assistant 消息
    tc_msg = next(m for m in api_msgs if m.get("role") == "assistant" and m.get("tool_calls"))
    assert "reasoning_content" in tc_msg, "有 tool_calls 时应保留 reasoning_content"
    assert tc_msg["reasoning_content"] == "deep thought"
    print("✓ 场景1: 有 tool_calls 的 assistant 保留 reasoning_content")
    
    # 场景2: 无 tool_calls 的 assistant 消息，reasoning_content 也应保留
    session.messages = [
        {"role": "system", "content": "test"},
        {"role": "user", "content": "hello"},
        {
            "role": "assistant",
            "content": "answering",
            "reasoning_content": "thinking for answer"
        },
        {"role": "user", "content": "next question"}
    ]
    
    api_msgs = session._build_api_messages()
    no_tc_msg = next(m for m in api_msgs if m.get("role") == "assistant" and not m.get("tool_calls"))
    assert "reasoning_content" in no_tc_msg, "无 tool_calls 时也应保留 reasoning_content"
    assert no_tc_msg["reasoning_content"] == "thinking for answer"
    print("✓ 场景2: 无 tool_calls 的 assistant 也保留 reasoning_content")
    
    # 场景3: 多轮混合对话，所有 reasoning_content 均应保留
    session.messages = [
        {"role": "system", "content": "test"},
        {"role": "user", "content": "q1"},
        {
            "role": "assistant",
            "content": "let me check",
            "reasoning_content": "reasoning for tool",
            "tool_calls": [
                {"id": "call_1", "type": "function", "function": {"name": "search", "arguments": "{}"}}
            ]
        },
        {"role": "tool", "tool_call_id": "call_1", "content": "result"},
        {"role": "assistant", "content": "here is answer"},
        {"role": "user", "content": "q2"},
        {
            "role": "assistant",
            "content": "answering directly",
            "reasoning_content": "reasoning for answer"
        },
        {"role": "user", "content": "q3"}
    ]
    
    api_msgs = session._build_api_messages()
    assistants = [m for m in api_msgs if m.get("role") == "assistant"]
    
    for i, a in enumerate(assistants):
        if "reasoning_content" in a or "tool_calls" in a:
            if "reasoning_content" in a:
                print(f"✓ 场景3: assistant[{i}] 保留 reasoning_content: {a['reasoning_content'][:40]}...")
    
    # 验证两个 reasoning_content 都在
    reasoning_msgs = [m for m in api_msgs if m.get("role") == "assistant" and "reasoning_content" in m]
    assert len(reasoning_msgs) == 2, f"应有两个 assistant 消息包含 reasoning_content，实际: {len(reasoning_msgs)}"
    print("✓ 场景3: 多轮混合对话，所有 reasoning_content 均保留")


if __name__ == "__main__":
    print("开始测试 reasoning_content 统一保留策略...")
    print()
    
    test_no_deepseek_special_detection()
    print()
    
    test_reasoning_content_always_preserved()
    print()
    
    print("所有测试通过！✓")
