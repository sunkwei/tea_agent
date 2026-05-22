"""Skill: TODO 工作流 — 简易清单 + Plan 计划引擎"""
SKILL_MANIFEST = {
    "name": "todo_workflow",
    "version": "1.1.0",
    "description": "TODO 清单 + Plan 工作流：简易任务用 create/check/clear，复杂多步依赖任务用 plan_create/plan_step/plan_run/plan_resume",
    "tools": [
        "toolkit_todo",
    ],
    "prompt_inject": """TODO 工作流准则：
修改代码前，先调用 toolkit_todo(action="create", items=[...]) 列出步骤清单；
每完成一步，调用 toolkit_todo(action="check", index=N) 勾选；
全部完成后调用 toolkit_todo(action="clear") 清理。
复杂多步任务可使用 plan_create/plan_run 进行结构化执行。
TODO 自动持久化到 DB per-topic，Plan 持久化到 .tea_agent_run/plans/，重启不丢失。""",
    "activation": "auto",
    "dependencies": [],
    "trigger_words": [
        "修改代码", "改代码", "实现", "修复", "添加功能", "删除",
        "重构", "写代码", "改一下", "bug", "feature", "fix",
        "优化", "改进", "拆分", "合并", "迁移", "替换",
        "规划", "计划", "plan",
    ],
}
