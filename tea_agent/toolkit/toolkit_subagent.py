"""
轻量 Subagent 工具 — 委托一个子 Agent 独立执行任务。

在单独的 LiteAgent 实例中运行指定的 prompt，
支持可选的 system_prompt 和控制最大轮次。
不受主会话上下文影响，隔离执行。
"""

import logging

logger = logging.getLogger("toolkit")

META = {
    "type": "function",
    "function": {
        "name": "toolkit_subagent",
        "description": "委托一个子 Agent 独立执行指定任务。适合需要隔离上下文或并发处理时使用。",
        "parameters": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "子任务的详细描述和指令"
                },
                "system_prompt": {
                    "type": "string",
                    "description": "可选的系统提示词，覆盖默认行为"
                },
                "max_turns": {
                    "type": "integer",
                    "description": "最大对话轮次（每轮=思考+工具调用），默认 3",
                    "default": 3
                }
            },
            "required": ["prompt"]
        }
    }
}


def toolkit_subagent(prompt: str, system_prompt: str = None, max_turns: int = 3) -> str:
    """
    启动一个独立的 LiteAgent 子进程执行 prompt。
    子 Agent 有独立的会话上下文，不会污染主会话。
    """
    logger.info(f"toolkit_subagent: prompt={prompt[:80]}...")
    try:
        from tea_agent.multi_agent.lite import run_lite_agent
        result = run_lite_agent(
            prompt=prompt,
            system_prompt=system_prompt,
            max_turns=max_turns
        )
        logger.info(f"toolkit_subagent done: {len(str(result))} chars")
        return str(result)
    except Exception as e:
        logger.error(f"toolkit_subagent failed: {e}")
        return f"[Subagent 错误: {e}]"
