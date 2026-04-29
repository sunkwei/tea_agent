# @2026-04-29 gen by deepseek-v4-pro, 内置工具: 自进化——修改项目代码并带注释/备份/验证
def toolkit_self_evolve(file_path: str, description: str, old_code: str, new_code: str, verify: bool = True, backup: bool = True) -> dict:
    """
    自进化：修改项目源文件，自动生成演化注释、备份原文件、验证编译。
    适用于 Agent 修改自身项目代码（tea_agent/*.py）的场景。

    Args:
        file_path: 要修改的文件路径（相对于项目根目录）
        description: 修改的简短描述
        old_code: 要替换的旧代码片段（精确匹配）
        new_code: 替换后的新代码片段
        verify: 是否验证编译通过
        backup: 是否备份原文件到 .bak
    """
    import os
    import shutil
    import py_compile
    from datetime import datetime

    cwd = os.getcwd()
    full_path = os.path.join(cwd, file_path)

    if not os.path.exists(full_path):
        return {"ok": False, "error": f"文件不存在: {file_path}"}

    # 读取当前文件
    with open(full_path, "r", encoding="utf-8") as f:
        content = f.read()

    if old_code not in content:
        return {"ok": False, "error": "old_code 在文件中未找到（精确匹配失败）"}

    # 生成演化注释
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    comment = f"# NOTE: {now}, self-evolved by tea_agent --- {description}\n"

    # 始终创建临时备份用于回滚
    tmp_bak = full_path + ".tmp_bak"
    shutil.copy2(full_path, tmp_bak)

    # 持久备份（如果用户要求）
    if backup:
        bak_path = full_path + ".bak"
        shutil.copy2(full_path, bak_path)
    else:
        bak_path = None

    # 应用修改（在 new_code 前加注释）
    annotated_new = comment + new_code
    new_content = content.replace(old_code, annotated_new, 1)

    # 写入
    with open(full_path, "w", encoding="utf-8") as f:
        f.write(new_content)

    # 验证编译
    verify_ok = True
    verify_error = None
    if verify and file_path.endswith(".py"):
        try:
            py_compile.compile(full_path, doraise=True)
        except py_compile.PyCompileError as e:
            verify_ok = False
            verify_error = str(e)
            # 回滚（始终从临时备份恢复）
            shutil.copy2(tmp_bak, full_path)
            if os.path.exists(tmp_bak):
                os.remove(tmp_bak)
            return {
                "ok": False,
                "error": f"编译失败，已回滚: {verify_error}",
                "file": file_path,
            }

    # 清理临时备份
    if os.path.exists(tmp_bak):
        os.remove(tmp_bak)

    return {
        "ok": True,
        "file": file_path,
        "comment": comment.strip(),
        "backup_path": (full_path + ".bak") if backup else None,
        "verified": verify_ok,
    }


def meta_toolkit_self_evolve():
    return {
        "type": "function",
        "function": {
            "name": "toolkit_self_evolve",
            "description": "自进化：修改项目源文件，自动添加演化注释(# NOTE: {date}, self-evolved by tea_agent)、备份原文件(.bak)、验证编译。适用于 Agent 修改自身项目代码。",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "要修改的文件路径（相对于项目根目录，如 tea_agent/store.py）",
                    },
                    "description": {
                        "type": "string",
                        "description": "修改的简短描述，会写入注释",
                    },
                    "old_code": {
                        "type": "string",
                        "description": "要替换的旧代码片段（必须精确匹配）",
                    },
                    "new_code": {
                        "type": "string",
                        "description": "替换后的新代码片段",
                    },
                    "verify": {
                        "type": "boolean",
                        "description": "是否验证编译通过，默认 true。编译失败自动回滚。",
                    },
                    "backup": {
                        "type": "boolean",
                        "description": "是否备份原文件到 .bak，默认 true",
                    },
                },
                "required": ["file_path", "description", "old_code", "new_code"],
            },
        },
    }
