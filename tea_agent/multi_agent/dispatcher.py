"""
子 Agent 调度器 — 任务分解 + 并行执行。

设计灵感:
  learn-claude-code 的 Subagent 隔离 + EvoAgentX 的工作流生成

功能:
  - 将复杂任务分解为子任务
  - 调度 lite_agent 并行执行
  - 整合结果

用法:
    from tea_agent.multi_agent import Dispatcher
    
    dispatcher = Dispatcher()
    result = await dispatcher.dispatch(
        goal="重构项目添加类型注解",
        tools=["toolkit_file", "toolkit_edit", "toolkit_lsp"]
    )
"""

import asyncio
import json
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

import logging

logger = logging.getLogger(__name__)


class TaskStatus(Enum):
    """任务状态"""
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
    tools: List[str]
    dependencies: List[str] = field(default_factory=list)  # 依赖的其他子任务 ID
    status: TaskStatus = TaskStatus.PENDING
    result: Optional[str] = None
    error: Optional[str] = None
    token_cost: int = 0
    time_seconds: float = 0


@dataclass
class Workflow:
    """工作流定义"""
    id: str
    goal: str
    tasks: List[SubTask]
    created_at: str = ""
    
    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()


class Dispatcher:
    """子 Agent 调度器"""
    
    # 任务分解模式
    DECOMPOSE_PATTERNS = {
        "refactor": ["分析代码", "设计重构方案", "执行重构", "验证测试"],
        "test": ["分析测试需求", "编写测试用例", "运行测试", "修复失败"],
        "doc": ["分析代码结构", "生成文档", "校验格式"],
        "fix": ["定位问题", "分析原因", "修复代码", "验证修复"],
        "feature": ["分析需求", "设计实现", "编写代码", "测试验证"],
        "default": ["分析任务", "执行操作", "验证结果"],
    }
    
    def __init__(self, max_workers: int = 3):
        """
        Args:
            max_workers: 最大并行 worker 数量
        """
        self.max_workers = max_workers
        self.workflows: Dict[str, Workflow] = {}
    
    async def dispatch(
        self,
        goal: str,
        tools: Optional[List[str]] = None,
        files: Optional[List[str]] = None,
        context: Optional[Dict] = None,
    ) -> Dict:
        """
        分发任务。
        
        Args:
            goal: 任务目标
            tools: 可用工具列表
            files: 相关文件列表
            context: 额外上下文
            
        Returns:
            执行结果
        """
        # 1. 分解任务
        workflow = self.decompose(goal, tools, files)
        self.workflows[workflow.id] = workflow
        
        logger.info(f"📋 工作流创建: {workflow.id} ({len(workflow.tasks)} 个子任务)")
        
        # 2. 拓扑排序，确定执行顺序
        execution_order = self._topological_sort(workflow.tasks)
        
        # 3. 执行工作流
        results = await self._execute_workflow(workflow, execution_order, context)
        
        # 4. 整合结果
        final_result = self._merge_results(workflow, results)
        
        return final_result
    
    def decompose(
        self,
        goal: str,
        tools: Optional[List[str]] = None,
        files: Optional[List[str]] = None,
    ) -> Workflow:
        """
        分解任务为工作流。
        
        Args:
            goal: 任务目标
            tools: 可用工具列表
            files: 相关文件列表
            
        Returns:
            Workflow 对象
        """
        if tools is None:
            tools = []
        if files is None:
            files = []
        
        # 生成工作流 ID
        workflow_id = f"wf_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        # 识别任务模式
        pattern = self._identify_pattern(goal)
        
        # 生成子任务
        tasks = self._generate_tasks(goal, pattern, tools, files)
        
        return Workflow(
            id=workflow_id,
            goal=goal,
            tasks=tasks,
        )
    
    def _identify_pattern(self, goal: str) -> str:
        """识别任务模式"""
        goal_lower = goal.lower()
        
        if any(kw in goal_lower for kw in ["重构", "refactor", "重写"]):
            return "refactor"
        elif any(kw in goal_lower for kw in ["测试", "test", "pytest"]):
            return "test"
        elif any(kw in goal_lower for kw in ["文档", "doc", "readme"]):
            return "doc"
        elif any(kw in goal_lower for kw in ["修复", "fix", "bug"]):
            return "fix"
        elif any(kw in goal_lower for kw in ["新增", "add", "创建", "create"]):
            return "feature"
        else:
            return "default"
    
    def _generate_tasks(
        self,
        goal: str,
        pattern: str,
        tools: List[str],
        files: List[str],
    ) -> List[SubTask]:
        """根据模式生成子任务"""
        steps = self.DECOMPOSE_PATTERNS.get(pattern, self.DECOMPOSE_PATTERNS["default"])
        
        tasks = []
        for i, step in enumerate(steps):
            task_id = f"task_{i+1}"
            
            # 确定每个子任务需要的工具
            task_tools = self._assign_tools(step, tools)
            
            # 确定依赖
            dependencies = [f"task_{i}"] if i > 0 else []
            
            task = SubTask(
                id=task_id,
                name=step,
                description=f"{goal} - {step}",
                tools=task_tools,
                dependencies=dependencies,
            )
            tasks.append(task)
        
        return tasks
    
    def _assign_tools(self, step: str, available_tools: List[str]) -> List[str]:
        """为子任务分配工具"""
        # 根据步骤名称推断需要的工具
        step_lower = step.lower()
        
        tool_mapping = {
            "分析": ["toolkit_file", "toolkit_search", "toolkit_lsp"],
            "测试": ["toolkit_run_tests"],
            "重构": ["toolkit_edit", "toolkit_diff"],
            "文档": ["toolkit_file", "toolkit_save_file"],
            "修复": ["toolkit_edit", "toolkit_diff"],
            "代码": ["toolkit_file", "toolkit_edit"],
        }
        
        assigned = []
        for keyword, tools in tool_mapping.items():
            if keyword in step_lower:
                assigned.extend(tools)
        
        # 添加用户指定的工具
        for tool in available_tools:
            if tool not in assigned:
                assigned.append(tool)
        
        # 确保至少有一个工具
        if not assigned:
            assigned = ["toolkit_file"]
        
        return assigned
    
    def _topological_sort(self, tasks: List[SubTask]) -> List[List[SubTask]]:
        """拓扑排序，返回执行层级"""
        task_map = {t.id: t for t in tasks}
        in_degree = {t.id: len(t.dependencies) for t in tasks}
        
        # 初始化队列
        queue = [t for t in tasks if in_degree[t.id] == 0]
        layers = []
        
        while queue:
            # 当前层
            layer = list(queue)
            layers.append(layer)
            
            # 下一层
            next_queue = []
            for task in queue:
                # 找到依赖当前任务的其他任务
                for other in tasks:
                    if task.id in other.dependencies:
                        in_degree[other.id] -= 1
                        if in_degree[other.id] == 0:
                            next_queue.append(other)
            
            queue = next_queue
        
        return layers
    
    async def _execute_workflow(
        self,
        workflow: Workflow,
        layers: List[List[SubTask]],
        context: Optional[Dict],
    ) -> Dict[str, Any]:
        """执行工作流"""
        results = {}
        
        for layer in layers:
            # 并行执行当前层
            layer_tasks = [
                self._execute_task(task, results, context)
                for task in layer
            ]
            layer_results = await asyncio.gather(*layer_tasks, return_exceptions=True)
            
            # 收集结果
            for task, result in zip(layer, layer_results):
                if isinstance(result, Exception):
                    task.status = TaskStatus.FAILED
                    task.error = str(result)
                    results[task.id] = {"success": False, "error": str(result)}
                    logger.error(f"❌ 子任务失败: {task.name}, {result}")
                else:
                    task.status = TaskStatus.COMPLETED
                    task.result = result
                    results[task.id] = {"success": True, "result": result}
                    logger.info(f"✅ 子任务完成: {task.name}")
        
        return results
    
    async def _execute_task(
        self,
        task: SubTask,
        context: Dict,
        extra_context: Optional[Dict],
    ) -> str:
        """执行单个子任务"""
        task.status = TaskStatus.RUNNING
        start_time = datetime.now()
        
        try:
            # 使用 lite_agent 执行
            from .lite_agent import LiteAgent
            
            agent = LiteAgent(
                tools=task.tools,
                context=context,
            )
            
            result = await agent.execute(
                goal=task.description,
                tools=task.tools,
            )
            
            # 更新统计
            elapsed = (datetime.now() - start_time).total_seconds()
            task.time_seconds = elapsed
            
            return result
            
        except Exception as e:
            task.status = TaskStatus.FAILED
            task.error = str(e)
            raise
    
    def _merge_results(self, workflow: Workflow, results: Dict) -> Dict:
        """整合结果"""
        successful = sum(1 for r in results.values() if r.get("success"))
        total = len(results)
        
        # 收集所有结果
        all_results = []
        for task in workflow.tasks:
            task_result = results.get(task.id, {})
            all_results.append({
                "task": task.name,
                "success": task_result.get("success", False),
                "result": task_result.get("result", ""),
            })
        
        return {
            "workflow_id": workflow.id,
            "goal": workflow.goal,
            "total_tasks": total,
            "successful_tasks": successful,
            "failed_tasks": total - successful,
            "success_rate": successful / total if total > 0 else 0,
            "tasks": all_results,
            "summary": self._generate_summary(workflow, results),
        }
    
    def _generate_summary(self, workflow: Workflow, results: Dict) -> str:
        """生成执行摘要"""
        successful = sum(1 for r in results.values() if r.get("success"))
        total = len(results)
        
        status = "✅ 成功" if successful == total else "⚠️ 部分成功"
        
        return f"{status}: {workflow.goal} ({successful}/{total} 子任务完成)"
    
    def get_workflow(self, workflow_id: str) -> Optional[Workflow]:
        """获取工作流"""
        return self.workflows.get(workflow_id)
    
    def list_workflows(self) -> List[Workflow]:
        """列出所有工作流"""
        return list(self.workflows.values())
