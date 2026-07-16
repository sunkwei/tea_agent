"""
权限管理系统 — 已禁用。

Tea Agent 主打"自由奔放"，使用者自行承担完全责任。
此模块保留仅为兼容性，所有检查均放行。
"""

from __future__ import annotations

__all__ = [
    "PermissionManager",
]


class PermissionManager:
    """权限管理器 — 已禁用，所有检查均放行。"""

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
        # 全部忽略，自由奔放
        pass

    def check_read(self, path: str) -> bool:
        return True

    def check_write(self, path: str) -> bool:
        return True

    def check_exec(self, command: str) -> bool:
        return True

    def check_net(self, host: str, port: int = 0) -> bool:
        return True
