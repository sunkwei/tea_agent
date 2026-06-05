# version: 1.1.0 — added replace_text + post-write verification

import logging

logger = logging.getLogger("toolkit")


def toolkit_edit(file_path: str, action: str = "apply_patch", content: str = "",
                 start_line: int = 0, end_line: int = 0, new_content: str = "",
                 old_text: str = "", preview: bool = False, backup: bool = True):
    """
    高级代码编辑工具。推荐使用 replace_text（文本匹配）代替 replace_lines（行号匹配）。

    action='replace_text': 【推荐】按旧文本精确匹配替换，免疫行号漂移
        toolkit_edit(file_path='x.py', action='replace_text',
                    old_text='def foo():\\n    pass',
                    new_content='def foo():\\n    return 42')

    action='replace_lines': 替换指定行范围（注意：连续多次编辑会行号漂移）
    action='insert_lines': 在指定行插入
    action='delete_lines': 删除指定行范围
    action='apply_patch': 应用 unified diff
    action='preview_patch': 预览 patch
    """
    logger.info(f"toolkit_edit called: file_path={file_path!r}, action={action!r}")

    import os

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
    elif action == "replace_text":
        return _replace_text(file_path, old_text, new_content, preview, backup)
    elif action == "preview_patch":
        return _preview_patch(file_path, content)
    else:
        return (1, "", f"未知 action: {action}")


# ═══════════════════════════════════════════════════════════════
#  post-write verification
# ═══════════════════════════════════════════════════════════════

def _verify_after_write(file_path: str, old_text: str = "",
                        new_text: str = "", label: str = "") -> str:
    """
    Read file back and verify old_text is gone, new_text is present.
    Returns warning string if something looks wrong, empty string if OK.
    """
    import os
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            current = f.read()
    except Exception as e:
        return f"⚠️ 验证失败：无法读回文件 {file_path}: {e}"

    if not current.strip():
        return f"⚠️ 验证警告：{label} — 文件变为空！请检查"

    warnings = []
    if old_text:
        old_norm = old_text.replace('\r\n', '\n').replace('\r', '\n')
        cur_norm = current.replace('\r\n', '\n').replace('\r', '\n')
        if old_norm in cur_norm:
            # count occurrences
            count = cur_norm.count(old_norm)
            warnings.append(f"旧内容仍然存在（出现 {count} 次），替换可能不完整")

    if new_text:
        new_norm = new_text.replace('\r\n', '\n').replace('\r', '\n')
        cur_norm = current.replace('\r\n', '\n').replace('\r', '\n')
        if new_norm not in cur_norm:
            warnings.append("新内容未在文件中找到，写入可能失败")

    if warnings:
        return f"⚠️ 验证警告：{label} — " + "；".join(warnings)
    return ""


# ═══════════════════════════════════════════════════════════════
#  replace_text — text-based matching (recommended)
# ═══════════════════════════════════════════════════════════════

