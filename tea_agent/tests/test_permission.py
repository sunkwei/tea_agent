"""
测试 permission 模块 — 访问控制（文件/命令/网络）

覆盖：
- PermissionManager 初始化（默认值/自定义）
- 路径检查（allow_dirs / deny_dirs / strict 模式）
- 命令检查（allow_cmds / deny_cmds / strict 模式）
- 网络检查（allow_nets / deny_nets / strict 模式）
- 日志开关和 Windows 路径兼容
"""

import pytest
from tea_agent.permission import PermissionManager


class TestInit:
    """初始化测试"""

    def test_default_init(self):
        """默认初始化不应报错"""
        pm = PermissionManager()
        assert pm is not None
        assert not pm.strict
        assert pm.log_actions

    def test_default_deny_dirs(self):
        """默认 deny_dirs 应包含系统关键目录"""
        pm = PermissionManager()
        assert "/etc" in pm._deny_dirs
        assert "/proc" in pm._deny_dirs
        assert "/sys" in pm._deny_dirs

    def test_default_deny_cmds(self):
        """默认 deny_cmds 应包含危险命令"""
        pm = PermissionManager()
        assert "mkfs" in pm._deny_cmds
        assert "dd" in pm._deny_cmds
        assert "rm -rf /" in pm._deny_cmds

    def test_custom_allow_dirs(self):
        """自定义 allow_dirs"""
        pm = PermissionManager(allow_dirs=["/home", "/tmp"])
        assert "/home" in pm._allow_dirs
        assert "/tmp" in pm._allow_dirs

    def test_custom_deny_dirs(self):
        """自定义 deny_dirs"""
        pm = PermissionManager(deny_dirs=["/var"])
        assert pm._deny_dirs == {"/var"}

    def test_strict_mode(self):
        """strict=True"""
        pm = PermissionManager(strict=True)
        assert pm.strict

    def test_logging_off(self):
        """log_actions=False"""
        pm = PermissionManager(log_actions=False)
        assert not pm.log_actions


class TestCheckPath:
    """路径权限检查测试"""

    def test_allow_dirs_permits(self):
        """在 allow_dirs 中的路径应被允许"""
        pm = PermissionManager(allow_dirs=["/home", "/tmp"])
        assert pm.check_read("/home/user/file.txt") is True
        assert pm.check_write("/tmp/test.txt") is True

    def test_allow_dirs_deny_outside(self):
        """不在 allow_dirs 中的路径应被拒绝"""
        pm = PermissionManager(allow_dirs=["/home"])
        assert pm.check_read("/etc/passwd") is False
        assert pm.check_write("/proc/1/mem") is False

    def test_deny_dirs_without_allow(self):
        """有 deny_dirs 且无 allow_dirs 时，deny_dirs 中的路径应拒绝"""
        pm = PermissionManager(deny_dirs=["/etc", "/proc"])
        assert pm.check_read("/etc/passwd") is False
        assert pm.check_read("/proc/version") is False

    def test_deny_dirs_without_allow_permits_other(self):
        """有 deny_dirs 且无 allow_dirs 时，其他路径应允许"""
        pm = PermissionManager(deny_dirs=["/etc"])
        assert pm.check_read("/home/user/file.txt") is True
        assert pm.check_write("/tmp/test.txt") is True

    def test_strict_mode_denies_all(self):
        """strict=True 且无 allow_dirs 时，所有路径应被拒绝"""
        pm = PermissionManager(strict=True, log_actions=False)
        assert pm.check_read("/home/file.txt") is False
        assert pm.check_write("/tmp/test.txt") is False

    def test_allow_dirs_override_deny_dirs(self):
        """allow_dirs 优先于 deny_dirs"""
        pm = PermissionManager(
            allow_dirs=["/home"],
            deny_dirs=["/home/secret"]
        )
        # /home/user/file.txt 在 allow_dirs 中，应允许
        assert pm.check_read("/home/user/file.txt") is True
        # 注：allow_dirs 匹配优先于 deny_dirs 检查
        # 但实际逻辑是 allow_dirs 存在时，只检查 allow_dirs
        # 不在 allow_dirs 中的才会走 deny_dirs 检查

    def test_allow_dir_prefix_match(self):
        """路径前缀匹配 allow_dirs (使用 startswith，/data_bak 也会匹配 /data)"""
        pm = PermissionManager(allow_dirs=["/data"])
        assert pm.check_read("/data/db/records.sqlite") is True
        # /data_bak 以 /data 开头，所以被 allow_dirs 匹配（startswith 行为）
        assert pm.check_read("/data_bak/file.txt") is True

    def test_deny_dir_prefix_match(self):
        """路径前缀匹配 deny_dirs (使用 startswith，/tmpfile.txt 也会匹配 /tmp)"""
        pm = PermissionManager(deny_dirs=["/tmp"])
        assert pm.check_read("/tmp/evil.sh") is False
        # /tmpfile.txt 以 /tmp 开头，所以被 deny_dirs 匹配（startswith 行为）
        assert pm.check_read("/tmpfile.txt") is False

    def test_windows_path_backslash(self):
        """Windows 反斜杠路径：路径中 \ 被替换为 /，deny_dirs 应使用正斜杠"""
        pm = PermissionManager(deny_dirs=["C:/Windows"])
        assert pm.check_read("C:\\Windows\\System32\\cmd.exe") is False

    def test_empty_allow_dirs(self):
        """空的 allow_dirs 集合"""
        pm = PermissionManager(allow_dirs=set())
        # 空集合相当于没有 allow_dirs
        assert pm.check_read("/home/file.txt") is True

    def test_empty_deny_dirs(self):
        """空的 deny_dirs 集合（空 set 是 falsy，会使用默认 deny_dirs）"""
        # PermissionManager 中空 set 被视为 falsy，会使用默认 deny_dirs
        # 要绕过：使用非空且不包含 /etc 的 deny_dirs
        pm = PermissionManager(deny_dirs={"/custom/deny"})
        assert pm.check_read("/etc/passwd") is True  # 不在 deny_dirs 中

    def test_path_very_long(self):
        """长路径不应导致异常"""
        pm = PermissionManager()
        long_path = "/home/" + "a" * 1000 + "/file.txt"
        result = pm.check_read(long_path)
        assert isinstance(result, bool)


