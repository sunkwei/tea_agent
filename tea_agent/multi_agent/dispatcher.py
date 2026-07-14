"""
子 Agent 调度器 — 角色化 + Flow 驱动。

核心设计演变:
  v1 (旧): DAG + 拓扑排序 + LiteAgent 无差别执行
  v2 (新): FlowEngine + RoleAgent + 结构化输出

关键改进:
  1. 每个子任务由特定 Role（角色）的 Agent 执行
  2. 执行流程由 FlowEngine 事件驱动（非固定 DAG）
  3. 支持结构化输出（Pydantic 模型）
  4. 条件路由和分支执行
  5. 完善的进度回调和可视化

用法:
    from tea_agent.multi_agent import RoleDispatcher

    dispatcher = RoleDispatcher()
    result = dispatcher.dispatch("重构项目添加类型注解")
    print(result["summary"])
    print(dispatcher.visualize("重构项目添加类型注解"))
"""

import json
import logging
from collections.abc import Callable
from datetime import datetime
from enum import Enum
from typing import Any

from .flow_engine import FlowEngine, FlowState, flow_start, flow_listen, flow_route
from .role_agent import RoleAgent, AgentResult
from .structured_output import AnalysisReport, CodeChangePlan, TestPlan

logger = logging.getLogger(__name__)


# ───────────────────────────────────────────────
# 任务模式定义
# ───────────────────────────────────────────────

class TaskPattern(Enum):
    """任务模式枚举。"""
    REFACTOR = "refactor"
    TYPE_ANNOTATION = "type_annotation"
    TEST = "test"
    FIX = "fix"
    DOC = "doc"
    FEATURE = "feature"
    REVIEW = "review"
    DEFAULT = "default"


PATTERN_KEYWORDS: dict[TaskPattern, list[str]] = {
    TaskPattern.REFACTOR: ["重构", "refactor", "重写", "优化", "optimize"],
    TaskPattern.TYPE_ANNOTATION: ["类型注解", "type annotation", "type hint", "类型提示"],
    TaskPattern.TEST: ["测试", "test", "pytest", "unittest", "测试用例"],
    TaskPattern.FIX: ["修复", "fix", "bug", "问题", "错误", "error", "故障"],
    TaskPattern.DOC: ["文档", "doc", "readme", "documentation"],
    TaskPattern.FEATURE: ["新增", "add", "创建", "create", "功能", "feature"],
    TaskPattern.REVIEW: ["审查", "review", "审阅", "检查", "audit"],
}


# ───────────────────────────────────────────────
# Flow 实现：各种模式的执行流
# ───────────────────────────────────────────────

