def toolkit_bump_version(version: str, file: str = "pyproject.toml", dry_run: bool = False):
    """
    跨平台版本号更新 — 纯 Python，零外部依赖。

    用法:
        toolkit_bump_version("0.5.3")                      # 更新 pyproject.toml
        toolkit_bump_version("1.0.0", "setup.cfg")         # 更新其他文件
        toolkit_bump_version("0.5.3", dry_run=True)        # 预览不改写
    """
    import re
    from pathlib import Path

    # 1. 验证版本号格式 (semver)
    if not re.match(r'^\d+\.\d+\.\d+(-[a-zA-Z0-9.]+)?(\+[a-zA-Z0-9.]+)?$', version):
        return {
            "ok": False,
            "error": f"无效的版本号: {version}。需要 semver 格式，如 0.5.3 或 0.5.3-beta1"
        }

    # 2. 读取文件
    fp = Path(file)
    if not fp.exists():
        return {"ok": False, "error": f"文件不存在: {fp.absolute()}"}

    original = fp.read_text(encoding="utf-8")
    lines = original.split("\n")

    # 3. 查找并替换 version = "..."
    found = False
    old_version = None
    new_lines = []
    version_pattern = re.compile(r'^(version\s*=\s*)"([^"]+)"')

    for line in lines:
        m = version_pattern.match(line)
        if m:
            old_version = m.group(2)
            if old_version == version:
                return {
                    "ok": True,
                    "changed": False,
                    "file": str(fp),
                    "version": version,
                    "message": f"版本号已是 {version}，无需修改"
                }
            # 保持原有缩进和格式
            new_line = f'{m.group(1)}"{version}"'
            new_lines.append(new_line)
            found = True
        else:
            new_lines.append(line)

    if not found:
        return {
            "ok": False,
            "error": f"在 {file} 中未找到 version = \"...\" 行",
            "hint": "文件是否使用 [project] 或 [tool.poetry] 格式？"
        }

    new_text = "\n".join(new_lines)

    # 4. dry_run 模式
    if dry_run:
        return {
            "ok": True,
            "changed": True,
            "dry_run": True,
            "file": str(fp),
            "old_version": old_version,
            "new_version": version,
            "diff_preview": f"- version = \"{old_version}\"\n+ version = \"{version}\""
        }

    # 5. 写入
    fp.write_text(new_text, encoding="utf-8")

    return {
        "ok": True,
        "changed": True,
        "file": str(fp),
        "old_version": old_version,
        "new_version": version,
        "message": f"版本号已更新: {old_version} → {version}"
    }


def meta_toolkit_bump_version() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "toolkit_bump_version",
            "description": "跨平台版本号更新。纯 Python 实现，不依赖 sed/awk/PowerShell。更新 pyproject.toml 中的 version 字段。支持 semver 验证。",
            "parameters": {
                "type": "object",
                "properties": {
                    "version": {
                        "type": "string",
                        "description": "新版本号，如 0.5.3"
                    },
                    "file": {
                        "type": "string",
                        "description": "要更新的文件路径，默认 pyproject.toml",
                        "default": "pyproject.toml"
                    },
                    "dry_run": {
                        "type": "boolean",
                        "description": "仅打印变更，不实际写入",
                        "default": False
                    }
                },
                "required": ["version"]
            }
        }
    }
