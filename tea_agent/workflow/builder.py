"""
工作流自动构建器 — 一句话生成执行计划。

设计灵感:
  EvoAgentX 的 WorkFlowGenerator

功能:
  - 从自然语言目标生成工作流
  - 自动分配工具和资源
  - 生成可执行计划

用法:
    from tea_agent.workflow import WorkflowBuilder
    
    builder = WorkflowBuilder()
    workflow = builder.build(
        goal="重构项目添加类型注解"
    )
    
    print(workflow)
    # Workflow(
    #   goal="重构项目添加类型注解",
    #   steps=[
    #     Step(name="扫描项目", tools=["toolkit_file"]),
    #     Step(name="分析代码", tools=["toolkit_lsp"]),
    #     Step(name="添加注解", tools=["toolkit_edit"]),
    #     Step(name="验证测试", tools=["toolkit_run_tests"]),
    #   ]
    # )
"""

from typing import List, Dict, Optional
from dataclasses import dataclass, field
from datetime import datetime
import json

import logging

logger = logging.getLogger(__name__)


@dataclass
class Step:
    """工作流步骤"""
    id: str
    name: str
    description: str
    tools: List[str]
    inputs: List[str] = field(default_factory=list)   # 输入依赖
    outputs: List[str] = field(default_factory=list)   # 输出产物
    estimated_tokens: int = 0
    estimated_time: float = 0


@dataclass
class Workflow:
    """工作流定义"""
    id: str
    goal: str
    steps: List[Step]
    created_at: str = ""
    
    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "goal": self.goal,
            "steps": [
                {
                    "id": s.id,
                    "name": s.name,
                    "description": s.description,
                    "tools": s.tools,
                    "inputs": s.inputs,
                    "outputs": s.outputs,
                }
                for s in self.steps
            ],
            "created_at": self.created_at,
        }
    
    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)


