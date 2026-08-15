"""Git 快照（修改工具自动"存盘"）回归测试。

背景: 修改工具（toolkit_edit/diff/save_file）修改成功后自动 git commit，
杜绝"改了没存盘"（会话中断导致已做修改丢失）。

覆盖:
- git_snapshot: 有变更时 add+commit（固定 author: tea_agent）
- git_snapshot: 无变更/非仓库时静默跳过（不产生空 commit）
- toolkit_edit 修改成功后自动快照（返回 git_snapshot hash）
- toolkit_edit preview 不落盘
- toolkit_save_file 写新文件后自动快照
"""

import os
import subprocess
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from tea_agent.toolkit._git_snapshot import git_snapshot, maybe_snapshot  # noqa: E402


def _run(cmd, cwd):
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, timeout=30)
    assert r.returncode == 0, f"cmd {cmd} failed: {r.stderr}"
    return r.stdout


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
    return tmp_path


def test_git_snapshot_commits_change(git_repo):
    """有变更时 add+commit，固定 author。"""
    (git_repo / "a.py").write_text("x = 2\n", encoding="utf-8")
    snap = git_snapshot(["a.py"], "edit a.py")
    assert snap["snapshotted"] is True
    assert snap["hash"]
    # 验证 author
    author = _run(["git", "log", "--format=%an <%ae>", "-1"], str(git_repo))
    assert author.strip() == "tea_agent <sunkwei@gmail.com>"


def test_git_snapshot_no_change_skips(git_repo):
    """无实际变更时不产生空 commit。"""
    snap = git_snapshot(["a.py"], "no-op")
    assert snap["snapshotted"] is False
    assert snap.get("clean") is True
    # 仍只有 init 一个 commit
    count = _run(["git", "rev-list", "--count", "HEAD"], str(git_repo))
    assert count.strip() == "1"


def test_git_snapshot_not_repo(tmp_path, monkeypatch):
    """非 git 目录静默跳过。"""
    monkeypatch.chdir(tmp_path)
    snap = git_snapshot(["x.py"], "test")
    assert snap["snapshotted"] is False
    assert "not a git repo" in snap.get("error", "")


def test_git_snapshot_only_target_files(git_repo):
    """只 add 目标文件，不触碰其他未提交改动。"""
    (git_repo / "a.py").write_text("x = 3\n", encoding="utf-8")
    (git_repo / "untracked.txt").write_text("dirty\n", encoding="utf-8")
    snap = git_snapshot(["a.py"], "edit a.py")
    assert snap["snapshotted"] is True
    # untracked.txt 仍未跟踪
    status = _run(["git", "status", "--porcelain"], str(git_repo))
    assert "untracked.txt" in status


def test_toolkit_edit_auto_snapshot(git_repo):
    """toolkit_edit 修改成功后自动快照。"""
    from tea_agent.toolkit.toolkit_edit import toolkit_edit

    r = toolkit_edit(
        file_path="a.py",
        action="replace_text",
        old_text="x = 1",
        new_text="x = 42",
    )
    assert r.get("ok") is True
    assert r.get("git_snapshot"), "期望自动快照 hash"
    count = _run(["git", "rev-list", "--count", "HEAD"], str(git_repo))
    assert count.strip() == "2"  # init + snapshot


def test_toolkit_edit_preview_no_snapshot(git_repo):
    """preview 模式不落盘、不快照。"""
    from tea_agent.toolkit.toolkit_edit import toolkit_edit

    r = toolkit_edit(
        file_path="a.py", action="replace_text",
        old_text="x = 1", new_text="x = 99", preview=True,
    )
    assert r.get("ok") is True
    assert not r.get("git_snapshot")
    count = _run(["git", "rev-list", "--count", "HEAD"], str(git_repo))
    assert count.strip() == "1"


def test_toolkit_save_file_auto_snapshot(git_repo):
    """toolkit_save_file 写新文件后自动快照（含未跟踪文件）。"""
    from tea_agent.toolkit.toolkit_save_file import toolkit_save_file

    r = toolkit_save_file(path="b.py", content="y = 2\n")
    assert r.get("status") == "ok"
    assert r.get("git_snapshot"), "期望自动快照 hash"
    count = _run(["git", "rev-list", "--count", "HEAD"], str(git_repo))
    assert count.strip() == "2"


def test_toolkit_diff_edit_auto_snapshot(git_repo):
    """toolkit_diff_edit 修改成功后自动快照。"""
    from tea_agent.toolkit.toolkit_diff_edit import toolkit_diff_edit

    r = toolkit_diff_edit(file_path="a.py", old_text="x = 1", new_text="x = 7")
    assert r.get("ok") is True
    assert r.get("git_snapshot"), "期望自动快照 hash"
    count = _run(["git", "rev-list", "--count", "HEAD"], str(git_repo))
    assert count.strip() == "2"


def test_maybe_snapshot_never_raises(tmp_path, monkeypatch):
    """maybe_snapshot 永不抛出（异常隔离）。"""
    monkeypatch.chdir(tmp_path)
    assert maybe_snapshot(["z.py"], "x")["snapshotted"] is False
