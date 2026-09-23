"""
操作系统信息注入模块单元测试。

测试范围:
- 辅助函数: _get_os_signature, _load_persisted_os_sig, _save_os_sig
- inject_os_info: Windows / Linux / macOS 三大分支
- 参数行为: toolkit_root_dir, supports_reasoning
"""

import json
import os
import tempfile
from unittest.mock import patch

import pytest

# ============================================================
# 辅助函数
# ============================================================

class TestGetOsSignature:
    """_get_os_signature 格式测试"""

    def test_returns_non_empty_string(self):
        """应返回非空字符串"""
        from tea_agent.session.os_info_injector import _get_os_signature

        sig = _get_os_signature()
        assert isinstance(sig, str)
        assert len(sig) > 0

    def test_contains_system_name(self):
        """应包含操作系统名称（如 Windows / Linux / Darwin）"""
        from tea_agent.session.os_info_injector import _get_os_signature

        sig = _get_os_signature()
        import platform
        assert platform.system() in sig

    def test_format_has_dash_separators(self):
        """格式应为 system-release-machine"""
        from tea_agent.session.os_info_injector import _get_os_signature

        sig = _get_os_signature()
        parts = sig.split("-")
        assert len(parts) >= 3


class TestPersistOsSig:
    """_save_os_sig / _load_persisted_os_sig 持久化测试"""

    @pytest.fixture
    def mock_state_file(self, monkeypatch, tmp_path):
        """将 _OS_STATE_FILE 指向临时路径"""
        fake_path = str(tmp_path / ".tea_agent" / "os_state.json")
        monkeypatch.setattr(
            "tea_agent.session.os_info_injector._OS_STATE_FILE",
            fake_path,
        )
        yield fake_path

    def test_save_and_load_roundtrip(self, mock_state_file):
        """保存后应能正确加载"""
        from tea_agent.session.os_info_injector import (
            _load_persisted_os_sig,
            _save_os_sig,
        )

        _save_os_sig("topic_123", "Windows-10-AMD64")
        loaded = _load_persisted_os_sig("topic_123")
        assert loaded == "Windows-10-AMD64"

    def test_load_nonexistent_topic(self, mock_state_file):
        """不存在的 topic 应返回空字符串"""
        from tea_agent.session.os_info_injector import _load_persisted_os_sig

        loaded = _load_persisted_os_sig("nonexistent_topic")
        assert loaded == ""

    def test_load_empty_topic(self, mock_state_file):
        """空 topic_id 应返回空字符串"""
        from tea_agent.session.os_info_injector import _load_persisted_os_sig

        assert _load_persisted_os_sig("") == ""

    def test_save_empty_topic_no_file(self, mock_state_file):
        """空 topic_id 不应创建文件"""
        from tea_agent.session.os_info_injector import _save_os_sig

        _save_os_sig("", "sig")
        assert not os.path.exists(mock_state_file)

    def test_multiple_topics_isolated(self, mock_state_file):
        """多个 topic 的数据应互不干扰"""
        from tea_agent.session.os_info_injector import (
            _load_persisted_os_sig,
            _save_os_sig,
        )

        _save_os_sig("topic_a", "Windows-10-AMD64")
        _save_os_sig("topic_b", "Linux-6.8.0-x86_64")

        assert _load_persisted_os_sig("topic_a") == "Windows-10-AMD64"
        assert _load_persisted_os_sig("topic_b") == "Linux-6.8.0-x86_64"

    def test_overwrite_existing_topic(self, mock_state_file):
        """同一 topic 的签名应被覆盖"""
        from tea_agent.session.os_info_injector import (
            _load_persisted_os_sig,
            _save_os_sig,
        )

        _save_os_sig("topic_x", "old-sig")
        _save_os_sig("topic_x", "new-sig")
        assert _load_persisted_os_sig("topic_x") == "new-sig"

    def test_corrupted_json_returns_empty(self, mock_state_file):
        """损坏的 JSON 文件应返回空字符串"""
        from tea_agent.session.os_info_injector import _load_persisted_os_sig

        # 写入无效 JSON
        os.makedirs(os.path.dirname(mock_state_file), exist_ok=True)
        with open(mock_state_file, "w") as f:
            f.write("{invalid json")

        loaded = _load_persisted_os_sig("topic_x")
        assert loaded == ""


