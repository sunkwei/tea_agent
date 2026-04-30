# @2026-04-29 gen by deepseek-v4-pro, 合并build_package+fix_pyproject
# version: 1.0.0

def toolkit_build(action: str, directory: str = "."):
    """
    统一构建/修复工具。
    - action="package": 在当前目录构建 Python 包（python -m build）。自动处理本地 build/ 目录冲突。
      返回 {ok, exit_code, stdout, stderr}。
    - action="fix": 修复 pyproject.toml 常见问题（BOM、license格式、classifier、缺失README）。
      需 directory（默认当前目录）。返回修改摘要。
    """
    import os

    if action == "package":
        import subprocess
        import shutil

        cwd = os.getcwd()
        build_dir = os.path.join(cwd, "build")
        bak_dir = os.path.join(cwd, "build.bak")
        had_conflict = os.path.isdir(build_dir)

        if had_conflict:
            if os.path.exists(bak_dir):
                shutil.rmtree(bak_dir)
            os.rename(build_dir, bak_dir)

        try:
            result = subprocess.run(
                ["python", "-m", "build"],
                capture_output=True, text=True, cwd=cwd, timeout=120,
            )
            return {
                "exit_code": result.returncode,
                "stdout": result.stdout[-3000:] if len(result.stdout) > 3000 else result.stdout,
                "stderr": result.stderr[-2000:] if len(result.stderr) > 2000 else result.stderr,
                "had_build_conflict": had_conflict,
                "ok": result.returncode == 0,
            }
        except subprocess.TimeoutExpired:
            return {"exit_code": -1, "stderr": "构建超时 (>120s)", "ok": False}
        except Exception as e:
            return {"exit_code": -1, "stderr": str(e), "ok": False}
        finally:
            if had_conflict and os.path.exists(bak_dir):
                if os.path.exists(build_dir):
                    shutil.rmtree(build_dir)
                os.rename(bak_dir, build_dir)

    elif action == "fix":
        import re

        filepath = os.path.join(directory, "pyproject.toml")
        if not os.path.exists(filepath):
            return "Error: pyproject.toml not found"

        with open(filepath, "rb") as f:
            raw = f.read()

        changes = []
        if raw.startswith(b'\xef\xbb\xbf'):
            content = raw.decode('utf-8-sig')
            changes.append("Removed BOM")
        else:
            content = raw.decode('utf-8')

        # Fix license table format
        pattern = r'license\s*=\s*\{\s*text\s*=\s*"([^"]+)"\s*\}'
        if re.search(pattern, content):
            content = re.sub(pattern, r'license = "\1"', content)
            changes.append("Fixed deprecated license format")

        # Remove deprecated license classifier
        lines = content.split('\n')
        new_lines = []
        removed = False
        for line in lines:
            if "License :: OSI Approved" in line:
                removed = True
                continue
            new_lines.append(line)
        if removed:
            changes.append("Removed deprecated license classifier")
            content = '\n'.join(new_lines)

        # Check readme
        readme_match = re.search(r'readme\s*=\s*"([^"]+)"', content)
        if readme_match:
            readme_name = readme_match.group(1)
            readme_path = os.path.join(directory, readme_name)
            if not os.path.exists(readme_path):
                with open(readme_path, "w", encoding="utf-8") as f:
                    f.write(f"# {os.path.basename(directory)}\n\nProject description.\n")
                changes.append(f"Created missing {readme_name}")

        if changes:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content)
            return "Applied changes: " + ", ".join(changes)
        else:
            return "No changes needed."

    else:
        return f"❌ 未知 action: '{action}'，可选: package / fix"


def meta_toolkit_build() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "toolkit_build",
            "description": "统一构建工具。action='package' 构建Python包（python -m build），自动处理build目录冲突；action='fix' 修复pyproject.toml常见问题（BOM/license/classifier/README）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["package", "fix"],
                        "description": "操作：package=构建包, fix=修复pyproject.toml",
                    },
                    "directory": {
                        "type": "string",
                        "description": "[fix] 项目目录路径，默认当前目录",
                        "default": ".",
                    },
                },
                "required": ["action"],
            },
        },
    }
