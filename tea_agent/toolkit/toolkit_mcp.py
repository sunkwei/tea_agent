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

    import json

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
        return (1, "", f"未知 action: {action}，支持: connect/list_tools/call_tool/disconnect/status")

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
        asyncio.set_event_loop(_MCP_LOOP)
        _MCP_LOOP.run_forever()

    _MCP_THREAD = threading.Thread(target=_run_loop, daemon=True, name="mcp-loop")
    _MCP_THREAD.start()
    return _MCP_LOOP

def _mcp_run_async(coro, timeout: float = 30.0):
    """在持久事件循环中运行协程，同步等待结果。返回 (rc, stdout, stderr)。"""
    import asyncio

    loop = _mcp_get_or_create_loop()
    future = asyncio.run_coroutine_threadsafe(coro, loop)

    try:
        result = future.result(timeout=timeout)
        return result
    except asyncio.TimeoutError:
        return (1, "", "⏰ MCP 操作超时")
    except Exception as e:
        import traceback
        return (1, "", f"❌ MCP 操作异常: {e.__class__.__name__}: {str(e)}")

def _mcp_connect(server_name: str, command: str, args: list, transport: str, url: str):
    """连接 MCP Server（在持久事件循环中，保持 stdio context manager 活跃）"""
    import json
    import asyncio

    if not server_name:
        return (1, "", "server_name 不能为空")

    if server_name in _MCP_SERVERS:
        return (0, json.dumps({"status": "already_connected", "server": server_name}, ensure_ascii=False, indent=2), "")

    try:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        from mcp.client.sse import sse_client

        async def _connect_and_keepalive():
            """连接并创建一个永不退出的 keepalive 任务来保持 context manager 活跃"""
            if transport == "stdio":
                if not command:
                    return (1, "", "stdio 传输方式需要 command 参数")

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
                    return (1, "", "sse 传输方式需要 url 参数")

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
                return (1, "", f"不支持的传输方式: {transport}，支持: stdio/sse")

            # 阻塞直到 keepalive 事件被 set（disconnect 时）
            await keepalive.wait()

            # 清理
            try:
                await session_ctx.__aexit__(None, None, None)
            except Exception:
                pass
            try:
                await ctx.__aexit__(None, None, None)
            except Exception:
                pass

            return (0, "disconnected", "")

        # 在后台提交 keepalive 任务，不等待完成
        loop = _mcp_get_or_create_loop()
        # 使用 run_coroutine_threadsafe 提交连接任务
        future = asyncio.run_coroutine_threadsafe(_connect_and_keepalive(), loop)

        # 等待连接完成（或用短超时）
        try:
            # 轮询直到 server 被注册
            import time
            deadline = time.time() + 15
            while time.time() < deadline:
                if server_name in _MCP_SERVERS:
                    return (0, f"✅ 已连接到 MCP Server: {server_name} (transport={transport})", "")
                time.sleep(0.05)
            return (1, "", f"❌ 连接超时: {server_name}")
        except Exception as e:
            return (1, "", f"❌ 连接失败: {str(e)}")

    except ImportError:
        return (1, "", "❌ 缺少 mcp 库，请运行: pip install mcp")
    except Exception as e:
        return (1, "", f"❌ 连接失败: {str(e)}")

def _mcp_list_tools(server_name: str):
    """列出 MCP Server 可用工具（在持久事件循环中）"""
    import json

    if not server_name:
        return (1, "", "server_name 不能为空")

    if server_name not in _MCP_SERVERS:
        return (1, "", f"Server '{server_name}' 未连接，请先调用 action='connect'")

    try:
        async def _list():
            server_info = _MCP_SERVERS[server_name]
            session = server_info["session"]

            result = await session.list_tools()
            tools = result.tools

            tools_info = []
            for tool in tools:
                tools_info.append({
                    "name": tool.name,
                    "description": tool.description or "",
                    "input_schema": tool.inputSchema if hasattr(tool, 'inputSchema') else {},
                })

            return (0, json.dumps({
                "server": server_name,
                "tools_count": len(tools_info),
                "tools": tools_info,
            }, ensure_ascii=False, indent=2), "")

        return _mcp_run_async(_list(), timeout=15.0)

    except Exception as e:
        return (1, "", f"❌ 列出工具失败: {str(e)}")