# ============================================================
# 状态文件健壮性（Linux/Windows 真实故障回归）
# ============================================================

class TestStateFileRobustness:
    """~/.tea_agent/os_state.json 是纯旁路缓存，必须 fail-open + 自愈。

    回归背景（Linux 启动报错）：设备上该文件变成空文件/带 BOM/半截 JSON，
    旧实现 ① 用 utf-8 读 → BOM 触发 JSONDecodeError；② 捕获后
    logger.exception 打 ERROR + traceback 刷屏；③ _save_os_sig 也先
    json.load，抛错即跳过整个写入 → 坏文件永不自愈，每次启动重复报错。
    """

    @pytest.fixture(autouse=True)
    def _reset_warn_flag(self):
        """每条测试重置「只提示一次」节流标志，避免相互串扰。"""
        import tea_agent.session.os_info_injector as mod
        mod._bad_state_warned = False
        yield
        mod._bad_state_warned = False

    @pytest.fixture
    def state_file(self, monkeypatch, tmp_path):
        fake_path = str(tmp_path / ".tea_agent" / "os_state.json")
        monkeypatch.setattr("tea_agent.session.os_info_injector._OS_STATE_FILE", fake_path)
        monkeypatch.delenv("TEA_OS_STATE_FILE", raising=False)
        return fake_path

    @staticmethod
    def _write_raw(path, content, encoding="utf-8"):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding=encoding, newline="") as f:
            f.write(content)

    # ── 读端：坏文件一律降级为空，且绝不冒泡 ERROR ──

    def test_empty_file_returns_empty_without_error_log(self, state_file, caplog):
        """0 字节文件（写入被中断）应返回 ""，且不得产生 ERROR/traceback。"""
        import logging
        self._write_raw(state_file, "")
        with caplog.at_level(logging.WARNING, logger="session.os_info_injector"):
            from tea_agent.session.os_info_injector import _load_persisted_os_sig
            assert _load_persisted_os_sig("topic_x") == ""
        assert not [r for r in caplog.records if r.levelno >= logging.ERROR]

    def test_bom_prefixed_json_is_still_read(self, state_file):
        """带 UTF-8 BOM 的合法 JSON 应能正常读出签名（utf-8-sig 兼容）。

        旧实现用 encoding='utf-8' 读，BOM 会让 json.load 在 char 0 抛
        'Expecting value' —— 与线上报错完全一致。
        """
        self._write_raw(state_file, '{"topics": {"t1": "Linux-6.8.0-arm64"}}',
                        encoding="utf-8-sig")
        # 前置检查：确认文件字节确实以 BOM 开头（否则这条测试就没测到 BOM）
        with open(state_file, "rb") as f:
            assert f.read(3) == b"\xef\xbb\xbf"

        from tea_agent.session.os_info_injector import _load_persisted_os_sig
        assert _load_persisted_os_sig("t1") == "Linux-6.8.0-arm64"

    @pytest.mark.parametrize("bad_content", [
        "{invalid json",
        "not json at all",
        "[1, 2, 3]",                       # 顶层不是对象
        '{"topics": "oops"}',              # topics 不是对象
        '{"topics": {"t1": 123}}',         # 值不是字符串
    ])
    def test_malformed_content_degrades_to_empty(self, state_file, bad_content):
        """各种畸形内容都应安全返回 ""，不抛异常。"""
        self._write_raw(state_file, bad_content)
        from tea_agent.session.os_info_injector import _load_persisted_os_sig
        assert _load_persisted_os_sig("t1") == ""

    def test_unreadable_file_is_swallowed(self, state_file, monkeypatch):
        """权限错误等 OSError 也必须静默降级（fail-open）。"""
        import builtins
        import tea_agent.session.os_info_injector as mod

        real_open = builtins.open

        def _deny_open(file, *a, **kw):
            if str(file).endswith("os_state.json"):
                raise PermissionError(13, "Permission denied", str(file))
            return real_open(file, *a, **kw)

        monkeypatch.setattr(builtins, "open", _deny_open)
        monkeypatch.setattr(os, "makedirs", lambda *a, **kw: None)
        assert mod._load_persisted_os_sig("t1") == ""
        assert mod._save_os_sig("t1", "Linux-1-x86_64") is None  # 不得抛出

    # ── 写端：坏文件必须自愈 ──

    def test_corrupted_file_self_heals_on_save(self, state_file):
        """坏文件经一次 _save_os_sig 后应变回合法 JSON 并可读回。

        这是本次故障的关键回归：旧实现保存前先 json.load，抛错即整体跳过，
        坏文件永远留在原地 → 每次启动重复报错。
        """
        self._write_raw(state_file, "{corrupted")
        from tea_agent.session.os_info_injector import _load_persisted_os_sig, _save_os_sig

        assert _load_persisted_os_sig("t1") == ""
        _save_os_sig("t1", "Linux-6.8.0-aarch64")

        with open(state_file, encoding="utf-8") as f:
            data = json.loads(f.read())          # 现在是合法 JSON
        assert data["topics"]["t1"] == "Linux-6.8.0-aarch64"
        assert _load_persisted_os_sig("t1") == "Linux-6.8.0-aarch64"

    def test_save_keeps_other_topics_and_leaves_no_temp_files(self, state_file, tmp_path):
        """保存应保留既有 topic，且原子写不在目录留下 .tmp 残留。"""
        from tea_agent.session.os_info_injector import _load_persisted_os_sig, _save_os_sig

        _save_os_sig("t_keep", "Windows-10-AMD64")
        _save_os_sig("t_new", "Linux-6.8.0-x86_64")

        assert _load_persisted_os_sig("t_keep") == "Windows-10-AMD64"
        assert _load_persisted_os_sig("t_new") == "Linux-6.8.0-x86_64"
        leftovers = [p.name for p in os.listdir(os.path.dirname(state_file))
                     if p.endswith(".tmp") or p.startswith(".os_state.")]
        assert leftovers == []

    def test_topics_capped_to_prevent_unbounded_growth(self, state_file, monkeypatch):
        """topic 数应有上限（嵌入式设备存储有限），旧条目被裁剪。"""
        import tea_agent.session.os_info_injector as mod
        monkeypatch.setattr(mod, "_MAX_TRACKED_TOPICS", 5)

        for i in range(12):
            mod._save_os_sig(f"topic_{i}", f"sig-{i}")

        with open(state_file, encoding="utf-8") as f:
            topics = json.load(f)["topics"]
        assert len(topics) <= 5
        assert topics.get("topic_11") == "sig-11"   # 最新的必须留下

    def test_env_override_takes_effect(self, tmp_path, monkeypatch):
        """TEA_OS_STATE_FILE 可改道（容器里 HOME 不可写时的逃生门）。"""
        alt = tmp_path / "elsewhere" / "os_state.json"
        monkeypatch.setenv("TEA_OS_STATE_FILE", str(alt))
        from tea_agent.session.os_info_injector import _load_persisted_os_sig, _save_os_sig

        _save_os_sig("t_env", "Linux-5.10-armv7l")
        assert alt.exists()
        assert _load_persisted_os_sig("t_env") == "Linux-5.10-armv7l"

    def test_state_file_path_is_usable_without_home(self, monkeypatch):
        """HOME 解析失败时退回临时目录，不得抛异常。"""
        import tea_agent.session.os_info_injector as mod
        monkeypatch.setattr(mod.os.path, "expanduser", lambda p: "~")
        path = mod._default_state_file()
        assert path.endswith(os.path.join("tea_agent", "os_state.json"))
        assert tempfile.gettempdir() in path


