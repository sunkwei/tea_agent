# version: 1.0.0

import logging
from typing import Optional, Tuple, List, Dict

logger = logging.getLogger("toolkit")



logger = logging.getLogger("toolkit")

def toolkit_edit(file_path: str, action: str = "apply_patch", content: str = "",
                 start_line: int = 0, end_line: int = 0, new_content: str = "",
                 preview: bool = False, backup: bool = True,
                 files: list = None, run_tests: bool = True, description: str = ""):
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
    elif action == "preview_patch":
        return _preview_patch(file_path, content)
    # ── Diff engine actions (return dict) ──
    elif action in ("diff_generate", "diff_preview", "diff_apply", "diff_undo", "diff_verify"):
        import os as _os_diff
        cwd = _os_diff.getcwd()
        diff_action = action[5:]  # strip "diff_"
        result = _toolkit_diff_impl(diff_action, files=files, cwd=cwd, run_tests=run_tests, description=description)
        return (0 if result.get("ok") else 1, str(result), "")
    else:
        return (1, "", f"未知 action: {action}，支持: apply_patch/insert_lines/delete_lines/replace_lines/preview_patch/diff_*")


def _apply_patch(file_path: str, patch_content: str, preview: bool, backup: bool):
    """应用 diff/patch"""
    import json

    import os
    import tempfile
    import subprocess

    try:
        # 读取原文件
        with open(file_path, 'r', encoding='utf-8') as f:
            original_content = f.read()

        # 尝试使用 patch 命令
        patch_available = False
        import shutil
        if shutil.which('patch'):
            patch_available = True

        if patch_available and not preview:
            # 使用系统 patch 命令
            with tempfile.NamedTemporaryFile(mode='w', suffix='.patch', delete=False, encoding='utf-8') as pf:
                pf.write(patch_content)
                patch_file = pf.name

            try:
                # 备份原文件
                if backup:
                    backup_path = file_path + '.bak'
                    import shutil as sh
                    sh.copy2(file_path, backup_path)

                # 应用 patch
                result = subprocess.run(
                    ['patch', '--batch', '--forward', file_path, patch_file],
                    capture_output=True, text=True, timeout=30
                )

                if result.returncode == 0:
                    return (0, f"✅ 成功应用 patch 到 {file_path}", "")
                else:
                    # patch 失败，尝试恢复
                    if backup and os.path.exists(backup_path):
                        sh.copy2(backup_path, file_path)
                    return (1, "", f"❌ patch 应用失败:\n{result.stderr}\n{result.stdout}")
            finally:
                try:
                    os.unlink(patch_file)
                except OSError:
                    pass
        else:
            # Python 实现的简易 patch 应用
            return _apply_patch_python(file_path, original_content, patch_content, preview, backup)

    except Exception as e:
        return (1, "", f"❌ 应用 patch 失败: {str(e)}")

