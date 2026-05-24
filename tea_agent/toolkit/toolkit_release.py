"""
toolkit_release — 统一版本发布工具

actions:
  bump    — 更新 pyproject.toml 版本号 (semver 验证)
  build   — 构建 Python 包 (python -m build)
  fix     — 修复 pyproject.toml 常见问题
  release — 完整发布: bump + changelog + build + git commit
"""

import logging
import re
import os
import shutil
import subprocess
from pathlib import Path
from datetime import datetime

logger = logging.getLogger("toolkit")


def toolkit_release(
    action: str,
    version: str = None,
    file: str = "pyproject.toml",
    dry_run: bool = False,
    directory: str = ".",
    changes: list = None,
    changelog_section: str = "Improvements & Changes",
    do_build: bool = True,
    git_commit: bool = True,
) -> dict:
    """
    统一版本发布工具。

    Args:
        action (str): Description.
        version (str): Description.
        file (str): Description.
        dry_run (bool): Description.
        directory (str): Description.
        changes (list): Description.
        changelog_section (str): Description.
        do_build (bool): Description.
        git_commit (bool): Description.

    Returns:
        dict: Description.
    """
    logger.info(f"toolkit_release: action={action!r}, version={version!r}")

    try:
        if action == "bump":
            return _do_bump(version, file, dry_run)
        elif action == "build":
            return _do_build(directory)
        elif action == "fix":
            return _do_fix(directory)
        elif action == "release":
            return _do_release(version, changes, changelog_section, do_build, git_commit, file)
        else:
            return {"ok": False, "error": f"未知 action: {action}，可选: bump/build/fix/release"}
    except Exception as e:
        logger.exception("toolkit_release")
        return {"ok": False, "error": str(e)[:300]}


def _do_bump(version, file, dry_run):
    """
    Bump version in pyproject.toml

    Args:
        version: Description.
        file: Description.
        dry_run: Description.
    """
    if not version:
        return {"ok": False, "error": "bump 需要 version 参数"}
    if not re.match(r'^\d+\.\d+\.\d+(-[a-zA-Z0-9.]+)?(\+[a-zA-Z0-9.]+)?$', version):
        return {"ok": False, "error": f"无效的版本号: {version}，需要 semver 格式"}

    fp = Path(file)
    if not fp.exists():
        return {"ok": False, "error": f"文件不存在: {fp.absolute()}"}

    original = fp.read_text(encoding="utf-8")
    lines = original.split("\n")
    found = False
    old_version = None
    new_lines = []
    version_pattern = re.compile(r'^(version\s*=\s*)"([^"]+)"')

    for line in lines:
        m = version_pattern.match(line)
        if m:
            old_version = m.group(2)
            if old_version == version:
                return {"ok": True, "changed": False, "version": version, "message": f"版本号已是 {version}"}
            new_line = f'{m.group(1)}"{version}"'
            new_lines.append(new_line)
            found = True
        else:
            new_lines.append(line)

    if not found:
        return {"ok": False, "error": f"在 {file} 中未找到 version 行"}

    if dry_run:
        return {"ok": True, "changed": True, "dry_run": True, "old_version": old_version, "new_version": version}

    fp.write_text("\n".join(new_lines), encoding="utf-8")
    return {"ok": True, "changed": True, "old_version": old_version, "new_version": version, "message": f"{old_version} → {version}"}


def _do_build(directory):
    """
    Build Python package

    Args:
        directory: Description.
    """
    cwd = os.path.abspath(directory)
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
        return {"ok": result.returncode == 0, "exit_code": result.returncode,
                "stdout": result.stdout[-3000:], "stderr": result.stderr[-2000:],
                "had_build_conflict": had_conflict}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "构建超时 (>120s)"}
    finally:
        if had_conflict and os.path.exists(bak_dir):
            if os.path.exists(build_dir):
                shutil.rmtree(build_dir)
            os.rename(bak_dir, build_dir)


