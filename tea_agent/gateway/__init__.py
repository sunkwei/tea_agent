"""Tea Agent Gateway — 后台守护进程 + WebSocket + Canvas 宿主"""

__version__ = "0.1.0"

from .gateway import GatewayDaemon

__all__ = ["GatewayDaemon"]