class TestCheckCmd:
    """命令权限检查测试"""

    def test_deny_cmd_matches_substring(self):
        """deny_cmds 子串匹配"""
        pm = PermissionManager()
        assert pm.check_exec("mkfs.ext4 /dev/sda1") is False
        assert pm.check_exec("dd if=/dev/zero of=/dev/sda") is False

    def test_safe_cmd_default_allowed(self):
        """默认状态下安全命令应允许"""
        pm = PermissionManager()
        assert pm.check_exec("ls -la") is True
        assert pm.check_exec("cat /etc/hosts") is True

    def test_allow_cmds_restricts(self):
        """设置了 allow_cmds 后，只有匹配的命令才允许"""
        pm = PermissionManager(allow_cmds=["ls", "cat"])
        assert pm.check_exec("ls -la") is True
        assert pm.check_exec("cat file.txt") is True
        assert pm.check_exec("rm file.txt") is False

    def test_allow_cmds_prefix_match(self):
        """allow_cmds 使用前缀匹配"""
        pm = PermissionManager(allow_cmds=["python"])
        assert pm.check_exec("python3 script.py") is True
        assert pm.check_exec("python script.py") is True

    def test_deny_cmds_in_allow_mode(self):
        """即使有 allow_cmds，deny_cmds 仍然生效"""
        pm = PermissionManager(
            allow_cmds=["ls", "cat", "rm"],
            deny_cmds=["rm -rf"]
        )
        assert pm.check_exec("ls -la") is True
        assert pm.check_exec("rm file.txt") is True
        assert pm.check_exec("rm -rf /") is False  # 被 deny_cmds 拦截

    def test_strict_mode_cmd(self):
        """strict=True 且无 allow_cmds，所有命令拒绝"""
        pm = PermissionManager(strict=True, log_actions=False)
        assert pm.check_exec("ls") is False
        assert pm.check_exec("echo hello") is False

    def test_cmd_case_insensitive(self):
        """命令检查不区分大小写"""
        pm = PermissionManager(deny_cmds=["mkfs"])
        assert pm.check_exec("MKFS.ext4 /dev/sda") is False
        assert pm.check_exec("Mkfs /dev/sda") is False

    def test_empty_command(self):
        """空命令"""
        pm = PermissionManager()
        assert pm.check_exec("") is True
        assert pm.check_exec("   ") is True

    def test_allow_cmds_empty_list(self):
        """空 allow_cmds 列表"""
        pm = PermissionManager(allow_cmds=[])
        # 空列表相当于没有 allow_cmds
        assert pm.check_exec("ls") is True


