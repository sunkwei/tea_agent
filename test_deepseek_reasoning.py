"""
测试 DeepSeek 推理模型的 reasoning_content 处理
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


def test_deepseek_detection():
    """测试 DeepSeek 模型检测"""
    # 创建会话实例
    session = OnlineToolSession(
        toolkit=MockToolkit(),
        api_key="test",
        api_url="http://test",
        model="deepseek-r1"
    )
    
    # 验证是否正确识别为 DeepSeek 推理模型
    assert session._is_deepseek_reasoning == True, "应该识别为 DeepSeek 推理模型"
    print("✓ DeepSeek 推理模型检测成功")
    
    # 测试非 DeepSeek 模型
    session2 = OnlineToolSession(
        toolkit=MockToolkit(),
        api_key="test",
        api_url="http://test",
        model="gpt-4"
    )
    assert session2._is_deepseek_reasoning == False, "不应该识别为 DeepSeek 推理模型"
    print("✓ 非 DeepSeek 模型检测成功")


def test_reasoning_content_handling():
    """测试 reasoning_content 处理逻辑"""
    session = OnlineToolSession(
        toolkit=MockToolkit(),
        api_key="test",
        api_url="http://test",
        model="deepseek-r1"
    )
    
    # 测试场景1: assistant 消息有 reasoning_content 和 tool_calls，且有对应的 tool 消息（应该保留）
    messages_1 = [
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
    
    processed_1 = session._handle_deepseek_reasoning_content(messages_1)
    assert "reasoning_content" in processed_1[2], "有工具调用时应保留 reasoning_content"
    assert processed_1[2]["reasoning_content"] == "deep thought", "应完整保留 reasoning_content"
    print("✓ 场景1: 有工具调用时保留 reasoning_content")
    
    # 测试场景2: assistant 消息有 reasoning_content 但没有 tool_calls（应该移除）
    messages_2 = [
        {"role": "system", "content": "test"},
        {"role": "user", "content": "hello"},
        {
            "role": "assistant",
            "content": "thinking...",
            "reasoning_content": "deep thought"
        },
        {"role": "user", "content": "next question"}
    ]
    
    processed_2 = session._handle_deepseek_reasoning_content(messages_2)
    assert "reasoning_content" not in processed_2[2], "没有工具调用时应移除 reasoning_content"
    print("✓ 场景2: 没有工具调用时移除 reasoning_content")
    
    # 测试场景3: 多轮对话混合场景
    messages_3 = [
        {"role": "system", "content": "test"},
        {"role": "user", "content": "question 1"},
        # 第1轮：有工具调用
        {
            "role": "assistant",
            "content": "let me check",
            "reasoning_content": "reasoning for tool call",
            "tool_calls": [
                {"id": "call_1", "type": "function", "function": {"name": "search", "arguments": "{}"}}
            ]
        },
        {"role": "tool", "tool_call_id": "call_1", "content": "search result"},
        {"role": "assistant", "content": "here is the result"},
        {"role": "user", "content": "question 2"},
        # 第2轮：没有工具调用
        {
            "role": "assistant",
            "content": "answering",
            "reasoning_content": "reasoning for answer"
        },
        {"role": "user", "content": "question 3"},
        # 第3轮：又有工具调用
        {
            "role": "assistant",
            "content": "let me search again",
            "reasoning_content": "reasoning for second tool",
            "tool_calls": [
                {"id": "call_2", "type": "function", "function": {"name": "search2", "arguments": "{}"}}
            ]
        },
        {"role": "tool", "tool_call_id": "call_2", "content": "result 2"}
    ]
    
    processed_3 = session._handle_deepseek_reasoning_content(messages_3)
    
    # 第1轮 assistant（索引2）有工具调用，应保留 reasoning_content
    assert "reasoning_content" in processed_3[2], "第1轮有工具调用，应保留 reasoning_content"
    assert processed_3[2]["reasoning_content"] == "reasoning for tool call"
    print("✓ 场景3.1: 第1轮有工具调用，保留 reasoning_content")
    
    # 第2轮 assistant（索引6）没有工具调用，应移除 reasoning_content
    assert "reasoning_content" not in processed_3[6], "第2轮没有工具调用，应移除 reasoning_content"
    print("✓ 场景3.2: 第2轮没有工具调用，移除 reasoning_content")
    
    # 第3轮 assistant（索引8）有工具调用，应保留 reasoning_content
    assert "reasoning_content" in processed_3[8], "第3轮有工具调用，应保留 reasoning_content"
    assert processed_3[8]["reasoning_content"] == "reasoning for second tool"
    print("✓ 场景3.3: 第3轮有工具调用，保留 reasoning_content")
    
    # 测试场景4: 非 DeepSeek 模型（不应该修改）
    session3 = OnlineToolSession(
        toolkit=MockToolkit(),
        api_key="test",
        api_url="http://test",
        model="gpt-4"
    )
    
    processed_4 = session3._handle_deepseek_reasoning_content(messages_2)
    assert "reasoning_content" in processed_4[2], "非 DeepSeek 模型不应修改消息"
    print("✓ 场景4: 非 DeepSeek 模型不修改消息")


if __name__ == "__main__":
    print("开始测试 DeepSeek 推理模型处理...")
    print()
    
    test_deepseek_detection()
    print()
    
    test_reasoning_content_handling()
    print()
    
    print("所有测试通过！✓")
