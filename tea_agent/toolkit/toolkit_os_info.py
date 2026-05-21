import platform
import functools

import logging

logger = logging.getLogger("toolkit")

@functools.lru_cache(maxsize=1)
def _cached_os_info():
    return {
        "system": platform.system(),
        "release": platform.release(),
        "version": platform.version(),
        "machine": platform.machine(),
        "is_windows": platform.system() == "Windows",
        "is_linux": platform.system() == "Linux",
    }

def toolkit_os_info(refresh: bool = False):
    """获取当前操作系统信息（进程级缓存）。agent 启动时调用一次即可。"""
    logger.info(f"toolkit_os_info called: refresh={refresh!r}")

    if refresh:
        _cached_os_info.cache_clear()
    return _cached_os_info()

def meta_toolkit_os_info() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "toolkit_os_info",
            "description": "获取当前操作系统信息（进程级缓存）。返回 system/release/version/machine/is_windows/is_linux。",
            "parameters": {
                "type": "object",
                "properties": {
                    "refresh": {
                        "type": "boolean",
                        "description": "强制刷新缓存，默认 false",
                    }
                },
                "required": [],
            },
        },
    }
