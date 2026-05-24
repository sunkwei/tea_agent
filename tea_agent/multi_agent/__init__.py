"""
# @2026-05-27 gen by Tea Agent, 多Agent协作模块

多Agent协作系统，支持：
- 主Agent负责任务分解和结果合并
- 子Agent并行执行子任务
- 每个子Agent可使用独立配置
- 工具可共享或独立

核心组件：
    MultiAgentOrchestrator  - 主编排器
    SubAgentWrapper         - 子Agent包装器
    TaskDecomposer          - 任务分解器
    ResultAggregator        - 结果合并器
    AgentPool               - Agent池管理
"""

from tea_agent.multi_agent.sub_agent import SubAgentWrapper, SubAgentConfig
from tea_agent.multi_agent.agent_pool import AgentPool
from tea_agent.multi_agent.task_decomposer import TaskDecomposer, SubTask
from tea_agent.multi_agent.result_aggregator import ResultAggregator
from tea_agent.multi_agent.orchestrator import MultiAgentOrchestrator

__all__ = [
    "SubAgentWrapper",
    "SubAgentConfig",
    "AgentPool",
    "TaskDecomposer",
    "SubTask",
    "ResultAggregator",
    "MultiAgentOrchestrator",
]
