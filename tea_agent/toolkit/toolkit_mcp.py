# @2026-05-19 gen by tea_agent, MCP Client 支持
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
_MCP_SERVERS = {}  # server_name → Client 实例


def _mcp_connect(server_name: str, command: str, args: list, transport: str, url: str):
    """连接 MCP Server"""
    import json

    if not server_name:
        return (1, "", "server_name 不能为空")

    if server_name in _MCP_SERVERS:
        return (0, json.dumps({"status": "already_connected", "server": server_name}, ensure_ascii=False, indent=2), "")

    try:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        from mcp.client.sse import sse_client
        import asyncio

        async def _connect():
            if transport == "stdio":
                if not command:
                    return (1, "", "stdio 传输方式需要 command 参数")

                server_params = StdioServerParameters(
                    command=command,
                    args=args,
                )

                # 创建客户端连接
                stdio_transport = await stdio_client(server_params).__aenter__()
                read_stream, write_stream = stdio_transport

                session = await ClientSession(read_stream, write_stream).__aenter__()
                await session.initialize()

                _MCP_SERVERS[server_name] = {
                    "session": session,
                    "stdio": stdio_transport,
                    "transport": "stdio",
                }

            elif transport == "sse":
                if not url:
                    return (1, "", "sse 传输方式需要 url 参数")

                sse_transport = await sse_client(url).__aenter__()
                read_stream, write_stream = sse_transport

                session = await ClientSession(read_stream, write_stream).__aenter__()
                await session.initialize()

                _MCP_SERVERS[server_name] = {
                    "session": session,
                    "stdio": sse_transport,
                    "transport": "sse",
                    "url": url,
                }
            else:
                return (1, "", f"不支持的传输方式: {transport}，支持: stdio/sse")

            return (0, f"✅ 已连接到 MCP Server: {server_name} (transport={transport})", "")

        result = asyncio.run(_connect())
        return result

    except ImportError:
        return (1, "", "❌ 缺少 mcp 库，请运行: pip install mcp")
    except Exception as e:
        return (1, "", f"❌ 连接失败: {str(e)}")


def _mcp_list_tools(server_name: str):
    """列出 MCP Server 可用工具"""
    import json

    if not server_name:
        return (1, "", "server_name 不能为空")

    if server_name not in _MCP_SERVERS:
        return (1, "", f"Server '{server_name}' 未连接，请先调用 action='connect'")

    try:
        import asyncio

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

        return asyncio.run(_list())

    except Exception as e:
        return (1, "", f"❌ 列出工具失败: {str(e)}")


def _mcp_call(server_name: str, tool_name: str, tool_args: dict):
    """调用 MCP 工具"""
    import json

    if not server_name:
        return (1, "", "server_name 不能为空")

    if not tool_name:
        return (1, "", "tool_name 不能为空")

    if server_name not in _MCP_SERVERS:
        return (1, "", f"Server '{server_name}' 未连接")

    try:
        import asyncio

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

        return asyncio.run(_call())

    except Exception as e:
        return (1, "", f"❌ 调用工具失败: {str(e)}")


def _mcp_disconnect(server_name: str):
    """断开 MCP Server 连接"""
    import json

    if not server_name:
        return (1, "", "server_name 不能为空")

    if server_name not in _MCP_SERVERS:
        return (0, json.dumps({"status": "not_connected", "server": server_name}), "")

    try:
        import asyncio

        async def _disconnect():
            server_info = _MCP_SERVERS[server_name]
            session = server_info["session"]
            stdio_transport = server_info["stdio"]

            try:
                await session.__aexit__(None, None, None)
                await stdio_transport.__aexit__(None, None, None)
            except Exception:
                pass  # 忽略关闭时的错误

            del _MCP_SERVERS[server_name]
            return (0, f"✅ 已断开连接: {server_name}", "")

        return asyncio.run(_disconnect())

    except Exception as e:
        return (1, "", f"❌ 断开连接失败: {str(e)}")


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
