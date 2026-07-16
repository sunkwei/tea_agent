"""
SubAgentManager — 通信/发现/注册一体化管理。

整合三大能力:
  1. MessageBus  — 跨 Agent 发布/订阅通信
  2. Agent-as-Tool — 子 Agent 自我注册为可调用工具
  3. ToolRegistry — 统一工具发现

核心工作流:
  1. 创建 RoleAgent
  2. 注册到 ToolRegistry（可被其他 Agent 发现）
  3. 注册到 MessageBus（可收发主题消息）
  4. 暴露为 AgentTool（可被其他 Agent 调用）
  5. 启动执行

使用场景:
  - 多 Agent 协作系统
  - 专家 Agent 市场
  - 动态任务分配
"""

import logging
import threading
import time
import uuid
from datetime import datetime
from typing import Any

from .agent_as_tool import AgentTool, AgentToolManager
from .checkpoint_manager import get_checkpoint_manager
from .message_bus import MessageBus, get_message_bus
from .pattern_market import get_pattern_market
from .role_agent import RoleAgent
from .tool_registry import ToolRegistry, get_tool_registry
from .trace_engine import get_trace_engine

logger = logging.getLogger(__name__)


class SubAgentInfo:
    """
    子 Agent 信息封装。

    记录一个子 Agent 的完整状态:
      - RoleAgent 实例
      - AgentTool 包装
      - MessageBus 订阅
      - 运行时状态
    """

    def __init__(
        self,
        agent_id: str,
        agent: RoleAgent,
        role: str,
        goal: str = "",
        topics: list[str] | None = None,
    ):
        self.agent_id = agent_id
        self.agent = agent
        self.role = role
        self.goal = goal
        self.topics = topics or []

        # 运行时
        self.status: str = "idle"  # idle, running, paused, error
        self.last_active: str = ""
        self.error: str | None = None
        self.metrics: dict = {
            "tasks_completed": 0,
            "tasks_failed": 0,
            "total_time": 0.0,
        }

        # AgentTool（延迟创建）
        self.agent_tool: AgentTool | None = None

        self.created_at = datetime.now().isoformat()

    def to_dict(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "role": self.role,
            "goal": self.goal[:80] if self.goal else "",
            "topics": self.topics,
            "status": self.status,
            "metrics": self.metrics,
            "created_at": self.created_at,
            "last_active": self.last_active,
            "error": self.error,
            "has_tool": self.agent_tool is not None,
        }

    def __repr__(self) -> str:
        return f"<SubAgent {self.agent_id} [{self.role}] {self.status}>"