# ============================================================
# inject_os_info — OS 分支测试
# ============================================================

class BaseInjectTest:
    """inject_os_info 测试基类，提供公共辅助方法"""

    @staticmethod
    def _call_inject(os_name: str, **kwargs):
        """使用 mock platform 调用 inject_os_info"""
        with (
            patch("tea_agent.session.os_info_injector.platform.system",
                  return_value=os_name),
            patch("tea_agent.session.os_info_injector.platform.release",
                  return_value="test-release"),
            patch("tea_agent.session.os_info_injector.platform.version",
                  return_value="test-version"),
            patch("tea_agent.session.os_info_injector.platform.machine",
                  return_value="x86_64"),
            patch("tea_agent.session.os_info_injector.platform.python_version",
                  return_value="3.11.0"),
            patch("tea_agent.session.os_info_injector.socket.gethostname",
                  return_value="test-host"),
            patch("tea_agent.session.os_info_injector.os.getcwd",
                  return_value="/fake/workdir"),
            patch("tea_agent.session.os_info_injector.os.sep",
                  "\\" if os_name == "Windows" else "/"),
            patch("tea_agent.session.os_info_injector.os.pathsep",
                  ";" if os_name == "Windows" else ":"),
        ):
            from tea_agent.session.os_info_injector import inject_os_info
            messages = kwargs.pop("messages", [{"role": "user", "content": "hello"}])
            return inject_os_info(messages, **kwargs)


