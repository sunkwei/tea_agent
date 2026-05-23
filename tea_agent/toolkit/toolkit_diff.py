# @2026-05-23 gen by tea_agent, extracted from toolkit_edit.py for independent auto-discovery
"""Diff-first 代码编辑引擎。独立工具，支持 generate/preview/apply/undo/verify。"""
import os
import json
import shutil
import difflib
import subprocess
import logging
from typing import List, Dict, Optional, Tuple

logger = logging.getLogger("toolkit")

def _generate_unified_diff(old: str, new: str, filename: str = "file", context_lines: int = 3) -> str:
    """生成 unified diff 格式的差异"""
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
    lsp_checks: bool = True,
) -> dict:
    """Diff-first 代码编辑引擎。

    action:
      generate — 生成 unified diff（不修改文件）
      preview  — 生成 diff + 冲突检测（不修改文件）
      apply    — git stash → 多文件原子应用 → 编译+lint+test+LSP 验证
      undo     — 恢复到 git stash
      verify   — 运行编译+lint+test（不修改文件）

    files: [{"file_path": "...", "old_code": "...", "new_code": "...", "symbol": "..."}, ...]
    lsp_checks: 应用成功后运行 LSP 检查（影响分析+lint增量+签名对比），默认 True
    """
    cwd = cwd or os.getcwd()

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

                # Step 3.5: LSP 检查（非阻塞，仅信息）
                lsp_results = None
                if lsp_checks:
                    from tea_agent.lsp.lsp_check import run_lsp_check
                    lsp_results = []
                    for f in files:
                        fp = os.path.join(cwd, f["file_path"])
                        if fp.endswith(".py"):
                            lr = run_lsp_check(
                                file_path=fp,
                                symbol=f.get("symbol"),
                                old_code=f.get("old_code"),
                                new_code=f.get("new_code"),
                                cwd=cwd,
                            )
                            lsp_results.append({"file": f["file_path"], "lsp": lr})
                            if lr.get("lint_new", 0) > 0:
                                logger.warning(f"LSP[{f['file_path']}]: +{lr['lint_new']} lint issues")
                            if lr.get("sig_changed"):
                                logger.warning(f"LSP[{f['file_path']}]: sig changed {lr.get('old_sig')} → {lr.get('new_sig')}")

                # Step 4: 成功，丢弃 stash
                if stashed:
                    _git_stash_drop(cwd)

                return {
                    "ok": True,
                    "files_modified": len(results),
                    "results": results,
                    "verify": verify,
                    "lsp": lsp_results,
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


def toolkit_diff(
    action: str,
    files: List[dict] = None,
    cwd: str = None,
    run_tests: bool = True,
    description: str = "",
    lsp_checks: bool = True,
) -> dict:
    """Diff-first 代码编辑引擎。

    action:
      generate — 生成 unified diff（不修改文件）
      preview  — 生成 diff + 冲突检测（不修改文件）
      apply    — git stash → 多文件原子应用 → 编译+lint+test+LSP 验证
      undo     — 恢复到 git stash
      verify   — 运行编译+lint+test（不修改文件）

    files: [{"file_path": "...", "old_code": "...", "new_code": "..."}, ...]
    """
    return _toolkit_diff_impl(action, files=files, cwd=cwd, run_tests=run_tests,
                              description=description, lsp_checks=lsp_checks)


def meta_toolkit_diff() -> dict:
    """Meta: register toolkit_diff as Agent tool."""
    return {
        "type": "function",
        "function": {
            "name": "toolkit_diff",
            "description": "Diff-first 代码编辑引擎。action: generate/preview/apply/undo/verify。支持多文件原子事务（git stash→apply→lint/test/LSP验证→回滚）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["generate", "preview", "apply", "undo", "verify"],
                        "description": "操作类型",
                    },
                    "files": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "file_path": {"type": "string"},
                                "old_code": {"type": "string"},
                                "new_code": {"type": "string"},
                                "symbol": {"type": "string", "description": "被修改的符号名（用于LSP影响分析+签名对比）"},
                            },
                            "required": ["file_path", "old_code", "new_code"],
                        },
                        "description": "文件列表 [{file_path, old_code, new_code, symbol?}]",
                    },
                    "cwd": {
                        "type": "string",
                        "description": "工作目录，默认当前目录",
                    },
                    "run_tests": {
                        "type": "boolean",
                        "description": "apply 后是否运行 pytest，默认 True",
                    },
                    "description": {
                        "type": "string",
                        "description": "变更描述（用于 git stash 消息）",
                    },
                    "lsp_checks": {
                        "type": "boolean",
                        "description": "apply 后是否运行 LSP 检查（影响分析+lint增量+签名对比），默认 True",
                    },
                },
                "required": ["action", "files"],
            },
        },
    }