class SubAgentManager:
    """
    子 Agent 管理器 — 通信/发现/注册一体化。

    用法:
        from tea_agent.multi_agent import SubAgentManager

        mgr = SubAgentManager()

        # 创建并注册一个分析 Agent
        analyst = mgr.create_agent(
            role="代码审查员",
            goal="审查代码质量问题",
            backstory="10 年经验的高级工程师",
            topics=["code:review", "code:security"],
        )

        # 创建编码 Agent
        coder = mgr.create_agent(
            role="高级开发工程师",
            goal="实现功能并确保代码质量",
            topics=["code:implement"],
        )

        # 让编码 Agent 调用分析 Agent
        result = mgr.call_agent("代码审查员", "审查 dispatcher.py 的代码质量")

        # 发现可用 Agent
        for info in mgr.discover("代码"):
            print(f"  {info.agent_id} - {info.role}")

        # 发布消息到主题
        mgr.publish("code:review", {"file": "dispatcher.py"})
    """

    def __init__(
        self,
        message_bus: MessageBus | None = None,
        tool_registry: ToolRegistry | None = None,
        agent_tool_manager: AgentToolManager | None = None,
        max_agents: int = 20,
        verbose: bool = True,
    ):
        self.message_bus = message_bus or get_message_bus()
        self.tool_registry = tool_registry or get_tool_registry()
        self.agent_tool_manager = agent_tool_manager or AgentToolManager()

        self.max_agents = max_agents
        self.verbose = verbose

        # 管理的子 Agent
        self._agents: dict[str, SubAgentInfo] = {}
        self._lock = threading.RLock()

        # 统计
        self.total_tasks = 0
        self._start_time = datetime.now()

    # ── Agent 创建与注册 ──────────────────────────

    def create_agent(
        self,
        role: str,
        goal: str = "",
        backstory: str = "",
        llm_config: dict | None = None,
        tools: list | None = None,
        topics: list[str] | None = None,
        agent_id: str = "",
        register_tool: bool = True,
        register_bus: bool = True,
    ) -> SubAgentInfo:
        """
        创建并注册一个子 Agent。

        Args:
            role: 角色名称（如"代码审查员"）
            goal: 目标描述
            backstory: 背景故事
            llm_config: LLM 配置
            tools: 可用工具列表
            topics: 订阅的消息主题
            agent_id: 自定义 ID（自动生成 if empty）
            register_tool: 是否注册为 AgentTool
            register_bus: 是否注册到 MessageBus

        Returns:
            SubAgentInfo 实例
        """
        if len(self._agents) >= self.max_agents:
            raise RuntimeError(f"达到最大 Agent 数量 ({self.max_agents})")

        agent_id = agent_id or f"agent_{role[:8].lower()}_{uuid.uuid4().hex[:6]}"

        # 1. 创建 RoleAgent
        if not backstory:
            backstory = f"我是一个专业的{role}，擅长完成相关任务。"

        agent = RoleAgent(
            role=role,
            goal=goal or f"作为{role}，高效完成任务",
            backstory=backstory,
            llm_config=llm_config,
            tools=tools or [],
        )

        # 2. 创建封装信息
        info = SubAgentInfo(
            agent_id=agent_id,
            agent=agent,
            role=role,
            goal=goal,
            topics=topics or [],
        )

        # 3. 注册到 MessageBus
        if register_bus:
            self.message_bus.register_agent(agent_id)
            for topic in info.topics:
                self.message_bus.subscribe(agent_id, topic)

        # 4. 注册为 AgentTool
        if register_tool:
            agent_tool = AgentTool(
                agent=agent,
                name=agent_id,
                description=f"🎭 {role}: {goal[:100]}" if goal else f"🎭 {role}",
            )
            self.agent_tool_manager.register(agent_tool)
            self.tool_registry.register_agent_tool(
                agent_tool,
                tags=[role, "agent"] + info.topics,
            )
            info.agent_tool = agent_tool

        # 5. 保存
        with self._lock:
            self._agents[agent_id] = info

        if self.verbose:
            logger.info(f"🤖 Agent 创建: {agent_id} [{role}] topics={info.topics}")

        return info

    def create_analyst_agent(self, goal: str = "", topics: list[str] | None = None) -> SubAgentInfo:
        """快速创建分析专家 Agent。"""
        return self.create_agent(
            role="资深分析专家",
            goal=goal or "分析代码结构、性能和安全性",
            backstory="10 年经验的代码分析专家，精通静态分析、性能优化和安全审计",
            topics=topics or ["code:analyze", "code:security"],
        )

    def create_coder_agent(self, goal: str = "", topics: list[str] | None = None) -> SubAgentInfo:
        """快速创建编码 Agent。"""
        return self.create_agent(
            role="高级开发工程师",
            goal=goal or "实现功能、重构代码、修复 Bug",
            backstory="全栈开发工程师，精通 Python、TypeScript、系统架构设计",
            topics=topics or ["code:implement", "code:refactor"],
        )

    def create_reviewer_agent(self, goal: str = "", topics: list[str] | None = None) -> SubAgentInfo:
        """快速创建审查 Agent。"""
        return self.create_agent(
            role="代码审查员",
            goal=goal or "审查代码质量、发现潜在问题",
            backstory="资深代码审查专家，关注代码质量、可维护性和最佳实践",
            topics=topics or ["code:review"],
        )

    def create_tester_agent(self, goal: str = "", topics: list[str] | None = None) -> SubAgentInfo:
        """快速创建测试 Agent。"""
        return self.create_agent(
            role="测试工程师",
            goal=goal or "编写和执行测试用例，确保代码质量",
            backstory="专业测试工程师，精通单元测试、集成测试和端到端测试",
            topics=topics or ["code:test"],
        )

    # ── 通信 ────────────────────────────────────────

    def publish(self, topic: str, payload: Any, sender: str = "manager") -> list[str]:
        """发布消息到主题（自动分发给订阅的 Agent）。"""
        return self.message_bus.publish(topic, payload, sender=sender)

    def send_to(self, target_id: str, message: Any, sender: str = "manager") -> bool:
        """直接发送消息给指定 Agent。"""
        self.message_bus.register_agent(target_id)
        self.message_bus.publish(f"direct:{target_id}", message, sender=sender)
        return True

    def broadcast(self, message: Any, sender: str = "manager") -> int:
        """广播给所有 Agent。"""
        return self.message_bus.broadcast(message, sender=sender)

    def get_messages(self, agent_id: str) -> list[dict]:
        """获取 Agent 的待处理消息。"""
        return self.message_bus.consume(agent_id)

    def subscribe(self, agent_id: str, topic: str) -> bool:
        """为 Agent 订阅主题。"""
        with self._lock:
            info = self._agents.get(agent_id)
            if info:
                if topic not in info.topics:
                    info.topics.append(topic)
                return self.message_bus.subscribe(agent_id, topic)
            return False

    # ── 发现 ────────────────────────────────────────

    def discover(self, query: str = "") -> list[SubAgentInfo]:
        """
        发现 Agent（按角色/目标/主题匹配）。

        Args:
            query: 搜索关键词

        Returns:
            匹配的 SubAgentInfo 列表
        """
        if not query:
            with self._lock:
                return list(self._agents.values())

        query_lower = query.lower()
        results = []

        with self._lock:
            for info in self._agents.values():
                # 角色匹配
                if query_lower in info.role.lower():
                    results.append(info)
                    continue
                # 目标匹配
                if query_lower in info.goal.lower():
                    results.append(info)
                    continue
                # 主题匹配
                for topic in info.topics:
                    if query_lower in topic.lower():
                        results.append(info)
                        break

        return results

    def find_by_role(self, role: str) -> list[SubAgentInfo]:
        """按角色查找。"""
        with self._lock:
            return [info for info in self._agents.values() if role.lower() in info.role.lower()]

    def find_by_id(self, agent_id: str) -> SubAgentInfo | None:
        """按 ID 查找。"""
        with self._lock:
            return self._agents.get(agent_id)

    # ── 调用 ────────────────────────────────────────

    def call_agent(self, agent_id: str, task: str, context: dict | None = None) -> dict:
        """
        调用指定 Agent 执行任务（通过 AgentTool）。

        Args:
            agent_id: 目标 Agent ID
            task: 任务描述
            context: 额外上下文

        Returns:
            执行结果
        """
        info = self.find_by_id(agent_id)
        if not info:
            return {"error": f"Agent '{agent_id}' 未找到"}

        # ── Phase 3: Checkpoint / Trace ──
        cpm = get_checkpoint_manager()
        te = get_trace_engine()

        self.total_tasks += 1
        info.status = "running"

        # 创建 trace
        trace_id = te.start_trace(
            agent_id=agent_id,
            task=task,
            agent_role=info.role,
        )

        # checkpoint
        cpm.save({
            'agent_id': agent_id,
            'role': info.role,
            'goal': info.goal[:200],
            'task': task[:500],
            'context': context or {},
            'status': 'running',
            'trace_id': trace_id,
        })

        if info.agent_tool:
            result = info.agent_tool.call(task, context)

            if result.get("error"):
                info.metrics["tasks_failed"] += 1
                info.status = "error"
                info.error = result["error"]
                te.end_span(f"root-{trace_id}", 'failed',
                            error=result["error"])
                cpm.update_status(agent_id, 'failed',
                                  error=result["error"][:500])
            else:
                info.metrics["tasks_completed"] += 1
                info.status = "idle"
                te.end_span(f"root-{trace_id}", 'completed',
                            result=str(result.get('result', ''))[:500])
                cpm.update_status(agent_id, 'completed',
                                  result=str(result.get('result', ''))[:500])

            info.last_active = datetime.now().isoformat()
            return result

        # 无 AgentTool，直接执行
        try:
            start = time.time()
            # 使用 RoleAgent.execute（含内置 checkpoint/trace）
            agent_result = info.agent.execute(
                task,
                context=context,
                trace_id=trace_id,
            )
            elapsed = time.time() - start

            if agent_result.success:
                info.metrics["tasks_completed"] += 1
                info.status = "idle"
            else:
                info.metrics["tasks_failed"] += 1
                info.status = "error"
                info.error = agent_result.error

            info.metrics["total_time"] += elapsed
            info.last_active = datetime.now().isoformat()

            return {
                "result": agent_result.output,
                "success": agent_result.success,
                "error": agent_result.error,
                "tool_calls": agent_result.tool_calls,
                "elapsed": round(elapsed, 2),
                "trace_id": trace_id,
            }
        except Exception as e:
            info.metrics["tasks_failed"] += 1
            info.status = "error"
            info.error = str(e)
            te.end_span(f"root-{trace_id}", 'failed', error=str(e)[:500])
            cpm.update_status(agent_id, 'failed', error=str(e)[:500])
            return {"error": str(e), "trace_id": trace_id}

    def call_role(self, role: str, task: str) -> list[dict]:
        """
        按角色调用：找到所有匹配角色的 Agent 并行执行。

        Returns:
            所有结果的列表
        """
        agents = self.find_by_role(role)
        if not agents:
            return [{"error": f"没有找到角色 '{role}' 的 Agent"}]

        results = []
        for info in agents:
            result = self.call_agent(info.agent_id, task)
            results.append({"agent_id": info.agent_id, "role": info.role, **result})
        return results

    # ── 生命周期 ────────────────────────────────────

    def remove_agent(self, agent_id: str) -> bool:
        """移除 Agent。"""
        with self._lock:
            info = self._agents.pop(agent_id, None)
            if info is None:
                return False

            # 取消 MessageBus 注册
            self.message_bus.unregister_agent(agent_id)

            # 注销 ToolRegistry
            # (AgentTool 由 agent_tool_manager 管理)

            self.agent_tool_manager.unregister(agent_id)

            if self.verbose:
                logger.info(f"🗑️ Agent 移除: {agent_id}")
            return True

    def pause_agent(self, agent_id: str) -> bool:
        """暂停 Agent。"""
        info = self.find_by_id(agent_id)
        if info:
            info.status = "paused"
            return True
        return False

    def resume_agent(self, agent_id: str) -> bool:
        """恢复 Agent。"""
        info = self.find_by_id(agent_id)
        if info:
            info.status = "idle"
            return True
        return False

    # ── 状态与统计 ──────────────────────────────────

    def list_agents(self, status: str = "") -> list[dict]:
        """列出所有 Agent。"""
        with self._lock:
            infos = list(self._agents.values())
            if status:
                infos = [i for i in infos if i.status == status]
            return [i.to_dict() for i in infos]

    def agent_status(self, agent_id: str) -> dict | None:
        """查询单个 Agent 状态。"""
        info = self.find_by_id(agent_id)
        return info.to_dict() if info else None

    def stats(self) -> dict:
        """管理器统计。"""
        with self._lock:
            status_counts = {}
            for info in self._agents.values():
                status_counts[info.status] = status_counts.get(info.status, 0) + 1

            total_tasks_done = sum(
                i.metrics["tasks_completed"] + i.metrics["tasks_failed"]
                for i in self._agents.values()
            )

            return {
                "total_agents": len(self._agents),
                "by_status": status_counts,
                "total_tasks": self.total_tasks,
                "total_tasks_completed": total_tasks_done,
                "bus_status": self.message_bus.status(),
                "registry_tools": self.tool_registry.count(),
                "agent_tools": self.agent_tool_manager.count(),
                "uptime": (datetime.now() - self._start_time).total_seconds(),
            }

    # ── Phase 4: Pattern Market 集成 ─────────────

    def create_from_pattern(
        self,
        name_or_id: str,
        topics: list[str] | None = None,
        register_tool: bool = True,
        register_bus: bool = True,
        **overrides,
    ) -> SubAgentInfo | None:
        """
        从模式市场创建 Agent。

        Args:
            name_or_id: 模式名称或 ID
            topics: 订阅的主题
            register_tool: 是否注册为 AgentTool
            register_bus: 是否注册到 MessageBus
            **overrides: 覆盖字段（role, goal, backstory 等）

        Returns:
            SubAgentInfo 或 None（模式不存在时）
        """
        pm = get_pattern_market()
        pat = pm.get(name_or_id)
        if not pat:
            pat = pm.get_by_name(name_or_id)
        if not pat:
            logger.error(f"⚠️ 模式不存在: {name_or_id}")
            return None

        return self.create_agent(
            role=overrides.get("role", pat["role"]),
            goal=overrides.get("goal", pat["goal"]),
            backstory=overrides.get("backstory", pat.get("backstory", "")),
            tools=overrides.get("tools", pat.get("tools", None)),
            topics=topics or [],
            register_tool=register_tool,
            register_bus=register_bus,
        )

    def register_agent_as_pattern(self, agent_id: str) -> str | None:
        """
        将已注册的 Agent 保存为模式。

        Args:
            agent_id: 目标 Agent ID

        Returns:
            模式 ID，失败时返回 None
        """
        info = self.find_by_id(agent_id)
        if not info:
            return None

        pattern = {
            "name": info.role,
            "role": info.role,
            "goal": info.goal,
            "backstory": info.agent.backstory if hasattr(info.agent, 'backstory') else "",
            "tools": info.agent.tools if hasattr(info.agent, 'tools') else [],
            "tags": info.topics + [info.role],
            "description": f"从 Agent {agent_id} 自动注册的模式",
        }
        pm = get_pattern_market()
        pid = pm.save(pattern)
        logger.info(f"📦 Agent {agent_id} 已保存为模式: {pid}")
        return pid

    def clear(self):
        """清空所有 Agent。"""
        agent_ids = list(self._agents.keys())
        for aid in agent_ids:
            self.remove_agent(aid)
        logger.info("🧹 SubAgentManager 已清空")