class TestInjectOsInfoWindows(BaseInjectTest):
    """Windows 分支测试"""

    def test_adds_os_info_messages(self):
        """应添加 user + assistant 两条消息"""
        result = self._call_inject("Windows")
        # 原消息 + user + assistant = 3
        assert len(result) == 3
        assert result[1]["role"] == "user"
        assert result[2]["role"] == "assistant"

    def test_user_message_contains_windows_hints(self):
        """user 消息应包含 Windows 特有提示"""
        result = self._call_inject("Windows")
        content = result[1]["content"]
        assert "Windows" in content
        assert "findstr" in content
        assert "cmd.exe" in content
        assert "PowerShell" in content
        assert "%USERPROFILE%" in content
        assert "dir" in content or "findstr" in content

    def test_user_message_contains_path_info(self):
        """user 消息应包含路径分隔符信息"""
        result = self._call_inject("Windows")
        content = result[1]["content"]
        assert "路径分隔符" in content
        assert "\\\\" in content or "\\" in content

    def test_assistant_confirms_os(self):
        """assistant 应确认识别到的环境"""
        result = self._call_inject("Windows")
        ack = result[2]
        assert ack["role"] == "assistant"
        assert "Windows" in ack["content"]

    def test_supports_reasoning_adds_empty_reasoning(self):
        """supports_reasoning=True 时 assistant 应有 reasoning_content"""
        result = self._call_inject("Windows", supports_reasoning=True)
        assert result[2].get("reasoning_content") == ""

    def test_no_reasoning_omits_reasoning_key(self):
        """supports_reasoning=False 时不应有 reasoning_content"""
        result = self._call_inject("Windows", supports_reasoning=False)
        assert "reasoning_content" not in result[2]


class TestInjectOsInfoLinux(BaseInjectTest):
    """Linux 分支测试"""

    def test_user_message_contains_linux_hints(self):
        """user 消息应包含 Linux 特有提示"""
        result = self._call_inject("Linux")
        content = result[1]["content"]
        assert "Linux" in content
        assert "grep" in content
        assert "ls" in content
        assert "cat" in content
        assert "$HOME" in content
        assert "sudo" in content

    def test_assistant_confirms_linux(self):
        """assistant 应确认 Linux 环境"""
        result = self._call_inject("Linux")
        ack = result[2]
        assert "Linux" in ack["content"]

    def test_does_not_contain_windows_hints(self):
        """不应包含 Windows 特有命令"""
        result = self._call_inject("Linux")
        content = result[1]["content"]
        assert "findstr" not in content
        assert "cmd.exe" not in content


class TestInjectOsInfoMacOS(BaseInjectTest):
    """macOS 分支测试"""

    def test_user_message_contains_macos_hints(self):
        """user 消息应包含 macOS 特有提示"""
        result = self._call_inject("Darwin")
        content = result[1]["content"]
        assert "macOS" in content
        assert "grep" in content
        assert "ls" in content
        assert "cat" in content
        assert "$HOME" in content

    def test_assistant_confirms_macos(self):
        """assistant 应确认 macOS 环境"""
        result = self._call_inject("Darwin")
        ack = result[2]
        assert "Darwin" in ack["content"]

    def test_does_not_contain_linux_specific(self):
        """不应包含仅 Linux 才有的提示（如 sudo 特定）"""
        result = self._call_inject("Darwin")
        # macOS 分支没有 sudo 提示文本
        content = result[1]["content"]
        # macOS 分支的提示不包含 "sudo"（对比 Linux 分支有 sudo）
        assert "sudo" not in content or "权限" not in content


