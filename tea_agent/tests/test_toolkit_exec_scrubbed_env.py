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


class TestEquivalentParamForms:
    """等价参数名 / 整行命令 / 包装层归一化。

    回归（设备端 tea_agent_api 日志高频）：
    - "toolkit_exec() got an unexpected keyword argument 'command'" / "'arguments'"
    - "app 需要可执行程序路径字符串，收到 bool"
    前者是等价参数名（模型换了写法），后者是形态问题；两者都不该让工具整体失败。
    """

    def test_app_as_bool_returns_self_correcting_error(self, tk_exec):
        """app 传布尔不得抛异常，且错误信息要给出正确用法供模型自纠。"""
        r = tk_exec.toolkit_exec(app=True, args=["x"], timeout=10)
        assert r["ok"] is False
        assert "正确用法" in r["error"], r["error"]

    def test_error_message_lists_received_values(self, tk_exec):
        """错误信息必须包含实际收到的参数形态（否则模型无从自查）。"""
        r = tk_exec.toolkit_exec(app=True, args=["x"], timeout=10)
        assert "实际收到" in r["error"] and "bool" in r["error"], r["error"]

    def test_command_alias(self, tk_exec):
        """command= 整行命令：自动拆成 app + args 并执行。"""
        r = tk_exec.toolkit_exec(command="echo alias-ok", timeout=10)
        assert r["ok"], r
        assert r["stdout"].strip() == "alias-ok"

    def test_executable_argv_aliases(self, tk_exec):
        """executable= / argv= 等价键。"""
        r = tk_exec.toolkit_exec(executable="echo", argv=["argv-ok"], timeout=10)
        assert r["ok"], r
        assert r["stdout"].strip() == "argv-ok"

    def test_arguments_dict_unwrapped(self, tk_exec):
        """arguments={...} 多包一层时应展开为真实参数。"""
        r = tk_exec.toolkit_exec(arguments={"app": "echo", "args": ["unwrapped"]}, timeout=10)
        assert r["ok"], r
        assert r["stdout"].strip() == "unwrapped"

    def test_arguments_json_string_unwrapped(self, tk_exec):
        """arguments 是 JSON 字符串时也应展开。"""
        r = tk_exec.toolkit_exec(
            arguments='{"app": "echo", "args": ["str-unwrapped"]}', timeout=10)
        assert r["ok"], r
        assert r["stdout"].strip() == "str-unwrapped"

    def test_app_whole_command_line_split(self, tk_exec):
        """app='echo x' 整行命令自动拆分（不再被当成不存在的可执行文件）。"""
        r = tk_exec.toolkit_exec(app="echo line-split", timeout=10)
        assert r["ok"], r
        assert r["stdout"].strip() == "line-split"

    def test_app_list_with_multiple_items(self, tk_exec):
        """app=['echo', 'x'] 首项为程序，其余并入 args。"""
        r = tk_exec.toolkit_exec(app=["echo", "from-list"], timeout=10)
        assert r["ok"], r
        assert r["stdout"].strip() == "from-list"

    def test_numeric_and_bool_arg_elements(self, tk_exec):
        """args 里的数字/布尔/None 元素转字符串，不得抛异常。"""
        r = tk_exec.toolkit_exec(app="echo", args=[1, True, None], timeout=10)
        assert r["ok"], r
        assert r["stdout"].strip() == "1 true"

    def test_conflicting_alias_values_refused(self, tk_exec):
        """app 与 command 给出不同值属语义歧义 → 报冲突，不许猜。"""
        r = tk_exec.toolkit_exec(app="ls", command="rm -rf /", timeout=10)
        assert r["ok"] is False
        assert "语义冲突" in r["error"], r["error"]

    def test_unknown_kwarg_names_the_key(self, tk_exec):
        """未知参数要指明键名（静默忽略会让模型误以为参数生效）。"""
        r = tk_exec.toolkit_exec(app="echo", args=["x"], foo=1, timeout=10)
        assert r["ok"] is False
        assert "foo" in r["error"], r["error"]

    def test_unparseable_arguments_blob_errors(self, tk_exec):
        """arguments 无法解析时不得静默丢弃（否则模型以为参数已生效）。"""
        r = tk_exec.toolkit_exec(arguments="not json at all", timeout=10)
        assert r["ok"] is False
        assert "arguments" in r["error"], r["error"]

    def test_arguments_blob_with_unknown_keys_errors(self, tk_exec):
        """包装层里的未知键要冒泡成明确报错，而不是被吞掉。"""
        r = tk_exec.toolkit_exec(arguments={"app": "echo", "args": ["x"], "bogus": 1}, timeout=10)
        assert r["ok"] is False
        assert "bogus" in r["error"], r["error"]


