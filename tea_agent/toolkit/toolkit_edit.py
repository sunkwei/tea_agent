import logging
import os
import json
import re
import shutil
import subprocess
import tempfile
import difflib
from tea_agent.toolkit.toolkit_diff import _toolkit_diff_impl
import py_compile
from typing import Optional, Tuple, List, Dict
from datetime import datetime

logger = logging.getLogger("toolkit")

def toolkit_edit(file_path: str, action: str = "apply_patch", content: str = "",
                 start_line: int = 0, end_line: int = 0, new_content: str = "",
                 preview: bool = False, backup: bool = True,
                 files: list = None, run_tests: bool = True, description: str = "",
                 lsp_checks: bool = True):
    """
    高级代码编辑工具，支持 diff/patch 应用和精准编辑。

    action='apply_patch': 应用 diff/patch
        toolkit_edit(file_path='src/main.py', action='apply_patch', 
                    content='@@ -10,3 +10,4 @@\\n def foo():\\n+    pass\\n     return 1')

    action='insert_lines': 在指定行插入内容
        toolkit_edit(file_path='src/main.py', action='insert_lines', start_line=10, 
                    new_content='def new_function():\\n    pass')

    action='delete_lines': 删除指定行范围
        toolkit_edit(file_path='src/main.py', action='delete_lines', start_line=10, end_line=15)

    action='replace_lines': 替换指定行范围
        toolkit_edit(file_path='src/main.py', action='replace_lines', start_line=10, end_line=15,
                    new_content='def updated_function():\\n    pass')

    action='preview_patch': 预览 patch 应用后的结果（不写入文件）
        toolkit_edit(file_path='src/main.py', action='preview_patch', content='...')

    Args:
        file_path: 目标文件路径
        action: 编辑操作类型
        content: patch 内容（apply_patch/preview_patch 使用）
        start_line: 起始行号（1-indexed）
        end_line: 结束行号（1-indexed，包含）
        new_content: 新内容（insert/replace 使用）
        preview: 是否仅预览不写入文件
        backup: 是否备份原文件（默认 True）

    返回:
        (returncode, stdout, stderr)
    """
    logger.info(f"toolkit_edit called: file_path={file_path!r}, action={action!r}")

    if not os.path.exists(file_path):
        return (1, "", f"文件不存在: {file_path}")

    if action == "apply_patch":
        return _apply_patch(file_path, content, preview, backup)
    elif action == "insert_lines":
        return _insert_lines(file_path, start_line, new_content, preview, backup)
    elif action == "delete_lines":
        return _delete_lines(file_path, start_line, end_line, preview, backup)
    elif action == "replace_lines":
        return _replace_lines(file_path, start_line, end_line, new_content, preview, backup)
    elif action == "preview_patch":
        return _preview_patch(file_path, content)
    elif action in ("diff_generate", "diff_preview", "diff_apply", "diff_undo", "diff_verify"):
        cwd = os.getcwd()
        diff_action = action[5:]
        result = _toolkit_diff_impl(diff_action, files=files, cwd=cwd, run_tests=run_tests,
                                     description=description, lsp_checks=lsp_checks)
        return (0 if result.get("ok") else 1, str(result), "")
    else:
        return (1, "", f"未知 action: {action}，支持: apply_patch/insert_lines/delete_lines/replace_lines/preview_patch/diff_*")