class TestInjectOsInfoCommon(BaseInjectTest):
    """所有 OS 共有的行为"""

    def test_original_messages_preserved(self):
        """原始消息列表应保留在开头"""
        original = [
            {"role": "system", "content": "you are a bot"},
            {"role": "user", "content": "do something"},
        ]
        result = self._call_inject("Linux", messages=original)
        assert result[0] is original[0]
        assert result[1] is original[1]

    def test_empty_messages_list(self):
        """空消息列表也应正常工作"""
        result = self._call_inject("Windows", messages=[])
        assert len(result) == 2  # user + assistant

    def test_toolkit_root_dir_included(self):
        """toolkit_root_dir 参数应出现在 user 消息中"""
        result = self._call_inject("Linux", toolkit_root_dir="/opt/tools")
        assert "/opt/tools" in result[1]["content"]

    def test_os_info_section_header(self):
        """消息开头应有 [系统环境信息] 标记"""
        result = self._call_inject("Linux")
        assert result[1]["content"].startswith("[系统环境信息]")

    def test_general_rules_section(self):
        """应包含通用规则部分"""
        result = self._call_inject("Linux")
        content = result[1]["content"]
        assert "通用规则" in content
        assert "toolkit_file" in content
        assert "toolkit_exec" in content

    def test_python_version_included(self):
        """应包含 Python 版本信息"""
        result = self._call_inject("Linux")
        assert "Python: 3.11.0" in result[1]["content"]

    def test_hostname_included(self):
        """应包含主机名"""
        result = self._call_inject("Linux")
        assert "test-host" in result[1]["content"]

    def test_architecture_included(self):
        """应包含架构信息"""
        result = self._call_inject("Linux")
        assert "x86_64" in result[1]["content"]


class TestInjectOsInfoEdgeCases:
    """边界情况测试"""

    def test_unknown_os(self):
        """未知 OS 名应仍然工作（无特有提示但通用规则在）"""
        with (
            patch("tea_agent.session.os_info_injector.platform.system",
                  return_value="FreeBSD"),
            patch("tea_agent.session.os_info_injector.platform.release",
                  return_value="13.0"),
            patch("tea_agent.session.os_info_injector.platform.version",
                  return_value="generic"),
            patch("tea_agent.session.os_info_injector.platform.machine",
                  return_value="amd64"),
            patch("tea_agent.session.os_info_injector.platform.python_version",
                  return_value="3.11.0"),
            patch("tea_agent.session.os_info_injector.socket.gethostname",
                  return_value="freebsd-host"),
            patch("tea_agent.session.os_info_injector.os.getcwd",
                  return_value="/usr/home"),
            patch("tea_agent.session.os_info_injector.os.sep", "/"),
            patch("tea_agent.session.os_info_injector.os.pathsep", ":"),
        ):
            from tea_agent.session.os_info_injector import inject_os_info

            result = inject_os_info([{"role": "user", "content": "test"}])
            content = result[1]["content"]
            # 通用信息应存在
            assert "FreeBSD" in content
            assert "通用规则" in content
            # 不应有 Windows/Linux/macOS 特有提示
            assert "findstr" not in content
            assert "grep" not in content

    def test_does_not_mutate_original_messages_object(self):
        """原始消息对象引用应保持不变（但内容被追加，这是预期行为）"""
        with (
            patch("tea_agent.session.os_info_injector.platform.system",
                  return_value="Linux"),
            patch("tea_agent.session.os_info_injector.platform.release",
                  return_value="6.8.0"),
            patch("tea_agent.session.os_info_injector.platform.version",
                  return_value="#1"),
            patch("tea_agent.session.os_info_injector.platform.machine",
                  return_value="x86_64"),
            patch("tea_agent.session.os_info_injector.platform.python_version",
                  return_value="3.11.0"),
            patch("tea_agent.session.os_info_injector.socket.gethostname",
                  return_value="host"),
            patch("tea_agent.session.os_info_injector.os.getcwd",
                  return_value="/tmp"),
            patch("tea_agent.session.os_info_injector.os.sep", "/"),
            patch("tea_agent.session.os_info_injector.os.pathsep", ":"),
        ):
            from tea_agent.session.os_info_injector import inject_os_info

            original = [{"role": "user", "content": "hello"}]
            original_copy = list(original)  # 浅拷贝
            result = inject_os_info(original)
            # 原有消息应保持不变
            assert result[0] == original_copy[0]
            # 返回值应与传入的是同一个 list 对象
            assert result is original

# ============================================================
# generate_os_info_text 纯函数测试
# ============================================================

