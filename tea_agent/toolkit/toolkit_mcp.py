# version: 1.0.0

import logging

logger = logging.getLogger("toolkit")

def toolkit_mcp(action: str = "connect", server_name: str = "", command: str = "",
                args: list = None, transport: str = "stdio", url: str = "",
                tool_name: str = "", tool_args: dict = None):
    """
    MCP (Model Context Protocol) 客户端工具，用于连接外部 MCP Server 并使用第三方工具。

    action='connect': 连接 MCP Server
        toolkit_mcp(action='connect', server_name='filesystem', command='npx',
                   args=['-y', '@modelcontextprotocol/server-filesystem', '/path/to/allow'])

    action='list_tools': 列出服务器可用工具
        toolkit_mcp(action='list_tools', server_name='filesystem')

    action='call_tool': 调用 MCP 工具
        toolkit_mcp(action='call_tool', server_name='filesystem',
                   tool_name='read_file', tool_args={'path': '/tmp/test.txt'})

    action='disconnect': 断开连接
        toolkit_mcp(action='disconnect', server_name='filesystem')

    action='status': 查看已连接服务器状态
        toolkit_mcp(action='status')

    返回:
        (returncode, stdout_json, stderr)
    """
    logger.info(f"toolkit_mcp called: action={action!r}, server_name={server_name!r}")


    if action == "connect":
        return _mcp_connect(server_name, command, args or [], transport, url)
    elif action == "list_tools":
        return _mcp_list_tools(server_name)
    elif action == "call_tool":
        return _mcp_call(server_name, tool_name, tool_args or {})
    elif action == "disconnect":
        return _mcp_disconnect(server_name)
    elif action == "status":
        return _mcp_status()
    else:
        return {"ok": False, "error": f"未知 action: {action}", "returncode": 1}

# MCP 客户端全局状态
_MCP_SERVERS = {}  # server_name → {"session": ..., "stdio": ..., "transport": ..., "keepalive": ...}
_MCP_LOOP = None  # 持久事件循环（后台线程）
_MCP_THREAD = None  # 后台线程

def _mcp_get_or_create_loop():
    """获取或创建持久事件循环（后台线程）"""
    import asyncio
    import threading

    global _MCP_LOOP, _MCP_THREAD

    if _MCP_LOOP is not None and _MCP_LOOP.is_running():
        return _MCP_LOOP

    # 创建新的事件循环在后台线程中运行
    _MCP_LOOP = asyncio.new_event_loop()

    def _run_loop():
        """Internal: run loop."""
        asyncio.set_event_loop(_MCP_LOOP)
        _MCP_LOOP.run_forever()

    _MCP_THREAD = threading.Thread(target=_run_loop, daemon=True, name="mcp-loop")
    _MCP_THREAD.start()
    return _MCP_LOOP

def _mcp_run_async(coro, timeout: float = 30.0):
    import asyncio

    loop = _mcp_get_or_create_loop()
    future = asyncio.run_coroutine_threadsafe(coro, loop)

    try:
        result = future.result(timeout=timeout)
        return result
    except asyncio.TimeoutError:
        return {"ok": False, "error": "MCP 操作超时", "returncode": 1}
    except Exception as e:
        return {"ok": False, "error": f"MCP 操作异常: {e}", "returncode": 1}

