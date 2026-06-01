"""
session_tools_builder 单元测试 — 独立纯函数 filter_tools()。

关键契约：
- tool_filter=None 时，返回全部（直接引用，不拷贝）
- tool_filter 提供列表时，仅保留 filter 中的工具 + 必要工具 (memory, kb)
- 必要工具始终可用，不受 filter 影响
- 空 filter [] 等效于无 filter（falsy 短路），保留全部工具
"""

import pytest
from tea_agent.session_tools_builder import filter_tools, has_tool, ESSENTIAL_TOOLS

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
    """tool_filter=None 时：全部工具返回"""

    def test_no_filter_keeps_all_tools(self):
        result = filter_tools(SAMPLE_TOOLS)
        assert len(result) == len(SAMPLE_TOOLS)

    def test_no_filter_reuses_same_list(self):
        """直接引用（非拷贝），性能优化"""
        result = filter_tools(SAMPLE_TOOLS)
        assert result is SAMPLE_TOOLS

    def test_no_filter_essential_still_present(self):
        result = filter_tools(SAMPLE_TOOLS)
        names = {t["function"]["name"] for t in result}
        assert "toolkit_memory" in names
        assert "toolkit_kb" in names


class TestFilterToolsWithFilter:
    """tool_filter 提供列表时：仅保留指定工具 + 必要工具"""

    def test_filter_keeps_matching_tools(self):
        result = filter_tools(SAMPLE_TOOLS, tool_filter=["toolkit_file", "toolkit_exec"])
        names = {t["function"]["name"] for t in result}
        assert "toolkit_file" in names
        assert "toolkit_exec" in names

    def test_filter_excludes_unmatched_tools(self):
        result = filter_tools(SAMPLE_TOOLS, tool_filter=["toolkit_file"])
        names = {t["function"]["name"] for t in result}
        assert "toolkit_exec" not in names
        assert "toolkit_search" not in names
        assert "toolkit_pkg" not in names

    def test_essential_tools_always_present(self):
        result = filter_tools(SAMPLE_TOOLS, tool_filter=["toolkit_file"])
        names = {t["function"]["name"] for t in result}
        assert "toolkit_memory" in names
        assert "toolkit_kb" in names

    def test_essential_tools_in_filter_duplicated(self):
        result = filter_tools(SAMPLE_TOOLS, tool_filter=["toolkit_memory", "toolkit_file"])
        mem_count = sum(1 for t in result if t["function"]["name"] == "toolkit_memory")
        assert mem_count == 1, "memory 不应重复"

    def test_empty_filter_keeps_all(self):
        """当前行为：空 filter [] 等效于无 filter（falsy 短路）"""
        result = filter_tools(SAMPLE_TOOLS, tool_filter=[])
        assert len(result) == len(SAMPLE_TOOLS)

    def test_filter_nonexistent_tool_graceful(self):
        result = filter_tools(SAMPLE_TOOLS, tool_filter=["toolkit_nonexistent"])
        names = {t["function"]["name"] for t in result}
        assert "toolkit_nonexistent" not in names
        assert "toolkit_memory" in names
        assert "toolkit_kb" in names


class TestFilterToolsEdgeCases:
    """边界和异常情况"""

    def test_empty_tool_list(self):
        result = filter_tools([], tool_filter=["toolkit_file"])
        assert result == []

    def test_filter_is_none_keeps_all(self):
        tools = [{"function": {"name": "toolkit_a"}}, {"function": {"name": "toolkit_b"}}]
        result = filter_tools(tools, tool_filter=None)
        assert len(result) == 2

    def test_has_tool_found(self):
        assert has_tool(SAMPLE_TOOLS, "toolkit_file") is True

    def test_has_tool_not_found(self):
        assert has_tool(SAMPLE_TOOLS, "toolkit_nonexistent") is False

    def test_has_tool_empty_list(self):
        assert has_tool([], "anything") is False

    def test_essential_tools_never_removed_by_filter(self):
        """验证 ESSENTIAL_TOOLS 确实包含预期值"""
        assert "toolkit_memory" in ESSENTIAL_TOOLS
        assert "toolkit_kb" in ESSENTIAL_TOOLS
