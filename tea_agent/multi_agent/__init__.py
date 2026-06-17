"""
多 Agent 协作模块 — 子 Agent 调度 + 工作流执行。

用法:
    from tea_agent.multi_agent import Dispatcher, LiteAgent
    
    # 使用调度器
    dispatcher = Dispatcher()
    result = await dispatcher.dispatch(
        goal="重构项目添加类型注解",
        tools=["toolkit_file", "toolkit_edit", "toolkit_lsp"]
    )
"""

from .dispatcher import Dispatcher, SubTask, Workflow, TaskStatus
from .lite_agent import LiteAgent

__all__ = ["Dispatcher", "SubTask", "Workflow", "TaskStatus", "LiteAgent"]
