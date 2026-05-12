"""
@2026-05-16 gen by tea_agent, TeaAgent 双实例对话测试

两个隔离的 TeaAgent 实例 A、B，互相传递 LLM 回复作为输入，循环 10 轮。

用法:
    python tests/test_tea_agent_dual.py [config_path]
"""

import sys
import os
from typing import List, Dict


def extract_final_reply(rounds: List[Dict]) -> str:
    """从轮次列表中提取 AI 的最终文本回复。"""
    # 倒序查找最后一个 assistant 消息（含 content 且非 tool_calls）
    for r in reversed(rounds):
        if r.get("role") == "assistant" and r.get("content"):
            return r["content"].strip()
    return "(无回复)"


def _format_content(text: str, max_len: int = 120) -> str:
    """截断过长文本用于打印。"""
    if len(text) <= max_len:
        return text
    return text[:max_len] + "..."


def main():
    config_path = sys.argv[1] if len(sys.argv) > 1 else None

    from tea_agent import TeaAgent

    print("=" * 60)
    print("TeaAgent 双实例对话测试")
    print(f"配置: {config_path or '默认'}")
    print("=" * 60)

    # ── 创建两个 isolate 实例 ──
    print("\n创建实例 A ...")
    agent_a = TeaAgent(config_path=config_path, use_tools=False, enable_thinking=False)

    print("创建实例 B ...")
    agent_b = TeaAgent(config_path=config_path, use_tools=False, enable_thinking=False)

    TOTAL_ROUNDS = 10

    # ── 首轮：A 发起 ──
    seed = "AI 最终会取代程序员的工作?"
    current_input = seed

    for round_num in range(1, TOTAL_ROUNDS + 1):
        speaker = "A" if round_num % 2 == 1 else "B"
        agent = agent_a if speaker == "A" else agent_b

        print(f"\n{'─' * 60}")
        print(f"第 {round_num}/{TOTAL_ROUNDS} 轮 — [{speaker}] 输入:")
        print(f"  {_format_content(current_input)}")

        try:
            rounds = agent.chat(current_input)
        except Exception as e:
            print(f"  ❌ 出错: {e}")
            break

        final_reply = extract_final_reply(rounds)

        print(f"[{speaker}] 输出:")
        print(f"  {_format_content(final_reply)}")

        # 把本轮输出作为下一轮输入
        current_input = final_reply

    # ── 清理 ──
    agent_a.close()
    agent_b.close()

    print(f"\n{'=' * 60}")
    print("测试完成")
    print("=" * 60)


if __name__ == "__main__":
    main()
