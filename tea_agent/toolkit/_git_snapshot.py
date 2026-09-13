"""Git 快照 — 修改工具自动"存盘"（借鉴 toolkit_self_evolve L0 的 git 快照机制）。

目的：杜绝"改了没存盘"——任何文件修改工具（toolkit_edit / toolkit_diff /
toolkit_file 等）修改成功后自动留一个 git 快照，会话中断也不丢失。

落点（默认 side ref）：
    快照写入独立引用 **refs/tea/snapshots**，而不是提交到当前分支。
    原因：提交到分支会把 git log 淹没 —— 实测 1028 个提交里有 153 个是
    「snapshot: edit replace_text X」这类纯操作噪音（占 15%）。
    side ref 方案下：当前分支历史保持干净，回滚点一个不少：

        git log refs/tea/snapshots --oneline      # 看快照
        git show refs/tea/snapshots --stat        # 看最近一次快照内容
        git checkout refs/tea/snapshots -- <file> # 把某文件恢复到快照点

    工作区与暂存区**完全不受影响**：快照通过临时索引（GIT_INDEX_FILE）
    构造，不 add 真实文件，也不移动 HEAD。

可配置（环境变量）：
    TEA_GIT_SNAPSHOT_MODE  side（默认）| branch（旧行为：提交到当前分支）| off
    TEA_SNAPSHOT_REF       自定义快照 ref，默认 refs/tea/snapshots

规则：
- 仅对 git 仓库生效（非仓库静默跳过，返回 snapshotted=False）
- 无实际变更时静默跳过，不产生空快照
- 快照 commit 固定 author: tea_agent <sunkwei@gmail.com>，消息前缀 "snapshot:"
- 失败仅告警返回 error，不影响修改主流程（异常隔离）

注意：本模块以下划线开头，tlk.py 按 toolkit_*.py 扫描，不会注册为工具。
"""

import logging
import os
import subprocess
import tempfile

logger = logging.getLogger("toolkit.snapshot")

AUTHOR_NAME = "tea_agent"
AUTHOR_EMAIL = "sunkwei@gmail.com"

# 空树 sha（git 的固定常量，用于无 HEAD 的空仓库）
_EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"

# staged 状态标记（git status --porcelain 第一列）—— 仅 branch 模式使用
_STAGED_PREFIXES = ("A", "M", "R", "C", "D", "T")


def _snapshot_ref() -> str:
    """快照落点引用（可用 TEA_SNAPSHOT_REF 覆盖）。"""
    return os.environ.get("TEA_SNAPSHOT_REF") or "refs/tea/snapshots"


def _mode() -> str:
    """快照模式：side（默认）/ branch / off。"""
    return (os.environ.get("TEA_GIT_SNAPSHOT_MODE") or "side").strip().lower()


