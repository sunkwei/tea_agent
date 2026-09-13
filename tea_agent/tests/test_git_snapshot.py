"""Git 快照（修改工具自动"存盘"）回归测试。

背景: 修改工具（toolkit_edit/diff/file）修改成功后自动留 git 快照，
杜绝"改了没存盘"（会话中断导致已做修改丢失）。

落点已从「提交到当前分支」改为「写入独立 ref refs/tea/snapshots」——
因为提交到分支会把 git log 淹没（实测 1028 个提交里 153 个是纯操作噪音）。
本文件重点验证这次改动**没有削弱**任何保证:

- 快照确实被创建（且带固定 author: tea_agent）
- **当前分支 HEAD 完全不动**、工作区/暂存区不受影响
- 无变更 / 非仓库 / 关闭时静默跳过
- 快照可用 `git checkout <rev> -- <file>` 回滚
- toolkit_edit / toolkit_file 修改成功后自动快照
"""

import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from tea_agent.toolkit._git_snapshot import git_snapshot, maybe_snapshot  # noqa: E402

SNAP_REF = "refs/tea/snapshots"


def _run(cmd, cwd):
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, timeout=30)
    assert r.returncode == 0, f"cmd {cmd} failed: {r.stderr}"
    return r.stdout


def _try_run(cmd, cwd):
    """不要求成功的 git 命令（用于探询 ref 是否存在）。"""
    return subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, timeout=30)


def _head_sha(cwd):
    return _run(["git", "rev-parse", "HEAD"], cwd).strip()


def _snap_sha(cwd):
    r = _try_run(["git", "rev-parse", "--verify", SNAP_REF], cwd)
    return r.stdout.strip() if r.returncode == 0 else None


@pytest.fixture
def git_repo(tmp_path, monkeypatch):
    """临时 git 仓库（含初始 commit 的文件 a.py），并 chdir 到仓库根。"""
    _run(["git", "init", "-q"], str(tmp_path))
    _run(["git", "config", "user.email", "test@example.com"], str(tmp_path))
    _run(["git", "config", "user.name", "test"], str(tmp_path))
    a = tmp_path / "a.py"
    a.write_text("x = 1\n", encoding="utf-8")
    _run(["git", "add", "a.py"], str(tmp_path))
    _run(["git", "commit", "-qm", "init"], str(tmp_path))
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("TEA_GIT_SNAPSHOT_MODE", raising=False)
    monkeypatch.delenv("TEA_SNAPSHOT_REF", raising=False)
    return tmp_path


# ── 核心：快照落在独立 ref，分支不受影响 ──────────────────────────


def test_snapshot_goes_to_side_ref_not_branch(git_repo):
    """快照写入 refs/tea/snapshots，**当前分支 HEAD 不变**、提交数不增。"""
    before = _head_sha(git_repo)
    (git_repo / "a.py").write_text("x = 2\n", encoding="utf-8")
    snap = git_snapshot(["a.py"], "edit a.py")

    assert snap["snapshotted"] is True
    assert snap["ref"] == SNAP_REF
    assert snap["hash"] and snap["rev"]
    # 分支完全没动
    assert _head_sha(git_repo) == before
    assert _run(["git", "rev-list", "--count", "HEAD"], str(git_repo)).strip() == "1"
    # 快照 ref 已建立
    assert _snap_sha(git_repo) == snap["rev"]
    # 固定 author
    author = _run(["git", "log", "--format=%an <%ae>", "-1", SNAP_REF], str(git_repo))
    assert author.strip() == "tea_agent <sunkwei@gmail.com>"


def test_snapshot_leaves_worktree_and_index_untouched(git_repo):
    """快照后改动仍是「未暂存的修改」——不 add 真实文件，不影响用户提交流程。"""
    (git_repo / "a.py").write_text("x = 2\n", encoding="utf-8")
    git_snapshot(["a.py"], "edit a.py")
    status = _run(["git", "status", "--porcelain"], str(git_repo))
    # 第二列 M = 工作区已改、暂存区干净
    assert " M a.py" in status, f"暂存区被污染: {status!r}"


def test_snapshot_restorable_from_side_ref(git_repo):
    """回滚能力保留：可用快照 rev 恢复文件内容。"""
    (git_repo / "a.py").write_text("x = 2\n", encoding="utf-8")
    snap = git_snapshot(["a.py"], "edit a.py")
    # 快照点内容
    got = _run(["git", "show", f"{snap['rev']}:a.py"], str(git_repo))
    assert got.strip() == "x = 2"
    # 再改坏它，然后回滚
    (git_repo / "a.py").write_text("x = BROKEN\n", encoding="utf-8")
    _run(["git", "checkout", snap["rev"], "--", "a.py"], str(git_repo))
    assert (git_repo / "a.py").read_text(encoding="utf-8").strip() == "x = 2"


def test_snapshot_chains_on_side_ref(git_repo):
    """连续快照在同一 ref 上成链（parent = 上一次快照）。"""
    (git_repo / "a.py").write_text("x = 2\n", encoding="utf-8")
    s1 = git_snapshot(["a.py"], "one")
    (git_repo / "a.py").write_text("x = 3\n", encoding="utf-8")
    s2 = git_snapshot(["a.py"], "two")
    assert _snap_sha(git_repo) == s2["rev"]
    parent = _run(["git", "rev-parse", f"{s2['rev']}^"], str(git_repo)).strip()
    assert parent == s1["rev"]


