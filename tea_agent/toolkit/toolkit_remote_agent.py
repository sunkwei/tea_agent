## llm generated tool func, created Mon Jul 27 13:33:04 2026
# version: 1.0.0

"""
远程设备Agent控制工具 — toolkit_remote_agent

核心场景：
  主机 Agent（PC）↔ 终端设备（BM1688/RK3588/X3等）上的 tea_agent.server
  主机向终端AI发送任务 → 终端AI自行调用本地工具执行 → 返回最终回答
  主机分析回答 → 决策下一步 → 循环直至任务完成
"""

import json
import logging
import threading
import time
from datetime import datetime
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

logger = logging.getLogger("toolkit.remote_agent")

# ── 设备注册表 ──────────────────────────────
_device_registry: dict[str, dict] = {}
_registry_lock = threading.Lock()


def _build_url(host: str, port: int) -> str:
    return f"http://{host}:{port}"


def _build_headers(auth_code: str = "") -> dict:
    headers = {"Content-Type": "application/json"}
    if auth_code:
        headers["Authorization"] = f"Bearer {auth_code}"
        headers["X-Api-Key"] = auth_code
    return headers


def _register_device(device_id, host, port, working_path, auth_code):
    with _registry_lock:
        _device_registry[device_id] = {
            "device_id": device_id,
            "host": host,
            "port": port,
            "working_path": working_path or "/home/root",
            "auth_code": auth_code,
            "base_url": _build_url(host, port),
            "registered_at": datetime.now().isoformat(),
            "last_seen": None,
        }
    return {"ok": True, "device_id": device_id, "base_url": _build_url(host, port)}


def _get_device(device_id):
    with _registry_lock:
        return _device_registry.get(device_id)


def _list_devices():
    with _registry_lock:
        return [
            {"device_id": did, "host": info["host"], "port": info["port"],
             "working_path": info["working_path"], "base_url": info["base_url"],
             "registered_at": info["registered_at"], "last_seen": info["last_seen"]}
            for did, info in _device_registry.items()
        ]


def _check_device_online(device):
    try:
        req = Request(f"{device['base_url']}/health", method="GET",
                      headers=_build_headers(device["auth_code"]))
        with urlopen(req, timeout=5) as resp:
            data = resp.read().decode()
            with _registry_lock:
                if device["device_id"] in _device_registry:
                    _device_registry[device["device_id"]]["last_seen"] = datetime.now().isoformat()
            return {"ok": True, "device_id": device["device_id"], "status": "online"}
    except Exception as e:
        return {"ok": False, "device_id": device["device_id"], "status": "offline", "error": str(e)}


def _exec_remote(device, goal, session_id="", enable_thinking=True, timeout=120):
    """向终端AI发送任务，获取最终回答。"""
    base_url = device["base_url"]
    headers = _build_headers(device["auth_code"])
    working_path = device.get("working_path", "/home/root")

    # 1. 创建或复用远程会话
    remote_session_id = session_id
    if not remote_session_id:
        try:
            body = json.dumps({"title": f"Remote: {goal[:40]}"}).encode()
            req = Request(f"{base_url}/v1/sessions", data=body, headers=headers, method="POST")
            with urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
                remote_session_id = data.get("id") or data.get("topic_id") or ""
        except Exception as e:
            return {"ok": False, "error": f"创建远程会话失败: {e}", "device_id": device["device_id"]}

    # 2. 构建消息（注入 working_path 上下文）
    system_ctx = f"你的工作目录是: {working_path}\n所有操作默认在此目录下执行。"
    messages = [{"role": "system", "content": system_ctx}, {"role": "user", "content": goal}]

    # 3. 发送聊天请求
    try:
        chat_body = json.dumps({
            "messages": messages,
            "topic_id": remote_session_id,
            "stream": False,
        }).encode()
        req = Request(f"{base_url}/v1/chat/completions", data=chat_body,
                      headers=headers, method="POST")
        start = time.time()
        with urlopen(req, timeout=timeout) as resp:
            result = json.loads(resp.read())
        elapsed = round(time.time() - start, 2)

        with _registry_lock:
            if device["device_id"] in _device_registry:
                _device_registry[device["device_id"]]["last_seen"] = datetime.now().isoformat()

        choices = result.get("choices", [])
        if not choices:
            return {"ok": False, "error": "远程AI未返回有效响应",
                    "device_id": device["device_id"], "session_id": remote_session_id}

        assistant_msg = choices[0].get("message", {}).get("content", "")
        tools_used = result.get("tools_used", [])

        return {
            "ok": True,
            "device_id": device["device_id"],
            "session_id": remote_session_id,
            "result": assistant_msg,        # ← 远程AI的最终回答（核心！）
            "tools_used": tools_used,        # ← 远程AI使用了哪些工具
            "elapsed": elapsed,              # ← 总耗时
        }

    except HTTPError as e:
        body = e.read().decode() if e.fp else ""
        return {"ok": False, "error": f"HTTP {e.code}: {body[:200]}",
                "device_id": device["device_id"], "session_id": remote_session_id}
    except Exception as e:
        return {"ok": False, "error": str(e),
                "device_id": device["device_id"], "session_id": remote_session_id}


