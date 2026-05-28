# -*- coding: utf-8 -*-
# 2026-05-21 gen by tea_agent, Extracted from onlinesession._build_tools
"""工具构建与过滤模块 — 独立纯函数，管理与注入工具定义列表。

用法:
    from tea_agent.session_tools_builder import filter_tools
    filtered = filter_tools(all_tools, tool_filter=["toolkit_file"])
"""

ESSENTIAL_TOOLS = {"toolkit_memory", "toolkit_kb"}
"""始终保留的必要工具集合，不受 filter 影响。"""


def filter_tools(tools: list, tool_filter: list = None) -> list:
    """根据 tool_filter 过滤工具列表。

    Args:
        tools: 完整工具定义列表，每项含 {"function": {"name": str}}
        tool_filter: 要保留的工具名列表
            - None: 返回全部（直接引用，不拷贝）
            - []:   当前等效于 None（falsy 短路），保留全部
                    注意：如果期望 [] 表示「仅必要工具」，
                    需将调用方实现从 `if tool_filter:` 改为 `if tool_filter is not None:`
            - ["toolkit_a", ...]: 仅保留匹配项 + 必要工具 (memory, kb)

    Returns:
        list: 过滤后的工具列表
    """
    if tool_filter:
        allowed = set(tool_filter) | ESSENTIAL_TOOLS
        return [t for t in tools if t["function"]["name"] in allowed]
    return tools


def has_tool(tools: list, name: str) -> bool:
    """检查指定工具是否存在。"""
    return any(t.get("function", {}).get("name") == name for t in tools)