def _run_git(args, cwd, env=None):
    """执行 git 命令，返回 (ok, output)。env 可注入（如临时索引 GIT_INDEX_FILE）。"""
    try:
        r = subprocess.run(
            ["git"] + list(args), capture_output=True, text=True,
            cwd=cwd, timeout=30, env=env,
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


def _snapshot_side(file_paths, msg, cwd) -> dict:
    """把快照写进独立 ref —— 不动分支 / 暂存区 / 工作区。

    Returns:
        {"snapshotted": bool, "hash": str, "rev": str, "ref": str,
         "message": str, "clean": bool, "error": str}
    """
    fd, idx = tempfile.mkstemp(prefix="tea_snap_idx_")
    os.close(fd)
    try:
        env = dict(os.environ, GIT_INDEX_FILE=idx)
        has_head, _ = _run_git(["rev-parse", "--verify", "HEAD"], cwd)
        # 临时索引从 HEAD 播种 —— 只把目标文件叠加上去，真实暂存区不受影响
        seed = ["read-tree", "HEAD"] if has_head else ["read-tree", "--empty"]
        ok, out = _run_git(seed, cwd, env)
        if not ok:
            return {"snapshotted": False, "error": f"read-tree failed: {out}"}
        if has_head:
            ok, base_tree = _run_git(["rev-parse", "HEAD^{tree}"], cwd)
            base_tree = base_tree.strip() if ok else _EMPTY_TREE
        else:
            base_tree = _EMPTY_TREE
        ok, out = _run_git(["add", "--"] + [str(p) for p in file_paths], cwd, env)
        if not ok:
            return {"snapshotted": False, "error": f"git add failed: {out}"}
        ok, tree = _run_git(["write-tree"], cwd, env)
        if not ok:
            return {"snapshotted": False, "error": f"write-tree failed: {tree}"}
        tree = tree.strip()
        if tree == base_tree:
            return {"snapshotted": False, "error": "no changes", "clean": True}
        # 父提交 = 当前快照 ref 顶端（无则作为首个快照）
        ref = _snapshot_ref()
        p_ok, parent = _run_git(["rev-parse", "--verify", ref], cwd)
        args = [
            "-c", f"user.name={AUTHOR_NAME}",
            "-c", f"user.email={AUTHOR_EMAIL}",
            "commit-tree", tree, "-m", msg,
        ]
        if p_ok and parent.strip():
            args += ["-p", parent.strip()]
        ok, sha = _run_git(args, cwd, env)
        if not ok:
            return {"snapshotted": False, "error": f"commit-tree failed: {sha}"}
        sha = sha.strip()
        ok, out = _run_git(["update-ref", ref, sha], cwd)
        if not ok:
            return {"snapshotted": False, "error": f"update-ref failed: {out}"}
        logger.info("git snapshot [%s] %s → %s", ref, msg, sha[:12])
        return {"snapshotted": True, "hash": sha[:12], "rev": sha, "ref": ref,
                "message": msg, "clean": False}
    finally:
        try:
            os.unlink(idx)
        except OSError:
            pass


def _snapshot_branch(file_paths, msg, cwd) -> dict:
    """旧行为：add + commit 到当前分支（保留以兼容，非默认）。"""
    ok, err = _run_git(["add"] + [str(p) for p in file_paths], cwd)
    if not ok:
        return {"snapshotted": False, "error": f"git add failed: {err}"}
    ok, status = _run_git(["status", "--porcelain"], cwd)
    if ok and status.strip():
        staged = [
            ln for ln in status.splitlines()
            if ln.strip() and ln[:1] in _STAGED_PREFIXES and ln[1:2] in (" ", "M", "A")
        ]
    else:
        staged = []
    if not staged:
        return {"snapshotted": False, "error": "no changes", "clean": True}
    ok, out = _run_git([
        "-c", f"user.name={AUTHOR_NAME}", "-c", f"user.email={AUTHOR_EMAIL}",
        "commit", "-m", msg,
    ], cwd)
    if not ok:
        return {"snapshotted": False, "error": f"commit failed: {out}"}
    h = ""
    for line in out.split("\n"):
        if line.startswith("["):
            parts = line.split()
            if len(parts) >= 2:
                h = parts[1].rstrip("]")
    logger.info("git snapshot (branch) committed: %s → %s", msg, h or out[:50])
    return {"snapshotted": True, "hash": h, "rev": h, "ref": "HEAD",
            "message": msg, "clean": False}


def git_snapshot(file_paths, message="snapshot") -> dict:
    """对指定文件创建 git 快照（默认写入 refs/tea/snapshots）。

    Args:
        file_paths: 文件路径列表（相对/绝对均可）
        message: 快照描述（自动加 "snapshot: " 前缀，便于过滤）

    Returns:
        {"snapshotted": bool, "hash": str, "rev": str, "ref": str,
         "message": str, "error": str, "clean": bool}
        snapshotted=True 表示已创建快照；False 时 error 说明原因
        （非仓库 / 无变更 / 已关闭 / git 失败），不影响调用方主流程。
    """
    if not file_paths:
        return {"snapshotted": False, "error": "no files to snapshot"}
    if _mode() == "off":
        return {"snapshotted": False, "error": "snapshot disabled", "clean": True}
    cwd = os.getcwd()
    if not _is_git_repo(cwd):
        return {"snapshotted": False, "error": "not a git repo", "clean": True}
    msg = message if message.startswith("snapshot:") else f"snapshot: {message}"
    if _mode() == "branch":
        return _snapshot_branch(file_paths, msg, cwd)
    return _snapshot_side(file_paths, msg, cwd)


def maybe_snapshot(file_paths, message="snapshot") -> dict:
    """安全包装：任何异常都返回失败 dict，绝不抛出（修改工具内联调用用）。"""
    try:
        return git_snapshot(file_paths, message)
    except Exception as e:  # pragma: no cover
        logger.warning("git snapshot failed (isolated): %s", e)
        return {"snapshotted": False, "error": str(e)[:200]}