def _mcp_call(server_name: str, tool_name: str, tool_args: dict):
    """调用 MCP 工具（在持久事件循环中）"""
    import json

    if not server_name:
        return (1, "", "server_name 不能为空")

    if not tool_name:
        return (1, "", "tool_name 不能为空")

    if server_name not in _MCP_SERVERS:
        return (1, "", f"Server '{server_name}' 未连接")

    try:
        async def _call():
            server_info = _MCP_SERVERS[server_name]
            session = server_info["session"]

            result = await session.call_tool(tool_name, tool_args)

            # 提取结果内容
            content_list = []
            for content in result.content:
                if hasattr(content, 'text'):
                    content_list.append(content.text)
                elif hasattr(content, 'data'):
                    content_list.append(str(content.data))
                else:
                    content_list.append(str(content))

            return (0, json.dumps({
                "server": server_name,
                "tool": tool_name,
                "content": "\n".join(content_list),
                "is_error": result.isError if hasattr(result, 'isError') else False,
            }, ensure_ascii=False, indent=2), "")

        return _mcp_run_async(_call(), timeout=120.0)

    except Exception as e:
        return (1, "", f"❌ 调用工具失败: {str(e)}")

def _mcp_disconnect(server_name: str):
    """断开 MCP Server 连接（设置 keepalive event 触发清理）"""
    import json
    import asyncio

    if not server_name:
        return (1, "", "server_name 不能为空")

    if server_name not in _MCP_SERVERS:
        return (0, json.dumps({"status": "not_connected", "server": server_name}), "")

    try:
        server_info = _MCP_SERVERS[server_name]
        keepalive = server_info.get("keepalive")

        if keepalive is not None:
            # 设置 keepalive event，让后台协程退出 context manager 并清理
            loop = _mcp_get_or_create_loop()
            asyncio.run_coroutine_threadsafe(_set_and_del(server_name, keepalive), loop)

        del _MCP_SERVERS[server_name]
        return (0, f"✅ 已断开连接: {server_name}", "")

    except Exception as e:
        return (1, "", f"❌ 断开连接失败: {str(e)}")

async def _set_and_del(server_name: str, keepalive):
    """设置 keepalive event 并清理 MCP_SERVERS 条目"""
    keepalive.set()
    # 给一点时间让 keepalive 协程退出 context manager
    import asyncio as _asyncio
    await _asyncio.sleep(0.1)

def _mcp_status():
    """查看已连接服务器状态"""
    import json

    if not _MCP_SERVERS:
        return (0, json.dumps({"status": "no_connections", "servers": []}, ensure_ascii=False, indent=2), "")

    servers_info = []
    for name, info in _MCP_SERVERS.items():
        servers_info.append({
            "name": name,
            "transport": info.get("transport", "unknown"),
            "url": info.get("url", ""),
        })

    return (0, json.dumps({
        "status": "connected",
        "servers_count": len(servers_info),
        "servers": servers_info,
    }, ensure_ascii=False, indent=2), "")

def meta_toolkit_mcp() -> dict:
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
                        "description": "操作类型: connect=连接服务器, list_tools=列出工具, call_tool=调用工具, disconnect=断开连接, status=查看状态",
                    },
                    "server_name": {
                        "type": "string",
                        "description": "MCP Server 名称（用于标识连接）",
                    },
                    "command": {
                        "type": "string",
                        "description": "[connect] 启动命令，如 'npx' 或 'python'",
                    },
                    "args": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "[connect] 启动命令参数列表",
                    },
                    "transport": {
                        "type": "string",
                        "enum": ["stdio", "sse"],
                        "description": "[connect] 传输方式，默认 stdio",
                    },
                    "url": {
                        "type": "string",
                        "description": "[connect] SSE 传输方式的服务器 URL",
                    },
                    "tool_name": {
                        "type": "string",
                        "description": "[call_tool] 要调用的工具名称",
                    },
                    "tool_args": {
                        "type": "object",
                        "description": "[call_tool] 工具参数",
                    },
                },
                "required": ["action"],
                "type": "object",
            },
        },
    }