class WorkflowBuilder:
    """工作流自动构建器"""
    
    # 任务模式到步骤的映射
    PATTERNS = {
        "refactor": {
            "name": "代码重构",
            "steps": [
                ("scan", "扫描代码结构", ["toolkit_file", "toolkit_explr"]),
                ("analyze", "分析重构点", ["toolkit_lsp"]),
                ("design", "设计重构方案", []),
                ("execute", "执行重构", ["toolkit_edit", "toolkit_diff"]),
                ("verify", "验证重构", ["toolkit_run_tests"]),
            ]
        },
        "type_annotation": {
            "name": "添加类型注解",
            "steps": [
                ("scan", "扫描 Python 文件", ["toolkit_file"]),
                ("analyze", "分析函数签名", ["toolkit_lsp"]),
                ("annotate", "添加类型注解", ["toolkit_edit"]),
                ("check", "类型检查", ["toolkit_exec"]),
                ("test", "运行测试", ["toolkit_run_tests"]),
            ]
        },
        "test": {
            "name": "编写测试",
            "steps": [
                ("analyze", "分析测试需求", ["toolkit_file", "toolkit_lsp"]),
                ("design", "设计测试用例", []),
                ("write", "编写测试代码", ["toolkit_edit"]),
                ("run", "运行测试", ["toolkit_run_tests"]),
                ("fix", "修复失败测试", ["toolkit_edit"]),
            ]
        },
        "fix": {
            "name": "修复问题",
            "steps": [
                ("locate", "定位问题", ["toolkit_search", "toolkit_lsp"]),
                ("analyze", "分析原因", ["toolkit_file"]),
                ("fix", "修复代码", ["toolkit_edit"]),
                ("test", "验证修复", ["toolkit_run_tests"]),
            ]
        },
        "doc": {
            "name": "生成文档",
            "steps": [
                ("analyze", "分析代码结构", ["toolkit_file", "toolkit_explr"]),
                ("draft", "草拟文档", []),
                ("write", "编写文档", ["toolkit_save_file"]),
                ("format", "格式化文档", ["toolkit_format_code"]),
            ]
        },
        "feature": {
            "name": "新功能开发",
            "steps": [
                ("analyze", "分析需求", []),
                ("design", "设计方案", []),
                ("implement", "实现功能", ["toolkit_edit"]),
                ("test", "编写测试", ["toolkit_run_tests"]),
                ("doc", "编写文档", ["toolkit_save_file"]),
            ]
        },
        "search": {
            "name": "代码搜索",
            "steps": [
                ("search", "搜索代码", ["toolkit_search"]),
                ("analyze", "分析结果", ["toolkit_file"]),
                ("report", "生成报告", []),
            ]
        },
        "default": {
            "name": "通用任务",
            "steps": [
                ("analyze", "分析任务", []),
                ("execute", "执行操作", ["toolkit_file"]),
                ("verify", "验证结果", []),
            ]
        },
    }
    
    def __init__(self):
        pass
    
    def build(
        self,
        goal: str,
        files: Optional[List[str]] = None,
        context: Optional[Dict] = None,
    ) -> Workflow:
        """
        从目标构建工作流。
        
        Args:
            goal: 任务目标
            files: 相关文件
            context: 额外上下文
            
        Returns:
            Workflow 对象
        """
        if files is None:
            files = []
        if context is None:
            context = {}
        
        # 1. 识别任务模式
        pattern = self._identify_pattern(goal, files)
        
        # 2. 生成工作流
        workflow = self._generate_workflow(goal, pattern, files, context)
        
        logger.info(f"🔧 工作流构建完成: {workflow.goal} ({len(workflow.steps)} 步)")
        
        return workflow
    
    def _identify_pattern(self, goal: str, files: List[str]) -> str:
        """识别任务模式"""
        goal_lower = goal.lower()
        
        # 检查关键词
        if any(kw in goal_lower for kw in ["类型注解", "type annotation", "type hint"]):
            return "type_annotation"
        
        if any(kw in goal_lower for kw in ["重构", "refactor"]):
            return "refactor"
        
        if any(kw in goal_lower for kw in ["测试", "test", "pytest"]):
            return "test"
        
        if any(kw in goal_lower for kw in ["修复", "fix", "bug"]):
            return "fix"
        
        if any(kw in goal_lower for kw in ["文档", "doc", "readme"]):
            return "doc"
        
        if any(kw in goal_lower for kw in ["新增", "add", "创建", "create", "功能"]):
            return "feature"
        
        if any(kw in goal_lower for kw in ["搜索", "search", "查找", "find"]):
            return "search"
        
        # 检查文件类型
        if files:
            py_files = [f for f in files if f.endswith('.py')]
            if py_files:
                if any(kw in goal_lower for kw in ["类型", "type"]):
                    return "type_annotation"
        
        return "default"
    
    def _generate_workflow(
        self,
        goal: str,
        pattern: str,
        files: List[str],
        context: Dict,
    ) -> Workflow:
        """生成工作流"""
        # 获取模式定义
        pattern_def = self.PATTERNS.get(pattern, self.PATTERNS["default"])
        
        # 生成工作流 ID
        workflow_id = f"wf_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        # 生成步骤
        steps = []
        for i, (step_id, step_name, tools) in enumerate(pattern_def["steps"]):
            step = Step(
                id=f"step_{i+1}",
                name=step_name,
                description=f"{goal} - {step_name}",
                tools=tools,
                inputs=self._infer_inputs(i, pattern_def["steps"]),
                outputs=self._infer_outputs(step_id, goal),
            )
            steps.append(step)
        
        return Workflow(
            id=workflow_id,
            goal=goal,
            steps=steps,
        )
    
    def _infer_inputs(self, step_index: int, steps: List) -> List[str]:
        """推断步骤输入"""
        if step_index == 0:
            return []  # 第一步无输入
        
        # 默认依赖上一步
        return [f"step_{step_index}"]
    
    def _infer_outputs(self, step_id: str, goal: str) -> List[str]:
        """推断步骤输出"""
        output_map = {
            "scan": ["file_list", "structure"],
            "analyze": ["analysis_report", "issues"],
            "design": ["design_doc"],
            "execute": ["modified_files"],
            "verify": ["test_results"],
            "annotate": ["annotated_files"],
            "check": ["type_check_results"],
            "test": ["test_results"],
            "write": ["output_files"],
            "search": ["search_results"],
            "report": ["report"],
        }
        
        return output_map.get(step_id, [])
    
    def visualize(self, workflow: Workflow) -> str:
        """生成工作流可视化文本"""
        lines = [
            f"📋 工作流: {workflow.goal}",
            f"   ID: {workflow.id}",
            f"   步骤数: {len(workflow.steps)}",
            "",
            "   执行计划:",
        ]
        
        for i, step in enumerate(workflow.steps):
            prefix = "   ├─" if i < len(workflow.steps) - 1 else "   └─"
            tools_str = ", ".join(step.tools) if step.tools else "(无工具)"
            lines.append(f"{prefix} [{step.id}] {step.name}")
            lines.append(f"   │  工具: {tools_str}")
            
            if i < len(workflow.steps) - 1:
                lines.append("   │")
        
        return "\n".join(lines)


def build_workflow(goal: str, **kwargs) -> Workflow:
    """
    便捷函数：构建工作流。
    
    Args:
        goal: 任务目标
        **kwargs: 传递给 WorkflowBuilder.build() 的参数
        
    Returns:
        Workflow 对象
    """
    builder = WorkflowBuilder()
    return builder.build(goal, **kwargs)