class TestBatchFormTolerance:
    """batch 模式的形态容错与出口校验。"""

    def test_commands_alias_keys(self, tk_exec):
        """commands 条目内的等价键（command=）也要归一化。"""
        r = tk_exec.toolkit_exec(
            action="batch",
            commands=[{"command": "echo b-alias"}, {"app": ["echo"], "args": "b-coerced"}],
            timeout=10,
        )
        assert r["ok"], r
        outs = sorted(x["stdout"].strip() for x in r["results"])
        assert outs == ["b-alias", "b-coerced"], outs

    def test_commands_string_entries_split(self, tk_exec):
        """commands 直接给整行命令字符串也要能跑。"""
        r = tk_exec.toolkit_exec(action="batch", commands=["echo line-a"], timeout=10)
        assert r["ok"], r
        assert r["results"][0]["stdout"].strip() == "line-a"

    def test_batch_with_only_app_runs_as_single(self, tk_exec):
        """action=batch 却只给 app：按 single 执行，不再静默返回空 results。"""
        r = tk_exec.toolkit_exec(action="batch", app="echo", args=["fallback"], timeout=10)
        assert r["ok"], r
        assert r["stdout"].strip() == "fallback"

    def test_batch_without_commands_errors(self, tk_exec):
        """batch 缺 commands 时必须报错，不能静默成功。"""
        r = tk_exec.toolkit_exec(action="batch", timeout=10)
        assert r["ok"] is False
        assert "commands" in r["error"], r["error"]

    def test_batch_entry_error_names_usage(self, tk_exec):
        """单个条目 app 无法解析时，该条目报错要带正确用法（失败隔离）。"""
        r = tk_exec.toolkit_exec(
            action="batch",
            commands=[{"args": ["-la"]}, {"app": "echo", "args": ["survivor"]}],
            timeout=10,
        )
        assert any(x and "survivor" in (x.get("stdout") or "") for x in r["results"]), r
        bad = [x for x in r["results"] if x and not (x.get("stdout") or "").strip()]
        assert bad and "正确用法" in bad[0]["stderr"], bad


class TestSafetyAfterNormalization:
    """归一化不得绕过安全护栏：提权/自杀检测要在归一化**之后**仍然生效。"""

    def test_elevation_refused_via_alias(self, tk_exec):
        """经 command= 别名传入的 sudo 仍被拒绝。"""
        r = tk_exec.toolkit_exec(command="sudo ls", timeout=10)
        assert r["ok"] is False
        assert "手动执行" in r["error"], r["error"]

    def test_elevation_refused_via_arguments_wrapper(self, tk_exec):
        """经 arguments 包装层传入的 sudo 仍被拒绝。"""
        r = tk_exec.toolkit_exec(
            arguments={"app": "sudo", "args": ["apt", "install", "-y", "nginx"]}, timeout=10)
        assert r["ok"] is False
        assert "手动执行" in r["error"], r["error"]

    def test_elevation_refused_in_batch_via_alias(self, tk_exec):
        """batch 条目里经 command= 传入的 sudo 仍被拒绝。"""
        r = tk_exec.toolkit_exec(action="batch", commands=[{"command": "sudo id"}], timeout=10)
        assert r["ok"] is False
        assert "手动执行" in (r.get("error") or ""), r

    def test_self_destructive_blocked_after_split(self, tk_exec):
        """整行形态的 kill 自杀命令仍被拦（归一化后要重新过检测）。"""
        r = tk_exec.toolkit_exec(app=f"kill -9 {os.getpid()}", timeout=10)
        assert r["ok"] is False
        assert "阻止自杀" in r["error"], r["error"]