class BaseGenerateTest:
    """generate_os_info_text 测试基类"""

    @staticmethod
    def _call_generate(os_name: str = "Linux", **kwargs):
        """使用 mock platform 调用 generate_os_info_text"""
        with (
            patch("tea_agent.session.os_info_injector.platform.system",
                  return_value=os_name),
            patch("tea_agent.session.os_info_injector.platform.release",
                  return_value="test-release"),
            patch("tea_agent.session.os_info_injector.platform.version",
                  return_value="test-version"),
            patch("tea_agent.session.os_info_injector.platform.machine",
                  return_value="x86_64"),
            patch("tea_agent.session.os_info_injector.platform.python_version",
                  return_value="3.11.0"),
            patch("tea_agent.session.os_info_injector.socket.gethostname",
                  return_value="test-host"),
            patch("tea_agent.session.os_info_injector.os.getcwd",
                  return_value="/fake/workdir"),
            patch("tea_agent.session.os_info_injector.os.sep",
                  "\\" if os_name == "Windows" else "/"),
            patch("tea_agent.session.os_info_injector.os.pathsep",
                  ";" if os_name == "Windows" else ":"),
        ):
            from tea_agent.session.os_info_injector import generate_os_info_text
            return generate_os_info_text(**kwargs)


class TestGenerateOsInfoText:
    """generate_os_info_text 纯函数测试"""

    def test_returns_string(self):
        """应返回字符串"""
        result = BaseGenerateTest._call_generate("Linux")
        assert isinstance(result, str)
        assert len(result) > 100

    def test_contains_os_section_header(self):
        """应包含 [系统环境信息] 标记"""
        result = BaseGenerateTest._call_generate("Linux")
        assert result.startswith("[系统环境信息]")

    def test_windows_specific_hints(self):
        """Windows 应有 findstr 等提示"""
        result = BaseGenerateTest._call_generate("Windows")
        assert "Windows" in result
        assert "findstr" in result
        assert "%USERPROFILE%" in result

    def test_linux_specific_hints(self):
        """Linux 应有 grep 等提示"""
        result = BaseGenerateTest._call_generate("Linux")
        assert "Linux" in result
        assert "grep" in result
        assert "$HOME" in result

    def test_macos_specific_hints(self):
        """macOS 应有 macOS 提示"""
        result = BaseGenerateTest._call_generate("Darwin")
        assert "macOS" in result
        assert "grep" in result

    def test_contains_path_separator_info(self):
        """应包含路径分隔符信息"""
        result = BaseGenerateTest._call_generate("Linux")
        assert "路径分隔符" in result

    def test_contains_interface_hints(self):
        """应包含接口类型提示"""
        result = BaseGenerateTest._call_generate("Linux", interface_type="web")
        assert "Web" in result or "链接" in result

    def test_contains_toolkit_root_dir(self):
        """toolkit_root_dir 应出现在结果中"""
        result = BaseGenerateTest._call_generate("Linux", toolkit_root_dir="/opt/tools")
        assert "/opt/tools" in result

    def test_unknown_os_still_works(self):
        """未知 OS 不应崩溃"""
        result = BaseGenerateTest._call_generate("FreeBSD")
        assert "FreeBSD" in result
        assert "通用规则" in result

    def test_interface_type_web(self):
        """web 接口类型应包含对应提示"""
        result = BaseGenerateTest._call_generate("Linux", interface_type="web")
        assert "Web" in result or "链接" in result

    def test_interface_type_cli(self):
        """已废弃的 cli 接口类型回退 web 口径（不再是纯文本提示）"""
        result = BaseGenerateTest._call_generate("Linux", interface_type="cli")
        assert "纯文本" not in result
        assert "Web 浏览器" in result, "cli 应回退为 Web 浏览器标签"

    def test_interface_type_gui(self):
        """已废弃的 gui 接口类型回退 web 口径（不再宣传桌面端能力）"""
        result = BaseGenerateTest._call_generate("Linux", interface_type="gui")
        assert "Tkinter" not in result
        assert "Web 浏览器" in result