def test_snapshot_only_target_files_in_diff(git_repo):
    """目标文件之外的未提交改动不会进入快照。

    基准用 HEAD 而非 ``rev^`` —— 首个快照是链的起点（无父提交，
    这样 ``git log refs/tea/snapshots`` 只显示快照、不掺分支历史）。
    """
    (git_repo / "a.py").write_text("x = 3\n", encoding="utf-8")
    (git_repo / "other.py").write_text("dirty = True\n", encoding="utf-8")
    snap = git_snapshot(["a.py"], "edit a.py")
    changed = _run(["git", "diff", "--name-only", "HEAD", snap["rev"]],
                   str(git_repo)).split()
    assert changed == ["a.py"], f"快照混入了非目标文件: {changed}"
    # other.py 仍未跟踪
    assert "other.py" in _run(["git", "status", "--porcelain"], str(git_repo))


# ── 跳过与开关 ────────────────────────────────────────────


def test_snapshot_no_change_skips(git_repo):
    """无实际变更时不产生快照。"""
    snap = git_snapshot(["a.py"], "no-op")
    assert snap["snapshotted"] is False
    assert snap.get("clean") is True
    assert _snap_sha(git_repo) is None


def test_snapshot_not_repo(tmp_path, monkeypatch):
    """非 git 目录静默跳过。"""
    monkeypatch.chdir(tmp_path)
    snap = git_snapshot(["x.py"], "test")
    assert snap["snapshotted"] is False
    assert "not a git repo" in snap.get("error", "")


def test_snapshot_mode_off(git_repo, monkeypatch):
    """TEA_GIT_SNAPSHOT_MODE=off 时完全跳过。"""
    monkeypatch.setenv("TEA_GIT_SNAPSHOT_MODE", "off")
    (git_repo / "a.py").write_text("x = 2\n", encoding="utf-8")
    snap = git_snapshot(["a.py"], "edit a.py")
    assert snap["snapshotted"] is False
    assert _snap_sha(git_repo) is None


def test_snapshot_mode_branch_legacy(git_repo, monkeypatch):
    """TEA_GIT_SNAPSHOT_MODE=branch 保留旧行为（提交到当前分支）。"""
    monkeypatch.setenv("TEA_GIT_SNAPSHOT_MODE", "branch")
    (git_repo / "a.py").write_text("x = 2\n", encoding="utf-8")
    snap = git_snapshot(["a.py"], "edit a.py")
    assert snap["snapshotted"] is True
    assert _run(["git", "rev-list", "--count", "HEAD"], str(git_repo)).strip() == "2"
    assert _snap_sha(git_repo) is None  # 未使用 side ref


def test_snapshot_custom_ref(git_repo, monkeypatch):
    """TEA_SNAPSHOT_REF 可自定义落点。"""
    monkeypatch.setenv("TEA_SNAPSHOT_REF", "refs/tea/alt")
    (git_repo / "a.py").write_text("x = 2\n", encoding="utf-8")
    snap = git_snapshot(["a.py"], "edit a.py")
    assert snap["ref"] == "refs/tea/alt"
    assert _run(["git", "rev-parse", "--verify", "refs/tea/alt"], str(git_repo)).strip()


# ── 修改工具自动快照 ──────────────────────────────────────


def test_toolkit_edit_auto_snapshot(git_repo):
    """toolkit_edit 修改成功后自动快照，且分支不受影响。"""
    from tea_agent.toolkit.toolkit_edit import toolkit_edit

    before = _head_sha(git_repo)
    r = toolkit_edit(file_path="a.py", action="replace_text",
                     old_text="x = 1", new_text="x = 42")
    assert r.get("ok") is True
    assert r.get("git_snapshot"), "期望自动快照 hash"
    assert _head_sha(git_repo) == before, "快照不应改动当前分支"
    assert _snap_sha(git_repo), "期望建立快照 ref"


def test_toolkit_edit_preview_no_snapshot(git_repo):
    """preview 模式不落盘、不快照。"""
    from tea_agent.toolkit.toolkit_edit import toolkit_edit

    r = toolkit_edit(file_path="a.py", action="replace_text",
                     old_text="x = 1", new_text="x = 99", preview=True)
    assert r.get("ok") is True
    assert not r.get("git_snapshot")
    assert _snap_sha(git_repo) is None


def test_toolkit_file_write_auto_snapshot(git_repo):
    """toolkit_file 写新文件后自动快照（含未跟踪文件）。"""
    from tea_agent.toolkit.toolkit_file import toolkit_file

    before = _head_sha(git_repo)
    r = toolkit_file(action="write", filename="b.py", content="y = 2\n")
    assert r == 0  # write 成功返回 0
    assert _head_sha(git_repo) == before
    assert _snap_sha(git_repo)


def test_toolkit_edit_replace_text_auto_snapshot(git_repo):
    """toolkit_edit replace_text 修改成功后自动快照（原 toolkit_diff_edit 能力）。"""
    from tea_agent.toolkit.toolkit_edit import toolkit_edit

    r = toolkit_edit(file_path="a.py", action="replace_text",
                     old_text="x = 1", new_text="x = 7", return_diff=True)
    assert r.get("ok") is True
    assert r.get("git_snapshot"), "期望自动快照 hash"
    assert r.get("diff"), "return_diff=True 应返回 unified diff"
    assert _run(["git", "rev-list", "--count", "HEAD"], str(git_repo)).strip() == "1"


def test_maybe_snapshot_never_raises(tmp_path, monkeypatch):
    """maybe_snapshot 永不抛出（异常隔离）。"""
    monkeypatch.chdir(tmp_path)
    assert maybe_snapshot(["z.py"], "x")["snapshotted"] is False
