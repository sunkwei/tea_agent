"""
# @2026-05-27 gen by Tea Agent, 多Agent协作模块

多Agent协作系统，支持：
- 主Agent负责任务分解和结果合并
- 子Agent并行执行子任务
- 每个子Agent可使用独立配置
- 工具可共享或独立

核心组件：
    MultiAgentOrchestrator  - 主编排器（基于 OnlineToolSession）
    LiteOrchestrator        - 轻量级编排器（基于 LiteAgent，零DB依赖）★推荐
    LiteAgent               - 轻量级Agent（独立YAML配置，纯内存运行）
    LiteAgentPool           - 轻量级Agent池
    SubAgentWrapper         - 子Agent包装器（基于 OnlineToolSession）
    TaskDecomposer          - 任务分解器
    ResultAggregator        - 结果合并器
    AgentPool               - Agent池管理（基于 SubAgentWrapper）
"""

from tea_agent.multi_agent.sub_agent import SubAgentWrapper, SubAgentConfig
from tea_agent.multi_agent.agent_pool import AgentPool, LiteAgentPool
from tea_agent.multi_agent.task_decomposer import TaskDecomposer, SubTask
from tea_agent.multi_agent.result_aggregator import ResultAggregator
from tea_agent.multi_agent.orchestrator import MultiAgentOrchestrator, LiteOrchestrator
from tea_agent.multi_agent.lite_agent import LiteAgent, LiteAgentConfig, LiteAgentModelConfig

__all__ = [
    # 轻量级（推荐）
    "LiteAgent",
    "LiteAgentConfig",
    "LiteAgentModelConfig",
    "LiteAgentPool",
    "LiteOrchestrator",
    # 完整版（基于 OnlineToolSession）
    "SubAgentWrapper",
    "SubAgentConfig",
    "AgentPool",
    "MultiAgentOrchestrator",
    # 通用
    "TaskDecomposer",
    "SubTask",
    "ResultAggregator",
]