class TestGenerateOsInfoCrossPlatform:
    """跨平台兼容性测试"""

    def test_path_sep_correct_for_windows(self):
        """Windows 路径分隔符应为反斜杠"""
        result = BaseGenerateTest._call_generate("Windows")
        assert "\\\\" in result  # 转义后的反斜杠

    def test_path_sep_correct_for_linux(self):
        """Linux 路径分隔符应为正斜杠"""
        result = BaseGenerateTest._call_generate("Linux")
        assert "Linux/macOS 使用 /" in result

    def test_tool_hints_windows(self):
        """Windows 工具提示应包含 cmd.exe"""
        result = BaseGenerateTest._call_generate("Windows")
        assert "cmd.exe" in result

    def test_tool_hints_linux(self):
        """Linux 工具提示应包含 toolbar 通用规则"""
        result = BaseGenerateTest._call_generate("Linux")
        assert "toolkit_file" in result

    def test_no_cross_os_leakage(self):
        """Windows 不应包含 Linux 特有提示"""
        result = BaseGenerateTest._call_generate("Windows")
        assert "sudo" not in result or "密码" not in result


# ============================================================
# _detect_interface_type 测试
# ============================================================

class TestDetectInterfaceType:
    """_detect_interface_type 接口类型检测测试"""

    def test_env_var_web(self):
        """TEA_AGENT_INTERFACE=web 应返回 web"""
        with patch.dict(os.environ, {"TEA_AGENT_INTERFACE": "web"}, clear=True):
            from tea_agent.session.os_info_injector import _detect_interface_type
            assert _detect_interface_type() == "web"

    def test_env_var_case_insensitive(self):
        """环境变量值不区分大小写"""
        with patch.dict(os.environ, {"TEA_AGENT_INTERFACE": "WEB"}, clear=True):
            from tea_agent.session.os_info_injector import _detect_interface_type
            assert _detect_interface_type() == "web"

    def test_env_var_mcp(self):
        """TEA_AGENT_INTERFACE=mcp 应返回 mcp"""
        with patch.dict(os.environ, {"TEA_AGENT_INTERFACE": "mcp"}, clear=True):
            from tea_agent.session.os_info_injector import _detect_interface_type
            assert _detect_interface_type() == "mcp"

    def test_no_env_var_fallback(self):
        """无环境变量且无特征时回退 web —— 不得回退到已废弃的 cli"""
        with patch.dict(os.environ, {}, clear=True), patch("tea_agent.session.os_info_injector.sys.modules", {}):
            with patch("tea_agent.session.os_info_injector.sys.argv", [""]):
                from tea_agent.session.os_info_injector import _detect_interface_type
                assert _detect_interface_type() == "web"

    def test_invalid_env_var_fallback(self):
        """无效环境变量值应走正常检测流程"""
        with patch.dict(os.environ, {"TEA_AGENT_INTERFACE": "invalid"}, clear=True):
            from tea_agent.session.os_info_injector import _detect_interface_type
            assert _detect_interface_type() == "web"


# ============================================================
# 接口类型提示测试
# ============================================================

class TestGetInterfaceHints:
    """_get_interface_hints 测试"""

    def test_web_hints(self):
        """web 接口应返回 HTML/链接相关提示"""
        from tea_agent.session.os_info_injector import _get_interface_hints
        hints = _get_interface_hints("web")
        assert "#topic:" in hints or "HTML" in hints
        assert "Markdown" in hints or "链接" in hints

    def test_removed_interfaces_fall_back_to_web_hints(self):
        """已废弃的 gui/cli/tui 与任意未知值一律回退 web 提示，不得返回空串。

        回退空串会让模型失去全部格式约定（旧实现 `hints.get(t, "")` 即如此）；
        Web 是当前唯一内置交互面，故未知类型按 web 口径组装提示。
        """
        from tea_agent.session.os_info_injector import _get_interface_hints
        web = _get_interface_hints("web")
        assert web, "web 提示不得为空"
        for legacy in ("gui", "cli", "tui", "invalid", ""):
            assert _get_interface_hints(legacy) == web, f"{legacy!r} 未回退 web 提示"

    def test_mcp_hints(self):
        """MCP 接口应返回纯文本/JSON 提示"""
        from tea_agent.session.os_info_injector import _get_interface_hints
        hints = _get_interface_hints("mcp")
        assert "纯文本" in hints or "JSON" in hints

    def test_unknown_interface_falls_back_to_web(self):
        """未知接口类型回退 web 提示，而非空串（空串会让模型失去全部格式约定）"""
        from tea_agent.session.os_info_injector import _get_interface_hints
        hints = _get_interface_hints("nonexistent")
        assert hints != ""
        assert hints == _get_interface_hints("web")
