"""
子 Agent 调度器 — 任务分解 + 并行执行。

核心设计:
  1. 将复杂任务分解为有向无环图 (DAG)
  2. 拓扑排序确定执行层级
  3. 同层子任务并行（ThreadPoolExecutor）
  4. 上下文透传：前置步骤结果 → 后续步骤

用法:
    from tea_agent.multi_agent import Dispatcher

    dispatcher = Dispatcher()
    result = dispatcher.dispatch("重构项目添加类型注解")
    print(result)
"""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from .lite_agent import LiteAgent

logger = logging.getLogger(__name__)


class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class SubTask:
    """子任务定义"""
    id: str
    name: str
    description: str
    tools: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    status: TaskStatus = TaskStatus.PENDING
    result: str | None = None
    error: str | None = None
    time_seconds: float = 0


class Dispatcher:
    """
    子 Agent 调度器。

    工作流: dispatch() → decompose() → _topological_sort() → _execute_layers() → _merge_results()
    """

    # 任务模式到步骤的映射
    PATTERNS = {
        "refactor": [
            ("analyze", "分析代码结构，列出需要重构的部分"),
            ("plan", "设计重构方案"),
            ("execute", "执行重构，修改代码"),
            ("verify", "验证：运行测试确保没有破坏"),
        ],
        "type_annotation": [
            ("scan", "扫描 Python 文件，列出需要添加类型注解的函数"),
            ("annotate", "为函数添加类型注解"),
            ("check", "运行类型检查 (mypy/pyright)"),
            ("test", "运行测试确保没有破坏"),
        ],
        "test": [
            ("analyze", "分析需要测试的代码"),
            ("write", "编写测试用例"),
            ("run", "运行测试"),
            ("fix", "修复失败的测试（如果有）"),
        ],
        "fix": [
            ("locate", "定位问题根因"),
            ("fix", "修复代码"),
            ("verify", "验证修复"),
        ],
        "doc": [
            ("analyze", "分析代码结构"),
            ("write", "编写文档"),
            ("format", "格式化文档"),
        ],
        "feature": [
            ("analyze", "分析需求"),
            ("implement", "实现功能"),
            ("test", "编写并运行测试"),
        ],
        "default": [
            ("analyze", "分析任务"),
            ("execute", "执行操作"),
            ("verify", "验证结果"),
        ],
    }

    def __init__(self, max_workers: int = 3):
        self.max_workers = max_workers

    def dispatch(
        self,
        goal: str,
        files: list[str] | None = None,
        context: dict | None = None,
        on_progress: callable | None = None,
    ) -> dict:
        """
        分发任务并同步执行。

        Args:
            goal: 任务目标
            files: 相关文件列表
            context: 额外上下文
            on_progress: 进度回调 fn(task_id, status, message)

        Returns:
            执行结果字典
        """
        # 1. 分解任务
        pattern = self._identify_pattern(goal)
        tasks = self._generate_tasks(goal, pattern)
        logger.info(f"📋 任务分解: {goal} → {len(tasks)} 个子任务 ({pattern})")

        # 2. 拓扑排序
        layers = self._topological_sort(tasks)

        # 3. 执行
        context = context or {}
        results = self._execute_layers(layers, context, on_progress)

        # 4. 整合结果
        return self._merge_results(goal, tasks, results)

    # ───────────────────────────────────────────────
    # 任务分解
    # ───────────────────────────────────────────────

    def _identify_pattern(self, goal: str) -> str:
        goal_lower = goal.lower()
        pattern_keywords = {
            "refactor": ["重构", "refactor", "重写"],
            "type_annotation": ["类型注解", "type annotation", "type hint", "类型提示"],
            "test": ["测试", "test", "pytest", "unittest"],
            "fix": ["修复", "fix", "bug", "问题", "错误"],
            "doc": ["文档", "doc", "readme"],
            "feature": ["新增", "add", "创建", "create", "功能"],
        }
        for pattern, keywords in pattern_keywords.items():
            if any(kw in goal_lower for kw in keywords):
                return pattern
        return "default"

    def _generate_tasks(self, goal: str, pattern: str) -> list[SubTask]:
        steps = self.PATTERNS.get(pattern, self.PATTERNS["default"])
        tasks = []
        for i, (name, desc) in enumerate(steps):
            task_id = f"step_{i + 1}"
            dependencies = [f"step_{i}"] if i > 0 else []
            tasks.append(SubTask(
                id=task_id,
                name=name,
                description=f"{goal} — {desc}",
                dependencies=dependencies,
            ))
        return tasks

    # ───────────────────────────────────────────────
    # 拓扑排序
    # ───────────────────────────────────────────────

    def _topological_sort(self, tasks: list[SubTask]) -> list[list[SubTask]]:
        in_degree = {t.id: len(t.dependencies) for t in tasks}
        queue = [t for t in tasks if in_degree[t.id] == 0]
        layers = []

        while queue:
            layers.append(list(queue))
            next_queue = []
            for task in queue:
                for other in tasks:
                    if task.id in other.dependencies:
                        in_degree[other.id] -= 1
                        if in_degree[other.id] == 0:
                            next_queue.append(other)
            queue = next_queue

        return layers

    # ───────────────────────────────────────────────
    # 执行引擎
    # ───────────────────────────────────────────────

    def _execute_layers(
        self,
        layers: list[list[SubTask]],
        context: dict,
        on_progress: callable | None,
    ) -> dict[str, dict]:
        """逐层执行，同层并行。"""
        all_results: dict[str, dict] = {}
        # 累积上下文：前置步骤结果
        accumulated_context: dict[str, str] = {}

        for layer_idx, layer in enumerate(layers):
            logger.info(f"  ⚡ 执行第 {layer_idx + 1}/{len(layers)} 层 ({len(layer)} 个子任务)")

            if len(layer) == 1:
                # 单任务直接执行
                task = layer[0]
                result = self._execute_single_task(task, accumulated_context, context)
                all_results[task.id] = result
                if result["success"]:
                    accumulated_context[task.name] = result["result"]
            else:
                # 多任务并行
                with ThreadPoolExecutor(max_workers=min(self.max_workers, len(layer))) as pool:
                    future_map = {
                        pool.submit(
                            self._execute_single_task, task, accumulated_context, context
                        ): task
                        for task in layer
                    }
                    for future in as_completed(future_map):
                        task = future_map[future]
                        try:
                            result = future.result()
                        except Exception as e:
                            result = {"success": False, "result": "", "error": str(e)}
                            task.status = TaskStatus.FAILED
                            task.error = str(e)

                        all_results[task.id] = result
                        if result["success"]:
                            accumulated_context[task.name] = result["result"]

        return all_results

    def _execute_single_task(
        self,
        task: SubTask,
        accumulated_context: dict[str, str],
        global_context: dict,
    ) -> dict:
        """执行单个子任务。"""
        task.status = TaskStatus.RUNNING
        start = datetime.now()

        if on_progress := getattr(self, '_on_progress', None):
            on_progress(task.id, "running", task.name)

        try:
            agent = LiteAgent(max_iterations=15, enable_thinking=False)

            # 构建子任务上下文
            sub_context = {}
            # 注入前置步骤结果
            for _dep_id in task.dependencies:
                for step_name, result_text in accumulated_context.items():
                    sub_context[step_name] = result_text
            # 注入全局上下文
            if global_context:
                sub_context.update(global_context)

            result_text = agent.execute_with_context(task.description, sub_context) if sub_context else agent.execute_sync(task.description)

            elapsed = (datetime.now() - start).total_seconds()
            task.status = TaskStatus.COMPLETED
            task.result = result_text
            task.time_seconds = elapsed

            logger.info(f"  ✅ {task.name} 完成 ({elapsed:.1f}s)")
            return {"success": True, "result": result_text, "error": None, "time": elapsed}

        except Exception as e:
            elapsed = (datetime.now() - start).total_seconds()
            task.status = TaskStatus.FAILED
            task.error = str(e)
            task.time_seconds = elapsed

            logger.error(f"  ❌ {task.name} 失败: {e}")
            return {"success": False, "result": "", "error": str(e), "time": elapsed}

    # ───────────────────────────────────────────────
    # 结果整合
    # ───────────────────────────────────────────────

    def _merge_results(self, goal: str, tasks: list[SubTask], results: dict) -> dict:
        total = len(tasks)
        successful = sum(1 for t in tasks if t.status == TaskStatus.COMPLETED)
        total_time = sum(t.time_seconds for t in tasks)

        task_summaries = []
        for t in tasks:
            task_summaries.append({
                "step": t.name,
                "description": t.description,
                "status": t.status.value,
                "result": t.result[:500] if t.result else None,
                "error": t.error,
                "time_seconds": round(t.time_seconds, 1),
            })

        return {
            "goal": goal,
            "success": successful == total,
            "total_steps": total,
            "completed_steps": successful,
            "failed_steps": total - successful,
            "total_time_seconds": round(total_time, 1),
            "tasks": task_summaries,
            "summary": self._build_summary(goal, successful, total, total_time),
        }

    def _build_summary(self, goal: str, successful: int, total: int, time: float) -> str:
        if successful == total:
            return f"✅ 全部完成: {goal} ({total} 步, {time:.1f}s)"
        else:
            return f"⚠️ 部分完成: {goal} ({successful}/{total} 步, {time:.1f}s)"

    def visualize(self, goal: str) -> str:
        """可视化执行计划（不执行）。"""
        pattern = self._identify_pattern(goal)
        tasks = self._generate_tasks(goal, pattern)

        lines = [f"📋 执行计划: {goal}", f"   模式: {pattern}", ""]
        for i, t in enumerate(tasks):
            prefix = "├─" if i < len(tasks) - 1 else "└─"
            lines.append(f"   {prefix} [{t.id}] {t.name}")
            lines.append(f"   │  {t.description}")
            if i < len(tasks) - 1:
                lines.append("   │")

        return "\n".join(lines)
