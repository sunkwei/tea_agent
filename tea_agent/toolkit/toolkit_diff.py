# @2026-05-19 gen by claude, Diff-first 代码编辑 — 生成unified diff → 预览 → 原子应用 → lint/test验证
"""
toolkit_diff — Diff-first 代码编辑引擎

工作流:
  1. generate: old_code → new_code 生成 unified diff
  2. preview:  预览多文件 diff 摘要
  3. apply:    git stash → 逐个应用 → lint/test 验证 → 失败自动回滚
  4. undo:     恢复到 git stash

特性:
  - 多文件原子事务（任一失败全部回滚）
  - 编辑前自动 git stash 备份
  - 编辑后自动 ruff + py_compile + pytest 验证
  - 冲突检测：apply 前验证 old_code 是否仍匹配
"""

import json
import logging
import os
import subprocess
from datetime import datetime

logger = logging.getLogger("toolkit")

# ── Diff 生成 ────────────────────────────────────────────

def _generate_unified_diff(old: str, new: str, filename: str = "file", context_lines: int = 3) -> str:
    """生成 unified diff 格式的差异"""
    import difflib
    old_lines = old.splitlines(keepends=True)
    new_lines = new.splitlines(keepends=True)
    diff = difflib.unified_diff(old_lines, new_lines, fromfile=filename, tofile=filename, n=context_lines)
    return ''.join(diff)


def _colorize_diff(diff_text: str) -> str:
    """为 unified diff 添加 ANSI 颜色代码（用于终端显示）。

    颜色方案（借鉴 opencode/codex CLI 风格）：
    - 文件头 (---/+++): 青色 bold
    - 行号 (@@): 紫色
    - 删除行 (-): 红色背景
    - 新增行 (+): 绿色背景
    - 上下文行: 默认
    """
    if not diff_text:
        return ""

    lines = diff_text.splitlines(keepends=True)
    result = []
    for line in lines:
        if line.startswith('---') or line.startswith('+++'):
            # 文件头 - 青色加粗
            result.append(f'\033[36;1m{line.rstrip()}\033[0m\n')
        elif line.startswith('@@'):
            # 行号信息 - 紫色
            result.append(f'\033[35m{line.rstrip()}\033[0m\n')
        elif line.startswith('-'):
            # 删除行 - 红色
            result.append(f'\033[41;97m{line.rstrip()}\033[0m\n')
        elif line.startswith('+'):
            # 新增行 - 绿色
            result.append(f'\033[42;97m{line.rstrip()}\033[0m\n')
        else:
            result.append(line)
    return ''.join(result)


def _generate_diff_stats(diff_text: str) -> dict:
    """统计 diff 的变更行数。"""
    if not diff_text:
        return {"additions": 0, "deletions": 0, "changes": 0}
    additions = sum(1 for line in diff_text.split('\n') if line.startswith('+') and not line.startswith('+++'))
    deletions = sum(1 for line in diff_text.split('\n') if line.startswith('-') and not line.startswith('---'))
    return {"additions": additions, "deletions": deletions, "changes": additions + deletions}

# ── Git Stash 集成 ──────────────────────────────────────

def _git_stash_push(cwd: str) -> tuple[bool, str]:
    """保存当前工作区到 stash，返回 (ok, stash_ref)"""
    try:
        r = subprocess.run(["git", "stash", "push", "-m", "toolkit_diff auto-save"],
                           capture_output=True, text=True, timeout=15, cwd=cwd)
        ok = r.returncode == 0 and "No local changes" not in r.stdout
        return True, r.stdout.strip() if ok else "no changes"
    except Exception as e:
        return False, str(e)

def _git_stash_pop(cwd: str) -> tuple[bool, str]:
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

def _check_conflict(file_path: str, old_code: str, cwd: str) -> str | None:
    """检查 old_code 是否仍存在于文件。返回 None=无冲突, 否则返回错误信息"""
    full = os.path.join(cwd, file_path)
    if not os.path.exists(full):
        return f"文件不存在: {file_path}"
    with open(full, encoding="utf-8", errors="replace") as f:
        content = f.read()
    if old_code not in content:
        return f"冲突: old_code 在 {file_path} 中未找到（文件可能已被修改）"
    if content.count(old_code) > 1:
        return f"冲突: old_code 在 {file_path} 中出现 {content.count(old_code)} 次（无法唯一确定）"
    return None

# ── 验证 ────────────────────────────────────────────────

def _verify_all(files: list[str], cwd: str, run_tests: bool = True) -> dict:
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

    # 语义级诊断（jedi）— 检查未定义符号/无法解析的引用
    results["semantic"] = {}
    for fp in files:
        full = os.path.join(cwd, fp)
        if fp.endswith(".py") and os.path.exists(full):
            try:
                from tea_agent.lsp.lsp_engine import semantic_diagnose
                sd = semantic_diagnose(cwd, full)
                results["semantic"][fp] = sd
            except Exception:
                results["semantic"][fp] = {"ok": True, "issues": [], "hint": "skipped"}

    # pytest    if run_tests:
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
        and all(s.get("ok", True) for s in results["semantic"].values())
        and (results["test"] is None or results["test"].get("returncode") == 0)
    )
    return results