class RefactorFlow(FlowEngine):
    """重构模式 Flow — 分析→规划→执行→验证。"""

    def __init__(self, goal: str, files: list[str], context: dict | None = None, verbose: bool = True):
        super().__init__(name=f"Refactor:{goal[:40]}")
        self._goal = goal
        self._files = files
        self._context = context or {}
        self._verbose = verbose
        self._agents: dict[str, RoleAgent] = {}
        self._results: dict[str, AgentResult] = {}

    @flow_start()
    def analyze(self):
        """步骤1: 分析代码（分析专家）。"""
        if self._verbose:
            logger.info(f"🔍 [分析] 分析代码结构: {self._files}")

        agent = self._get_agent("analyst", "资深代码分析专家",
            "分析代码结构、识别问题、评估工作量",
            "你擅长快速理解代码架构，发现设计问题和代码坏味道。")
        result = agent.execute(
            f"请分析以下文件的结构和问题：{self._files}。\n"
            f"任务目标：{self._goal}\n"
            f"请输出：1) 文件结构摘要 2) 需要修改的部分 3) 潜在风险",
            output_model=AnalysisReport,
        )
        self._results["analyze"] = result
        # 保存到 state
        if result.structured:
            self.state["analysis"] = result.structured
        return result.output

    @flow_listen(analyze)
    def plan(self):
        """步骤2: 规划修改方案（架构师）。"""
        analysis = self.state.get("analysis", {})
        issues = analysis.get("issues", []) if isinstance(analysis, dict) else []

        agent = self._get_agent("architect", "软件架构师",
            "设计修改方案，确保架构一致性",
            "你有丰富的重构经验，善于制定最小改动量的优化方案。")
        result = agent.execute(
            f"基于分析结果制定修改计划。\n"
            f"任务目标：{self._goal}\n"
            f"相关文件：{self._files}\n"
            f"发现问题：{json.dumps(issues, ensure_ascii=False, indent=2)[:2000]}\n"
            f"请输出具体的修改步骤（文件、修改内容、顺序）。",
            output_model=CodeChangePlan,
        )
        self._results["plan"] = result
        if result.structured:
            self.state["plan"] = result.structured
        return result.output

    @flow_listen(plan)
    def execute(self):
        """步骤3: 执行修改（高级工程师）。"""
        plan_data = self.state.get("plan", {})

        agent = self._get_agent("coder", "高级软件工程师",
            "实现代码修改，保持代码质量",
            "你擅长编写高质量 Python 代码，注重类型安全和可读性。")
        changes = plan_data.get("files_to_change", []) if isinstance(plan_data, dict) else []
        changes_str = json.dumps(changes, ensure_ascii=False, indent=2) if changes else "(按分析结果执行)"

        result = agent.execute(
            f"执行修改计划。\n"
            f"任务目标：{self._goal}\n"
            f"修改方案：{changes_str}\n"
            f"请逐步完成所有修改，确保代码编译通过。",
        )
        self._results["execute"] = result
        self.state["execute_output"] = result.output
        return result.output

    @flow_listen(execute)
    def verify(self):
        """步骤4: 验证（测试工程师）。"""
        agent = self._get_agent("tester", "测试工程师",
            "验证修改正确性，运行测试",
            "你精通 pytest，善于编写和运行测试用例。")
        result = agent.execute(
            f"验证修改结果。\n"
            f"任务目标：{self._goal}\n"
            f"请运行相关测试，确保没有回归问题。\n"
            f"如发现失败，分析根因并给出修复建议。",
        )
        self._results["verify"] = result
        self.state["verify_output"] = result.output
        return result.output

    def _get_agent(self, name: str, role: str, goal: str, backstory: str) -> RoleAgent:
        """获取或创建角色 Agent。"""
        if name not in self._agents:
            self._agents[name] = RoleAgent(
                role=role,
                goal=goal,
                backstory=backstory,
                verbose=self._verbose,
            )
        return self._agents[name]


class ReviewFlow(FlowEngine):
    """审查模式 Flow。"""

    def __init__(self, goal: str, files: list[str], context: dict | None = None, verbose: bool = True):
        super().__init__(name=f"Review:{goal[:40]}")
        self._goal = goal
        self._files = files
        self._context = context or {}
        self._verbose = verbose
        self._agents: dict[str, RoleAgent] = {}

    @flow_start()
    def scan(self):
        agent = self._get_agent("reviewer", "严格的代码审查员",
            "全面审查代码质量",
            "你以严苛著称，对代码质量零容忍。")
        result = agent.execute(
            f"审查以下文件：{self._files}\n"
            f"审查维度：类型安全、错误处理、性能、可维护性、设计模式",
            output_model=AnalysisReport,
        )
        self._results["scan"] = result
        if result.structured:
            self.state["scan_result"] = result.structured
        return result.output

    @flow_listen(scan)
    def report(self):
        issues = self.state.get("scan_result", {}).get("issues", [])
        critical = [i for i in issues if isinstance(i, dict) and i.get("severity") in ("critical", "high")]
        yield {"issues_count": len(issues), "critical_count": len(critical)}
        return json.dumps({"issues": issues}, ensure_ascii=False)

    def _get_agent(self, name: str, role: str, goal: str, backstory: str) -> RoleAgent:
        if name not in self._agents:
            self._agents[name] = RoleAgent(role=role, goal=goal, backstory=backstory, verbose=self._verbose)
        return self._agents[name]


