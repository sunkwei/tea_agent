"""
多 Agent 协作模块 — 子 Agent 调度 + 并行执行 + 角色化 Flow + Agent 通信。

# ── 架构概览 ──
#
# Phase 1 (核心架构):
#   RoleAgent     — 角色化 Agent（有身份、目标、背景故事）
#   FlowEngine    — 事件驱动流程引擎（@start/@listen 装饰器）
#   RoleDispatcher — 角色化调度器（Flow + RoleAgent 整合）
#
# Phase 2 (Agent 间通信):
#   MessageBus    — 跨 Agent 发布/订阅消息队列
#   AgentTool/AgentToolManager — 子 Agent 自我注册为可调用工具
#   ToolRegistry  — 统一工具注册与发现
#   SubAgentManager — 通信/发现/注册一体化管理
#
# Phase 3 (持久化执行 + 可观测性):
#   CheckpointManager — 执行状态持久化与崩溃恢复
#   TraceEngine       — Agent 执行轨迹追踪（Span-based）
#   get_checkpoint_manager / get_trace_engine — 模块级便利函数
#
# Phase 4 (管理面板 + 模式市场):
#   PatternMarket — 可复用 Agent 模式仓库（CRUD + 搜索 + 推荐 + 实例化）
#   AdminPanel    — 统一管理界面（CLI + API）
#   get_pattern_market — 模块级便利函数
#
# Phase 5 (高性能并行执行引擎):
#   ExecutionPool — 双通道并行执行池（线程池 + 异步通道）
#   LoadBalancer  — 智能负载均衡（轮询/最少连接/加权）
#   ResourceGuard — 资源隔离保护（CPU/内存/并发限制）
#   CircuitBreaker / RetryPolicy — 熔断器 + 重试策略
#   FaultTolerant — 容错机制
#   get_execution_pool — 模块级便利函数
#
# Phase 1 兼容:
#   Dispatcher    — 旧版调度器（向后兼容）
#   LiteAgent     — 轻量 Agent（旧版）
#
# ── 快速上手 ──
#
#     from tea_agent.multi_agent import RoleDispatcher
#
#     dispatcher = RoleDispatcher()
#     result = dispatcher.dispatch("重构项目添加类型注解")
#     print(result["summary"])

用法:
    # 自定义 Flow
    from tea_agent.multi_agent import FlowEngine, flow_start, flow_listen

    class MyFlow(FlowEngine):
        @flow_start()
        def step1(self):
            return "done"
        @flow_listen(step1)
        def step2(self):
            return "done too"

    dispatcher.dispatch_with_flow(MyFlow, "自定义任务")

    # 多 Agent 协作
    from tea_agent.multi_agent import SubAgentManager

    mgr = SubAgentManager()
    analyst = mgr.create_analyst_agent(goal="审查代码")
    coder = mgr.create_coder_agent(goal="实现功能")
    result = mgr.call_agent(analyst.agent_id, "审查 dispatcher.py")
"""

# ── Phase 1: 核心架构 ──────────────────────────

# 角色化 Agent
from .role_agent import (
    RoleAgent,
    AgentResult,
    AgentStatus,
    create_analyst,
    create_coder,
    create_tester,
    create_reviewer,
)

# 流程引擎
from .flow_engine import (
    FlowEngine,
    FlowState,
    flow_start,
    flow_listen,
    flow_route,
    StepStatus,
)

# 结构化输出
from .structured_output import (
    StructuredOutput,
    AnalysisReport,
    CodeChangePlan,
    CodeIssue,
    TestPlan,
    TestCase,
    TestResult,
    CodeReview,
    ReviewComment,
    ArchitectureDesign,
)

# 角色化调度器
from .dispatcher import RoleDispatcher, TaskPattern

# ── Phase 2: Agent 间通信 ──────────────────────

# 消息总线
from .message_bus import (
    MessageBus,
    Message,
    MessagePriority,
    get_message_bus,
    reset_message_bus,
)

# Agent-as-Tool
from .agent_as_tool import (
    AgentTool,
    AgentToolManager,
)

