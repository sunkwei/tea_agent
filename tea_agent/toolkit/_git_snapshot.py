"""Git 快照 — 修改工具自动"存盘"（借鉴 toolkit_self_evolve L0 + toolkit_git_commit）。

目的：杜绝"改了没存盘"——任何文件修改工具（toolkit_edit / toolkit_diff /
toolkit_file 等）修改成功后自动 git commit 该文件，会话中断也不丢失。

规则：
- 仅对 git 仓库生效（非仓库静默跳过，返回 snapshotted=False）
- 只 add 目标文件，不触碰其他未提交改动
- 无实际变更（add 后该文件 clean）时静默跳过，不产生空 commit
- commit 固定 author: tea_agent <sunkwei@gmail.com>，消息前缀 "snapshot:"
- 失败仅告警返回 error，不影响修改主流程（异常隔离）

注意：本模块以下划线开头，tlk.py 按 toolkit_*.py 扫描，不会注册为工具。
"""

import logging
import os
import subprocess

logger = logging.getLogger("toolkit.snapshot")

AUTHOR_NAME = "tea_agent"
AUTHOR_EMAIL = "sunkwei@gmail.com"

# staged 状态标记（git status --porcelain 第一列）
_STAGED_PREFIXES = ("A", "M", "R", "C", "D", "T")


def _run_git(args, cwd):
    """执行 git 命令，返回 (ok, output)。"""
    try:
        r = subprocess.run(
            ["git"] + args, capture_output=True, text=True, cwd=cwd, timeout=30
        )
        return r.returncode == 0, (r.stderr or r.stdout).strip()
    except subprocess.TimeoutExpired:
        return False, "git timeout"
    except FileNotFoundError:
        return False, "git not found"
    except Exception as e:  # pragma: no cover
        return False, str(e)[:200]


def _is_git_repo(cwd) -> bool:
    ok, _ = _run_git(["rev-parse", "--is-inside-work-tree"], cwd)
    return ok


def git_snapshot(file_paths, message="snapshot") -> dict:
    """对指定文件创建 git 快照（add + commit）。

    Args:
        file_paths: 文件路径列表（相对/绝对均可）
        message: commit 描述（自动加 "snapshot: " 前缀，用于过滤自动快照）

    Returns:
        {"snapshotted": bool, "hash": str, "message": str, "error": str, "clean": bool}
        snapshotted=True 表示已创建快照 commit；False 时 error 说明原因
        （非仓库 / 无变更 / git 失败），不影响调用方主流程。
    """
    if not file_paths:
        return {"snapshotted": False, "error": "no files to snapshot"}
    cwd = os.getcwd()
    if not _is_git_repo(cwd):
        return {"snapshotted": False, "error": "not a git repo", "clean": True}

    # 只 add 目标文件（不触碰其他未提交改动）
    ok, err = _run_git(["add"] + list(file_paths), cwd)
    if not ok:
        return {"snapshotted": False, "error": f"git add failed: {err}"}

    # 无实际 staged 变更则跳过（避免空 commit；如 preview/无改动）
    ok, status = _run_git(["status", "--porcelain"], cwd)
    if ok and status.strip():
        staged = [
            l for l in status.splitlines()
            if l.strip() and l[:1] in _STAGED_PREFIXES and l[1:2] in (" ", "M", "A")
        ]
    else:
        staged = []
    if not staged:
        return {"snapshotted": False, "error": "no changes", "clean": True}

    msg = message if message.startswith("snapshot:") else f"snapshot: {message}"
    commit_args = [
        "-c", f"user.name={AUTHOR_NAME}",
        "-c", f"user.email={AUTHOR_EMAIL}",
        "commit", "-m", msg,
    ]
    ok, out = _run_git(commit_args, cwd)
    if not ok:
        return {"snapshotted": False, "error": f"commit failed: {out}"}

    # 提取 commit hash（[master abc1234] ...）
    h = ""
    for line in out.split("\n"):
        if line.startswith("["):
            parts = line.split()
            if len(parts) >= 2:
                h = parts[1].rstrip("]")
    logger.info("git snapshot committed: %s → %s", msg, h or out[:50])
    return {"snapshotted": True, "hash": h, "message": msg, "clean": False}


def maybe_snapshot(file_paths, message="snapshot") -> dict:
    """安全包装：任何异常都返回失败 dict，绝不抛出（修改工具内联调用用）。"""
    try:
        return git_snapshot(file_paths, message)
    except Exception as e:  # pragma: no cover
        logger.warning("git snapshot failed (isolated): %s", e)
        return {"snapshotted": False, "error": str(e)[:200]}