def toolkit_remote_agent(
    action="list",
    device_id="",
    host="",
    port=8282,
    working_path="",
    auth_code="",
    goal="",
    session_id="",
    timeout=120,
    enable_thinking=True,
):
    """
    远程设备Agent控制工具。

    与终端设备上的 tea_agent.server 通信，向设备AI发送任务，
    获取AI的最终回答。主机Agent基于回答决策下一步。

    Args:
        action: register(注册)/unregister(移除)/list(列表)/exec(执行)/status(状态)
        device_id: 设备标识名，如 "bm1688-1"
        host: 设备IP或主机名
        port: 设备端口（默认8282）
        working_path: 设备上的工作目录
        auth_code: 设备的API授权码（可选）
        goal: 发送给设备AI的任务描述（exec时必需）
        session_id: 远程会话ID，多轮对话保持上下文
        timeout: 等待远程响应的超时秒数（默认120）
        enable_thinking: 是否启用设备AI的推理

    Returns:
        exec时返回远程AI的 final message（在 result 字段）

    典型用法:
        # 注册设备
        toolkit_remote_agent(action="register", device_id="bm1688",
            host="192.168.1.100", port=8282, working_path="/home/root/project")

        # 发送任务给设备AI
        r1 = toolkit_remote_agent(action="exec", device_id="bm1688",
            goal="执行 pytest test_device.py，分析结果")

        # 基于设备AI的回答继续交互（同一session保持上下文）
        r2 = toolkit_remote_agent(action="exec", device_id="bm1688",
            goal=f"修复问题: {r1['result'][:300]}",
            session_id=r1["session_id"])
    """
    if action == "register":
        if not device_id:
            return {"error": "device_id 是必需的"}
        if not host:
            return {"error": "host 是必需的"}
        return _register_device(device_id, host, port, working_path, auth_code)

    elif action == "unregister":
        if not device_id:
            return {"error": "device_id 是必需的"}
        with _registry_lock:
            if device_id in _device_registry:
                del _device_registry[device_id]
                return {"ok": True, "message": f"设备 {device_id} 已移除"}
            return {"error": f"设备 {device_id} 未找到"}

    elif action == "list":
        return {"devices": _list_devices(), "total": len(_device_registry)}

    elif action == "status":
        if device_id:
            device = _get_device(device_id)
            if not device:
                return {"error": f"设备 {device_id} 未注册"}
            return _check_device_online(device)
        results = []
        for did in list(_device_registry.keys()):
            dev = _get_device(did)
            if dev:
                results.append(_check_device_online(dev))
        return {"devices": results, "total": len(results)}

    elif action == "exec":
        if not goal:
            return {"error": "goal 是必需的"}
        if device_id:
            device = _get_device(device_id)
            if not device:
                return {"error": f"设备 {device_id} 未注册，请先 register"}
            return _exec_remote(device, goal, session_id, enable_thinking, timeout)
        # 临时连接（不注册）
        if not host:
            return {"error": "需要 device_id（已注册设备）或 host（临时连接）"}
        device = {
            "device_id": device_id or f"temp-{host}",
            "base_url": _build_url(host, port),
            "working_path": working_path or "/home/root",
            "auth_code": auth_code,
        }
        return _exec_remote(device, goal, session_id, enable_thinking, timeout)

    return {"error": f"未知 action: {action}"}


def meta_toolkit_remote_agent() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "toolkit_remote_agent",
            "description": "远程设备Agent控制工具。与终端设备(BM1688/RK3588/X3等)上的tea_agent.server通信，向设备AI发送任务，获取AI的最终回答。主机AI基于回答决策下一步。",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["register", "unregister", "list", "exec", "status"],
                        "description": "register=注册设备, unregister=移除, list=已注册设备, exec=向设备AI发任务, status=检查在线"
                    },
                    "device_id": {"type": "string", "description": "设备标识名，如 bm1688-1"},
                    "host": {"type": "string", "description": "设备IP或主机名"},
                    "port": {"type": "integer", "description": "设备端口，默认8282"},
                    "working_path": {"type": "string", "description": "设备上的工作目录，远程AI在此操作"},
                    "auth_code": {"type": "string", "description": "设备的API授权码（可选）"},
                    "goal": {"type": "string", "description": "发送给设备AI的任务描述（exec时）"},
                    "session_id": {"type": "string", "description": "远程会话ID，多轮对话保持上下文"},
                    "timeout": {"type": "integer", "description": "等待远程AI响应的超时秒数"},
                    "enable_thinking": {"type": "boolean", "description": "是否启用设备AI的推理"},
                },
                "required": ["action"],
            },
        },
    }
