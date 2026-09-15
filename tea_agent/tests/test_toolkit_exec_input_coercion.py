"""复审回归：归一化层**不得破坏合法输入**。

教训：为容忍畸形参数而引入的「整行命令拆分」「值形态收敛」「timeout 回落」
很容易反过来弄坏本来就合法的调用 —— 且这类破坏常表现为 ok=True 却什么都没执行
（比直接报错更危险）。本文件把三类合法形态钉成断言。
"""
import importlib.util
import os
import shutil
import sys
import tempfile

import pytest

_TOOLKIT_EXEC_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "toolkit", "toolkit_exec.py",
)


@pytest.fixture(scope="module")
def tk_exec():
    spec = importlib.util.spec_from_file_location("_tk_exec_space_test", _TOOLKIT_EXEC_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def spaced_exe():
    """一个真实存在、路径含空格的可执行文件（复刻 'C:\\Program Files\\...' 场景）。"""
    workdir = tempfile.mkdtemp(prefix="tea space test ")
    exe = os.path.join(workdir, "my python.exe")
    shutil.copy2(sys.executable, exe)
    yield exe
    shutil.rmtree(workdir, ignore_errors=True)


class TestLegitPathsNotSplit:
    """含空格的合法路径绝不可被当作整行命令拆开。"""

    def test_spaced_existing_path_kept_intact(self, tk_exec, spaced_exe):
        app, extra = tk_exec._coerce_app(spaced_exe)
        assert app == spaced_exe, f"合法含空格路径被拆坏: {app!r} + {extra!r}"
        assert extra == []

    def test_spaced_path_forward_slashes_kept_intact(self, tk_exec, spaced_exe):
        """模型在 Windows 常写正斜杠，同样不得拆坏。"""
        fwd = spaced_exe.replace("\\", "/")
        app, extra = tk_exec._coerce_app(fwd)
        assert app == fwd, f"正斜杠含空格路径被拆坏: {app!r} + {extra!r}"
        assert extra == []

    def test_quoted_spaced_path_survives(self, tk_exec, spaced_exe):
        app, extra = tk_exec._coerce_app(f'"{spaced_exe}"')
        assert app == spaced_exe
        assert extra == []

    def test_execution_uses_the_whole_path(self, tk_exec, tmp_path):
        """端到端：路径含空格的真实可执行文件必须整体传给系统执行。

        用 .bat 而非复制 python.exe —— 后者会因找不到 pyvenv.cfg 而启动失败，
        那是测试构造的问题，不是归一化的问题。
        """
        if os.name != "nt":
            pytest.skip("Windows 专属：验证含空格路径的整体传参")
        bat_dir = tmp_path / "my tools dir with space"
        bat_dir.mkdir()
        bat = bat_dir / "my tool.bat"
        bat.write_text("@echo off\r\necho SPACED-OK %*\r\n", encoding="ascii")
        r = tk_exec.toolkit_exec(app=str(bat), args=["x"], timeout=60)
        assert r["ok"], r
        assert "SPACED-OK" in r["stdout"], r["stdout"]

    def test_nonexistent_spaced_path_not_fabricated(self, tk_exec):
        """不存在的带空格路径：保留整串交给系统诚实报错，不得凭空造出可执行目标。"""
        app, extra = tk_exec._coerce_app("C:/Program Files/Nope Nox/7z.exe")
        assert app == "C:/Program Files/Nope Nox/7z.exe"
        assert extra == []

    def test_real_line_command_still_splits(self, tk_exec):
        """反例：真正的整行命令仍要拆（回归保护，别把容错改成失效）。"""
        app, extra = tk_exec._coerce_app("echo hello world")
        assert app == "echo"
        assert extra == ["hello", "world"]


class TestTimeoutSemanticsPreserved:
    """timeout 回落语义必须与改造前 effective = timeout or 120 一致。"""

    @pytest.mark.parametrize("value", [0, -5, None, ""])
    def test_unset_like_values_keep_legacy_120(self, tk_exec, value):
        """未指定/非正值 → 120（沿用旧语义）；回落成 30 会误杀长命令。"""
        assert tk_exec._coerce_timeout(value) == 120, f"{value!r} 改变了原有超时语义"

    @pytest.mark.parametrize("value", ["abc", True, False, [], {}])
    def test_garbage_values_fall_back_to_default(self, tk_exec, value):
        assert tk_exec._coerce_timeout(value) == 30

    @pytest.mark.parametrize("value,expected", [(30, 30), ("60", 60), (12.7, 12)])
    def test_valid_values_pass_through(self, tk_exec, value, expected):
        assert tk_exec._coerce_timeout(value) == expected

    def test_absurd_value_capped(self, tk_exec):
        assert tk_exec._coerce_timeout(10 ** 9) == 86400

    def test_explicit_timeout_reaches_subprocess(self, tk_exec):
        """显式 timeout 不得被归一化层吞掉。"""
        r = tk_exec.toolkit_exec(app=sys.executable,
                                 args=["-c", "import time; time.sleep(30)"], timeout=1)
        assert r["timed_out"], f"显式 timeout=1 未生效: {r}"


class TestPositionPreserved:
    """形态收敛不得让参数整体左移（会造出另一条命令）。"""

    def test_app_list_keeps_positions(self, tk_exec):
        r = tk_exec.toolkit_exec(app=["echo", "a", "b"], timeout=10)
        assert r["ok"] and r["stdout"].strip() == "a b", r

    def test_nested_container_not_turned_into_program_name(self, tk_exec):
        """[[1,2]] 不可被 json.dumps 成 "[1, 2]" 后当成程序去执行。"""
        r = tk_exec.toolkit_exec(app=[[1, 2]], args=[], timeout=10)
        assert r["ok"] is False
        assert "参数错误" in r["error"], r
        assert "[1," not in r.get("stderr", ""), "嵌套容器被当成程序名执行了"

    def test_deeply_wrapped_args_no_recursion_crash(self, tk_exec):
        """args 里套 args 的畸形输入不得 RecursionError（必须转成友好错误）。"""
        blob = {"app": "echo"}
        for _ in range(200):
            blob = {"args": blob}
        try:
            r = tk_exec.toolkit_exec(app="", args=blob, timeout=10)
        except RecursionError as e:  # pragma: no cover
            pytest.fail(f"归一化递归爆栈: {e}")
        assert r["ok"] is False


class TestBatchErrorNamesRealKeys:
    """batch 报错必须回报模型实际写的键名。"""

    def test_misspelled_keys_surfaced(self, tk_exec):
        r = tk_exec.toolkit_exec(
            action="batch",
            commands=[{"ap": "echo", "args": ["x"], "timout": 1},
                      {"app": "echo", "args": ["survivor"]}],
            timeout=10,
        )
        bad = [x for x in r["results"] if x and x.get("error")]
        assert bad, r
        msg = bad[0]["stderr"]
        assert "ap" in msg and "timout" in msg, f"未回报模型实际写的键名: {msg}"
        # 失败隔离：另一条仍须成功
        assert any(x and "survivor" in (x.get("stdout") or "") for x in r["results"]), r