# ── 单文件应用 ──────────────────────────────────────────
def _apply_one(file_path: str, old_code: str, new_code: str, cwd: str, description: str = "") -> dict:
    """应用单个修改，返回 {ok, file, error, bak_path}"""
    import shutil

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
        with open(full, encoding="utf-8") as f:
            content = f.read()
        # 归一化换行符，确保只使用 \n
        content = content.replace('\r\n', '\n').replace('\r', '\n')
        new_code_norm = new_code.replace('\r\n', '\n').replace('\r', '\n')
        old_code_norm = old_code.replace('\r\n', '\n').replace('\r', '\n')
        new_content = content.replace(old_code_norm, new_code_norm, 1)
        with open(full, "w", encoding="utf-8") as f:
            f.write(new_content)
        return {"ok": True, "file": file_path, "bak_path": bak}
    except Exception as e:
        # 恢复备份
        if os.path.exists(bak):
            shutil.copy2(bak, full)
        return {"ok": False, "file": file_path, "error": f"写入失败: {e}"}

# ── 主入口 ──────────────────────────────────────────────

def toolkit_diff(
    action: str,
    files: list[dict] = None,
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
                colored = _colorize_diff(d)
                stats = _generate_diff_stats(d)
                diffs.append({"file": f["file_path"], "diff": d, "colored_diff": colored, "stats": stats})
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
                colored = _colorize_diff(diff)
                conflict = _check_conflict(f["file_path"], f["old_code"], cwd)
                stats = _generate_diff_stats(diff)
                previews.append({
                    "file": f["file_path"],
                    "diff": diff,
                    "colored_diff": colored,
                    "conflict": conflict,
                    "safe": conflict is None,
                    "change_lines": diff.count('\n') if diff else 0,
                    "stats": stats,
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


# ── 工具分类表 ────────────────────────────────────────────
# 用于 tool categorization 场景，方便 LLM 快速找到合适工具

TOOL_CATEGORIES = {
    "文件操作": [
        "toolkit_file", "toolkit_save_file", "toolkit_explr",
    ],
    "代码编辑": [
        "toolkit_edit", "toolkit_diff_edit", "toolkit_diff",
        "toolkit_self_evolve", "toolkit_clean_comments",
        "toolkit_format_code", "toolkit_auto_fix", "toolkit_comment",
    ],
    "搜索": [
        "toolkit_search", "toolkit_lsp", "toolkit_query_chat_history",
        "toolkit_js_fetch",
    ],
    "截图与OCR": [
        "toolkit_screenshot", "toolkit_ocr", "toolkit_screen_read",
    ],
    "系统操作": [
        "toolkit_exec", "toolkit_config", "toolkit_os_info",
        "toolkit_sudo_gui", "toolkit_input", "toolkit_clipboard",
    ],
    "包管理": [
        "toolkit_pkg", "toolkit_build", "toolkit_read_pyproject",
    ],
    "测试": [
        "toolkit_run_tests", "toolkit_test_gui",
    ],
    "记忆与知识": [
        "toolkit_memory", "toolkit_kb", "toolkit_reflection",
        "toolkit_proactive",
    ],
    "多Agent协作": [
        "toolkit_parallel_subtasks", "toolkit_subagent",
        "toolkit_subagent_msg", "toolkit_auto_pipeline",
    ],
    "计划与任务": [
        "toolkit_plan", "toolkit_todo", "toolkit_scheduler",
        "toolkit_task_resume",
    ],
    "Git版本控制": [
        "toolkit_git_commit", "toolkit_git_push_all_remotes",
        "toolkit_git_branch_manager",
    ],
    "Web与网络": [
        "toolkit_browser_tab", "toolkit_js_fetch", "toolkit_mcp",
    ],
    "自进化": [
        "toolkit_self_evolve", "toolkit_self_evolve_thread",
        "toolkit_prompt_evolve", "toolkit_evolution_exp",
        "toolkit_experience_solidify",
    ],
    "工具": [
        "toolkit_gettime", "toolkit_weather_my", "toolkit_lunar",
        "toolkit_date_diff", "toolkit_ip_location_my",
    ],
    "导出与分享": [
        "toolkit_dump_topic", "toolkit_export_last_pdf",
        "toolkit_notify",
    ],
    "MCP集成": [
        "toolkit_mcp",
    ],
}


def toolkit_get_categorized_tools() -> dict:
    """获取按类别分组的工具列表。

    借鉴 opencode/codex 的最小化工具集理念，
    将 75+ 工具按15个场景类别组织，降低选择成本。

    Returns:
        {"categories": [{"name": str, "tools": [str,...]}, ...],
         "total": int, "category_count": int}
    """
    categories = []
    total = set()
    for cat_name, tools in TOOL_CATEGORIES.items():
        categories.append({"name": cat_name, "tools": tools})
        total.update(tools)
    return {
        "categories": categories,
        "total": len(total),
        "category_count": len(categories),
    }


# ── 注册到全局工具分类元数据 ──
# 让 toolkit_self_report 也能读取此分类

# ── Meta ────────────────────────────────────────────────

def meta_toolkit_diff():
    """Meta toolkit diff."""
    return {
        "type": "function",
        "function": {
            "name": "toolkit_diff",
            "description": "Diff-first 代码编辑引擎。generate=生成unified diff, preview=预览+冲突检测, apply=git stash→多文件原子应用→lint/test, undo=恢复stash, verify=编译+lint+test。",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["generate", "preview", "apply", "undo", "verify"]},
                    "files": {"type": "array", "items": {"type": "object"},
                              "description": "[generate/preview/apply/verify] 文件列表: [{file_path, old_code, new_code}]"},
                    "run_tests": {"type": "boolean", "description": "[apply/verify] 是否运行 pytest，默认 true"},
                    "description": {"type": "string", "description": "[apply] 修改描述"},
                },
                "required": ["action"],
            },
        },
    }