def _mcp_connect(server_name: str, command: str, args: list, transport: str, url: str):
    """连接 MCP Server（在持久事件循环中，保持 stdio context manager 活跃）"""
    import asyncio
    import json

    if not server_name:
        return {"ok": False, "error": "server_name 不能为空", "returncode": 1}

    if server_name in _MCP_SERVERS:
        return {"ok": True, "status": "already_connected", "server": server_name, "returncode": 0}

    try:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.sse import sse_client
        from mcp.client.stdio import stdio_client

        async def _connect_and_keepalive():
            """连接并创建一个永不退出的 keepalive 任务来保持 context manager 活跃"""
            if transport == "stdio":
                if not command:
                    return {"ok": False, "error": "stdio 传输方式需要 command 参数", "returncode": 1}

                server_params = StdioServerParameters(
                    command=command,
                    args=args,
                )

                # 使用 async with 保持 context manager 活跃
                ctx = stdio_client(server_params)
                read_stream, write_stream = await ctx.__aenter__()
                session_ctx = ClientSession(read_stream, write_stream)
                session = await session_ctx.__aenter__()
                await session.initialize()

                # 创建一个 keepalive 事件，永远不会 set（除非断开连接）
                keepalive = asyncio.Event()

                _MCP_SERVERS[server_name] = {
                    "session": session,
                    "transport_ctx": ctx,
                    "session_ctx": session_ctx,
                    "transport": "stdio",
                    "keepalive": keepalive,
                }

            elif transport == "sse":
                if not url:
                    return {"ok": False, "error": "sse 传输方式需要 url 参数", "returncode": 1}

                ctx = sse_client(url)
                read_stream, write_stream = await ctx.__aenter__()
                session_ctx = ClientSession(read_stream, write_stream)
                session = await session_ctx.__aenter__()
                await session.initialize()

                keepalive = asyncio.Event()

                _MCP_SERVERS[server_name] = {
                    "session": session,
                    "transport_ctx": ctx,
                    "session_ctx": session_ctx,
                    "transport": "sse",
                    "url": url,
                    "keepalive": keepalive,
                }
            else:
                return {"ok": False, "error": f"不支持的传输方式: {transport}", "returncode": 1}

            # 阻塞直到 keepalive 事件被 set（disconnect 时）
            await keepalive.wait()

            # 清理
            try:
                await session_ctx.__aexit__(None, None, None)
            except Exception:
                logger.exception('op_failed')

            try:
                await ctx.__aexit__(None, None, None)
            except Exception:
                logger.exception('op_failed')


            return {"ok": True, "status": "disconnected", "returncode": 0}

        # 在后台提交 keepalive 任务，不等待完成
        loop = _mcp_get_or_create_loop()
        # 使用 run_coroutine_threadsafe 提交连接任务
        asyncio.run_coroutine_threadsafe(_connect_and_keepalive(), loop)

        # 等待连接完成（或用短超时）
        try:
            # 轮询直到 server 被注册
            import time
            deadline = time.time() + 15
            while time.time() < deadline:
                if server_name in _MCP_SERVERS:
                    return {"ok": True, "message": f"已连接到 MCP Server: {server_name}", "transport": transport, "returncode": 0}
                time.sleep(0.05)
            return {"ok": False, "error": f"连接超时: {server_name}", "returncode": 1}
        except Exception as e:
            return {"ok": False, "error": f"连接失败: {e}", "returncode": 1}

    except ImportError:
        return {"ok": False, "error": "缺少 mcp 库，请运行: pip install mcp", "returncode": 1}
    except Exception as e:
        return {"ok": False, "error": f"连接失败: {e}", "returncode": 1}

def _mcp_list_tools(server_name: str):
    if not server_name:
        return {"ok": False, "error": "server_name 不能为空", "returncode": 1}

    if server_name not in _MCP_SERVERS:
        return {"ok": False, "error": f"Server '{server_name}' 未连接", "returncode": 1}

    try:
        async def _list():
            server_info = _MCP_SERVERS[server_name]
            session = server_info["session"]
            result = await session.list_tools()
            tools = result.tools
            tools_info = [{"name": t.name, "description": t.description or "", "input_schema": t.inputSchema if hasattr(t, 'inputSchema') else {}} for t in tools]
            return {"ok": True, "server": server_name, "tools_count": len(tools_info), "tools": tools_info, "returncode": 0}

        return _mcp_run_async(_list(), timeout=15.0)

    except Exception as e:
        return {"ok": False, "error": f"列出工具失败: {e}", "returncode": 1}

