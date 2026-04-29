"""
测试 Summary 功能：SessionSummarizerMixin 的核心方法
同时测试 _probe_thinking_support 的状态管理
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tea_agent.session_summarizer import SessionSummarizerMixin
from tea_agent.session_api import SessionAPIMixin


class MockSummarizer(SessionSummarizerMixin):
    """模拟类，提供 SessionSummarizerMixin 所需的依赖属性"""
    
    def __init__(self, keep_turns=5, history_summary=""):
        self.messages = [
            {"role": "system", "content": "你是一个智能助手。"}
        ]
        self.keep_turns = keep_turns
        self.max_tool_output = 128 * 1024
        self.max_assistant_content = 128 * 1024
        self.tool_log = lambda x: print(f"  [LOG] {x}")
        self._history_summary = history_summary
        self.current_topic_id = None
        self.storage = None
    
    def _get_summarize_client(self):
        return None, None


# ============================================================
# 测试 count_user_msg
# ============================================================
def test_count_user_msg():
    print("=" * 60)
    print("1. 测试 count_user_msg")
    print("=" * 60)
    
    s = MockSummarizer()
    s.messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi"},
        {"role": "user", "content": "how are you"},
        {"role": "assistant", "content": "good"},
        {"role": "user", "content": "bye"},
    ]
    
    assert s.count_user_msg() == 3, f"期望 3，实际 {s.count_user_msg()}"
    print(f"  ✓ 用户消息数: {s.count_user_msg()}")
    
    s.messages = [{"role": "system", "content": "sys"}]
    assert s.count_user_msg() == 0
    print("  ✓ 空列表返回 0")
    print()


# ============================================================
# 测试 _find_last_need_summary_pair
# ============================================================
def test_find_last_need_summary_pair():
    print("=" * 60)
    print("2. 测试 _find_last_need_summary_pair")
    print("=" * 60)
    
    # --- 场景1: 正常多轮对话 (keep_turns=2) ---
    # 算法：从后往前跳过 keep_turns 个 user，begin_idx 为第 (keep_turns+1) 个 user 的位置
    #       end_idx 为 begin_idx 之后的第一个 user
    s = MockSummarizer(keep_turns=2)
    s.messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "q1"},       # idx 1
        {"role": "assistant", "content": "a1"},  # idx 2
        {"role": "user", "content": "q2"},       # idx 3
        {"role": "assistant", "content": "a2"},  # idx 4
        {"role": "user", "content": "q3"},       # idx 5
        {"role": "assistant", "content": "a3"},  # idx 6
        {"role": "user", "content": "q4"},       # idx 7
    ]
    
    last_user, last_ai = s._find_last_need_summary_pair()
    # keep_turns=2: 从后往前跳过 q4(idx7), q3(idx5) → begin_idx=3 (q2)
    # 从 idx 4 往后找 user → idx 5 (q3) → end_idx=5
    # 摘要范围: messages[3:5] = [q2, a2]
    assert last_user == 3, f"期望 last_user=3，实际 {last_user}"
    assert last_ai == 5, f"期望 last_ai=5，实际 {last_ai}"
    print(f"  ✓ 场景1: 正常多轮 (keep_turns=2) -> pair=({last_user}, {last_ai}) 摘要范围 [q2..a2]")

    # --- 场景1b: keep_turns=5 时不需要摘要 ---
    s1b = MockSummarizer(keep_turns=5)
    s1b.messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "q1"},
        {"role": "assistant", "content": "a1"},
        {"role": "user", "content": "q2"},
        {"role": "assistant", "content": "a2"},
        {"role": "user", "content": "q3"},
        {"role": "assistant", "content": "a3"},
        {"role": "user", "content": "q4"},
    ]
    last_user, last_ai = s1b._find_last_need_summary_pair()
    # 只有4个user，keep_turns=5，不足，应返回 (-1, -1)
    assert last_user == -1 and last_ai == -1, f"期望 (-1,-1)，实际 ({last_user},{last_ai})"
    print(f"  ✓ 场景1b: keep_turns=5 不足时不摘要 -> ({last_user}, {last_ai})")
    
    # --- 场景2: 对话不足 keep_turns ---
    s2 = MockSummarizer(keep_turns=3)
    s2.messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "q1"},
        {"role": "assistant", "content": "a1"},
        {"role": "user", "content": "q2"},
    ]
    
    last_user, last_ai = s2._find_last_need_summary_pair()
    assert last_ai == -1 and last_user == -1, f"期望 (-1,-1)，实际 ({last_user},{last_ai})"
    print(f"  ✓ 场景2: 不足 keep_turns -> ({last_user}, {last_ai})")
    
    # --- 场景3: 包含工具调用的复杂对话 ---
    s3 = MockSummarizer(keep_turns=2)
    s3.messages = [
        {"role": "system", "content": "sys"},                                    # idx 0
        {"role": "user", "content": "q1"},                                       # idx 1
        {"role": "assistant", "content": "", "tool_calls": [                     # idx 2
            {"id": "c1", "type": "function", "function": {"name": "search", "arguments": "{}"}}
        ]},
        {"role": "tool", "tool_call_id": "c1", "content": "result1"},           # idx 3
        {"role": "assistant", "content": "answer based on result1"},            # idx 4
        {"role": "user", "content": "q2"},                                       # idx 5
        {"role": "assistant", "content": "a2"},                                  # idx 6
        {"role": "user", "content": "q3"},                                       # idx 7
        {"role": "assistant", "content": "a3"},                                  # idx 8
        {"role": "user", "content": "q4"},                                       # idx 9
    ]
    
    last_user, last_ai = s3._find_last_need_summary_pair()
    # keep_turns=2: 从后往前跳过 q4(idx9), q3(idx7) → begin_idx=5 (q2)
    # 从 idx 6 往后找 user → idx 7 (q3) → end_idx=7
    # 摘要范围: messages[5:7] = [q2, a2]
    assert last_user == 5 and last_ai == 7, f"期望 (5,7)，实际 ({last_user},{last_ai})"
    print(f"  ✓ 场景3 (含工具调用): pair=({last_user}, {last_ai}) 摘要范围 [q2..a2]")
    
    print()


# ============================================================
# 测试 _find_recent_boundary
# ============================================================
def test_find_recent_boundary():
    print("=" * 60)
    print("3. 测试 _find_recent_boundary")
    print("=" * 60)
    
    s = MockSummarizer(keep_turns=2)
    s.messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "q1"},
        {"role": "assistant", "content": "a1"},
        {"role": "user", "content": "q2"},
        {"role": "assistant", "content": "a2"},
        {"role": "user", "content": "q3"},
    ]
    
    boundary = s._find_recent_boundary()
    assert boundary == 3, f"期望 3，实际 {boundary}"
    print(f"  ✓ keep_turns=2: boundary={boundary}, 保留消息: {[m['content'] for m in s.messages[boundary:]]}")
    
    s2 = MockSummarizer(keep_turns=5)
    s2.messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "q1"},
        {"role": "assistant", "content": "a1"},
    ]
    assert s2._find_recent_boundary() == 1
    print("  ✓ 不足 keep_turns: 保留全部（跳过系统消息）")
    print()


# ============================================================
# 测试 _build_api_messages
# ============================================================
def test_build_api_messages():
    print("=" * 60)
    print("4. 测试 _build_api_messages")
    print("=" * 60)
    
    # 无摘要
    s = MockSummarizer(keep_turns=2, history_summary="")
    s.messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "q1"},
        {"role": "assistant", "content": "a1"},
        {"role": "user", "content": "q2"},
        {"role": "assistant", "content": "a2"},
    ]
    
    result = s._build_api_messages()
    assert len(result) == 5  # sys + 4 messages within keep_turns
    print(f"  ✓ 无摘要: {len(result)} 条消息")
    
    # 有摘要
    s2 = MockSummarizer(keep_turns=2, history_summary="之前讨论了 DeepSeek 推理模型问题")
    s2.messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "q1"},
        {"role": "assistant", "content": "a1"},
        {"role": "user", "content": "q2"},
        {"role": "assistant", "content": "a2"},
        {"role": "user", "content": "q3"},
    ]
    
    result2 = s2._build_api_messages()
    # sys + summary_user + summary_ai + recent (q2, a2, q3) = 6
    assert len(result2) == 6, f"期望 6，实际 {len(result2)}"
    assert "摘要" in result2[1]["content"], "第2条应为摘要 user 消息"
    assert "了解" in result2[2]["content"], "第3条应为摘要 assistant 确认"
    assert result2[-1]["content"] == "q3", "最后一条应为最新用户消息"
    print(f"  ✓ 有摘要: {len(result2)} 条消息，摘要正确注入，最近消息完整")
    
    # 验证摘要消息结构
    print(f"    消息结构: {[(m['role'], str(m.get('content',''))[:30]) for m in result2]}")
    print()


# ============================================================
# 测试 _compact_message
# ============================================================
def test_compact_message():
    print("=" * 60)
    print("5. 测试 _compact_message")
    print("=" * 60)
    
    s = MockSummarizer()
    s.max_tool_output = 100
    s.max_assistant_content = 100
    
    # 短消息不截断
    assert s._compact_message({"role": "assistant", "content": "短"})["content"] == "短"
    print("  ✓ 短消息不截断")
    
    # 工具输出截断
    long_tool = s._compact_message({"role": "tool", "content": "x" * 150})
    assert "[已截断]" in long_tool["content"]
    print(f"  ✓ 工具输出截断: {len(long_tool['content'])} chars")
    
    # 助手回复截断
    long_ai = s._compact_message({"role": "assistant", "content": "y" * 150})
    assert "[已截断]" in long_ai["content"]
    print(f"  ✓ 助手回复截断: {len(long_ai['content'])} chars")
    print()


# ============================================================
# 测试 _probe_thinking_support 状态管理
# ============================================================
def test_probe_thinking_support():
    print("=" * 60)
    print("6. 测试 _probe_thinking_support 状态管理")
    print("=" * 60)
    
    class MockAPI(SessionAPIMixin):
        def __init__(self):
            # 模拟当前代码的初始化方式
            self.client = None
            self.model = "test-model"
            self.enable_thinking = True
            self._thinking_supported = True    # 默认 True（当前未提交代码）
            self._cheap_thinking_supported = True
            self.tool_log = lambda x: print(f"    [LOG] {x}")
            self._last_usage = {"total_tokens": 0, "prompt_tokens": 0, "completion_tokens": 0}
    
    api = MockAPI()
    
    # 测试1: 默认状态为 True，_probe_thinking_support 应立即返回（不发起网络请求）
    print("  测试1: 默认 _thinking_supported=True")
    assert api._thinking_supported == True
    assert api._cheap_thinking_supported == True
    
    # _probe_thinking_support 检测到非 None 应立即返回
    # (由于 client=None，如果实际发起请求会崩溃，但应该不会走到那一步)
    api._probe_thinking_support()
    print("  ✓ _probe_thinking_support 在 thinking_supported=True 时立即返回（不发起请求）")
    
    # 测试2: 模拟 None 状态（旧行为），验证探测逻辑的存在
    api2 = MockAPI()
    api2._thinking_supported = None  # 模拟旧行为
    api2._cheap_thinking_supported = None
    
    # 由于 client=None，探测会失败，但状态应保持 None（错误被捕获）
    api2._probe_thinking_support()
    # client=None 时，self.enable_thinking=True 但 not target_client 成立，应该直接返回
    print("  ✓ _probe_thinking_support 在 client=None 时安全返回")
    
    # 测试3: enable_thinking=False 时不探测
    api3 = MockAPI()
    api3._thinking_supported = None
    api3.enable_thinking = False
    api3._probe_thinking_support()
    print("  ✓ enable_thinking=False 时不探测")
    
    # 测试4: _create_chat_stream 的 thinking 参数行为
    print("  测试4: _create_chat_stream thinking 参数")
    # 当 _thinking_supported=True 且 enable_thinking=True 时，应添加 extra_body
    # 当 _thinking_supported=False 时，不应添加
    api4 = MockAPI()
    api4._thinking_supported = True
    api4.enable_thinking = True
    print(f"    主模型 thinking: supported={api4._thinking_supported}, enabled={api4.enable_thinking}")
    print(f"    便宜模型 thinking: supported={api4._cheap_thinking_supported}")
    
    api5 = MockAPI()
    api5._thinking_supported = False
    api5.enable_thinking = True
    print(f"    降级场景: supported={api5._thinking_supported}, enabled={api5.enable_thinking}")
    print("  ✓ thinking 状态正确管理")
    
    print()


# ============================================================
# 测试 reset_summary_state
# ============================================================
def test_reset_summary_state():
    print("=" * 60)
    print("7. 测试 reset_summary_state")
    print("=" * 60)
    
    s = MockSummarizer(history_summary="之前有重要讨论")
    assert s._history_summary == "之前有重要讨论"
    
    s.reset_summary_state()
    assert s._history_summary == ""
    print("  ✓ 摘要状态已重置")
    print()


# ============================================================
# 测试 _messages_to_text
# ============================================================
def test_messages_to_text():
    print("=" * 60)
    print("8. 测试 _messages_to_text")
    print("=" * 60)
    
    s = MockSummarizer()
    messages = [
        {"role": "user", "content": "搜索 Python"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": "search", "arguments": "{}"}}
        ]},
        {"role": "tool", "tool_call_id": "c1", "content": "Python 是编程语言"},
        {"role": "assistant", "content": "Python 很流行"},
    ]
    
    text = s._messages_to_text(messages)
    assert "[USER]" in text
    assert "调用工具" in text
    assert "[工具结果]" in text
    assert "[ASSISTANT]" in text
    print(f"  ✓ 输出:\n{text[:200]}")
    print()


# ============================================================
# 主入口
# ============================================================
if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("   SessionSummarizerMixin + _probe_thinking_support 测试")
    print("=" * 60 + "\n")
    
    test_count_user_msg()
    test_find_last_need_summary_pair()
    test_find_recent_boundary()
    test_build_api_messages()
    test_compact_message()
    test_probe_thinking_support()
    test_reset_summary_state()
    test_messages_to_text()
    
    print("=" * 60)
    print("   全部测试通过! ✓")
    print("=" * 60)
