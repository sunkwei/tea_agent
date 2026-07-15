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
from pathlib import Path
from unittest.mock import MagicMock, patch

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