def _apply_patch_python(file_path: str, original_content: str, patch_content: str, preview: bool, backup: bool):
    """Python 实现的简易 patch 应用（统一 diff 格式）"""
    import json
    import os
    import re

    try:
        lines = original_content.split('\n')
        patch_lines = patch_content.split('\n')

        # 解析 unified diff
        # 简化的解析器，支持基本的 @@ -old_start,old_count +new_start,new_count @@ 格式
        hunks = []
        current_hunk = None

        for line in patch_lines:
            if line.startswith('@@'):
                if current_hunk:
                    hunks.append(current_hunk)
                # 解析 hunk header
                match = re.match(r'@@ -(\d+),?(\d*) \+(\d+),?(\d*) @@', line)
                if match:
                    old_start = int(match.group(1))
                    old_count = int(match.group(2)) if match.group(2) else 1
                    new_start = int(match.group(3))
                    new_count = int(match.group(4)) if match.group(4) else 1
                    current_hunk = {
                        'old_start': old_start,
                        'old_count': old_count,
                        'new_start': new_start,
                        'new_count': new_count,
                        'lines': []
                    }
            elif current_hunk is not None and (line.startswith('+') or line.startswith('-') or line.startswith(' ') or line == '\\ No newline at end of file'):
                current_hunk['lines'].append(line)

        if current_hunk:
            hunks.append(current_hunk)

        if not hunks:
            return (1, "", "❌ 无法解析 patch 内容，请确保是有效的 unified diff 格式")

        # 应用 hunks（从后往前，避免行号偏移）
        new_lines = lines[:]
        for hunk in reversed(hunks):
            old_start = hunk['old_start']
            hunk_lines = hunk['lines']

            # 提取删除和新增的行
            delete_lines = []
            insert_lines = []
            for hl in hunk_lines:
                if hl.startswith('-'):
                    delete_lines.append(hl[1:])
                elif hl.startswith('+'):
                    insert_lines.append(hl[1:])

            # 验证删除的行是否匹配
            start_idx = old_start - 1  # 转换为 0-indexed
            if start_idx < 0 or start_idx >= len(new_lines):
                return (1, "", f"❌ patch 行号超出范围: {old_start}")

            # 检查上下文是否匹配
            match = True
            for i, dl in enumerate(delete_lines):
                if start_idx + i < len(new_lines) and new_lines[start_idx + i].strip() != dl.strip():
                    match = False
                    break

            if match and delete_lines:
                # 删除旧行
                for _ in delete_lines:
                    new_lines.pop(start_idx)
                # 插入新行
                for i, il in enumerate(insert_lines):
                    new_lines.insert(start_idx + i, il)
            elif not delete_lines and insert_lines:
                # 纯插入
                for i, il in enumerate(insert_lines):
                    new_lines.insert(start_idx + i, il)

        new_content = '\n'.join(new_lines)

        if preview:
            # 返回预览
            diff_preview = _generate_diff(original_content, new_content)
            return (0, json.dumps({
                "status": "preview",
                "file": file_path,
                "diff": diff_preview,
            }, ensure_ascii=False, indent=2), "")

        # 写入文件
        if backup:
            import shutil
            backup_path = file_path + '.bak'
            shutil.copy2(file_path, backup_path)

        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(new_content)

        return (0, f"✅ 成功应用编辑到 {file_path}", "")

    except Exception as e:
        return (1, "", f"❌ 应用 patch 失败: {str(e)}")

def _insert_lines(file_path: str, start_line: int, new_content: str, preview: bool, backup: bool):
    """在指定行插入内容"""
    import json
    import os
    import shutil

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        if start_line < 1 or start_line > len(lines) + 1:
            return (1, "", f"❌ 行号 {start_line} 超出范围 (1-{len(lines)+1})")

        # 保存原始内容用于 diff 生成
        original_content = ''.join(lines)

        # 插入新内容
        insert_lines = new_content.split('\n')
        # 正确处理换行符
        insert_lines_with_newline = []
        for i, line in enumerate(insert_lines):
            if i < len(insert_lines) - 1:
                insert_lines_with_newline.append(line + '\n')
            else:
                # 最后一行：如果原文件该行有换行符，则也添加
                if lines and lines[-1].endswith('\n'):
                    insert_lines_with_newline.append(line + '\n')
                else:
                    insert_lines_with_newline.append(line)

        insert_index = start_line - 1  # 转换为 0-indexed
        # 在指定位置插入
        new_lines = lines[:insert_index] + insert_lines_with_newline + lines[insert_index:]
        new_content_joined = ''.join(new_lines)

        if preview:
            diff_preview = _generate_diff(original_content, new_content_joined)
            return (0, json.dumps({
                "status": "preview",
                "file": file_path,
                "action": "insert",
                "at_line": start_line,
                "diff": diff_preview,
            }, ensure_ascii=False, indent=2), "")

        # 备份并写入
        if backup:
            shutil.copy2(file_path, file_path + '.bak')

        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(new_content_joined)

        return (0, f"✅ 成功在 {file_path}:{start_line} 插入 {len(insert_lines)} 行", "")

    except Exception as e:
        return (1, "", f"❌ 插入失败: {str(e)}")

def _delete_lines(file_path: str, start_line: int, end_line: int, preview: bool, backup: bool):
    """删除指定行范围"""
    import json
    import shutil

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        if start_line < 1 or start_line > len(lines):
            return (1, "", f"❌ 起始行号 {start_line} 超出范围")

        if end_line < start_line or end_line > len(lines):
            return (1, "", f"❌ 结束行号 {end_line} 超出范围")

        # 删除行
        deleted = lines[start_line-1:end_line]
        new_lines = lines[:start_line-1] + lines[end_line:]
        new_content = ''.join(new_lines)

        if preview:
            diff_preview = _generate_diff(''.join(lines), new_content)
            return (0, json.dumps({
                "status": "preview",
                "file": file_path,
                "action": "delete",
                "deleted_lines": f"{start_line}-{end_line}",
                "diff": diff_preview,
            }, ensure_ascii=False, indent=2), "")

        # 备份并写入
        if backup:
            shutil.copy2(file_path, file_path + '.bak')

        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(new_content)

        return (0, f"✅ 成功删除 {file_path}:{start_line}-{end_line} ({len(deleted)} 行)", "")

    except Exception as e:
        return (1, "", f"❌ 删除失败: {str(e)}")

