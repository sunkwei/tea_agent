"""
AdminPanel — 统一 Agent 管理界面（CLI + API）。

集中管理所有组件：Agent 生命周期、模式市场、Checkpoint、
Trace、系统统计。提供人类可读的 CLI 输出和程序化的 API。

用法:
    from tea_agent.multi_agent import AdminPanel

    panel = AdminPanel()
    panel.cli()   # 交互式 CLI
    # 或直接调用 API
    panel.status()
    panel.list_agents()
"""

import logging
import threading
from datetime import datetime

from .execution_pool import get_execution_pool  # Phase 5

logger = logging.getLogger(__name__)


class AdminPanel:
    """
    统一管理员面板。

    聚合 SubAgentManager、PatternMarket、CheckpointManager、TraceEngine
    的所有管理能力，提供统一的 API + CLI 接口。
    """

    def __init__(
        self,
        subagent_manager=None,
        pattern_market=None,
        checkpoint_manager=None,
        trace_engine=None,
        verbose: bool = True,
    ):
        self.verbose = verbose
        self._lock = threading.RLock()

        # 延迟导入 + 获取单例
        self._subagent_manager = subagent_manager
        self._pattern_market = pattern_market
        self._checkpoint_manager = checkpoint_manager
        self._trace_engine = trace_engine

        self._start_time = datetime.now()

    # ── 延迟获取单例 ────────────────────────────

    @property
    def sm(self):
        if self._subagent_manager is None:
            from .subagent_manager import SubAgentManager
            self._subagent_manager = SubAgentManager()
        return self._subagent_manager

    @property
    def pm(self):
        if self._pattern_market is None:
            from .pattern_market import get_pattern_market
            self._pattern_market = get_pattern_market()
        return self._pattern_market

    @property
    def cpm(self):
        if self._checkpoint_manager is None:
            from .checkpoint_manager import get_checkpoint_manager
            self._checkpoint_manager = get_checkpoint_manager()
        return self._checkpoint_manager

    @property
    def te(self):
        if self._trace_engine is None:
            from .trace_engine import get_trace_engine
            self._trace_engine = get_trace_engine()
        return self._trace_engine

    # ═══════════════════════════════════════════
    # Agent 管理
    # ═══════════════════════════════════════════

    def list_agents(self, status: str = "") -> list[dict]:
        """列出所有子 Agent。"""
        return self.sm.list_agents(status) if hasattr(self.sm, 'list_agents') else []

    def create_agent(
        self,
        role: str,
        goal: str = "",
        backstory: str = "",
        tools: list | None = None,
        topics: list[str] | None = None,
    ) -> dict:
        """创建新 Agent。"""
        info = self.sm.create_agent(
            role=role,
            goal=goal or f"作为{role}高效完成任务",
            backstory=backstory,
            tools=tools or [],
            topics=topics or [],
        )
        return info.to_dict() if hasattr(info, 'to_dict') else {"agent_id": info.agent_id}

    def remove_agent(self, agent_id: str) -> bool:
        """移除 Agent。"""
        return self.sm.remove_agent(agent_id)

    def call_agent(self, agent_id: str, task: str, context: dict | None = None) -> dict:
        """调用 Agent 执行任务。"""
        return self.sm.call_agent(agent_id, task, context)

    # ═══════════════════════════════════════════
    # 模式管理
    # ═══════════════════════════════════════════

    def list_patterns(self, query: str = "", limit: int = 20) -> list[dict]:
        """列出/搜索模式。"""
        if query:
            return self.pm.search(query, limit=limit)
        return self.pm.list_all(limit=limit)

    def save_pattern(self, pattern: dict) -> str:
        """保存模式。"""
        return self.pm.save(pattern)

    def instantiate_pattern(self, name_or_id: str, **overrides):
        """从模式实例化 Agent。"""
        # 先按 ID 查，再按名称查
        pat = self.pm.get(name_or_id)
        if not pat:
            pat = self.pm.get_by_name(name_or_id)
        if not pat:
            return None

        agent = self.pm.instantiate(pat["id"], **overrides)
        return {
            "agent_id": agent.agent_id,
            "role": agent.role,
            "goal": agent.goal,
            "pattern": pat["name"],
        } if agent else None

    def recommend_patterns(self, task: str = "", limit: int = 5) -> list[dict]:
        """推荐模式。"""
        return self.pm.recommend(task, limit=limit)

    # ═══════════════════════════════════════════
    # 检查点管理
    # ═══════════════════════════════════════════

    def list_checkpoints(self, status: str = "") -> list[dict]:
        """列出检查点。"""
        if status:
            return self.cpm.load_by_status(status) if hasattr(self.cpm, 'load_by_status') else []
        return self.cpm.list_recent() if hasattr(self.cpm, 'list_recent') else []

    def recover_agent(self, agent_id: str) -> dict | None:
        """从 checkpoint 恢复 Agent。"""
        from .role_agent import RoleAgent
        agent = RoleAgent.recover(agent_id)
        if not agent:
            return None
        return {
            "agent_id": agent.agent_id,
            "role": agent.role,
            "status": agent.status.value,
        }

    def cleanup_checkpoints(self, hours: int = 24) -> int:
        """清理旧检查点。"""
        return self.cpm.cleanup(hours) if hasattr(self.cpm, 'cleanup') else 0

    # ═══════════════════════════════════════════
    # 追踪管理
    # ═══════════════════════════════════════════

    def list_traces(self, limit: int = 10) -> list[dict]:
        """列出最近追踪。"""
        return self.te.list_traces(limit) if hasattr(self.te, 'list_traces') else []

    def view_trace(self, trace_id: str) -> dict | None:
        """查看追踪详情（树形）。"""
        return self.te.get_trace(trace_id) if hasattr(self.te, 'get_trace') else None

    def trace_stats(self) -> dict:
        """追踪统计。"""
        return self.te.get_stats() if hasattr(self.te, 'get_stats') else {}

    # ═══════════════════════════════════════════
    # 系统状态
    # ═══════════════════════════════════════════

    def status(self) -> dict:
        """系统全面状态报告。"""
        agents = self.sm.stats() if hasattr(self.sm, 'stats') else {}
        patterns = self.pm.stats() if hasattr(self.pm, 'stats') else {}
        traces = self.trace_stats()
        checkpoints = {
            "total": self.cpm.count() if hasattr(self.cpm, 'count') else 0,
        }

        # Phase 5: 执行池状态
        pool_status = {}
        try:
            pool = get_execution_pool()
            ps = pool.status()
            pool_status = {
                "pool_name": ps["pool_name"],
                "state": ps["state"],
                "active": ps["active"],
                "tasks": ps["tasks"],
                "stats": ps["stats"],
            }
        except Exception:
            pool_status = {"error": "执行池未初始化"}

        return {
            "timestamp": datetime.now().isoformat(),
            "uptime": (datetime.now() - self._start_time).total_seconds(),
            "agents": agents,
            "patterns": patterns,
            "checkpoints": checkpoints,
            "traces": traces,
            "execution_pool": pool_status,
        }

    # ═══════════════════════════════════════════
    # 报告
    # ═══════════════════════════════════════════

    def report(self) -> str:
        """生成 Markdown 状态报告。"""
        s = self.status()

        lines = [
            "## 📊 Agent 系统状态报告",
            f"> 生成时间: {s['timestamp']}",
            f"> 运行时长: {s['uptime']:.0f}s",
            "",
            "### 🤖 Agent 状态",
        ]

        agent_stats = s.get("agents", {})
        if isinstance(agent_stats, dict):
            for k, v in agent_stats.items():
                lines.append(f"- **{k}**: {v}")
        else:
            lines.append(f"- 总数: {agent_stats}")

        lines.extend([
            "",
            "### 📦 模式市场",
            f"- 总模式: {s.get('patterns', {}).get('total', 0)}",
            f"- 内置: {s.get('patterns', {}).get('builtin', 0)}",
            f"- 自定义: {s.get('patterns', {}).get('custom', 0)}",
            f"- 总使用次数: {s.get('patterns', {}).get('total_usage', 0)}",
            "",
            "### 💾 检查点",
            f"- 总数: {s.get('checkpoints', {}).get('total', 0)}",
            "",
            "### 📊 Trace 统计",
        ])

        trace_stats = s.get("traces", {})
        if isinstance(trace_stats, dict):
            for k, v in trace_stats.items():
                lines.append(f"- **{k}**: {v}")

        return "\n".join(lines)

    # ═══════════════════════════════════════════
    # CLI
    # ═══════════════════════════════════════════

    def cli(self, cmd: str = "") -> str:
        """
        执行 CLI 命令。

        支持命令:
          status       — 系统状态
          agents       — 列出 Agent
          patterns     — 列出模式
          checkpoints  — 列出检查点
          traces       — 列出追踪
          pool         — 执行池状态 (Phase 5)
          workflow     — 工作流状态 (Phase 6)
          report       — 生成 Markdown 报告
          help         — 帮助信息
        """
        cmd = cmd.strip().lower()

        if not cmd or cmd == "help":
            return self._cli_help()

        if cmd == "status":
            return self._format_status()
        elif cmd == "agents":
            return self._format_agents()
        elif cmd == "patterns":
            return self._format_patterns()
        elif cmd == "checkpoints":
            return self._format_checkpoints()
        elif cmd == "traces":
            return self._format_traces()
        elif cmd == "pool":
            return self._format_pool()
        elif cmd == "workflow":
            return self._format_workflow()
        elif cmd == "report":
            return self.report()
        else:
            return f"未知命令: {cmd}\n\n{self._cli_help()}"

    def _cli_help(self) -> str:
        return """🎛️  AdminPanel CLI

用法: panel.cli("<command>")

命令:
  status       — 系统状态概览
  agents       — 列出所有 Agent
  patterns     — 列出所有模式
  checkpoints  — 列出检查点
  traces       — 列出执行追踪
  report       — 生成 Markdown 报告
  help         — 本帮助信息
"""

    def _format_status(self) -> str:
        """格式化状态输出。"""
        s = self.status()
        lines = [
            "=" * 60,
            "🎛️  Agent 系统状态",
            "=" * 60,
            f"运行时长: {s['uptime']:.0f}s",
            "",
            "🤖 Agents:",
        ]
        agent_stats = s.get("agents", {})
        if isinstance(agent_stats, dict):
            for k, v in agent_stats.items():
                lines.append(f"   {k}: {v}")

        lines.extend([
            "",
            "📦 模式市场:",
            f"   总数: {s.get('patterns', {}).get('total', 0)}",
            f"   内置: {s.get('patterns', {}).get('builtin', 0)}",
            f"   自定义: {s.get('patterns', {}).get('custom', 0)}",
            f"   总使用: {s.get('patterns', {}).get('total_usage', 0)}",
            "",
            "💾 检查点:",
            f"   总数: {s.get('checkpoints', {}).get('total', 0)}",
            "",
            "📊 Traces:",
        ])
        trace_stats = s.get("traces", {})
        if isinstance(trace_stats, dict):
            for k, v in trace_stats.items():
                lines.append(f"   {k}: {v}")
        lines.append("=" * 60)
        return "\n".join(lines)

    def _format_agents(self) -> str:
        """格式化 Agent 列表。"""
        agents = self.list_agents()
        if not agents:
            return "🤖 当前没有活跃 Agent。"

        lines = [
            "=" * 60,
            f"🤖 Agent 列表 ({len(agents)})",
            "=" * 60,
        ]
        for a in agents:
            lines.append(
                f"  [{a.get('status','?')}] {a.get('agent_id','?'):20s} "
                f"{a.get('role','?'):15s} "
                f"tasks: {a.get('metrics',{}).get('tasks_completed',0)}✓/{a.get('metrics',{}).get('tasks_failed',0)}✗"
            )
        lines.append("=" * 60)
        return "\n".join(lines)

    def _format_patterns(self) -> str:
        """格式化模式列表。"""
        patterns = self.list_patterns()
        if not patterns:
            return "📦 没有模式。"

        lines = [
            "=" * 60,
            f"📦 模式市场 ({len(patterns)})",
            "=" * 60,
        ]
        for p in patterns:
            tags = ",".join(p.get("tags", []))[:30]
            lines.append(
                f"  [{p.get('usage_count',0)}次] {p.get('name','?'):20s} "
                f"→ {p.get('role','?'):15s} [{tags}]"
            )
        lines.append("=" * 60)
        return "\n".join(lines)

    def _format_checkpoints(self) -> str:
        """格式化检查点列表。"""
        checkpoints = self.list_checkpoints()
        if not checkpoints:
            return "💾 没有检查点。"

        lines = [
            "=" * 60,
            f"💾 检查点 ({len(checkpoints)})",
            "=" * 60,
        ]
        for cp in checkpoints:
            lines.append(
                f"  [{cp.get('status','?')}] {cp.get('agent_id','?'):20s} "
                f"{cp.get('task','')[:50]}"
            )
        lines.append("=" * 60)
        return "\n".join(lines)

    def _format_traces(self) -> str:
        """格式化追踪列表。"""
        traces = self.list_traces()
        if not traces:
            return "📊 没有追踪记录。"

        lines = [
            "=" * 60,
            f"📊 执行追踪 ({len(traces)})",
            "=" * 60,
        ]
        for t in traces:
            lines.append(
                f"  [{t.get('status','?')}] {t.get('trace_id','?'):20s} "
                f"{t.get('task','')[:50]} "
                f"({t.get('duration_ms',0)}ms)"
            )
        lines.append("=" * 60)
        return "\n".join(lines)

    def _format_pool(self) -> str:
        """格式化执行池状态。"""
        try:
            pool = get_execution_pool()
            ps = pool.status()
        except Exception:
            return "⚡ 执行池未初始化。"

        lines = [
            "=" * 60,
            f"⚡ ExecutionPool [{ps['pool_name']}] ({ps['state']})",
            "=" * 60,
            f"  活跃线程: {ps['max_workers']}",
            f"  队列: {ps['queue_size']}",
            f"  活跃任务: {ps['active']}",
            "",
            "  📊 任务统计:",
            f"    待处理: {ps['tasks']['pending']}",
            f"    运行中: {ps['tasks']['running']}",
            f"    已完成: {ps['tasks']['completed']}",
            f"    失败:   {ps['tasks']['failed']}",
            "",
            "  📈 性能:",
            f"    平均耗时: {ps['stats']['avg_duration']}s",
            f"    总耗时:   {ps['stats']['total_duration']:.1f}s",
            "=" * 60,
        ]
        return "\n".join(lines)

    def _format_workflow(self) -> str:
        """格式化工作流状态 (Phase 6)。"""
        from .workflow_engine import WorkflowTemplate

        templates = WorkflowTemplate.list_templates()
        lines = [
            "=" * 60,
            f"📋 工作流模板 ({len(templates)})",
            "=" * 60,
        ]
        if not templates:
            lines.append("  (空) 使用 WorkflowTemplate.save() 添加")
        for t in templates:
            name = t["name"]
            desc = t.get("description", "")[:40]
            nodes = len(t.get("dag", {}).get("nodes", {}))
            lines.append(f"  📄 {name:20s} {desc:40s} nodes={nodes}")
        lines.append("=" * 60)
        lines.append("")
        lines.append("💡 快速开始:")
        lines.append('  from tea_agent.multi_agent import WorkflowDAG, WorkflowNode, NodeType')
        lines.append('  dag = WorkflowDAG()')
        lines.append('  dag.add_node(WorkflowNode("start", NodeType.TASK, fn=...))')
        lines.append('  wf = WorkflowExec(dag).run()')
        lines.append("=" * 60)
        return "\n".join(lines)

    def __repr__(self):
        return f"AdminPanel(uptime={(datetime.now()-self._start_time).total_seconds():.0f}s)"
