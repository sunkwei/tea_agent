"""
多 Agent 协作模块 — 子 Agent 调度 + 并行执行。

用法:
    from tea_agent.multi_agent import Dispatcher, LiteAgent

    # 一步到位：分解 + 执行
    dispatcher = Dispatcher()
    result = dispatcher.dispatch("重构项目添加类型注解")
    print(result["summary"])

    # 可视化执行计划（不执行）
    print(dispatcher.visualize("为 gui.py 添加类型注解"))

    # 单独使用 LiteAgent
    agent = LiteAgent()
    result = agent.execute_sync("读取 README.md 并总结")
"""

from .dispatcher import Dispatcher, SubTask, TaskStatus
from .lite_agent import LiteAgent

__all__ = ["Dispatcher", "SubTask", "TaskStatus", "LiteAgent"]