def _replace_lines(file_path: str, start_line: int, end_line: int, new_content: str, preview: bool, backup: bool):
    """替换指定行范围"""
    import json
    import shutil

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        if start_line < 1 or start_line > len(lines):
            return (1, "", f"❌ 起始行号 {start_line} 超出范围")

        if end_line < start_line or end_line > len(lines):
            return (1, "", f"❌ 结束行号 {end_line} 超出范围")

        # 替换行
        old_lines = lines[start_line-1:end_line]
        insert_lines = new_content.split('\n')
        insert_lines_with_newline = [l + '\n' for l in insert_lines[:-1]] + [insert_lines[-1]]

        new_lines = lines[:start_line-1] + insert_lines_with_newline + lines[end_line:]
        new_content_joined = ''.join(new_lines)

        if preview:
            diff_preview = _generate_diff(''.join(lines), new_content_joined)
            return (0, json.dumps({
                "status": "preview",
                "file": file_path,
                "action": "replace",
                "replaced_lines": f"{start_line}-{end_line}",
                "diff": diff_preview,
            }, ensure_ascii=False, indent=2), "")

        # 备份并写入
        if backup:
            shutil.copy2(file_path, file_path + '.bak')

        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(new_content_joined)

        return (0, f"✅ 成功替换 {file_path}:{start_line}-{end_line} ({len(old_lines)} → {len(insert_lines)} 行)", "")

    except Exception as e:
        return (1, "", f"❌ 替换失败: {str(e)}")

def _preview_patch(file_path: str, patch_content: str):
    """预览 patch 应用后的结果"""
    return _apply_patch(file_path, patch_content, preview=True, backup=False)

def _generate_diff(old_content: str, new_content: str) -> str:
    """生成 unified diff"""
    import difflib

    old_lines = old_content.splitlines(keepends=True)
    new_lines = new_content.splitlines(keepends=True)

    diff = difflib.unified_diff(old_lines, new_lines, fromfile='original', tofile='modified', n=3)
    return ''.join(diff)


# ═══ Diff engine (merged from toolkit_diff) ═══
def _generate_unified_diff(old: str, new: str, filename: str = "file", context_lines: int = 3) -> str:
    """生成 unified diff 格式的差异"""
    import difflib
    old_lines = old.splitlines(keepends=True)
    new_lines = new.splitlines(keepends=True)
    diff = difflib.unified_diff(old_lines, new_lines, fromfile=filename, tofile=filename, n=context_lines)
    return ''.join(diff)

# ── Git Stash 集成 ──────────────────────────────────────

def _git_stash_push(cwd: str) -> Tuple[bool, str]:
    """保存当前工作区到 stash，返回 (ok, stash_ref)"""
    try:
        r = subprocess.run(["git", "stash", "push", "-m", "toolkit_diff auto-save"],
                           capture_output=True, text=True, timeout=15, cwd=cwd)
        ok = r.returncode == 0 and "No local changes" not in r.stdout
        return True, r.stdout.strip() if ok else "no changes"
    except Exception as e:
        return False, str(e)

def _git_stash_pop(cwd: str) -> Tuple[bool, str]:
    """恢复最近一次 stash"""
    try:
        r = subprocess.run(["git", "stash", "pop"], capture_output=True, text=True, timeout=15, cwd=cwd)
        return r.returncode == 0, r.stderr or r.stdout
    except Exception as e:
        return False, str(e)

def _git_stash_drop(cwd: str) -> bool:
    """丢弃最近一次 stash（确认成功）"""
    try:
        subprocess.run(["git", "stash", "drop"], capture_output=True, text=True, timeout=10, cwd=cwd)
        return True
    except Exception:
        return False

# ── 冲突检测 ────────────────────────────────────────────

