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


# ── SQL 安全助手（_sql_safety）────────────────────────────────────
def test_safe_ident_accepts_and_rejects():
    from tea_agent.store._sql_safety import safe_ident

    assert safe_ident("content") == "content"
    assert safe_ident("col", {"col", "other"}) == "col"
    for bad in ("bad; DROP TABLE x", "1col", "", "a b", "a--b", "t.col"):
        with pytest.raises(ValueError):
            safe_ident(bad)
    with pytest.raises(ValueError):
        safe_ident("content", {"other"})


def test_safe_placeholders_count():
    from tea_agent.store._sql_safety import safe_placeholders

    assert safe_placeholders(0) == ""
    assert safe_placeholders(1) == "?"
    assert safe_placeholders(3) == "?,?,?"
    with pytest.raises(ValueError):
        safe_placeholders(-1)


def test_safe_set_clause_columns_and_raw():
    from tea_agent.store._sql_safety import safe_set_clause

    got = safe_set_clause(["content", "updated_at"],
                          raw={"updated_at": "CURRENT_TIMESTAMP"})
    assert got == "content = ?, updated_at=CURRENT_TIMESTAMP", got
    with pytest.raises(ValueError):
        safe_set_clause(["content; DROP TABLE x"])


def test_safe_where_clause_operators_and_literals():
    """关键回归：字面量值（is_active = 1）必须放行，否则 search_memories 会崩。"""
    from tea_agent.store._sql_safety import safe_where_clause

    assert safe_where_clause(["is_active = 1"]) == "is_active = 1"
    assert safe_where_clause([]) == "1=1"
    assert safe_where_clause(["a = ?", "b >= ?"]) == "a = ? AND b >= ?"
    got = safe_where_clause(["c.stamp >= ?", "c.stamp <= ?"], joiner=" OR ", wrap=True)
    assert got == "(c.stamp >= ?) OR (c.stamp <= ?)", got
    assert safe_where_clause(["content LIKE ?"]) == "content LIKE ?"
    for bad in ("1=1 OR 1=1", "x = ?; DROP TABLE t", "x = ? -- comment", "UNION SELECT",
                "is_active = 1 AND priority = 0"):
        with pytest.raises(ValueError):
            safe_where_clause([bad])


def test_safe_ddl_and_fragment():
    from tea_agent.store._sql_safety import safe_ddl, safe_sql_fragment

    assert safe_ddl("TEXT DEFAULT ''") == "TEXT DEFAULT ''"
    assert safe_ddl("INTEGER NOT NULL DEFAULT 0")
    assert safe_sql_fragment("CAST(col AS TEXT) as col")
    assert safe_sql_fragment(", ".join(["a=?", "b=?"]))
    for bad in ("TEXT); DROP TABLE x --", "TEXT DEFAULT ''; --"):
        with pytest.raises(ValueError):
            safe_ddl(bad)
    for bad in ("a; DROP TABLE x", "a/*c*/", "a' OR '1'='1"):
        with pytest.raises(ValueError):
            safe_sql_fragment(bad)