class TestFlow(FlowEngine):
    """测试模式 Flow。"""

    def __init__(self, goal: str, files: list[str], context: dict | None = None, verbose: bool = True):
        super().__init__(name=f"Test:{goal[:40]}")
        self._goal = goal
        self._files = files
        self._context = context or {}
        self._verbose = verbose
        self._agents: dict[str, RoleAgent] = {}

    @flow_start()
    def plan_tests(self):
        agent = self._get_agent("tester", "测试工程师", "制定测试计划", "精通 pytest")
        result = agent.execute(
            f"为以下文件制定测试计划：{self._files}\n目标：{self._goal}",
            output_model=TestPlan,
        )
        self._results["plan_tests"] = result
        if result.structured:
            self.state["test_plan"] = result.structured
        return result.output

    @flow_listen(plan_tests)
    def write_tests(self):
        agent = self._get_agent("coder", "测试开发工程师", "编写测试用例", "擅长编写高质量测试")
        plan = self.state.get("test_plan", {})
        result = agent.execute(
            f"编写测试用例。\n"
            f"文件：{self._files}\n"
            f"测试计划：{json.dumps(plan, ensure_ascii=False, indent=2)[:2000]}",
        )
        self._results["write_tests"] = result
        return result.output

    @flow_listen(write_tests)
    def run_tests(self):
        agent = self._get_agent("tester", "测试工程师", "运行测试并分析结果", "精通 pytest")
        result = agent.execute(
            f"运行测试并分析结果：{self._files}\n"
            f"如有失败，分析根因并给出修复建议。"
        )
        self._results["run_tests"] = result
        return result.output

    def _get_agent(self, name: str, role: str, goal: str, backstory: str) -> RoleAgent:
        if name not in self._agents:
            self._agents[name] = RoleAgent(role=role, goal=goal, backstory=backstory, verbose=self._verbose)
        return self._agents[name]


class FixFlow(FlowEngine):
    """修复模式 Flow。"""

    def __init__(self, goal: str, files: list[str], context: dict | None = None, verbose: bool = True):
        super().__init__(name=f"Fix:{goal[:40]}")
        self._goal = goal
        self._files = files
        self._context = context or {}
        self._verbose = verbose
        self._agents: dict[str, RoleAgent] = {}

    @flow_start()
    def diagnose(self):
        agent = self._get_agent("debugger", "调试专家", "定位问题根因", "擅长调试和根因分析")
        result = agent.execute(
            f"分析并定位以下问题：{self._goal}\n"
            f"相关文件：{self._files}\n"
            f"请定位根因并给出修复建议。"
        )
        self._results["diagnose"] = result
        return result.output

    @flow_listen(diagnose)
    def fix(self):
        agent = self._get_agent("coder", "修复工程师", "修复问题", "擅长精确修复")
        diagnosis = self.get_step_output("diagnose") or ""
        result = agent.execute(
            f"根据分析结果修复问题。\n"
            f"诊断结果：{diagnosis[:2000]}\n"
            f"相关文件：{self._files}"
        )
        self._results["fix"] = result
        return result.output

    @flow_listen(fix)
    def verify(self):
        agent = self._get_agent("tester", "验证工程师", "验证修复", "擅长验证")
        result = agent.execute(f"验证修复是否正确：{self._files}")
        self._results["verify"] = result
        return result.output

    def _get_agent(self, name: str, role: str, goal: str, backstory: str) -> RoleAgent:
        if name not in self._agents:
            self._agents[name] = RoleAgent(role=role, goal=goal, backstory=backstory, verbose=self._verbose)
        return self._agents[name]


class FeatureFlow(FlowEngine):
    """功能开发模式 Flow。"""

    def __init__(self, goal: str, files: list[str], context: dict | None = None, verbose: bool = True):
        super().__init__(name=f"Feature:{goal[:40]}")
        self._goal = goal
        self._files = files
        self._context = context or {}
        self._verbose = verbose
        self._agents: dict[str, RoleAgent] = {}

    @flow_start()
    def analyze(self):
        agent = self._get_agent("analyst", "需求分析师", "理解需求并制定实现方案", "擅长需求分析")
        result = agent.execute(
            f"分析需求并制定实现方案：{self._goal}\n"
            f"相关文件：{self._files}"
        )
        self._results["analyze"] = result
        return result.output

    @flow_listen(analyze)
    def implement(self):
        agent = self._get_agent("coder", "高级工程师", "实现功能", "精通 Python 开发")
        analysis = self.get_step_output("analyze") or ""
        result = agent.execute(
            f"实现功能。\n需求：{self._goal}\n分析：{analysis[:2000]}\n文件：{self._files}"
        )
        self._results["implement"] = result
        return result.output

    @flow_listen(implement)
    def test(self):
        agent = self._get_agent("tester", "测试工程师", "编写并运行测试", "精通 pytest")
        result = agent.execute(
            f"为新增功能编写测试并运行：{self._files}\n功能：{self._goal}"
        )
        self._results["test"] = result
        return result.output

    def _get_agent(self, name: str, role: str, goal: str, backstory: str) -> RoleAgent:
        if name not in self._agents:
            self._agents[name] = RoleAgent(role=role, goal=goal, backstory=backstory, verbose=self._verbose)
        return self._agents[name]