def _replace_text(file_path: str, old_text: str, new_content: str,
                  preview: bool, backup: bool):
    """Replace by exact text match — immune to line number drift."""
    import json
    import shutil

    if not old_text:
        return (1, "", "❌ old_text 不能为空，请提供要替换的原始文本")

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            original = f.read()

        # normalize line endings
        original_norm = original.replace('\r\n', '\n').replace('\r', '\n')
        old_norm = old_text.replace('\r\n', '\n').replace('\r', '\n')
        new_norm = new_content.replace('\r\n', '\n').replace('\r', '\n')

        # find old_text
        idx = original_norm.find(old_norm)
        if idx == -1:
            old_stripped = old_norm.strip()
            idx_stripped = original_norm.find(old_stripped)
            if idx_stripped == -1:
                return (1, "",
                        f"❌ 未找到匹配文本。old_text 的前80字符: {old_norm[:80]!r}")
            # use stripped match
            idx = idx_stripped
            old_norm = old_stripped

        # check for duplicate matches
        second = original_norm.find(old_norm, idx + len(old_norm))
        if second != -1:
            logger.warning(
                f"⚠️ old_text 在文件中出现多次，将替换第一个匹配 "
                f"(位置 {idx} 和 {second})"
            )

        # perform replacement (preserve original line endings style)
        new_content_raw = original[:idx] + new_norm + original[idx + len(old_norm):]

        if preview:
            diff_preview = _generate_diff(original, new_content_raw)
            return (0, json.dumps({
                "status": "preview",
                "file": file_path,
                "action": "replace_text",
                "match_at": idx,
                "duplicate": second != -1,
                "diff": diff_preview,
            }, ensure_ascii=False, indent=2), "")

        # backup
        if backup:
            shutil.copy2(file_path, file_path + '.bak')

        # write
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(new_content_raw)

        # verify
        vrf = _verify_after_write(file_path,
                                  old_text=old_norm,
                                  new_text=new_norm,
                                  label="replace_text")
        if vrf:
            return (0, f"✅ 成功替换（文本匹配，位置 {idx}）{vrf}", "")
        return (0, f"✅ 成功替换（文本匹配，位置 {idx}）", "")

    except Exception as e:
        return (1, "", f"❌ replace_text 失败: {str(e)}")


# ═══════════════════════════════════════════════════════════════
#  existing actions (with verification added)
# ═══════════════════════════════════════════════════════════════

def _apply_patch(file_path: str, patch_content: str, preview: bool, backup: bool):
    import json
    import os
    import tempfile
    import subprocess
    import shutil

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            original_content = f.read()

        patch_available = shutil.which('patch') is not None

        if patch_available and not preview:
            with tempfile.NamedTemporaryFile(mode='w', suffix='.patch',
                                             delete=False, encoding='utf-8') as pf:
                pf.write(patch_content)
                patch_file = pf.name
            try:
                if backup:
                    shutil.copy2(file_path, file_path + '.bak')
                result = subprocess.run(
                    ['patch', '--batch', '--forward', file_path, patch_file],
                    capture_output=True, text=True, timeout=30)
                if result.returncode == 0:
                    return (0, f"✅ 成功应用 patch 到 {file_path}", "")
                else:
                    if backup and os.path.exists(file_path + '.bak'):
                        shutil.copy2(file_path + '.bak', file_path)
                    return (1, "", f"❌ patch 应用失败:\n{result.stderr}\n{result.stdout}")
            finally:
                try:
                    os.unlink(patch_file)
                except OSError:
                    pass
        else:
            return _apply_patch_python(file_path, original_content,
                                       patch_content, preview, backup)
    except Exception as e:
        return (1, "", f"❌ 应用 patch 失败: {str(e)}")


def _apply_patch_python(file_path: str, original_content: str,
                        patch_content: str, preview: bool, backup: bool):
    import json
    import os
    import re
    import shutil

    try:
        original_content = original_content.replace('\r\n', '\n').replace('\r', '\n')
        patch_content = patch_content.replace('\r\n', '\n').replace('\r', '\n')
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
                    current_hunk = {
                        'old_start': int(match.group(1)),
                        'old_count': int(match.group(2)) if match.group(2) else 1,
                        'new_start': int(match.group(3)),
                        'new_count': int(match.group(4)) if match.group(4) else 1,
                        'lines': []
                    }
            elif current_hunk is not None and (
                    line.startswith('+') or line.startswith('-') or
                    line.startswith(' ') or line == '\\ No newline at end of file'):
                current_hunk['lines'].append(line)
        if current_hunk:
            hunks.append(current_hunk)
        if not hunks:
            return (1, "", "❌ 无法解析 patch 内容")

        new_lines = lines[:]
        for hunk in reversed(hunks):
            old_start = hunk['old_start']
            delete_lines = [l[1:] for l in hunk['lines'] if l.startswith('-')]
            insert_lines = [l[1:] for l in hunk['lines'] if l.startswith('+')]
            start_idx = old_start - 1
            if start_idx < 0 or start_idx >= len(new_lines):
                return (1, "", f"❌ patch 行号超出范围: {old_start}")
            for _ in delete_lines:
                if start_idx < len(new_lines):
                    new_lines.pop(start_idx)
            for i, il in enumerate(insert_lines):
                new_lines.insert(start_idx + i, il)

        new_content = '\n'.join(new_lines)

        if preview:
            diff_preview = _generate_diff(original_content, new_content)
            return (0, json.dumps({"status": "preview", "file": file_path,
                                   "diff": diff_preview},
                                  ensure_ascii=False, indent=2), "")

        if backup:
            shutil.copy2(file_path, file_path + '.bak')
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(new_content)

        vrf = _verify_after_write(file_path, label="apply_patch")
        if vrf:
            return (0, f"✅ 成功应用编辑到 {file_path} {vrf}", "")
        return (0, f"✅ 成功应用编辑到 {file_path}", "")
    except Exception as e:
        return (1, "", f"❌ 应用 patch 失败: {str(e)}")


