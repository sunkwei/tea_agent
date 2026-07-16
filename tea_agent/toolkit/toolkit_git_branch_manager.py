## llm generated tool func, created Thu Jul 16 21:52:39 2026
# version: 1.0.0

"""
toolkit_git_branch_manager — Git 自动分支管理工具。

借鉴 opencode/codex CLI 的「会话即分支」模式：
每次任务自动创建独立分支，任务完成后自动合并清理。

用法:
    toolkit_git_branch_manager(action="auto", task_desc="添加登录功能")
    toolkit_git_branch_manager(action="create", branch_name="feat/login")
    toolkit_git_branch_manager(action="switch", branch_name="main")
    toolkit_git_branch_manager(action="merge")
    toolkit_git_branch_manager(action="list")
    toolkit_git_branch_manager(action="current")
"""

import json
import logging
import os
import re
import subprocess
import sys

logger = logging.getLogger("toolkit")

# ── 辅助函数 ───────────────────────────────────


def _run_git(args: list[str], cwd: str | None = None) -> tuple[int, str, str]:
    """执行 git 命令。"""
    try:
        result = subprocess.run(
            ["git"] + args,
            capture_output=True, text=True, timeout=30, cwd=cwd,
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except FileNotFoundError:
        return -1, "", "git 命令未找到，请先安装 Git"
    except subprocess.TimeoutExpired:
        return -1, "", "git 命令超时"
    except Exception as e:
        return -1, "", str(e)


def _get_repo_root(cwd: str | None = None) -> str:
    """获取 Git 仓库根目录。"""
    rc, out, err = _run_git(["rev-parse", "--show-toplevel"], cwd)
    if rc != 0:
        raise RuntimeError(f"不在 Git 仓库中: {err}")
    return out


def _get_current_branch(cwd: str | None = None) -> str:
    """获取当前分支名。"""
    rc, out, err = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd)
    if rc != 0:
        raise RuntimeError(f"获取分支失败: {err}")
    return out


def _branch_exists(branch_name: str, cwd: str | None = None) -> bool:
    """检查分支是否存在。"""
    rc, out, err = _run_git(["branch", "--list", branch_name], cwd)
    return bool(out.strip())


def _sanitize_branch_name(task_desc: str) -> str:
    """将任务描述转换为合法的分支名。"""
    name = task_desc.lower().strip()
    name = re.sub(r'[^a-z0-9\u4e00-\u9fff\-_]', '-', name)
    name = re.sub(r'-+', '-', name)
    name = name.strip('-')[:40]
    if not name:
        name = "task"
    en_part = re.sub(r'[\u4e00-\u9fff]', '', name).strip('-')
    if en_part and len(en_part) >= 3:
        name = en_part
    return name


# ── 核心 API ───────────────────────────────────