class DocFlow(FlowEngine):
    """文档模式 Flow。"""

    def __init__(self, goal: str, files: list[str], context: dict | None = None, verbose: bool = True):
        super().__init__(name=f"Doc:{goal[:40]}")
        self._goal = goal
        self._files = files
        self._context = context or {}
        self._verbose = verbose
        self._agents: dict[str, RoleAgent] = {}

    @flow_start()
    def analyze(self):
        agent = self._get_agent("analyst", "技术文档工程师", "分析代码结构", "擅长文档编写")
        result = agent.execute(f"分析代码结构，准备编写文档：{self._files}")
        self._results["analyze"] = result
        return result.output

    @flow_listen(analyze)
    def write(self):
        agent = self._get_agent("writer", "技术文档专家", "编写文档", "擅长技术写作")
        analysis = self.get_step_output("analyze") or ""
        result = agent.execute(f"编写文档。\n目标：{self._goal}\n分析：{analysis[:2000]}")
        self._results["write"] = result
        return result.output

    @flow_listen(write)
    def format(self):
        agent = self._get_agent("writer", "文档工程师", "格式化文档", "擅长 markdown 排版")
        result = agent.execute(f"格式化文档，确保排版美观：{self._files}")
        self._results["format"] = result
        return result.output

    def _get_agent(self, name: str, role: str, goal: str, backstory: str) -> RoleAgent:
        if name not in self._agents:
            self._agents[name] = RoleAgent(role=role, goal=goal, backstory=backstory, verbose=self._verbose)
        return self._agents[name]


# ───────────────────────────────────────────────
# Flow 工厂
# ───────────────────────────────────────────────

_FLOW_REGISTRY: dict[TaskPattern, type[FlowEngine]] = {
    TaskPattern.REFACTOR: RefactorFlow,
    TaskPattern.REVIEW: ReviewFlow,
    TaskPattern.TEST: TestFlow,
    TaskPattern.FIX: FixFlow,
    TaskPattern.FEATURE: FeatureFlow,
    TaskPattern.DOC: DocFlow,
}


def create_flow(pattern: TaskPattern, goal: str, files: list[str], context: dict | None = None, verbose: bool = True) -> FlowEngine:
    """根据模式创建对应的 Flow 实例。"""
    flow_cls = _FLOW_REGISTRY.get(pattern)
    if flow_cls is None:
        # 默认使用 RefactorFlow
        flow_cls = RefactorFlow
    return flow_cls(goal=goal, files=files, context=context, verbose=verbose)


# ───────────────────────────────────────────────
# RoleDispatcher — 主要公开 API
# ───────────────────────────────────────────────