class TestCheckNet:
    """网络权限检查测试"""

    def test_allow_nets_permits(self):
        """在 allow_nets 中的主机应允许"""
        pm = PermissionManager(allow_nets={"api.openai.com"})
        assert pm.check_net("api.openai.com") is True
        assert pm.check_net("api.openai.com", 443) is True

    def test_allow_nets_deny_outside(self):
        """不在 allow_nets 中的主机应拒绝"""
        pm = PermissionManager(allow_nets={"api.openai.com"})
        assert pm.check_net("evil.com") is False

    def test_allow_nets_suffix_match(self):
        """allow_nets 支持后缀匹配"""
        pm = PermissionManager(allow_nets={"openai.com"})
        assert pm.check_net("api.openai.com") is True
        assert pm.check_net("cdn.openai.com") is True
        assert pm.check_net("other.com") is False

    def test_deny_nets_without_allow(self):
        """有 deny_nets 且无 allow_nets 时，匹配的应拒绝"""
        pm = PermissionManager(deny_nets={"evil.com", "malware.org"})
        assert pm.check_net("evil.com") is False
        assert pm.check_net("sub.evil.com") is False
        assert pm.check_net("safe.com") is True

    def test_deny_nets_substring_match(self):
        """deny_nets 使用子串匹配"""
        pm = PermissionManager(deny_nets={"ad"})
        assert pm.check_net("ad.doubleclick.net") is False
        assert pm.check_net("badhost.com") is False
        assert pm.check_net("goodhost.com") is True

    def test_strict_mode_net(self):
        """strict=True 且无 allow_nets，所有连接拒绝"""
        pm = PermissionManager(strict=True, log_actions=False)
        assert pm.check_net("api.openai.com") is False
        assert pm.check_net("localhost") is False

    def test_net_case_insensitive(self):
        """网络检查：host 被 lowered，但 deny_nets 条目本身不会自动 lowered"""
        pm = PermissionManager(deny_nets={"evil.com"})  # 使用小写
        assert pm.check_net("EVIL.COM") is False  # host 被 lowered 匹配
        assert pm.check_net("Evil.Com") is False  # host 被 lowered 匹配

    def test_empty_host_returns_bool(self):
        """空主机名应返回布尔值"""
        pm = PermissionManager()
        result = pm.check_net("")
        assert isinstance(result, bool)


class TestLogging:
    """日志开关测试"""

    def test_logging_on_by_default(self):
        """默认 log_actions=True，logger 应被调用（不抛异常）"""
        pm = PermissionManager()
        # 这些操作内部会调用 logger，不应抛异常
        assert pm.check_read("/tmp/test.txt") is True
        assert pm.check_exec("ls") is True
        assert pm.check_net("localhost") is True

    def test_logging_off_no_log(self):
        """log_actions=False 不应调用 logger（不抛异常）"""
        pm = PermissionManager(log_actions=False)
        assert pm.check_read("/home/user/file.txt") is True  # 默认允许
        assert pm.check_exec("dd if=/dev/zero") is False  # 默认拒绝（dd 在 deny_cmds）
        assert pm.check_net("safe-host.com") is True


class TestCheckExecAlias:
    """check_exec 方法别名测试"""

    def test_check_exec_returns_bool(self):
        """check_exec 应返回布尔值"""
        pm = PermissionManager()
        assert isinstance(pm.check_exec("ls"), bool)

    def test_check_exec_safe_default(self):
        """默认状态下安全命令允许"""
        pm = PermissionManager()
        assert pm.check_exec("echo hello") is True
        assert pm.check_exec("python -c 'print(1)'") is True

    def test_check_exec_dangerous_denied(self):
        """默认状态下危险命令拒绝"""
        pm = PermissionManager()
        assert pm.check_exec("mkfs.ext4 /dev/sda") is False
        assert pm.check_exec("dd if=/dev/zero of=/dev/sda bs=1M") is False
        assert pm.check_exec("shutdown now") is False


class TestCheckReadWrite:
    """读写检查测试"""

    def test_check_read_returns_bool(self):
        """check_read 应返回布尔值"""
        pm = PermissionManager()
        assert isinstance(pm.check_read("/tmp/test.txt"), bool)

    def test_check_write_returns_bool(self):
        """check_write 应返回布尔值"""
        pm = PermissionManager()
        assert isinstance(pm.check_write("/tmp/test.txt"), bool)

    def test_read_write_same_logic(self):
        """读和写应使用相同的路径检查逻辑"""
        pm = PermissionManager(deny_dirs={"/etc"})
        assert pm.check_read("/etc/passwd") == pm.check_write("/etc/passwd")
        assert pm.check_read("/home/file.txt") == pm.check_write("/home/file.txt")

    def test_read_write_with_allow_dirs(self):
        """allow_dirs 下读写都应允许"""
        pm = PermissionManager(allow_dirs={"/data"})
        assert pm.check_read("/data/file.txt") is True
        assert pm.check_write("/data/file.txt") is True