def _insert_lines(file_path: str, start_line: int, new_content: str,
                  preview: bool, backup: bool):
    import json
    import shutil

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        if start_line < 1 or start_line > len(lines) + 1:
            return (1, "", f"❌ 行号 {start_line} 超出范围 (1-{len(lines)+1})")

        original_content = ''.join(lines)
        new_content = new_content.replace('\r\n', '\n').replace('\r', '\n')
        insert_lines_list = new_content.split('\n')
        insert_with_nl = []
        for i, line in enumerate(insert_lines_list):
            if i < len(insert_lines_list) - 1:
                insert_with_nl.append(line + '\n')
            else:
                if lines and lines[-1].endswith('\n'):
                    insert_with_nl.append(line + '\n')
                else:
                    insert_with_nl.append(line)

        insert_index = start_line - 1
        new_lines = (lines[:insert_index] + insert_with_nl +
                     lines[insert_index:])
        new_content_joined = ''.join(new_lines)

        if preview:
            diff_preview = _generate_diff(original_content, new_content_joined)
            return (0, json.dumps({"status": "preview", "file": file_path,
                                   "action": "insert", "at_line": start_line,
                                   "diff": diff_preview},
                                  ensure_ascii=False, indent=2), "")

        if backup:
            shutil.copy2(file_path, file_path + '.bak')
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(new_content_joined)

        vrf = _verify_after_write(file_path, new_text=new_content.strip(),
                                  label=f"insert_lines@{start_line}")
        if vrf:
            return (0, f"✅ 成功在 {file_path}:{start_line} 插入 "
                       f"{len(insert_lines_list)} 行 {vrf}", "")
        return (0, f"✅ 成功在 {file_path}:{start_line} 插入 "
                   f"{len(insert_lines_list)} 行", "")
    except Exception as e:
        return (1, "", f"❌ 插入失败: {str(e)}")


def _delete_lines(file_path: str, start_line: int, end_line: int,
                  preview: bool, backup: bool):
    import json
    import shutil

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        if start_line < 1 or start_line > len(lines):
            return (1, "", f"❌ 起始行号 {start_line} 超出范围")
        if end_line < start_line or end_line > len(lines):
            return (1, "", f"❌ 结束行号 {end_line} 超出范围")

        deleted = lines[start_line - 1:end_line]
        deleted_text = ''.join(deleted).strip()
        new_lines = lines[:start_line - 1] + lines[end_line:]
        new_content = ''.join(new_lines)

        if preview:
            diff_preview = _generate_diff(''.join(lines), new_content)
            return (0, json.dumps({"status": "preview", "file": file_path,
                                   "action": "delete",
                                   "deleted_lines": f"{start_line}-{end_line}",
                                   "diff": diff_preview},
                                  ensure_ascii=False, indent=2), "")

        if backup:
            shutil.copy2(file_path, file_path + '.bak')
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(new_content)

        vrf = _verify_after_write(file_path, old_text=deleted_text,
                                  label=f"delete_lines:{start_line}-{end_line}")
        if vrf:
            return (0, f"✅ 成功删除 {file_path}:{start_line}-{end_line} "
                       f"({len(deleted)} 行) {vrf}", "")
        return (0, f"✅ 成功删除 {file_path}:{start_line}-{end_line} "
                   f"({len(deleted)} 行)", "")
    except Exception as e:
        return (1, "", f"❌ 删除失败: {str(e)}")