def _mcp_call(server_name: str, tool_name: str, tool_args: dict):
    """调用 MCP 工具（在持久事件循环中）"""
    import json

    if not server_name:
        return {"ok": False, "error": "server_name 不能为空", "returncode": 1}

    if not tool_name:
        return {"ok": False, "error": "tool_name 不能为空", "returncode": 1}

    if server_name not in _MCP_SERVERS:
        return {"ok": False, "error": f"Server '{server_name}' 未连接", "returncode": 1}

    try:
        async def _call():
            server_info = _MCP_SERVERS[server_name]
            session = server_info["session"]
            result = await session.call_tool(tool_name, tool_args)
            content_list = []
            for content in result.content:
                if hasattr(content, 'text'):
                    content_list.append(content.text)
                elif hasattr(content, 'data'):
                    content_list.append(str(content.data))
                else:
                    content_list.append(str(content))
            return {"ok": True, "server": server_name, "tool": tool_name, "content": "\n".join(content_list), "is_error": result.isError if hasattr(result, 'isError') else False, "returncode": 0}

        return _mcp_run_async(_call(), timeout=120.0)

    except Exception as e:
        return {"ok": False, "error": f"调用工具失败: {e}", "returncode": 1}

def _mcp_disconnect(server_name: str):
    if not server_name:
        return {"ok": False, "error": "server_name 不能为空", "returncode": 1}

    if server_name not in _MCP_SERVERS:
        return {"ok": True, "status": "not_connected", "server": server_name, "returncode": 0}

    try:
        server_info = _MCP_SERVERS[server_name]
        keepalive = server_info.get("keepalive")
        if keepalive is not None:
            loop = _mcp_get_or_create_loop()
            asyncio.run_coroutine_threadsafe(_set_and_del(server_name, keepalive), loop)
        del _MCP_SERVERS[server_name]
        return {"ok": True, "message": f"已断开连接: {server_name}", "returncode": 0}
    except Exception as e:
        return {"ok": False, "error": f"断开连接失败: {e}", "returncode": 1}

async def _set_and_del(server_name: str, keepalive):
    """设置 keepalive event 并清理 MCP_SERVERS 条目"""
    keepalive.set()
    # 给一点时间让 keepalive 协程退出 context manager
    import asyncio as _asyncio
    await _asyncio.sleep(0.1)

def _mcp_status():
    if not _MCP_SERVERS:
        return {"ok": True, "status": "no_connections", "servers": [], "returncode": 0}

    servers_info = [{"name": n, "transport": i.get("transport", "unknown"), "url": i.get("url", "")} for n, i in _MCP_SERVERS.items()]
    return {"ok": True, "status": "connected", "servers_count": len(servers_info), "servers": servers_info, "returncode": 0}

def meta_toolkit_mcp() -> dict:
    """Meta toolkit mcp."""
    return {
        "type": "function",
        "function": {
            "name": "toolkit_mcp",
            "description": "MCP (Model Context Protocol) 客户端工具，用于连接外部 MCP Server 并使用第三方工具。支持 stdio 和 SSE 传输方式。",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["connect", "list_tools", "call_tool", "disconnect", "status"],
                        "description": "connect/list_tools/call_tool/disconnect/status",
                    },
                    "server_name": {
                        "type": "string",
                        "description": "MCP Server 名称（用于标识连接）",
                    },
                    "command": {
                        "type": "string",
                        "description": "启动命令，如 'npx' 或 'python'",
                    },
                    "args": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "启动命令参数列表",
                    },
                    "transport": {
                        "type": "string",
                        "enum": ["stdio", "sse"],
                        "description": "传输方式，默认 stdio",
                    },
                    "url": {
                        "type": "string",
                        "description": "SSE 传输方式的服务器 URL",
                    },
                    "tool_name": {
                        "type": "string",
                        "description": "要调用的工具名称",
                    },
                    "tool_args": {
                        "type": "object",
                        "description": "工具参数",
                    },
                },
                "required": ["action"],
            },
        },
    }