def toolkit_git_branch_manager(
    action: str = "current",
    branch_name: str = "",
    base_branch: str = "main",
    task_desc: str = "",
    delete_after_merge: bool = True,
) -> str:
    """Git 自动分支管理。

    Args:
        action: 操作类型: create/switch/merge/cleanup/list/current/auto
        branch_name: 分支名称
        base_branch: 基础分支
        task_desc: 任务描述（auto 模式用）
        delete_after_merge: 合并后是否删除分支

    Returns:
        JSON 格式的结果
    """
    try:
        cwd = os.getcwd()
        repo_root = _get_repo_root(cwd)
    except RuntimeError as e:
        return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)

    # 检测默认分支（main 或 master）
    if base_branch == "main":
        for candidate in ["main", "master"]:
            rc, out, err = _run_git(["show-ref", "--verify", f"refs/heads/{candidate}"], cwd)
            if rc == 0:
                base_branch = candidate
                break

    # ── list: 列出分支 ──
    if action == "list":
        rc, out, err = _run_git(["branch", "-a"], cwd)
        if rc != 0:
            return json.dumps({"ok": False, "error": err}, ensure_ascii=False)
        current = _get_current_branch(cwd)
        branches = []
        for line in out.split("\n"):
            name = line.strip().replace("* ", "").strip()
            is_current = "*" in line
            branches.append({"name": name, "current": is_current})
        return json.dumps({
            "ok": True,
            "branches": branches,
            "current": current,
        }, ensure_ascii=False)

    # ── current: 当前分支信息 ──
    if action == "current":
        current = _get_current_branch(cwd)
        rc, out, err = _run_git(["status", "--short"], cwd)
        has_uncommitted = bool(out.strip())
        return json.dumps({
            "ok": True,
            "branch": current,
            "has_uncommitted": has_uncommitted,
            "repo": repo_root,
        }, ensure_ascii=False)

    # ── create: 创建新分支 ──
    if action == "create":
        if not branch_name:
            return json.dumps({"ok": False, "error": "需要指定 branch_name"}, ensure_ascii=False)
        if _branch_exists(branch_name, cwd):
            return json.dumps({
                "ok": False,
                "error": f"分支 '{branch_name}' 已存在",
                "branch": branch_name,
            }, ensure_ascii=False)
        rc, out, err = _run_git(["checkout", base_branch], cwd)
        if rc != 0:
            return json.dumps({"ok": False, "error": f"切换到 {base_branch} 失败: {err}"}, ensure_ascii=False)
        rc, out, err = _run_git(["pull", "--ff-only"], cwd)
        if rc != 0:
            logger.warning(f"拉取最新代码失败: {err}")
        rc, out, err = _run_git(["checkout", "-b", branch_name], cwd)
        if rc != 0:
            return json.dumps({"ok": False, "error": f"创建分支失败: {err}"}, ensure_ascii=False)
        return json.dumps({
            "ok": True,
            "action": "created",
            "branch": branch_name,
            "base": base_branch,
        }, ensure_ascii=False)

    # ── switch: 切换分支 ──
    if action == "switch":
        if not branch_name:
            return json.dumps({"ok": False, "error": "需要指定 branch_name"}, ensure_ascii=False)
        rc, out, err = _run_git(["status", "--short"], cwd)
        has_changes = bool(out.strip())
        if has_changes:
            _run_git(["stash", "push", "-m", f"auto-stash before switch to {branch_name}"], cwd)
        rc, out, err = _run_git(["checkout", branch_name], cwd)
        if rc != 0:
            return json.dumps({"ok": False, "error": f"切换分支失败: {err}"}, ensure_ascii=False)
        result = {"ok": True, "action": "switched", "branch": branch_name}
        if has_changes:
            result["stashed"] = True
        return json.dumps(result, ensure_ascii=False)

    # ── merge: 合并到基础分支 ──
    if action == "merge":
        current = _get_current_branch(cwd)
        if current == base_branch:
            return json.dumps({"ok": False, "error": f"当前已在 {base_branch} 分支上"})
        rc, out, err = _run_git(["status", "--short"], cwd)
        if out.strip():
            _run_git(["add", "."], cwd)
            _run_git(["commit", "-m", f"chore: auto-commit before merge {current}"], cwd)
        rc, out, err = _run_git(["checkout", base_branch], cwd)
        if rc != 0:
            return json.dumps({"ok": False, "error": f"切换到 {base_branch} 失败: {err}"})
        _run_git(["pull", "--ff-only"], cwd)
        rc, out, err = _run_git(["merge", current], cwd)
        if rc != 0:
            return json.dumps({
                "ok": False,
                "error": f"合并失败: {err}",
                "branch": current,
                "target": base_branch,
                "conflict": True,
            })
        _run_git(["push"], cwd)
        merged_info = {"ok": True, "action": "merged", "branch": current, "target": base_branch}
        if delete_after_merge:
            rc2, out2, err2 = _run_git(["branch", "-d", current], cwd)
            if rc2 == 0:
                merged_info["deleted"] = True
            else:
                merged_info["delete_failed"] = err2
        return json.dumps(merged_info, ensure_ascii=False)

    # ── cleanup: 清理已合并分支 ──
    if action == "cleanup":
        rc, out, err = _run_git(["branch", "--merged"], cwd)
        if rc != 0:
            return json.dumps({"ok": False, "error": err})
        cleaned = []
        skipped = []
        for line in out.split("\n"):
            name = line.strip().replace("*", "").strip()
            if name and name not in (base_branch, "main", "master"):
                rc2, _, err2 = _run_git(["branch", "-d", name], cwd)
                if rc2 == 0:
                    cleaned.append(name)
                else:
                    skipped.append({"branch": name, "reason": err2})
        return json.dumps({
            "ok": True,
            "action": "cleanup",
            "cleaned": cleaned,
            "skipped": skipped,
        }, ensure_ascii=False)

    # ── auto: 自动模式 ──
    if action == "auto":
        if not task_desc:
            return json.dumps({"ok": False, "error": "auto 模式需要 task_desc"}, ensure_ascii=False)
        safe_name = _sanitize_branch_name(task_desc)
        timestamp = ""
        if sys.platform != "win32":
            rc, ts, _ = _run_git(["log", "-1", "--format=%cd", "--date=format:%Y%m%d-%H%M%S"])
            if rc == 0:
                timestamp = ts
        if not timestamp:
            import datetime
            timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        auto_branch = f"feat/{safe_name}-{timestamp}" if safe_name else f"task/{timestamp}"

        current = _get_current_branch(cwd)
        if current != base_branch:
            _run_git(["checkout", base_branch], cwd)
            _run_git(["pull", "--ff-only"], cwd)

        rc, out, err = _run_git(["checkout", "-b", auto_branch], cwd)
        if rc != 0:
            return json.dumps({"ok": False, "error": f"创建分支失败: {err}"})
        return json.dumps({
            "ok": True,
            "action": "auto_created",
            "branch": auto_branch,
            "base": base_branch,
            "task": task_desc,
        }, ensure_ascii=False)

    return json.dumps({"ok": False, "error": f"未知操作: {action}"})


def meta_toolkit_git_branch_manager() -> dict:
    return {"type": "function", "function": {"name": "toolkit_git_branch_manager", "description": "Git 自动分支管理工具 — 借鉴 opencode/codex 的会话即分支模式。自动创建/切换/合并/清理功能分支，每次任务对应一个分支。", "parameters": {"type": "object", "properties": {"action": {"type": "string", "enum": ["create", "switch", "merge", "cleanup", "list", "current", "auto"], "description": "操作类型"}, "branch_name": {"type": "string", "description": "[create/switch/merge] 分支名称"}, "base_branch": {"type": "string", "description": "基础分支，默认 main", "default": "main"}, "task_desc": {"type": "string", "description": "[auto] 任务描述"}, "delete_after_merge": {"type": "boolean", "description": "合并后是否删除分支", "default": True}}, "required": ["action"]}}}