class RoleDispatcher:
    """
    角色化调度器 — Flow 驱动的多 Agent 执行引擎。

    相比旧版 Dispatcher 的关键改进:
      - 使用 FlowEngine 事件驱动而非固定 DAG
      - 每个步骤由专门角色的 Agent 执行
      - 支持结构化输出（Pydantic）
      - 条件路由和分支执行
      - 进度回调和可视化
    """

    def __init__(self, max_workers: int = 3, verbose: bool = True):
        self.max_workers = max_workers
        self.verbose = verbose
        self._last_flow: FlowEngine | None = None

    def dispatch(
        self,
        goal: str,
        files: list[str] | None = None,
        context: dict | None = None,
        on_progress: Callable | None = None,
    ) -> dict:
        """
        分发任务并执行。

        Args:
            goal: 任务目标
            files: 相关文件列表
            context: 额外上下文
            on_progress: 进度回调 fn(step_name, status, message)

        Returns:
            执行结果字典
        """
        files = files or []
        context = context or {}

        # 1. 识别模式
        pattern = self._identify_pattern(goal)
        if self.verbose:
            logger.info(f"📋 任务: {goal} → 模式: {pattern.value} ({len(files)} 个文件)")

        # 2. 创建 Flow
        flow = create_flow(pattern, goal, files, context, verbose=self.verbose)
        self._last_flow = flow

        # 3. 注入初始上下文
        initial_state = {"goal": goal, "files": files, **context}

        # 4. 执行
        if self.verbose:
            logger.info(f"🔀 执行 Flow: {flow.name}")
        result = flow.run(initial_state=initial_state)

        # 5. 格式化输出
        return self._format_result(goal, pattern, result)

    def dispatch_with_flow(
        self,
        flow_cls: type[FlowEngine],
        goal: str,
        files: list[str] | None = None,
        context: dict | None = None,
    ) -> dict:
        """
        使用自定义 Flow 类执行任务。

        允许用户传入自定义的 Flow 子类，实现完全自定义的执行流程。

        Args:
            flow_cls: FlowEngine 子类
            goal: 任务目标
            files: 相关文件列表
            context: 额外上下文

        Returns:
            执行结果字典
        """
        files = files or []
        context = context or {}
        flow = flow_cls(goal=goal, files=files, context=context, verbose=self.verbose)
        self._last_flow = flow
        result = flow.run(initial_state={"goal": goal, "files": files, **context})
        return self._format_result(goal, TaskPattern.DEFAULT, result)

    def visualize(self, goal: str) -> str:
        """可视化执行计划（不执行）。"""
        pattern = self._identify_pattern(goal)
        flow = create_flow(pattern, goal, [])
        return flow.visualize()

    def get_last_flow(self) -> FlowEngine | None:
        """获取最后一次执行的 Flow 实例（用于后续分析）。"""
        return self._last_flow

    # ───────────────────────────────────────────────
    # 内部方法
    # ───────────────────────────────────────────────

    def _identify_pattern(self, goal: str) -> TaskPattern:
        """根据任务目标识别模式。"""
        goal_lower = goal.lower()
        for pattern, keywords in PATTERN_KEYWORDS.items():
            if any(kw in goal_lower for kw in keywords):
                return pattern
        return TaskPattern.DEFAULT

    def _format_result(self, goal: str, pattern: TaskPattern, flow_result: dict) -> dict:
        """将 Flow 执行结果格式化为统一输出格式。"""
        total = flow_result.get("total_steps", 0)
        completed = flow_result.get("completed_steps", 0)
        failed = flow_result.get("failed_steps", 0)
        total_time = flow_result.get("total_time_seconds", 0)
        success = flow_result.get("success", False)

        # 构建步骤摘要
        execution_log = flow_result.get("execution_log", [])
        task_summaries = []
        for entry in execution_log:
            task_summaries.append({
                "step": entry["step"],
                "status": entry["status"],
                "time_seconds": entry.get("time_seconds", 0),
                "error": entry.get("error"),
            })

        return {
            "goal": goal,
            "pattern": pattern.value,
            "success": success,
            "total_steps": total,
            "completed_steps": completed,
            "failed_steps": failed,
            "total_time_seconds": total_time,
            "tasks": task_summaries,
            "state": flow_result.get("state", {}),
            "errors": flow_result.get("errors", {}),
            "summary": self._build_summary(goal, completed, total, total_time, success),
        }

    @staticmethod
    def _build_summary(goal: str, completed: int, total: int, time: float, success: bool) -> str:
        if success:
            return f"✅ 全部完成: {goal} ({total} 步, {time:.1f}s)"
        else:
            return f"⚠️ 部分完成: {goal} ({completed}/{total} 步, {time:.1f}s)"


# ───────────────────────────────────────────────
# 向后兼容: 旧版 Dispatcher 保留
# ───────────────────────────────────────────────

from .dispatcher_v1 import Dispatcher as _DispatcherV1


class Dispatcher(_DispatcherV1):
    """
    旧版 Dispatcher（向后兼容）。

    推荐使用 RoleDispatcher 替代。
    """
    pass
