## llm generated tool func, created Thu Apr 16 21:15:45 2026

import re
import os
from pathlib import Path
from datetime import datetime

def toolkit_release_version(version: str, changes: list, changelog_section: str = "Improvements & Changes", 
                           build: bool = True, git_commit: bool = True) -> dict:
    """
    自动化版本发布工具
    
    Args:
        version: 新版本号，如 '0.2.4'
        changes: 变更说明列表
        changelog_section: 变更章节类型（Features, Improvements & Changes, Bug Fixes, Documentation等）
        build: 是否执行构建
        git_commit: 是否创建 git commit
    
    Returns:
        dict: 包含操作结果的字典
    """
    results = {
        "version": version,
        "status": "success",
        "steps": []
    }
    
    # 1. 更新 pyproject.toml 版本号
    pyproject_path = Path("pyproject.toml")
    if pyproject_path.exists():
        content = pyproject_path.read_text(encoding='utf-8')
        new_content = re.sub(
            r'version\s*=\s*["\'][^"\']+["\']',
            f'version = "{version}"',
            content
        )
        pyproject_path.write_text(new_content, encoding='utf-8')
        results["steps"].append("✓ 更新 pyproject.toml 版本号")
    
    # 2. 更新 CHANGELOG.md
    changelog_path = Path("CHANGELOG.md")
    if changelog_path.exists():
        changelog_content = changelog_path.read_text(encoding='utf-8')
        
        # 生成新条目
        today = datetime.now().strftime("%Y-%m-%d")
        new_entry = f"\n## [{version}] - {today}\n"
        
        # 根据章节类型添加前缀
        section_prefix = {
            "Features": "### Features",
            "Improvements & Changes": "### Improvements & Changes",
            "Bug Fixes": "### Bug Fixes",
            "Documentation": "### Documentation",
            "Chore": "### Chore"
        }
        
        new_entry += f"{section_prefix.get(changelog_section, '### Improvements & Changes')}\n"
        for change in changes:
            new_entry += f"- {change}\n"
        
        # 插入到第一个版本号之前
        first_version_match = re.search(r'##\s*\[', changelog_content)
        if first_version_match:
            insert_pos = first_version_match.start()
            new_changelog = changelog_content[:insert_pos] + new_entry + changelog_content[insert_pos:]
        else:
            new_changelog = changelog_content + new_entry
        
        changelog_path.write_text(new_changelog, encoding='utf-8')
        results["steps"].append("✓ 更新 CHANGELOG.md")
    
    # 3. 执行构建
    if build:
        ret, stdout, stderr = toolkit_exec("bash", ["-c", "python -m build"])
        if ret == 0:
            results["steps"].append(f"✓ 构建成功: tea_agent-{version}.tar.gz 和 .whl")
        else:
            results["steps"].append(f"✗ 构建失败: {stderr}")
            results["status"] = "partial_failure"
    
    # 4. Git 提交
    if git_commit:
        # 先 add
        toolkit_exec("bash", ["-c", "git add -A"])
        
        # 构建提交消息
        commit_title = f"release: v{version}"
        if len(changes) > 0:
            commit_title += f" - {changes[0][:50]}"
        
        commit_msg_parts = [f"'{commit_title}'"]
        for change in changes:
            commit_msg_parts.append(f"-m '{change}'")
        
        commit_cmd = f"git commit -m ' ' ".join(commit_msg_parts)
        ret, stdout, stderr = toolkit_exec("bash", ["-c", f"git commit {' '.join(commit_msg_parts)}"])
        
        if ret == 0:
            results["steps"].append("✓ Git 提交成功")
        else:
            results["steps"].append(f"✗ Git 提交失败: {stderr}")
            results["status"] = "partial_failure"
    
    return results

def meta_toolkit_release_version() -> dict:
    return {"type": "function", "function": {"name": "toolkit_release_version", "description": "自动化版本发布工具。更新版本号、CHANGELOG，并构建项目。", "parameters": {"type": "object", "properties": {"version": {"type": "string", "description": "新版本号，如 '0.2.4'"}, "changes": {"type": "array", "items": {"type": "string"}, "description": "变更说明列表"}, "changelog_section": {"type": "string", "description": "变更章节类型：Features, Improvements & Changes, Bug Fixes, Documentation 等", "default": "Improvements & Changes"}, "build": {"type": "boolean", "description": "是否执行构建（python -m build）", "default": True}, "git_commit": {"type": "boolean", "description": "是否创建 git commit", "default": True}}, "required": ["version", "changes"]}}}