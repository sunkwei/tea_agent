"""
session_tools_builder 单元测试 — 自由奔放模式：filter_tools 不再过滤。

关键契约：
- filter_tools 始终返回全部工具（忽略 tool_filter 参数）
- has_tool 行为不变
- ESSENTIAL_TOOLS 已废弃（保留仅为兼容性）
"""

from tea_agent.onlinesession import filter_tools, has_tool

SAMPLE_TOOLS = [
    {"function": {"name": "toolkit_file", "description": "文件操作"}},
    {"function": {"name": "toolkit_exec", "description": "命令执行"}},
    {"function": {"name": "toolkit_memory", "description": "记忆管理"}},
    {"function": {"name": "toolkit_kb", "description": "知识库"}},
    {"function": {"name": "toolkit_search", "description": "搜索"}},
    {"function": {"name": "toolkit_pkg", "description": "包管理"}},
    {"function": {"name": "toolkit_gettime", "description": "时间"}},
]


class TestFilterToolsNoFilter:
    """自由奔放模式：始终返回全部工具"""

    def test_no_filter_keeps_all(self):
        result = filter_tools(SAMPLE_TOOLS)
        assert len(result) == len(SAMPLE_TOOLS)

    def test_filter_ignored_keeps_all(self):
        """即使指定 tool_filter，仍返回全部工具"""
        result = filter_tools(SAMPLE_TOOLS, tool_filter=["toolkit_file"])
        assert len(result) == len(SAMPLE_TOOLS)

    def test_filter_none_keeps_all(self):
        result = filter_tools(SAMPLE_TOOLS, tool_filter=None)
        assert len(result) == len(SAMPLE_TOOLS)

    def test_empty_filter_keeps_all(self):
        result = filter_tools(SAMPLE_TOOLS, tool_filter=[])
        assert len(result) == len(SAMPLE_TOOLS)

    def test_filter_nonexistent_keeps_all(self):
        result = filter_tools(SAMPLE_TOOLS, tool_filter=["toolkit_ghost"])
        assert len(result) == len(SAMPLE_TOOLS)


class TestFilterToolsEdgeCases:
    """边界情况"""

    def test_empty_list(self):
        result = filter_tools([], tool_filter=["toolkit_file"])
        assert result == []

    def test_has_tool_found(self):
        assert has_tool(SAMPLE_TOOLS, "toolkit_file") is True

    def test_has_tool_not_found(self):
        assert has_tool(SAMPLE_TOOLS, "toolkit_nonexistent") is False

    def test_has_tool_empty_list(self):
        assert has_tool([], "anything") is False
