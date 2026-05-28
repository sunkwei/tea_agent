# @2026-05-21 gen by tea_agent, 工具构建过滤契约测试
"""
_build_tools 契约测试 — 确保工具过滤逻辑正确。

关键契约：
- tool_filter=None 时，全部工具可用（直接引用，不拷贝）
- tool_filter 提供列表时，仅保留 filter 中的工具 + 必要工具 (memory, kb)
- 必要工具始终可用，不受 filter 影响
- 空 filter [] 等效于无 filter（falsy 短路），保留全部工具
  （若期望 [] 表示「仅必要工具」，需修改 _build_tools 实现）
"""

import pytest
from unittest.mock import MagicMock


# 模块级缓存 OnlineToolSession，避免重复 import
@pytest.fixture(scope="session")
def _session_class():
    from tea_agent.onlinesession import OnlineToolSession
    return OnlineToolSession


def _make_session(session_class, tools_list):
    """创建 mock OnlineToolSession，绑定真实 _build_tools 方法"""
    sess = MagicMock(spec=session_class)
    sess.tools_comp = MagicMock()
    sess.tools_comp.build_tools.return_value = tools_list
    sess._build_tools = session_class._build_tools.__get__(sess, session_class)
    return sess


# ══════════════════════════════════════════════════════════════
# 无 filter 测试
# ══════════════════════════════════════════════════════════════

class TestToolBuildNoFilter:
    """tool_filter=None 或省略时：全部工具可用"""

    TOOLS = [
        {"function": {"name": "toolkit_file", "description": "文件操作"}},
        {"function": {"name": "toolkit_exec", "description": "命令执行"}},
        {"function": {"name": "toolkit_memory", "description": "记忆管理"}},
        {"function": {"name": "toolkit_kb", "description": "知识库"}},
        {"function": {"name": "toolkit_search", "description": "搜索"}},
    ]

    @pytest.fixture
    def session(self, _session_class):
        return _make_session(_session_class, self.TOOLS)

    def test_no_filter_keeps_all_tools(self, session):
        """无 filter 时，所有工具都可用"""
        session._build_tools()
        names = {t["function"]["name"] for t in session.tools}
        assert names == {"toolkit_file", "toolkit_exec", "toolkit_memory",
                         "toolkit_kb", "toolkit_search"}

    def test_no_filter_reuses_same_list(self, session):
        """当前实现：无 filter 时 tools 直接引用 build_tools 返回值（非拷贝）"""
        session._build_tools()
        # 代码路径: `self.tools = tools`（直接赋值），所以是同一对象
        assert session.tools is session.tools_comp.build_tools.return_value


# ══════════════════════════════════════════════════════════════
# 有 filter 测试
# ══════════════════════════════════════════════════════════════

class TestToolBuildWithFilter:
    """tool_filter 提供列表时：仅保留指定工具 + 必要工具"""

    TOOLS = [
        {"function": {"name": "toolkit_file", "description": "文件操作"}},
        {"function": {"name": "toolkit_exec", "description": "命令执行"}},
        {"function": {"name": "toolkit_memory", "description": "记忆管理"}},
        {"function": {"name": "toolkit_kb", "description": "知识库"}},
        {"function": {"name": "toolkit_search", "description": "搜索"}},
        {"function": {"name": "toolkit_pkg", "description": "包管理"}},
        {"function": {"name": "toolkit_gettime", "description": "时间"}},
    ]

    @pytest.fixture
    def session(self, _session_class):
        return _make_session(_session_class, self.TOOLS)

    def test_filter_keeps_matching_tools(self, session):
        """filter 保留匹配的工具"""
        session._build_tools(tool_filter=["toolkit_file", "toolkit_exec"])
        names = {t["function"]["name"] for t in session.tools}
        assert "toolkit_file" in names
        assert "toolkit_exec" in names

    def test_filter_excludes_unmatched_tools(self, session):
        """filter 排除未匹配的工具"""
        session._build_tools(tool_filter=["toolkit_file"])
        names = {t["function"]["name"] for t in session.tools}
        assert "toolkit_exec" not in names
        assert "toolkit_search" not in names
        assert "toolkit_pkg" not in names

    def test_essential_tools_always_present(self, session):
        """必要工具 (memory, kb) 始终保留"""
        session._build_tools(tool_filter=["toolkit_file"])
        names = {t["function"]["name"] for t in session.tools}
        assert "toolkit_memory" in names, "memory 是必要工具"
        assert "toolkit_kb" in names, "kb 是必要工具"

    def test_essential_tools_in_filter_duplicated(self, session):
        """必要工具在 filter 中不重复"""
        session._build_tools(tool_filter=["toolkit_memory", "toolkit_file"])
        mem_count = sum(1 for t in session.tools
                        if t["function"]["name"] == "toolkit_memory")
        assert mem_count == 1, "memory 不应重复"

    def test_empty_filter_keeps_all(self, session):
        """当前行为：空 filter [] 等效于无 filter（falsy 短路到 else）→ 保留全部

        注意：如果期望 [] 表示「仅必要工具」，需要将 `if tool_filter:`
        改为 `if tool_filter is not None:`。
        """
        session._build_tools(tool_filter=[])
        names = {t["function"]["name"] for t in session.tools}
        # [] 是 falsy → if tool_filter: → False → else → 保留全部
        assert names == {"toolkit_file", "toolkit_exec", "toolkit_memory",
                         "toolkit_kb", "toolkit_search", "toolkit_pkg",
                         "toolkit_gettime"}

    def test_filter_nonexistent_tool_graceful(self, session):
        """filter 包含不存在的工具名时静默忽略"""
        session._build_tools(tool_filter=["toolkit_nonexistent"])
        names = {t["function"]["name"] for t in session.tools}
        assert "toolkit_nonexistent" not in names
        # 必要工具仍存在
        assert "toolkit_memory" in names
        assert "toolkit_kb" in names


# ══════════════════════════════════════════════════════════════
# 边界情况
# ══════════════════════════════════════════════════════════════

class TestToolBuildEdgeCases:
    """边界和异常情况"""

    @pytest.fixture
    def session(self, _session_class):
        return _make_session(_session_class, [])

    def test_empty_tool_list(self, session):
        """工具列表为空时，filter 不影响"""
        session.tools_comp.build_tools.return_value = []
        # 重新绑定（因为 fixture 中已绑定，但 return_value 在 fixture 后修改）
        session._build_tools(tool_filter=["toolkit_file"])
        assert session.tools == []

    def test_filter_is_none_keeps_all(self, session):
        """filter=None 等效于无 filter"""
        session.tools_comp.build_tools.return_value = [
            {"function": {"name": "toolkit_a"}},
            {"function": {"name": "toolkit_b"}},
        ]
        session._build_tools(tool_filter=None)
        assert len(session.tools) == 2