def _check_conflict(file_path: str, old_code: str, cwd: str) -> Optional[str]:
    """检查 old_code 是否仍存在于文件。返回 None=无冲突, 否则返回错误信息"""
    full = os.path.join(cwd, file_path)
    if not os.path.exists(full):
        return f"文件不存在: {file_path}"
    with open(full, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()
    if old_code not in content:
        return f"冲突: old_code 在 {file_path} 中未找到（文件可能已被修改）"
    if content.count(old_code) > 1:
        return f"冲突: old_code 在 {file_path} 中出现 {content.count(old_code)} 次（无法唯一确定）"
    return None

# ── 验证 ────────────────────────────────────────────────

def _verify_all(files: List[str], cwd: str, run_tests: bool = True) -> dict:
    """批量编译+lint 验证，可选测试"""
    results = {"compile": {}, "lint": {}, "test": None}

    # py_compile
    import py_compile
    for fp in files:
        full = os.path.join(cwd, fp)
        if fp.endswith(".py") and os.path.exists(full):
            try:
                py_compile.compile(full, doraise=True)
                results["compile"][fp] = "ok"
            except py_compile.PyCompileError as e:
                results["compile"][fp] = f"FAIL: {e}"

    # ruff lint
    for fp in files:
        full = os.path.join(cwd, fp)
        if os.path.exists(full):
            r = subprocess.run(["ruff", "check", "--output-format", "json", full],
                               capture_output=True, text=True, timeout=20, cwd=cwd)
            diags = json.loads(r.stdout) if r.stdout.strip() else []
            results["lint"][fp] = len(diags) if diags else 0

    # pytest
    if run_tests:
        try:
            r = subprocess.run(
                [os.sys.executable, "-m", "pytest", "test_*.py", "-q", "--tb=short"],
                capture_output=True, text=True, timeout=60, cwd=cwd,
            )
            output = r.stdout + r.stderr
            results["test"] = {
                "returncode": r.returncode,
                "output": output[-500:],
            }
        except subprocess.TimeoutExpired:
            results["test"] = {"returncode": -1, "output": "timeout (>60s)"}
        except Exception as e:
            results["test"] = {"returncode": -1, "output": str(e)[:200]}

    results["all_ok"] = (
        all(not str(v).startswith("FAIL") for v in results["compile"].values())
        and all(v == 0 for v in results["lint"].values())
        and (results["test"] is None or results["test"].get("returncode") == 0)
    )
    return results

# ── 单文件应用 ──────────────────────────────────────────

def _apply_one(file_path: str, old_code: str, new_code: str, cwd: str, description: str = "") -> dict:
    """应用单个修改，返回 {ok, file, error, bak_path}"""
    import shutil
    from datetime import datetime

    full = os.path.join(cwd, file_path)

    # 冲突检测
    conflict = _check_conflict(file_path, old_code, cwd)
    if conflict:
        return {"ok": False, "file": file_path, "error": conflict}

    # 备份
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = f"{full}.bak.{ts}"
    try:
        shutil.copy2(full, bak)
    except Exception as e:
        return {"ok": False, "file": file_path, "error": f"备份失败: {e}"}

    # 应用
    try:
        with open(full, "r", encoding="utf-8") as f:
            content = f.read()
        new_content = content.replace(old_code, new_code, 1)
        with open(full, "w", encoding="utf-8") as f:
            f.write(new_content)
        return {"ok": True, "file": file_path, "bak_path": bak}
    except Exception as e:
        # 恢复备份
        if os.path.exists(bak):
            shutil.copy2(bak, full)
        return {"ok": False, "file": file_path, "error": f"写入失败: {e}"}

# ── 主入口 ──────────────────────────────────────────────

def _toolkit_diff_impl(
    action: str,
    files: List[dict] = None,
    cwd: str = None,
    run_tests: bool = True,
    description: str = "",
    stash_ref: str = None,
) -> dict:
    """Diff-first 代码编辑引擎。

    action:
      generate — 生成 unified diff（不修改文件）
      preview  — 生成 diff + 冲突检测（不修改文件）
      apply    — git stash → 多文件原子应用 → 编译+lint+test 验证
      undo     — 恢复到 git stash
      verify   — 运行编译+lint+test（不修改文件）

    files: [{"file_path": "...", "old_code": "...", "new_code": "..."}, ...]
    """
    import os as _os
    cwd = cwd or _os.getcwd()

    try:
        if action == "generate":
            if not files:
                return {"ok": False, "error": "generate 需要 files 参数"}
            diffs = []
            for f in files:
                d = _generate_unified_diff(f["old_code"], f["new_code"], f["file_path"])
                diffs.append({"file": f["file_path"], "diff": d})
            combined = "\n".join(d["diff"] for d in diffs)
            return {"ok": True, "diffs": diffs, "combined": combined,
                    "file_count": len(diffs)}

        elif action == "preview":
            if not files:
                return {"ok": False, "error": "preview 需要 files 参数"}
            previews = []
            conflicts = []
            for f in files:
                diff = _generate_unified_diff(f["old_code"], f["new_code"], f["file_path"])
                conflict = _check_conflict(f["file_path"], f["old_code"], cwd)
                previews.append({
                    "file": f["file_path"],
                    "diff": diff,
                    "conflict": conflict,
                    "safe": conflict is None,
                    "change_lines": diff.count('\n') if diff else 0,
                })
                if conflict:
                    conflicts.append(f["file_path"])
            all_safe = len(conflicts) == 0
            return {
                "ok": all_safe,
                "safe": all_safe,
                "files": previews,
                "conflicts": conflicts,
                "total_changes": sum(p["change_lines"] for p in previews),
                "hint": "所有文件无冲突 ✓" if all_safe else f"{len(conflicts)} 个文件有冲突，请解决后再 apply",
            }

        elif action == "apply":
            if not files:
                return {"ok": False, "error": "apply 需要 files 参数"}
            if not description:
                description = f"toolkit_diff: {len(files)} files"

            # Step 0: 冲突检测
            for f in files:
                conflict = _check_conflict(f["file_path"], f["old_code"], cwd)
                if conflict:
                    return {"ok": False, "error": f"pre-check 失败: {conflict}", "phase": "conflict_check"}

            # Step 1: git stash
            stashed, stash_msg = _git_stash_push(cwd)
            stash_applied = False
            try:
                # Step 2: 逐个应用
                results = []
                all_ok = True
                for f in files:
                    r = _apply_one(f["file_path"], f["old_code"], f["new_code"], cwd, description)
                    results.append(r)
                    if not r["ok"]:
                        all_ok = False
                        break

                if not all_ok:
                    # 回滚：恢复已修改的文件
                    for r in results:
                        if r.get("bak_path") and os.path.exists(r["bak_path"]):
                            import shutil
                            shutil.copy2(r["bak_path"], os.path.join(cwd, r["file"]))
                    if stashed:
                        _git_stash_pop(cwd)
                        stash_applied = True
                    return {
                        "ok": False,
                        "error": f"应用失败: {next((r['error'] for r in results if not r['ok']), 'unknown')}",
                        "phase": "apply",
                        "results": results,
                    }

                # Step 3: 验证
                modified_files = [f["file_path"] for f in files]
                verify = _verify_all(modified_files, cwd, run_tests=run_tests)

                if not verify["all_ok"]:
                    # 回滚
                    for r in results:
                        if r.get("bak_path") and os.path.exists(r["bak_path"]):
                            import shutil
                            shutil.copy2(r["bak_path"], os.path.join(cwd, r["file"]))
                    if stashed:
                        _git_stash_pop(cwd)
                        stash_applied = True
                    return {
                        "ok": False,
                        "error": "验证失败，已回滚",
                        "phase": "verify",
                        "verify": verify,
                        "results": results,
                    }

                # Step 4: 成功，丢弃 stash
                if stashed:
                    _git_stash_drop(cwd)

                return {
                    "ok": True,
                    "files_modified": len(results),
                    "results": results,
                    "verify": verify,
                    "stashed": stashed,
                }

            except Exception as e:
                if stashed and not stash_applied:
                    _git_stash_pop(cwd)
                return {"ok": False, "error": str(e)[:300], "phase": "exception"}

        elif action == "undo":
            ok, msg = _git_stash_pop(cwd)
            return {"ok": ok, "message": msg, "hint": "git stash pop 完成" if ok else "stash 恢复失败"}

        elif action == "verify":
            if not files:
                return {"ok": False, "error": "verify 需要 files 参数"}
            modified = [f["file_path"] for f in files]
            verify = _verify_all(modified, cwd, run_tests=run_tests)
            return {"ok": verify["all_ok"], "verify": verify}

        else:
            return {"ok": False, "error": f"未知 action: {action}。支持: generate/preview/apply/undo/verify"}

    except Exception as e:
        logger.exception(f"toolkit_diff: {e}")
        return {"ok": False, "error": str(e)[:300]}

# ── Meta ────────────────────────────────────────────────

def meta_toolkit_edit() -> dict:
    """Meta toolkit edit."""
    return {
        "type": "function",
        "function": {
            "name": "toolkit_edit",
            "description": "高级代码编辑 + Diff 引擎。行级编辑: apply_patch/insert_lines/delete_lines/replace_lines/preview_patch。多文件原子编辑: diff_generate/diff_preview/diff_apply/diff_undo/diff_verify（git stash + lint/test 验证）。",
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
                        "description": "编辑操作类型。diff_*=多文件原子编辑(git stash→apply→lint/test→回滚)",
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
                },
                "required": ["file_path", "action"],
                "type": "object",
            },
        },
    }