def _apply_patch(file_path: str, patch_content: str, preview: bool, backup: bool):
    """
    应用 diff/patch

    Args:
        file_path (str): Description.
        patch_content (str): Description.
        preview (bool): Description.
        backup (bool): Description.
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            original_content = f.read()

        patch_available = False
        if shutil.which('patch'):
            patch_available = True

        if patch_available and not preview:
            with tempfile.NamedTemporaryFile(mode='w', suffix='.patch', delete=False, encoding='utf-8') as pf:
                pf.write(patch_content)
                patch_file = pf.name

            try:
                if backup:
                    backup_path = file_path + '.bak'
                    shutil.copy2(file_path, backup_path)

                result = subprocess.run(
                    ['patch', '--batch', '--forward', file_path, patch_file],
                    capture_output=True, text=True, timeout=30
                )

                if result.returncode == 0:
                    return (0, f"✅ 成功应用 patch 到 {file_path}", "")
                else:
                    if backup and os.path.exists(backup_path):
                        shutil.copy2(backup_path, file_path)
                    return (1, "", f"❌ patch 应用失败:\n{result.stderr}\n{result.stdout}")
            finally:
                try:
                    os.unlink(patch_file)
                except OSError:
                    pass
        else:
            return _apply_patch_python(file_path, original_content, patch_content, preview, backup)

    except Exception as e:
        return (1, "", f"❌ 应用 patch 失败: {str(e)}")

def _apply_patch_python(file_path: str, original_content: str, patch_content: str, preview: bool, backup: bool):
    """
    Python 实现的 patch 应用（统一 diff 格式）

    Args:
        file_path (str): Description.
        original_content (str): Description.
        patch_content (str): Description.
        preview (bool): Description.
        backup (bool): Description.
    """
    try:
        lines = original_content.split('\n')
        patch_lines = patch_content.split('\n')

        hunks = []
        current_hunk = None

        for line in patch_lines:
            if line.startswith('@@'):
                if current_hunk:
                    hunks.append(current_hunk)
                match = re.match(r'@@ -(\d+),?(\d*) \+(\d+),?(\d*) @@', line)
                if match:
                    old_start = int(match.group(1))
                    old_count = int(match.group(2)) if match.group(2) else 1
                    new_start = int(match.group(3))
                    new_count = int(match.group(4)) if match.group(4) else 1
                    current_hunk = {
                        'old_start': old_start, 'old_count': old_count,
                        'new_start': new_start, 'new_count': new_count,
                        'lines': [], 'no_newline': False
                    }
            elif current_hunk is not None:
                if line == '\\ No newline at end of file':
                    current_hunk['no_newline'] = True
                elif line.startswith('+') or line.startswith('-') or line.startswith(' '):
                    current_hunk['lines'].append(line)

        if current_hunk:
            hunks.append(current_hunk)

        if not hunks:
            return (1, "", "❌ 无法解析 patch 内容，请确保是有效的 unified diff 格式")

        new_lines = lines[:]
        for hunk in reversed(hunks):
            old_start = hunk['old_start']
            hunk_lines = hunk['lines']

            delete_indices = [i for i, hl in enumerate(hunk_lines) if hl.startswith('-')]
            delete_lines = [hunk_lines[i][1:] for i in delete_indices]
            insert_lines = [hl[1:] for hl in hunk_lines if hl.startswith('+')]

            start_idx = old_start - 1
            if start_idx < 0 or start_idx > len(new_lines):
                return (1, "", f"❌ patch 行号超出范围: {old_start} (文件共 {len(new_lines)} 行)")

            context_ok = True
            temp_idx = start_idx
            for dl in delete_lines:
                if temp_idx < len(new_lines):
                    actual = new_lines[temp_idx]
                    if actual.rstrip() != dl.rstrip():
                        context_ok = False
                        break
                    temp_idx += 1
                else:
                    context_ok = False
                    break

            if not context_ok and delete_lines:
                found = False
                scan_range = range(max(0, old_start - 6), min(len(new_lines), old_start + 4))
                for scan_offset in scan_range:
                    if scan_offset < len(new_lines) and new_lines[scan_offset].rstrip() == delete_lines[0].rstrip():
                        start_idx = scan_offset
                        found = True
                        break
                if not found:
                    return (1, "", f"❌ 上下文不匹配: 行 {old_start} 附近找不到 '{delete_lines[0][:40]}...'")

            delete_count = len(delete_lines)
            if delete_count > 0 and start_idx + delete_count <= len(new_lines):
                del new_lines[start_idx:start_idx + delete_count]
            for i, il in enumerate(insert_lines):
                pos = start_idx + i
                if pos <= len(new_lines):
                    new_lines.insert(pos, il)
                else:
                    new_lines.append(il)

        new_content = '\n'.join(new_lines)

        if preview:
            diff_preview = _generate_unified_diff(original_content, new_content)
            return (0, json.dumps({
                "status": "preview",
                "file": file_path,
                "diff": diff_preview,
            }, ensure_ascii=False, indent=2), "")

        if backup:
            backup_path = file_path + '.bak'
            shutil.copy2(file_path, backup_path)

        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(new_content)

        return (0, f"✅ 成功应用编辑到 {file_path}", "")

    except Exception as e:
        return (1, "", f"❌ 应用 patch 失败: {str(e)}")

def _insert_lines(file_path: str, start_line: int, new_content: str, preview: bool, backup: bool):
    """
    在指定行插入内容

    Args:
        file_path (str): Description.
        start_line (int): Description.
        new_content (str): Description.
        preview (bool): Description.
        backup (bool): Description.
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        if start_line < 1 or start_line > len(lines) + 1:
            return (1, "", f"❌ 行号 {start_line} 超出范围 (1-{len(lines)+1})")

        original_content = ''.join(lines)

        insert_lines = new_content.split('\n')
        insert_lines_with_newline = []
        for i, line in enumerate(insert_lines):
            if i < len(insert_lines) - 1:
                insert_lines_with_newline.append(line + '\n')
            else:
                if lines and lines[-1].endswith('\n'):
                    insert_lines_with_newline.append(line + '\n')
                else:
                    insert_lines_with_newline.append(line)

        insert_index = start_line - 1
        new_lines = lines[:insert_index] + insert_lines_with_newline + lines[insert_index:]
        new_content_joined = ''.join(new_lines)

        if preview:
            diff_preview = _generate_unified_diff(original_content, new_content_joined)
            return (0, json.dumps({
                "status": "preview",
                "file": file_path,
                "action": "insert",
                "at_line": start_line,
                "diff": diff_preview,
            }, ensure_ascii=False, indent=2), "")

        if backup:
            shutil.copy2(file_path, file_path + '.bak')

        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(new_content_joined)

        return (0, f"✅ 成功在 {file_path}:{start_line} 插入 {len(insert_lines)} 行", "")

    except Exception as e:
        return (1, "", f"❌ 插入失败: {str(e)}")

