"""toolkit_exec 环境变量清洗（Scrubbed Env）回归测试。

参考 DeepSeek Harness 防御模式：
"Spawned commands get a scrubbed env (drop *KEY*/*SECRET*/*TOKEN*/*PASSWORD*) so
harness credentials cannot leak into output, env, or spill files."

覆盖：
- _build_scrubbed_env() 单元测试：敏感变量被剔除、普通变量保留
- 集成测试：subprocess 子进程看不到敏感环境变量
"""

import importlib.util
import os
import sys

import pytest

_TOOLKIT_EXEC_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "toolkit", "toolkit_exec.py",
)

_SENSITIVE_KEYWORDS = ("KEY", "SECRET", "TOKEN", "PASSWORD", "PASSWD", "CREDENTIAL", "AUTH")


@pytest.fixture(scope="module")
def tk_exec():
    """加载 toolkit_exec 模块（独立加载，不依赖全局注册）。"""
    spec = importlib.util.spec_from_file_location("_tk_exec_scrub_test", _TOOLKIT_EXEC_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestScrubbedEnvUnit:
    """_build_scrubbed_env 纯函数单元测试。"""

    def test_sensitive_vars_removed(self, tk_exec, monkeypatch):
        monkeypatch.setenv("TEST_API_KEY", "secret-abc")
        monkeypatch.setenv("MY_PASSWORD", "pwd-xyz")
        monkeypatch.setenv("DB_CREDENTIAL", "root:pass")
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_fake")
        monkeypatch.setenv("AUTH_TOKEN", "auth123")
        scrubbed = tk_exec._build_scrubbed_env()
        assert "TEST_API_KEY" not in scrubbed
        assert "MY_PASSWORD" not in scrubbed
        assert "DB_CREDENTIAL" not in scrubbed
        assert "GITHUB_TOKEN" not in scrubbed
        assert "AUTH_TOKEN" not in scrubbed

    def test_normal_vars_kept(self, tk_exec, monkeypatch):
        monkeypatch.setenv("SAFE_VAR", "hello")
        monkeypatch.setenv("PATH", os.environ.get("PATH", "/usr/bin"))
        scrubbed = tk_exec._build_scrubbed_env()
        assert "SAFE_VAR" in scrubbed
        assert "PATH" in scrubbed

    def test_case_insensitive(self, tk_exec, monkeypatch):
        """变量名大小写不敏感匹配（Windows 环境变量名不区分大小写）。"""
        monkeypatch.setenv("deepseek_api_key", "sk-fake")
        monkeypatch.setenv("My_Token_Value", "abc")
        scrubbed = tk_exec._build_scrubbed_env()
        for key in ("deepseek_api_key", "My_Token_Value"):
            assert key not in scrubbed


class TestScrubbedEnvIntegration:
    """端到端验证：真实子进程看不到敏感变量。"""

    def test_subprocess_has_no_secrets(self, tk_exec, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-fake-secret-123456")
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_fake_token_xyz")
        probe = (
            "import os; "
            "ks=[k for k in os.environ if any(x in k.upper() for x in "
            "('KEY','TOKEN','SECRET','PASSWORD','CREDENTIAL','AUTH'))]; "
            "print('VISIBLE=' + repr(ks))"
        )
        result = tk_exec.toolkit_exec(app=sys.executable, args=["-c", probe], timeout=15)
        assert result["ok"], f"命令执行失败: {result}"
        assert "VISIBLE=[]" in result["stdout"], f"敏感变量泄露进子进程: {result['stdout']}"

    def test_batch_mode_still_works(self, tk_exec):
        """batch 模式接入清洗后仍正常执行。"""
        result = tk_exec.toolkit_exec(
            action="batch",
            commands=[
                {"app": sys.executable, "args": ["-c", "print(1+1)"]},
                {"app": sys.executable, "args": ["-c", "print(2+2)"]},
            ],
            timeout=10,
        )
        assert result["ok"]
        assert result["success_rate"] == "2/2"
        outputs = [r["stdout"].strip() for r in result["results"]]
        assert outputs == ["2", "4"]

    def test_normal_command_works(self, tk_exec):
        """普通命令执行不受清洗影响。"""
        result = tk_exec.toolkit_exec(app="echo", args=["hello-scrubbed-env"], timeout=10)
        assert result["ok"]
        assert result["stdout"].strip() == "hello-scrubbed-env"


class TestArgTypeNormalization:
    """入参类型归一化：小模型常把 app 写成数组、args 写成字符串。

    回归：app=["bash"] 曾导致 "'list' object has no attribute 'lower'"
    这种无从诊断的 AttributeError（工具整体失败，模型拿到无意义报错）。
    """

    def test_app_as_list_coerced(self, tk_exec):
        """app 传单元素数组时取首个字符串，不得抛 AttributeError。"""
        result = tk_exec.toolkit_exec(app=["echo"], args=["coerced"], timeout=10)
        assert result["ok"], f"app 数组未归一化: {result}"
        assert result["stdout"].strip() == "coerced"

    def test_args_as_string_wrapped(self, tk_exec):
        """args 传字符串时按单参数包装，不得被逐字符拆开。"""
        result = tk_exec.toolkit_exec(app="echo", args="wrapped-arg", timeout=10)
        assert result["ok"], f"args 字符串未归一化: {result}"
        assert result["stdout"].strip() == "wrapped-arg"

    def test_both_malformed_coerced(self, tk_exec):
        """app 数组 + args 字符串同时出现也要能跑。"""
        result = tk_exec.toolkit_exec(app=["echo"], args="both-bad", timeout=10)
        assert result["ok"], f"混合畸形参数未归一化: {result}"
        assert result["stdout"].strip() == "both-bad"

    def test_uncoercible_app_returns_clear_error(self, tk_exec):
        """无法归一化的 app（嵌套数组无字符串元素）应返回明确错误而非异常。"""
        result = tk_exec.toolkit_exec(app=[[1, 2]], args=[], timeout=10)
        assert result["ok"] is False
        assert "参数错误" in result.get("error", "")

    def test_uncoercible_args_returns_clear_error(self, tk_exec):
        """args 传入非法类型（dict）应返回明确错误而非异常。"""
        result = tk_exec.toolkit_exec(app="echo", args={"a": 1}, timeout=10)
        assert result["ok"] is False
        assert "参数错误" in result.get("error", "")

    def test_batch_malformed_entries_coerced(self, tk_exec):
        """batch 模式下单个 command 的畸形 app/args 也要归一化。"""
        result = tk_exec.toolkit_exec(
            action="batch",
            commands=[
                {"app": ["echo"], "args": "batch-coerced"},
                {"app": "echo", "args": ["batch-normal"]},
            ],
            timeout=10,
        )
        assert result["ok"], f"batch 畸形参数未归一化: {result}"
        outputs = sorted(r["stdout"].strip() for r in result["results"])
        assert outputs == ["batch-coerced", "batch-normal"]


class TestPrivilegeElevationRefused:
    """提权一律拒绝：Agent 不允许获取管理员/root 权限。

    产品决策：需要管理员权限的操作必须由用户手动执行。toolkit_sudo_gui 已删除，
    toolkit_exec 也不再弹密码框 / 调 pkexec / 直接跑 sudo（免密 NOPASSWD 下会真的提权）。
    """

    @pytest.mark.parametrize(
        "app,args",
        [
            ("sudo", ["ls"]),
            ("/usr/bin/sudo", ["-u", "root", "id"]),
            ("su", ["-", "root"]),
            ("pkexec", ["id"]),
            ("doas", ["id"]),
            ("runas", ["/user:admin", "cmd"]),
            ("gsudo", ["id"]),
        ],
    )
    def test_elevation_binaries_refused(self, tk_exec, app, args):
        r = tk_exec.toolkit_exec(app=app, args=args, timeout=10)
        assert r["ok"] is False, f"{app} 未被拒绝: {r}"
        assert r["returncode"] == 126, r
        assert "手动执行" in r["error"], r["error"]

    def test_shell_smuggling_refused(self, tk_exec):
        """拼接命令里的提权同样要拦（不能只看首个 token）。"""
        r = tk_exec.toolkit_exec(app="bash", args=["-c", "echo x; sudo rm -rf /tmp/nope"], timeout=10)
        assert r["ok"] is False and r["returncode"] == 126, r
        assert "手动执行" in r["error"]

    def test_shell_pipe_and_env_prefix_refused(self, tk_exec):
        for inner in ("echo pw | sudo -S ls", "env FOO=1 sudo ls", "timeout 5 sudo ls"):
            r = tk_exec.toolkit_exec(app="sh", args=["-c", inner], timeout=10)
            assert r["ok"] is False, f"{inner!r} 未被拒绝: {r}"

    def test_windows_uac_refused(self, tk_exec):
        r = tk_exec.toolkit_exec(app="powershell", args=["-Command", "Start-Process cmd -Verb RunAs"], timeout=10)
        assert r["ok"] is False and r["returncode"] == 126, r

    def test_batch_with_elevation_refused(self, tk_exec):
        r = tk_exec.toolkit_exec(
            action="batch",
            commands=[
                {"app": "echo", "args": ["ok"]},
                {"app": "sudo", "args": ["ls"]},
            ],
            timeout=10,
        )
        assert r["ok"] is False, f"batch 中的提权未被拒绝: {r}"
        assert "手动执行" in r["error"]

    def test_refusal_happens_before_execution(self, tk_exec, tmp_path):
        """拒绝必须发生在执行之前：命令副作用不得产生。"""
        marker = tmp_path / "elevated_marker.txt"
        r = tk_exec.toolkit_exec(app="sudo", args=["touch", str(marker)], timeout=10)
        assert r["ok"] is False
        assert not marker.exists(), "提权保护未拦住执行（marker 被创建）"

    def test_error_message_contains_command_for_manual_run(self, tk_exec):
        """拒绝提示要带完整命令，用户可直接复制手动执行。"""
        r = tk_exec.toolkit_exec(app="sudo", args=["apt", "install", "-y", "nginx"], timeout=10)
        assert "sudo apt install -y nginx" in r["error"], r["error"]

    def test_normal_commands_still_work(self, tk_exec):
        r = tk_exec.toolkit_exec(app="echo", args=["hello"], timeout=10)
        assert r["ok"] and r["stdout"].strip() == "hello"

    def test_sudo_as_argument_not_refused(self, tk_exec):
        """`sudo` 只是参数时不得误判（否则会误伤 grep/日志检索）。"""
        r = tk_exec.toolkit_exec(app="echo", args=["run sudo manually"], timeout=10)
        assert r["ok"] and "sudo" in r["stdout"], r

    def test_detector_directly(self, tk_exec):
        """_elevation_refusal 返回值语义：拒绝有 dict，放行返回 None。"""
        assert tk_exec._elevation_refusal("sudo", ["ls"]) is not None
        assert tk_exec._elevation_refusal("echo", ["sudo"]) is None
        assert tk_exec._elevation_refusal("grep", ["-rn", "sudo", "/var/log"]) is None

    def test_command_words_extraction(self, tk_exec):
        """命令位置提取：只认命令名，不认参数里的同名词。"""
        assert tk_exec._command_words("echo a; sudo rm") == ["echo", "sudo"]
        assert tk_exec._command_words("grep -rn sudo /var/log") == ["grep"]
        assert tk_exec._command_words("env FOO=1 sudo ls") == ["sudo"]
