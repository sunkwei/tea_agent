"""
Lite Agent 测试工具

用法:
    python test_lite_agent.py "你好"
    python test_lite_agent.py --config_fname config_ds.yaml "获取当前时间"
    python test_lite_agent.py --system_prompt "你是翻译助手" "Hello"
    python test_lite_agent.py --config_fname config_qwen.yaml --no_think "你好"
    python test_lite_agent.py --use_main "你好"
"""

import argparse
import sys
from tea_agent.agent import Agent


def main():
    parser = argparse.ArgumentParser(
        description="Lite Agent 测试工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python test_lite_agent.py "你好"
  python test_lite_agent.py --config_fname config_ds.yaml "获取当前时间"
  python test_lite_agent.py --system_prompt "你是翻译助手" "Hello world"
  python test_lite_agent.py --config_fname config_qwen.yaml --no_think "你好"
  python test_lite_agent.py --use_main "你好"
        """
    )
    parser.add_argument("user_msg", help="用户输入消息")
    parser.add_argument("--config_fname", default=None, help="配置文件名 (在 ~/.tea_agent/ 下)")
    parser.add_argument("--config_path", default=None, help="配置文件完整路径")
    parser.add_argument("--system_prompt", default=None, help="自定义系统提示词")
    parser.add_argument("--no_think", action="store_true", help="禁用思考链")
    parser.add_argument("--no_tools", action="store_true", help="禁用工具调用")
    parser.add_argument("--use_cheap", action="store_true", default=True, help="使用便宜模型 (默认开启)")
    parser.add_argument("--use_main", action="store_true", help="使用主模型")

    args = parser.parse_args()

    # 确定是否使用便宜模型
    use_cheap = not args.use_main

    # 创建 Agent
    agent = Agent(
        mode="lite",
        config_path=args.config_path,
        config_fname=args.config_fname,
        use_tools=not args.no_tools,
        enable_thinking=not args.no_think,
        use_cheap_model=use_cheap,
    )

    # 获取模型信息
    model_name = agent._sess.model
    system_prompt = agent._sess.system_prompt
    if args.system_prompt:
        # 临时修改系统提示词
        agent._sess.system_prompt = args.system_prompt
        system_prompt = args.system_prompt

    # 打印配置信息
    print("=" * 60)
    print("📋 Lite Agent 配置")
    print("=" * 60)
    print(f"  模型:     {model_name}")
    print(f"  工具:     {'启用' if not args.no_tools else '禁用'}")
    print(f"  思考链:   {'启用' if not args.no_think else '禁用'}")
    print(f"  便宜模型: {'是' if use_cheap else '否'}")
    print()
    print("📝 系统提示词:")
    print("-" * 40)
    print(system_prompt[:500] + ("..." if len(system_prompt) > 500 else ""))
    print("-" * 40)
    print()
    print(f"👤 用户输入: {args.user_msg}")
    print()
    print("=" * 60)
    print("🤖 模型响应")
    print("=" * 60)

    # 执行对话
    result = agent.chat(args.user_msg)

    # 打印结果
    if result["thinking"]:
        print()
        print("💭 思考过程:")
        print("-" * 40)
        print(result["thinking"])
        print("-" * 40)

    print()
    print("💬 最终回复:")
    print("-" * 40)
    print(result["assistant"])
    print("-" * 40)

    print()
    print("📊 统计:")
    print(f"  工具调用: {result['tool_calls']} 次")

    if result["error"]:
        print()
        print("❌ 错误:")
        print(f"  {result['error']}")
        sys.exit(1)
    else:
        print()
        print("✅ 完成")


if __name__ == "__main__":
    main()
