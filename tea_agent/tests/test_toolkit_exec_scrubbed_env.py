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
