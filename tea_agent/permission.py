"""
权限管理系统 — 控制文件读写、命令执行和网络访问的安全策略。

设计原则：
- 白名单优先：设置了 allow 列表时，只有列表中的资源被允许
- 黑名单回退：未设置 allow 列表时，拒绝 deny 列表中的资源
- strict 模式：未明确允许即拒绝（白名单安全模型）
- 所有检查均有日志记录，便于审计

权限类型：
1. 文件访问（read/write）：基于路径前缀匹配
2. 命令执行（exec）：基于命令字符串子串匹配
3. 网络连接（net）：基于主机名后缀匹配
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("permission")

__all__ = [
    "PermissionManager",
]


class PermissionManager:
    """权限管理器 — 控制文件、命令和网络的安全访问策略。

    支持 allow/deny 列表和 strict 模式，所有检查操作均有日志记录。

    Attributes:
        strict: 严格模式下，未明确允许的访问一律拒绝
        log_actions: 是否记录每次权限检查的日志
    """

    def __init__(
        self,
        allow_dirs: list[str] | None = None,
        deny_dirs: list[str] | None = None,
        allow_cmds: list[str] | None = None,
        deny_cmds: list[str] | None = None,
        allow_nets: list[str] | None = None,
        deny_nets: list[str] | None = None,
        strict: bool = False,
        log_actions: bool = True,
    ) -> None:
        """初始化权限管理器。

        Args:
            allow_dirs: 允许访问的目录路径前缀列表
            deny_dirs: 禁止访问的目录路径前缀列表。
                       默认禁止系统关键目录: /etc, /proc, /sys, /bin, /sbin, /boot
            allow_cmds: 允许执行的命令前缀列表
            deny_cmds: 禁止执行的命令子串列表。
                       默认禁止危险命令: mkfs, dd, format, shutdown, reboot, init, rm -rf /
            allow_nets: 允许连接的主机后缀列表
            deny_nets: 禁止连接的主机子串列表
            strict: True 时启用白名单模式，未明确允许的访问一律拒绝
            log_actions: 是否记录每次权限检查的日志
        """
        self._allow_dirs: set[str] = set(allow_dirs) if allow_dirs else set()
        self._deny_dirs: set[str] = set(deny_dirs) if deny_dirs else {
            "/etc", "/proc", "/sys", "/bin", "/sbin", "/boot"
        }
        self._allow_cmds: list[str] = list(allow_cmds) if allow_cmds else []
        self._deny_cmds: list[str] = list(deny_cmds) if deny_cmds else [
            "mkfs", "dd", "format", "shutdown", "reboot", "init", "rm -rf /"
        ]
        self._allow_nets: set[str] = set(allow_nets) if allow_nets else set()
        self._deny_nets: set[str] = set(deny_nets) if deny_nets else set()
        self.strict = strict
        self.log_actions = log_actions

    # ── 公共接口 ──────────────────────────────────────────────

    def check_read(self, path: str) -> bool:
        """检查是否允许读取指定路径。

        Args:
            path: 文件或目录路径

        Returns:
            True 表示允许读取，False 表示拒绝
        """
        return self._check_path(path, "read")

    def check_write(self, path: str) -> bool:
        """检查是否允许写入指定路径。

        Args:
            path: 文件或目录路径

        Returns:
            True 表示允许写入，False 表示拒绝
        """
        return self._check_path(path, "write")

    def check_exec(self, command: str) -> bool:
        """检查是否允许执行指定命令。

        Args:
            command: 命令行字符串

        Returns:
            True 表示允许执行，False 表示拒绝
        """
        return self._check_cmd(command)

    def check_net(self, host: str, port: int = 0) -> bool:
        """检查是否允许连接到指定主机。

        Args:
            host: 主机名或 IP 地址
            port: 端口号（仅用于日志，不参与匹配）

        Returns:
            True 表示允许连接，False 表示拒绝
        """
        return self._check_net(host, port)

    # ── 内部实现 ──────────────────────────────────────────────

    def _check_path(self, path: str, access: str) -> bool:
        """检查路径访问权限。

        策略：
        - 如果设置了 allow_dirs，只在白名单中的路径允许访问
        - 否则拒绝 deny_dirs 中的路径
        - strict 模式下 deny-by-default

        Args:
            path: 文件路径
            access: 访问类型（"read" 或 "write"）

        Returns:
            True 表示允许
        """
        p = path.replace("\\", "/")

        # 白名单优先：设置了 allow_dirs 时，只有前缀匹配才允许
        if self._allow_dirs:
            for ad in self._allow_dirs:
                if p.startswith(ad):
                    if self.log_actions:
                        logger.info(f"✓ Permit {access}: {path}")
                    return True
            if self.log_actions:
                logger.warning(f"✖ Deny {access}: {path} (not in allow_dirs)")
            return False

        # 黑名单检查
        for dd in self._deny_dirs:
            if p.startswith(dd):
                if self.log_actions:
                    logger.warning(f"✖ Deny {access}: {path} (in deny_dirs)")
                return False

        # strict 模式：默认拒绝
        if self.strict:
            if self.log_actions:
                logger.warning(f"✖ Deny {access}: {path} (strict)")
            return False

        if self.log_actions:
            logger.info(f"✓ Permit {access}: {path} (default)")
        return True

    def _check_cmd(self, command: str) -> bool:
        """检查命令执行权限。

        Args:
            command: 命令行字符串

        Returns:
            True 表示允许执行
        """
        cmd_low = command.strip().lower()

        # 先检查黑名单
        for dc in self._deny_cmds:
            if dc in cmd_low:
                if self.log_actions:
                    logger.warning(f"✖ Deny cmd: {command} (matches deny: {dc})")
                return False

        # 白名单优先
        if self._allow_cmds:
            for ac in self._allow_cmds:
                if cmd_low.startswith(ac.lower()):
                    if self.log_actions:
                        logger.info(f"✓ Permit cmd: {command}")
                    return True
            if self.log_actions:
                logger.warning(f"✖ Deny cmd: {command} (not in allow_cmds)")
            return False

        if self.strict:
            if self.log_actions:
                logger.warning(f"✖ Deny cmd: {command} (strict)")
            return False

        if self.log_actions:
            logger.info(f"✓ Permit cmd: {command} (default)")
        return True

    def _check_net(self, host: str, port: int = 0) -> bool:
        """检查网络连接权限。

        策略：
        - 如果设置了 allow_nets，只有后缀匹配的主机允许连接
        - 否则拒绝 deny_nets 列表中的主机
        - strict 模式下 deny-by-default

        Args:
            host: 主机名或 IP
            port: 端口号

        Returns:
            True 表示允许连接
        """
        host_low = host.strip().lower()

        if self._allow_nets:
            for an in self._allow_nets:
                if host_low.endswith(an) or host_low == an:
                    if self.log_actions:
                        logger.info(f"✓ Permit net: {host}:{port}")
                    return True
            if self.log_actions:
                logger.warning(f"✖ Deny net: {host}:{port} (not in allow_nets)")
            return False

        for dn in self._deny_nets:
            if dn in host_low:
                if self.log_actions:
                    logger.warning(f"✖ Deny net: {host}:{port} (in deny_nets)")
                return False

        if self.strict:
            if self.log_actions:
                logger.warning(f"✖ Deny net: {host}:{port} (strict)")
            return False

        if self.log_actions:
            logger.info(f"✓ Permit net: {host}:{port} (default)")
        return True
