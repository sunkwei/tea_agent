"""
测试 PermissionManager — 自由奔放模式：所有检查一律放行。
"""

from tea_agent.permission import PermissionManager


class TestInit:
    """初始化 — 所有参数仅保留兼容性，不影响行为"""

    def test_init_no_error(self):
        pm = PermissionManager()
        assert pm is not None

    def test_init_with_all_params(self):
        pm = PermissionManager(
            allow_dirs=["/home"],
            deny_dirs=["/etc"],
            allow_cmds=["ls"],
            deny_cmds=["rm"],
            allow_nets={"api.example.com"},
            deny_nets={"evil.com"},
            strict=True,
            log_actions=False,
        )
        assert pm is not None


class TestAlwaysPermit:
    """自由奔放：所有路径/命令/网络检查均返回 True"""

    def test_any_path_read(self):
        pm = PermissionManager()
        assert pm.check_read("/etc/shadow") is True
        assert pm.check_read("C:\\Windows\\System32\\config") is True
        assert pm.check_read("/home/user/file.txt") is True

    def test_any_path_write(self):
        pm = PermissionManager()
        assert pm.check_write("/root/.bashrc") is True
        assert pm.check_write("C:\\bootmgr") is True

    def test_any_command(self):
        pm = PermissionManager()
        assert pm.check_exec("rm -rf /") is True
        assert pm.check_exec("mkfs.ext4 /dev/sda") is True
        assert pm.check_exec("shutdown -h now") is True
        assert pm.check_exec("dd if=/dev/zero of=/dev/sda") is True

    def test_any_network(self):
        pm = PermissionManager()
        assert pm.check_net("evil.com", 666) is True
        assert pm.check_net("localhost") is True
        assert pm.check_net("") is True

    def test_check_exec_returns_bool(self):
        assert isinstance(PermissionManager().check_exec("ls"), bool)

    def test_check_read_returns_bool(self):
        assert isinstance(PermissionManager().check_read("/tmp"), bool)

    def test_check_write_returns_bool(self):
        assert isinstance(PermissionManager().check_write("/tmp"), bool)

    def test_check_net_returns_bool(self):
        assert isinstance(PermissionManager().check_net("host"), bool)
