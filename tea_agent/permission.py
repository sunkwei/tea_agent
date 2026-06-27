"""
Permission System - Access Control for Files, Commands, and Network.
"""
import logging
logger = logging.getLogger("permission")

class PermissionManager:
    def __init__(self, allow_dirs=None, deny_dirs=None,
                 allow_cmds=None, deny_cmds=None,
                 allow_nets=None, deny_nets=None,
                 strict=False, log_actions=True):
        self._allow_dirs = set(allow_dirs) if allow_dirs else set()
        self._deny_dirs = set(deny_dirs) if deny_dirs else {"/etc","/proc","/sys","/bin","/sbin","/boot"}
        self._allow_cmds = list(allow_cmds) if allow_cmds else []
        self._deny_cmds = list(deny_cmds) if deny_cmds else ["mkfs","dd","format","shutdown","reboot","init","rm -rf /"]
        self._allow_nets = set(allow_nets) if allow_nets else set()
        self._deny_nets = set(deny_nets) if deny_nets else set()
        self.strict = strict
        self.log_actions = log_actions

    def check_read(self, path: str) -> bool:
        return self._check_path(path, "read")
    def check_write(self, path: str) -> bool:
        return self._check_path(path, "write")
    def check_exec(self, command: str) -> bool:
        return self._check_cmd(command)
    def check_net(self, host: str, port: int = 0) -> bool:
        return self._check_net(host, port)

    def _check_path(self, path: str, access: str) -> bool:
        p = path.replace(chr(92), '/')
        # Check allow_dirs first
        if self._allow_dirs:
            for ad in self._allow_dirs:
                if p.startswith(ad):
                    if self.log_actions:
                        logger.info(f"✓ Permit {access}: {path}")
                    return True
            if self.log_actions:
                logger.warning(f"✖ Deny {access}: {path} (not in allow_dirs)")
            return False
        # Check deny_dirs
        for dd in self._deny_dirs:
            if p.startswith(dd):
                if self.log_actions:
                    logger.warning(f"✖ Deny {access}: {path} (in deny_dirs)")
                return False
        # Strict mode: deny by default
        if self.strict:
            if self.log_actions:
                logger.warning(f"✖ Deny {access}: {path} (strict)")
            return False
        if self.log_actions:
            logger.info(f"✓ Permit {access}: {path} (default)")
        return True

    def _check_cmd(self, command: str) -> bool:
        cmd_low = command.strip().lower()
        for dc in self._deny_cmds:
            if dc in cmd_low:
                if self.log_actions:
                    logger.warning(f"✖ Deny cmd: {command} (matches deny: {dc})")
                return False
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