def _delete_lines(file_path: str, start_line: int, end_line: int, preview: bool, backup: bool):
    """
    删除指定行范围

    Args:
        file_path (str): Description.
        start_line (int): Description.
        end_line (int): Description.
        preview (bool): Description.
        backup (bool): Description.
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        if start_line < 1 or start_line > len(lines):
            return (1, "", f"❌ 起始行号 {start_line} 超出范围")

        if end_line < start_line or end_line > len(lines):
            return (1, "", f"❌ 结束行号 {end_line} 超出范围")

        deleted = lines[start_line-1:end_line]
        new_lines = lines[:start_line-1] + lines[end_line:]
        new_content = ''.join(new_lines)

        if preview:
            diff_preview = _generate_unified_diff(''.join(lines), new_content)
            return (0, json.dumps({
                "status": "preview",
                "file": file_path,
                "action": "delete",
                "deleted_lines": f"{start_line}-{end_line}",
                "diff": diff_preview,
            }, ensure_ascii=False, indent=2), "")

        if backup:
            shutil.copy2(file_path, file_path + '.bak')

        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(new_content)

        return (0, f"✅ 成功删除 {file_path}:{start_line}-{end_line} ({len(deleted)} 行)", "")

    except Exception as e:
        return (1, "", f"❌ 删除失败: {str(e)}")

def _replace_lines(file_path: str, start_line: int, end_line: int, new_content: str, preview: bool, backup: bool):
    """
    替换指定行范围

    Args:
        file_path (str): Description.
        start_line (int): Description.
        end_line (int): Description.
        new_content (str): Description.
        preview (bool): Description.
        backup (bool): Description.
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        if start_line < 1 or start_line > len(lines):
            return (1, "", f"❌ 起始行号 {start_line} 超出范围")

        if end_line < start_line or end_line > len(lines):
            return (1, "", f"❌ 结束行号 {end_line} 超出范围")

        old_lines = lines[start_line-1:end_line]
        insert_lines = new_content.split('\n')
        insert_lines_with_newline = []
        for i, il in enumerate(insert_lines):
            if i < len(insert_lines) - 1 or (lines and lines[-1].endswith('\n')):
                insert_lines_with_newline.append(il + '\n')
            else:
                insert_lines_with_newline.append(il)

        new_lines = lines[:start_line-1] + insert_lines_with_newline + lines[end_line:]
        new_content_joined = ''.join(new_lines)

        if preview:
            diff_preview = _generate_unified_diff(''.join(lines), new_content_joined)
            return (0, json.dumps({
                "status": "preview",
                "file": file_path,
                "action": "replace",
                "replaced_lines": f"{start_line}-{end_line}",
                "diff": diff_preview,
            }, ensure_ascii=False, indent=2), "")

        if backup:
            shutil.copy2(file_path, file_path + '.bak')

        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(new_content_joined)

        return (0, f"✅ 成功替换 {file_path}:{start_line}-{end_line} ({len(old_lines)} → {len(insert_lines)} 行)", "")

    except Exception as e:
        return (1, "", f"❌ 替换失败: {str(e)}")