def _replace_lines(file_path: str, start_line: int, end_line: int,
                   new_content: str, preview: bool, backup: bool):
    import json
    import shutil

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        if start_line < 1 or start_line > len(lines):
            return (1, "", f"❌ 起始行号 {start_line} 超出范围")
        if end_line < start_line or end_line > len(lines):
            return (1, "", f"❌ 结束行号 {end_line} 超出范围")

        old_lines = lines[start_line - 1:end_line]
        old_text = ''.join(old_lines)
        new_content = new_content.replace('\r\n', '\n').replace('\r', '\n')
        insert_list = new_content.split('\n')
        insert_with_nl = [l + '\n' for l in insert_list[:-1]] + [insert_list[-1]]

        new_lines = (lines[:start_line - 1] + insert_with_nl +
                     lines[end_line:])
        new_content_joined = ''.join(new_lines)

        if preview:
            diff_preview = _generate_diff(''.join(lines), new_content_joined)
            return (0, json.dumps({"status": "preview", "file": file_path,
                                   "action": "replace",
                                   "replaced_lines": f"{start_line}-{end_line}",
                                   "diff": diff_preview},
                                  ensure_ascii=False, indent=2), "")

        if backup:
            shutil.copy2(file_path, file_path + '.bak')
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(new_content_joined)

        vrf = _verify_after_write(file_path,
                                  old_text=old_text.strip(),
                                  new_text=new_content.strip(),
                                  label=f"replace_lines:{start_line}-{end_line}")
        if vrf:
            return (0, f"✅ 成功替换 {file_path}:{start_line}-{end_line} "
                       f"({len(old_lines)}→{len(insert_list)} 行) {vrf}", "")
        return (0, f"✅ 成功替换 {file_path}:{start_line}-{end_line} "
                   f"({len(old_lines)}→{len(insert_list)} 行)", "")
    except Exception as e:
        return (1, "", f"❌ 替换失败: {str(e)}")


def _preview_patch(file_path: str, patch_content: str):
    return _apply_patch(file_path, patch_content, preview=True, backup=False)


def _generate_diff(old_content: str, new_content: str) -> str:
    import difflib
    old_lines = old_content.splitlines(keepends=True)
    new_lines = new_content.splitlines(keepends=True)
    diff = difflib.unified_diff(old_lines, new_lines,
                                fromfile='original', tofile='modified', n=3)
    return ''.join(diff)


def meta_toolkit_edit() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "toolkit_edit",
            "description": "高级代码编辑工具。推荐 replace_text（文本匹配）免疫行号漂移。",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "目标文件路径"},
                    "action": {
                        "type": "string",
                        "enum": ["apply_patch", "insert_lines", "delete_lines",
                                 "replace_lines", "replace_text", "preview_patch"],
                        "description": "编辑操作类型。推荐 replace_text",
                    },
                    "content": {
                        "type": "string",
                        "description": "patch 内容（apply_patch/preview_patch）",
                    },
                    "start_line": {
                        "type": "integer",
                        "description": "起始行号 1-indexed（insert/delete/replace_lines）",
                    },
                    "end_line": {
                        "type": "integer",
                        "description": "结束行号 1-indexed（delete/replace_lines）",
                    },
                    "new_content": {
                        "type": "string",
                        "description": "新内容（insert/replace_lines/replace_text）",
                    },
                    "old_text": {
                        "type": "string",
                        "description": "要替换的旧文本（replace_text，精确匹配）",
                    },
                    "preview": {
                        "type": "boolean",
                        "description": "是否仅预览不写入",
                    },
                    "backup": {
                        "type": "boolean",
                        "description": "是否备份（默认 True）",
                    },
                },
                "required": ["file_path", "action"],
            },
        },
    }
