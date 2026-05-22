"""Skill: 自我进化 — 代码修改、版本管理、提示词进化、测试运行"""
SKILL_MANIFEST = {
    "name": "self_evolution",
    "version": "1.1.0",
    "description": "自我进化能力：修改项目源码、版本号管理、提示词进化、构建打包、运行测试、查看自身状态",
    "tools": [
        "toolkit_self_evolve",
        "toolkit_save",
        "toolkit_prompt_evolve",
        "toolkit_release",
        "toolkit_comment",
        "toolkit_self_report",
        "toolkit_config",
        "toolkit_toggle_reasoning",
        "toolkit_run_tests",
    ],
    "prompt_inject": """自我进化准则：
1. 修改自身代码用 self_evolve（自动备份、验证编译）
2. 版本管理用 release（bump/build/fix/release）
3. 工具版本管理用 save（save/reload/rollback/versions）
4. 运行时调优用 config（白名单限制，防止破坏性修改）
5. 连续调用 self_evolve 超过3次通常无新信息，应限制
6. 修改后运行 run_tests 验证""",
    "activation": "auto",
    "dependencies": [],
    "trigger_words": [
        "修改代码", "改代码", "修改", "改一下",
        "进化", "版本", "发布", "打包", "构建",
        "测试", "配置", "调优", "refactor",
        "thinking", "推理", "状态", "报告",
        "pyproject", "changelog", "readme",
    ],
}