# 工具注册与发现
from .tool_registry import (
    ToolRegistry,
    ToolEntry,
    get_tool_registry,
    reset_tool_registry,
    registry,
)

# 一体化 SubAgent 管理
from .subagent_manager import (
    SubAgentManager,
    SubAgentInfo,
)

# ── Phase 3: 持久化执行 + 可观测性 ─────────────

# 检查点（执行状态持久化与恢复）
from .checkpoint_manager import (
    CheckpointManager,
    get_checkpoint_manager,
)

# 执行追踪（Span-based Tracing）
from .trace_engine import (
    TraceEngine,
    TraceSpan,
    get_trace_engine,
)

# ── Phase 4: 管理面板 + 模式市场 ─────────────

# 模式市场
from .pattern_market import (
    PatternMarket,
    get_pattern_market,
)

# 统一管理面板
from .admin_panel import (
    AdminPanel,
)

# ── Phase 5: 高性能并行执行引擎 ──────────────

# 执行池核心
from .execution_pool import (
    ExecutionPool,
    TaskInfo,
    TaskState,
    PoolState,
    get_execution_pool,
    # 负载均衡
    LoadBalancer,
    LoadBalancerStrategy,
    PoolNode,
    # 资源隔离
    ResourceGuard,
    ResourceLimit,
    # 容错
    CircuitBreaker,
    CircuitState,
    RetryPolicy,
    RetryExhaustedError,
)

# ── Phase 6: 高级编排能力编排 ──────────────

# 工作流 DAG 引擎
from .workflow_engine import (
    WorkflowNode,
    NodeType,
    NodeState,
    WorkflowState,
    WorkflowDAG,
    WorkflowExec,
    WorkflowTemplate,
)

# ── Phase 1 兼容 ────────────────────────────────

from .dispatcher_v1 import Dispatcher, SubTask, TaskStatus as V1TaskStatus
from .lite_agent import LiteAgent

# ── 导出清单 ────────────────────────────────────

__all__ = [
    # Phase 1: 核心架构
    "RoleDispatcher",
    "RoleAgent",
    "AgentResult",
    "AgentStatus",
    "FlowEngine",
    "FlowState",
    "flow_start",
    "flow_listen",
    "flow_route",
    "StepStatus",
    "TaskPattern",
    # 快捷创建
    "create_analyst",
    "create_coder",
    "create_tester",
    "create_reviewer",
    # 结构化输出
    "StructuredOutput",
    "AnalysisReport",
    "CodeChangePlan",
    "CodeIssue",
    "TestPlan",
    "TestCase",
    "TestResult",
    "CodeReview",
    "ReviewComment",
    "ArchitectureDesign",
    # Phase 2: Agent 间通信
    "MessageBus",
    "Message",
    "MessagePriority",
    "get_message_bus",
    "reset_message_bus",
    "AgentTool",
    "AgentToolManager",
    "ToolRegistry",
    "ToolEntry",
    "get_tool_registry",
    "reset_tool_registry",
    "registry",
    "SubAgentManager",
    "SubAgentInfo",
    # Phase 3: 持久化执行 + 可观测性
    "CheckpointManager",
    "get_checkpoint_manager",
    "TraceEngine",
    "TraceSpan",
    "get_trace_engine",
    # Phase 4: 管理面板 + 模式市场
    "PatternMarket",
    "get_pattern_market",
    "AdminPanel",
    # Phase 5: 并行执行引擎
    "ExecutionPool",
    "TaskInfo",
    "TaskState",
    "PoolState",
    "get_execution_pool",
    "LoadBalancer",
    "LoadBalancerStrategy",
    "PoolNode",
    "ResourceGuard",
    "ResourceLimit",
    "CircuitBreaker",
    "CircuitState",
    "RetryPolicy",
    "RetryExhaustedError",
    # Phase 6: 高级编排
    "WorkflowNode",
    "NodeType",
    "NodeState",
    "WorkflowState",
    "WorkflowDAG",
    "WorkflowExec",
    "WorkflowTemplate",
    # 旧版兼容
    "Dispatcher",
    "SubTask",
    "V1TaskStatus",
    "LiteAgent",
]
