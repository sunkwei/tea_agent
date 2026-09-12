"""安全回归：toolkit_file 路径逃逸防护 + toolkit_scheduler 无 shell 执行。

覆盖两轮真实修复（均由 EvolutionBench 难度任务集驱动发现）：
- toolkit_file 路径逃逸（AGENTS.md「路径遍历：禁止 ../ 逃逸」）
- toolkit_scheduler shell=True 注入面（改用 argv + shell=False）
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


# ── toolkit_file 路径逃逸防护 ──────────────────────────────────────

def test_resolve_path_rejects_relative_escape():
    """相对路径 ../ 逃逸必须被拒绝。"""
    from tea_agent.toolkit.toolkit_file import _resolve_path

    ok, msg = _resolve_path("../../etc/passwd")
    assert ok is False, "相对 ../ 逃逸未被拒绝"
    assert "逃逸" in msg or "拒绝" in msg, msg


def test_resolve_path_allows_in_project_relative():
    """项目内相对路径应放行（解析为 cwd 下绝对路径）。"""
    from tea_agent.toolkit.toolkit_file import _resolve_path

    ok, resolved = _resolve_path("docs/probe.md")
    assert ok is True, resolved


def test_resolve_path_allows_explicit_absolute():
    """显式绝对/有根路径放行。

    含 Windows 特有形态：'/tmp/x' 属「有根无盘符」，Path.is_absolute() 为 False，
    须由 p.root 兜底放行（否则跨平台行为不一致）。
    """
    from tea_agent.toolkit.toolkit_file import _resolve_path

    assert _resolve_path("/tmp/abs_probe.txt")[0] is True


def test_resolve_path_rejects_empty():
    from tea_agent.toolkit.toolkit_file import _resolve_path

    assert _resolve_path("")[0] is False
    assert _resolve_path("   ")[0] is False


def test_toolkit_file_write_blocks_escape():
    """真实调用：逃逸写入须返回错误，且不得创建文件。"""
    from tea_agent.toolkit.toolkit_file import toolkit_file

    target = ROOT.parent.parent / "__escape_probe.txt"
    if target.exists():
        target.unlink()
    out = toolkit_file(action="write", filename="../../__escape_probe.txt", content="x")
    assert isinstance(out, str) and "Error" in out, out
    assert not target.exists(), "逃逸文件被创建"


def test_env_override_allows_outside(monkeypatch):
    """TEA_FILE_ALLOW_OUTSIDE=1 可放宽（跨目录操作场景）。"""
    from tea_agent.toolkit.toolkit_file import _resolve_path

    monkeypatch.setenv("TEA_FILE_ALLOW_OUTSIDE", "1")
    assert _resolve_path("../../etc/passwd")[0] is True


# ── toolkit_scheduler：命令拆分（不经 shell） ───────────────────────

def test_split_command_basic():
    from tea_agent.toolkit.toolkit_scheduler import _split_command

    assert _split_command("python build.py --fast") == ["python", "build.py", "--fast"]


def test_split_command_quoted_path_with_space():
    """带空格的引号路径须保持为单个参数（跨平台）。"""
    from tea_agent.toolkit.toolkit_scheduler import _split_command

    got = _split_command('python "C:/path with space/a.py"')
    assert got == ["python", "C:/path with space/a.py"], got


def test_split_command_raises_on_unbalanced_quote():
    from tea_agent.toolkit.toolkit_scheduler import _split_command

    with pytest.raises(ValueError):
        _split_command('python "unclosed')


def test_no_real_shell_true_in_toolkit_layer():
    """AST 级：工具层不得存在真实 shell=True（注释/docstring 提及不算）。"""
    from tea_agent.evaluation.evo_bench import _bench_metrics

    m = _bench_metrics(str(ROOT))
    assert m.get("shell_true_toolkit") == 0, "工具层存在 shell=True 注入面"