def test_no_unsafe_sql_interpolation_in_store():
    """AST 语义级：SQL 插值不得来自未校验来源（与基准同一判据）。"""
    import ast

    from tea_agent.evaluation import evo_bench as eb

    offenders = []
    for rel, src in eb._pyfiles(str(ROOT), subdir="tea_agent/store"):
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        for fn in [n for n in ast.walk(tree)
                   if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
            nodes = list(eb._own_nodes(fn))
            safe = eb._safe_sql_vars(nodes)
            for node in nodes:
                if not isinstance(node, ast.JoinedStr):
                    continue
                first = next((v for v in node.values
                              if isinstance(v, ast.Constant) and isinstance(v.value, str)), None)
                if not first or not eb._SQL_SHAPE_RE.match(str(first.value)):
                    continue
                for v in node.values:
                    if (isinstance(v, ast.FormattedValue)
                            and not eb._is_safe_sql_expr(v.value, safe)):
                        offenders.append(f"{rel}:{node.lineno}")
    assert offenders == [], f"未校验 SQL 插值: {offenders}"


def test_exec_does_not_hang_on_stdin_reading_command():
    """toolkit_exec 必须给子进程 DEVNULL 而非继承 stdin。

    交互式命令（ssh/git/sudo 的密码对话）会阻塞等输入；若继承 stdin，命令会
    一直等到空闲超时（单条 timeout、硬上限 timeout×4）才被杀，表现为「无输出假死」。
    DEVNULL 使其立即 EOF 快速失败。此处用 reading-stdin 的 python 子进程验证：
    必须在远小于 timeout 的墙钟时间内返回，而不是拖到超时。
    """
    import sys as _sys
    import time as _t

    from tea_agent.toolkit.toolkit_exec import _run_single_with_monitor

    t0 = _t.time()
    res = _run_single_with_monitor(
        _sys.executable,
        ["-c", "import sys; sys.stdin.read() or print('reached-eof')"],
        timeout=30,
    )
    elapsed = _t.time() - t0
    assert elapsed < 15, f"命令未在 stdin EOF 后立即结束，耗时 {elapsed:.1f}s（疑似继承 stdin 阻塞）"
    assert not res["timed_out"], f"命令被超时终止（应因 EOF 立即退出）: {res}"
    assert res["returncode"] == 0, f"退出码异常: {res}"


def test_no_silent_exception_sinks_in_security_modules():
    """安全模块（审批/审计/权限/钩子）不得静默吞异常。

    这些模块的静默失败意味着闸门失效而无人知晓；本测试要求其静默吞异常为 0
    （即失败至少记 warning，使问题在常规日志级别可见）。与 toolkit_exec 的 env
    清洗、audit 链同属「失败必须可诊断」的安全底座。
    """
    from tea_agent.evaluation.evo_bench import _bench_metrics

    n = _bench_metrics(str(ROOT))["except_pass_security"]
    assert n == 0, f"安全模块存在 {n} 处静默吞异常（应至少记 warning）"


# ── 提权能力移除（Agent 不得获取管理员权限）──────────────────────

def test_sudo_gui_tool_removed():
    """toolkit_sudo_gui 必须彻底移除：提权一律交给用户手动执行。"""
    import importlib.util

    assert not (ROOT / "tea_agent" / "toolkit" / "toolkit_sudo_gui.py").exists(), "toolkit_sudo_gui.py 仍存在"
    assert importlib.util.find_spec("tea_agent.toolkit.toolkit_sudo_gui") is None, "toolkit_sudo_gui 仍可被导入"


def test_no_gui_elevation_helper_in_exec():
    """toolkit_exec 不得保留任何 GUI/pkexec 提权实现（只允许在拒绝清单里出现这些名字）。"""
    from tea_agent.toolkit import toolkit_exec as te

    assert not hasattr(te, "_sudo_with_gui"), "toolkit_exec 仍保留 _sudo_with_gui 提权实现"
    src = (ROOT / "tea_agent" / "toolkit" / "toolkit_exec.py").read_text(encoding="utf-8")
    # GUI 密码框启动器：应彻底消失
    for launcher in ("kdialog", "zenity"):
        assert launcher not in src, f"toolkit_exec 仍引用 GUI 提权启动器 {launcher}"
    # 提权程序的**调用形态**：argv 字面量 / which() 探测都不允许
    for invocation in (
        '["pkexec"',
        "['pkexec'",
        '["sudo", "-S"',
        "['sudo', '-S'",
        'shutil.which("pkexec")',
        "shutil.which('pkexec')",
    ):
        assert invocation not in src, f"toolkit_exec 仍在调用提权程序: {invocation}"


def test_approval_critical_tools_no_sudo_gui():
    """审批分级里不得再出现已删除的提权工具。"""
    from tea_agent.tool_approval import _CRITICAL_TOOLS

    assert "toolkit_sudo_gui" not in _CRITICAL_TOOLS, _CRITICAL_TOOLS
    assert "toolkit_self_evolve" in _CRITICAL_TOOLS, "自身进化仍应保持 critical"


def test_harness_schema_declares_no_privilege_elevation():
    """对外能力声明不得再声称支持提权。"""
    from tea_agent.toolkit.toolkit_harness_schema import _get_capabilities, _get_security

    assert _get_capabilities()["permission_control"].get("privilege_elevation") is False
    assert "sudo_elevation" not in _get_security()
    assert not any("sudo_elevation" in str(v) for v in _get_security().values())


def test_scheduler_cannot_smuggle_elevation():
    """定时任务是另一条执行路径，必须同样拒绝提权。

    否则 Agent 可以"建一个 sudo 定时任务"变相拿到管理员权限；
    执行期拦截同时覆盖数据库里历史遗留的提权任务。
    """
    from tea_agent.toolkit.toolkit_scheduler import (
        _elevation_refusal_for_command,
        _task_elevation_guard,
    )

    # 执行期（argv）
    guarded = _task_elevation_guard(["sudo", "ls"])
    assert guarded and guarded[0] == 126, guarded
    assert "手动执行" in guarded[1]
    assert _task_elevation_guard(["echo", "hi"]) is None
    assert _task_elevation_guard([]) is None

    # 创建/更新期（命令字符串）
    assert _elevation_refusal_for_command("sudo apt install nginx") is not None
    assert _elevation_refusal_for_command("echo x; sudo rm -rf /") is not None
    assert _elevation_refusal_for_command("python3 /opt/backup.py") is None


def test_scheduler_execute_path_wires_the_guard():
    """结构性回归：_execute_task 必须在 subprocess 之前调用提权守卫。"""
    src = (ROOT / "tea_agent" / "toolkit" / "toolkit_scheduler.py").read_text(encoding="utf-8")
    assert "_task_elevation_guard(argv)" in src, "定时任务执行路径未接提权守卫"
    guard_at = src.index("_task_elevation_guard(argv)")
    run_at = src.index("result = subprocess.run(")
    assert guard_at < run_at, "提权守卫必须位于 subprocess.run 之前"
