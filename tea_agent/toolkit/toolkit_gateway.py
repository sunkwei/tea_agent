"""toolkit_gateway — 控制 Gateway 守护进程的启停"""

import logging
from typing import Optional

logger = logging.getLogger("toolkit_gateway")

# 延迟导入，避免循环依赖
_gateway = None

def _get_gateway():
    global _gateway
    if _gateway is None:
        from tea_agent.gateway.gateway import GatewayDaemon
        _gateway = GatewayDaemon()
    return _gateway


def toolkit_gateway(
    action: str = "status",
    port: Optional[int] = None,
    host: Optional[str] = None,
) -> dict:
    """控制 Gateway 守护进程。
    
    参数:
        action: start=启动, stop=停止, restart=重启, status=查询状态
        port: 端口号（action=start 时可选，默认 18789）
        host: 监听地址（action=start 时可选，默认 127.0.0.1）
    
    返回:
        {"ok": bool, "port": int, "url": str, ...}
    """
    gw = _get_gateway()
    
    if action == "status":
        return gw.status()
    
    elif action == "start":
        if host:
            gw.host = host
        if port:
            gw.port = port
        return gw.start(daemon=True)
    
    elif action == "stop":
        return gw.stop()
    
    elif action == "restart":
        gw.stop()
        import time
        time.sleep(0.5)
        if host:
            gw.host = host
        if port:
            gw.port = port
        return gw.start(daemon=True)
    
    else:
        return {"ok": False, "error": f"未知操作: {action}，可用: start/stop/restart/status"}
def meta_toolkit_gateway() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "toolkit_gateway",
            "description": "控制 Gateway 守护进程。后台常驻服务，提供 WebSocket 实时通信和 Canvas 可视化工作区。",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["start", "stop", "restart", "status"],
                        "description": "start=启动, stop=停止, restart=重启, status=查询状态"
                    },
                    "port": {
                        "type": "integer",
                        "description": "端口号（action=start 时可选，默认 18789）"
                    },
                    "host": {
                        "type": "string",
                        "description": "监听地址（action=start 时可选，默认 127.0.0.1）"
                    }
                },
                "required": ["action"],
            },
        },
    }
