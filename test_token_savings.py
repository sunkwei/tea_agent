"""
模拟测试：30 轮工具调用后，新旧 load_history 的 token 差异
"""

import sys
import os

# ---------- 模拟数据 ----------

SYSTEM_PROMPT = "你是一个智能助手，可以调用工具函数来帮助用户解决问题。"

USER_MSG = "帮我整理项目的所有 Python 文件，列出每个文件的用途"

# 模拟 30 轮工具调用的中间消息（assistant tool_call + tool result 交替）
def simulate_tool_call_rounds(n: int = 30):
    """生成 n 轮工具调用的中间消息"""
    rounds = []
    for i in range(n):
        # assistant tool_call
        rounds.append({
            "role": "assistant",
            "content": None,
            "tool_calls": [{
                "id": f"call_{i:03d}",
                "type": "function",
                "function": {
                    "name": f"toolkit_tool_{i}",
                    "arguments": f'{{"path": "/some/file_{i}.py"}}'
                }
            }]
        })
        # tool result
        rounds.append({
            "role": "tool",
            "tool_call_id": f"call_{i:03d}",
            "content": f"# File content for file_{i}.py\nprint('hello world')  " * 50  # ~1000 chars
        })
    return rounds

FINAL_AI_MSG = "好的，我已经检查了所有 30 个文件。项目结构如下：\n- file_0.py: 主入口\n- file_1.py: 配置\n...\n所有文件整理完毕。"

# ---------- Token 估算 ----------

def rough_token_count(text: str) -> int:
    """粗略 token 估算：英文 1 token ≈ 4 chars，中文 1 token ≈ 1.5 chars"""
    import re
    chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
    other_chars = len(text) - chinese_chars
    return int(chinese_chars / 1.5 + other_chars / 4)

def count_messages_tokens(messages: list) -> int:
    """估算消息列表的总 token 数"""
    total = 0
    for msg in messages:
        content = str(msg.get("content", ""))
        total += rough_token_count(content)
        # tool_calls 参数
        if msg.get("tool_calls"):
            for tc in msg["tool_calls"]:
                args = tc.get("function", {}).get("arguments", "")
                name = tc.get("function", {}).get("name", "")
                total += rough_token_count(name + args)
        # role + 结构开销（~4 tokens per message）
        total += 4
    return total


# ---------- 旧行为 vs 新行为 ----------

def old_load_history():
    """旧行为：加载所有中间轮次"""
    msgs = [{"role": "system", "content": SYSTEM_PROMPT}]
    msgs.append({"role": "user", "content": USER_MSG})
    
    rounds = simulate_tool_call_rounds(30)
    for rd in rounds:
        msgs.append(rd)  # ← 旧行为：全部塞入
    
    msgs.append({"role": "assistant", "content": FINAL_AI_MSG})
    return msgs

def new_load_history():
    """新行为：只保留最终 ai_msg"""
    msgs = [{"role": "system", "content": SYSTEM_PROMPT}]
    msgs.append({"role": "user", "content": USER_MSG})
    msgs.append({"role": "assistant", "content": FINAL_AI_MSG})  # ← 新行为：只要最终回复
    return msgs


if __name__ == "__main__":
    print("=" * 60)
    print("📊 Token 节省测试：30 轮工具调用场景")
    print("=" * 60)
    
    old_msgs = old_load_history()
    new_msgs = new_load_history()
    
    old_tokens = count_messages_tokens(old_msgs)
    new_tokens = count_messages_tokens(new_msgs)
    
    print(f"\n旧行为（加载全部中间轮次）:")
    print(f"  消息数: {len(old_msgs)} 条")
    print(f"  估算 tokens: ~{old_tokens:,}")
    
    print(f"\n新行为（只保留最终 ai_msg）:")
    print(f"  消息数: {len(new_msgs)} 条")
    print(f"  估算 tokens: ~{new_tokens:,}")
    
    print(f"\n{'─' * 40}")
    print(f"📉 消息数: {len(old_msgs)} → {len(new_msgs)} (减少 {len(old_msgs) - len(new_msgs)} 条, -{(len(old_msgs)-len(new_msgs))/len(old_msgs)*100:.0f}%)")
    print(f"📉 Token 估算: {old_tokens:,} → {new_tokens:,} (节省 {old_tokens - new_tokens:,}, -{(old_tokens-new_tokens)/old_tokens*100:.1f}%)")
    
    print(f"\n💡 实际 API 调用的 prompt tokens 通常在估算值的 1.5-2x 之间")
    print(f"   因为 API 会对消息结构、tool_calls 等进行编码")
    print(f"   按 1.5x 估算，实际节省约 {(old_tokens-new_tokens)*1.5:,.0f} tokens/轮对话")
    
    # 多轮对话场景
    print(f"\n📈 多轮对话累计节省（每轮都触发 30 轮工具调用）:")
    for rounds in [3, 5, 10]:
        cumulative = (old_tokens - new_tokens) * rounds
        print(f"  {rounds} 轮对话: ~{cumulative*1.5:,.0f} tokens (按 1.5x 实际系数)")
    
    print("\n" + "=" * 60)
    print("✅ 测试完成")
