"""Skill: 文件与系统 — 文件读写、命令执行、包管理"""
SKILL_MANIFEST = {
    "name": "file_system",
    "version": "1.1.0",
    "description": "文件与系统操作：读写文件、执行命令、Python包管理（sudo 由 exec 内置支持）",
    "tools": [
        "toolkit_file",
        "toolkit_edit",
        "toolkit_exec",
        "toolkit_pkg",
    ],
    "prompt_inject": """文件和系统操作准则：
1. 执行命令前先检查文件是否存在（用 file list 或 read）
2. 系统命令用 exec，sudo 命令会自动弹出 GUI 密码框
3. Python 包安装用 pkg，支持批量安装
4. 写文件前确认目标路径，避免覆盖重要文件
5. 精确编辑用 edit（行级插入/删除/替换）""",
    "activation": "auto",
    "dependencies": [],
    "trigger_words": [
        "文件", "目录", "读写", "写入", "读取", "创建文件",
        "执行", "命令", "运行", "编译", "安装包", "pip",
        "sudo", "管理员", "权限", "apt", "yum",
        "下载", "git", "clone", "build", "make",
    ],
}