def _do_fix(directory):
    """
    Fix pyproject.toml issues

    Args:
        directory: Description.
    """
    filepath = os.path.join(directory, "pyproject.toml")
    if not os.path.exists(filepath):
        return {"ok": False, "error": "pyproject.toml not found"}

    with open(filepath, "rb") as f:
        raw = f.read()
    changes_made = []
    if raw.startswith(b'\xef\xbb\xbf'):
        content = raw.decode('utf-8-sig')
        changes_made.append("Removed BOM")
    else:
        content = raw.decode('utf-8')

    pattern = r'license\s*=\s*\{\s*text\s*=\s*"([^"]+)"\s*\}'
    if re.search(pattern, content):
        content = re.sub(pattern, r'license = "\1"', content)
        changes_made.append("Fixed license format")

    lines = content.split('\n')
    new_lines = [l for l in lines if "License :: OSI Approved" not in l]
    if len(new_lines) < len(lines):
        changes_made.append("Removed deprecated license classifier")
        content = '\n'.join(new_lines)

    readme_match = re.search(r'readme\s*=\s*"([^"]+)"', content)
    if readme_match:
        readme_path = os.path.join(directory, readme_match.group(1))
        if not os.path.exists(readme_path):
            with open(readme_path, "w", encoding="utf-8") as f:
                f.write(f"# {os.path.basename(directory)}\n\nProject description.\n")
            changes_made.append(f"Created missing {readme_match.group(1)}")

    if changes_made:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        return {"ok": True, "changes": changes_made}
    return {"ok": True, "changes": [], "message": "No changes needed"}


def _do_release(version, changes, section, do_build, git_commit, file):
    """
    Full release workflow

    Args:
        version: Description.
        changes: Description.
        section: Description.
        do_build: Description.
        git_commit: Description.
        file: Description.
    """
    if not version or not changes:
        return {"ok": False, "error": "release 需要 version 和 changes 参数"}
    results = {"version": version, "steps": []}

    bump_result = _do_bump(version, file, dry_run=False)
    if bump_result.get("ok"):
        results["steps"].append(f"✓ bump: {bump_result.get('message', version)}")
    else:
        results["steps"].append(f"✗ bump: {bump_result.get('error')}")
        return {"ok": False, "steps": results["steps"]}

    changelog_path = Path("CHANGELOG.md")
    if changelog_path.exists():
        cl_content = changelog_path.read_text(encoding='utf-8')
        today = datetime.now().strftime("%Y-%m-%d")
        new_entry = f"\n## [{version}] - {today}\n### {section}\n"
        for change in changes:
            new_entry += f"- {change}\n"
        first_match = re.search(r'##\s*\[', cl_content)
        if first_match:
            cl_content = cl_content[:first_match.start()] + new_entry + cl_content[first_match.start():]
        else:
            cl_content += new_entry
        changelog_path.write_text(cl_content, encoding='utf-8')
        results["steps"].append("✓ 更新 CHANGELOG.md")

    if do_build:
        build_result = _do_build(".")
        if build_result.get("ok"):
            results["steps"].append("✓ 构建成功")
        else:
            results["steps"].append(f"✗ 构建失败: {build_result.get('stderr', '')[:200]}")

    if git_commit:
        try:
            subprocess.run(["git", "add", "-A"], capture_output=True, timeout=30)
            commit_msg = f"release: v{version}"
            if changes:
                commit_msg += f" - {changes[0][:50]}"
            r = subprocess.run(["git", "commit", "-m", commit_msg], capture_output=True, text=True, timeout=30)
            if r.returncode == 0:
                results["steps"].append("✓ Git commit")
            else:
                results["steps"].append(f"✗ Git commit: {r.stderr[:200]}")
        except Exception as e:
            results["steps"].append(f"✗ Git error: {e}")

    results["ok"] = True
    return results


def meta_toolkit_release() -> dict:
    """
    Meta toolkit release

    Returns:
        dict: Description.
    """
    return {
        "type": "function",
        "function": {
            "name": "toolkit_release",
            "description": "统一版本发布工具。action=bump 更新版本号, build 构建包, fix 修复pyproject.toml, release 完整发布(bump+changelog+build+git commit)。",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["bump", "build", "fix", "release"],
                        "description": "bump=更新版本号, build=构建包, fix=修复pyproject.toml, release=完整发布"
                    },
                    "version": {"type": "string", "description": "[bump/release] 新版本号，如 0.5.3"},
                    "file": {"type": "string", "description": "[bump] 文件路径，默认 pyproject.toml", "default": "pyproject.toml"},
                    "dry_run": {"type": "boolean", "description": "[bump] 仅预览不写入", "default": False},
                    "directory": {"type": "string", "description": "[build/fix] 项目目录", "default": "."},
                    "changes": {"type": "array", "items": {"type": "string"}, "description": "[release] 变更说明列表"},
                    "changelog_section": {"type": "string", "description": "[release] 变更章节: Features/Improvements & Changes/Bug Fixes/Documentation", "default": "Improvements & Changes"},
                    "do_build": {"type": "boolean", "description": "[release] 是否执行构建", "default": True},
                    "git_commit": {"type": "boolean", "description": "[release] 是否 git commit", "default": True},
                },
                "required": ["action"],
            },
        },
    }
