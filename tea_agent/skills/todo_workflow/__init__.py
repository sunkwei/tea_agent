"""Skill: TODO 工作流 — 结构化任务分步跟踪"""
SKILL_MANIFEST = {
    "name": "todo_workflow",
    "version": "1.0.0",
    "description": "TODO 清单工作流：修改代码前创建步骤清单，逐步勾选完成，确保过程有条不紊、可追踪",
    "tools": [
        "toolkit_todo",
    ],
    "prompt_inject": """TODO 工作流准则：
修改代码前，先调用 toolkit_todo(action="create", items=[...]) 列出步骤清单；
每完成一步，调用 toolkit_todo(action="check", index=N) 勾选；
全部完成后调用 toolkit_todo(action="clear") 清理。
这确保修改过程有条不紊、可追踪。TODO 自动持久化到 DB per-topic，重启不丢失。""",
    "activation": "auto",
    "dependencies": [],
    "trigger_words": [
        "修改代码", "改代码", "实现", "修复", "添加功能", "删除",
        "重构", "写代码", "改一下", "bug", "feature", "fix",
        "优化", "改进", "拆分", "合并", "迁移", "替换",
    ],
}
