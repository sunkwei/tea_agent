"""
工作流模块 — 自动生成执行计划。

用法:
    from tea_agent.workflow import WorkflowBuilder, build_workflow

    # 使用类
    builder = WorkflowBuilder()
    workflow = builder.build("重构项目添加类型注解")

    # 使用便捷函数
    workflow = build_workflow("重构项目添加类型注解")

    print(workflow.to_json())
"""

from .builder import Step, Workflow, WorkflowBuilder, build_workflow

__all__ = ["WorkflowBuilder", "Workflow", "Step", "build_workflow"]
