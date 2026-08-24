"""
session_tools_builder 单元测试 — filter_tools 核心集常驻 + 按需过滤。

关键契约：
- tool_filter=None/[] → 返回全部工具（默认行为不变）
- tool_filter 指定 → 返回 核心集 + 意图集（核心工具永不缺席）
- has_tool 行为不变
"""

from tea_agent.onlinesession import CORE_TOOLS, filter_tools, has_tool

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
    """未指定过滤：返回全部工具（默认行为）"""

    def test_no_filter_keeps_all(self):
        result = filter_tools(SAMPLE_TOOLS)
        assert len(result) == len(SAMPLE_TOOLS)

    def test_filter_none_keeps_all(self):
        result = filter_tools(SAMPLE_TOOLS, tool_filter=None)
        assert len(result) == len(SAMPLE_TOOLS)

    def test_empty_filter_keeps_all(self):
        result = filter_tools(SAMPLE_TOOLS, tool_filter=[])
        assert len(result) == len(SAMPLE_TOOLS)


class TestFilterToolsWithFilter:
    """指定意图工具集：核心集常驻 + 意图集追加"""

    def test_filter_narrows_to_core_plus_intent(self):
        """tool_filter 指定时只保留 核心集 + 意图集"""
        result = filter_tools(SAMPLE_TOOLS, tool_filter=["toolkit_pkg"])
        names = {t["function"]["name"] for t in result}
        # 意图工具
        assert "toolkit_pkg" in names
        # 核心工具常驻（exec/file/search 等均在 CORE_TOOLS 中）
        for core in ("toolkit_exec", "toolkit_file", "toolkit_search"):
            assert core in names
        # 非核心非意图工具被过滤
        assert "toolkit_gettime" not in names

    def test_filter_nonexistent_only_keeps_core(self):
        """意图工具不存在时仅保留核心集"""
        result = filter_tools(SAMPLE_TOOLS, tool_filter=["toolkit_ghost"])
        names = {t["function"]["name"] for t in result}
        assert "toolkit_ghost" not in names
        assert "toolkit_exec" in names

    def test_core_tools_defined(self):
        """CORE_TOOLS 应包含最基础的原语"""
        for t in ("toolkit_exec", "toolkit_file", "toolkit_edit", "toolkit_search"):
            assert t in CORE_TOOLS


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
