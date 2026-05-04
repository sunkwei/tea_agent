"""Skill: 记忆与知识 — 长期记忆、知识库、反思、自主管理"""
SKILL_MANIFEST = {
    "name": "memory_knowledge",
    "version": "1.0.0",
    "description": "记忆与知识管理：存储/搜索长期记忆、Markdown知识库、元认知反思、自主目标管理、会话导出、人格模式切换",
    "tools": [
        "toolkit_memory",
        "toolkit_kb",
        "toolkit_reflection",
        "toolkit_proactive",
        "toolkit_subconscious",
        "toolkit_dump_topic",
        "toolkit_mode",
    ],
    "prompt_inject": """记忆和知识管理准则：
1. 用户表达偏好/事实/教训时，用 memory 记录下来（含优先级和标签）
2. 需要查阅文档/知识时，用 kb 搜索
3. 任务完成后用 reflection 做元认知反思，持续改进
4. 跨会话目标用 proactive 管理
5. 用户说"搞定了，总结一下"时：用 memory 的 extract 动作生成对话摘要""",
    "activation": "auto",
    "dependencies": [],
    "trigger_words": [
        "记住", "记忆", "忘了", "知识库", "文档",
        "反思", "总结", "目标", "计划", "导出",
        "模式", "切换", "搞定了", "记录",
    ],
}