def _preview_patch(file_path: str, patch_content: str):
    """
    预览 patch 应用后的结果

    Args:
        file_path (str): Description.
        patch_content (str): Description.
    """
    return _apply_patch(file_path, patch_content, preview=True, backup=False)

def meta_toolkit_edit() -> dict:
    """
    Meta toolkit edit

    Returns:
        dict: Description.
    """
    return {
        "type": "function",
        "function": {
            "name": "toolkit_edit",
            "description": "高级代码编辑 + Diff 引擎。行级编辑: apply_patch/insert_lines/delete_lines/replace_lines/preview_patch。多文件原子编辑: diff_generate/diff_preview/diff_apply/diff_undo/diff_verify（git stash + lint/test/LSP验证 + 回滚）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "目标文件路径",
                    },
                    "action": {
                        "type": "string",
                        "enum": ["apply_patch", "insert_lines", "delete_lines", "replace_lines", "preview_patch",
                                 "diff_generate", "diff_preview", "diff_apply", "diff_undo", "diff_verify"],
                        "description": "编辑操作类型。diff_*=多文件原子编辑(git stash→apply→lint/test/LSP→回滚)",
                    },
                    "content": {
                        "type": "string",
                        "description": "patch 内容（apply_patch/preview_patch 使用，unified diff 格式）",
                    },
                    "start_line": {
                        "type": "integer",
                        "description": "起始行号（1-indexed）",
                    },
                    "end_line": {
                        "type": "integer",
                        "description": "结束行号（1-indexed，包含）",
                    },
                    "new_content": {
                        "type": "string",
                        "description": "新内容（insert/replace 使用）",
                    },
                    "preview": {
                        "type": "boolean",
                        "description": "是否仅预览不写入文件",
                    },
                    "backup": {
                        "type": "boolean",
                        "description": "是否备份原文件（默认 True）",
                    },
                    "files": {
                        "type": "array",
                        "description": "[diff_*] 多文件列表 [{file_path, old_code, new_code, symbol?}]",
                    },
                    "run_tests": {
                        "type": "boolean",
                        "description": "[diff_apply] 是否运行 pytest，默认 True",
                    },
                    "description": {
                        "type": "string",
                        "description": "[diff_*] 变更描述（用于 git stash 消息）",
                    },
                    "lsp_checks": {
                        "type": "boolean",
                        "description": "[diff_apply] 是否运行 LSP 检查，默认 True",
                    },
                },
                "required": ["file_path", "action"],
                "type": "object",
            },
        },
    }
