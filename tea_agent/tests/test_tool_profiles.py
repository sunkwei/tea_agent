"""
测试：工具档位系统（tool_profiles）— 按 max_context_tokens 自适应裁剪工具暴露量。

覆盖：
  #1 resolve_tool_profile 档位边界（0/未知、16K/32K/64K/200K 阈值）
  #2 显式 tool_profile 优先；非法档位回退 auto
  #3 档位嵌套不变式（nano ⊂ minimal ⊂ core ⊂ standard ⊂ full）
  #4 filter_tools_by_profile 过滤结果与顺序
  #5 config.ModelConfig.tool_profile 读写 round-trip
  #6 context_fragments AGENTS.md 预算按窗口缩放
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from tea_agent.config import ModelConfig  # noqa: E402
from tea_agent.context_fragments import _agents_md_budget  # noqa: E402
from tea_agent.tool_profiles import (  # noqa: E402
    PROFILE_TOOLS,
    filter_tools_by_profile,
    resolve_tool_profile,
)


# ═══ #1 档位边界 ═══════════════════════════════════════

class TestResolveToolProfile:
    """resolve_tool_profile：按 max_context_tokens 推导档位。"""

    def test_unknown_ctx_falls_back_full(self):
        """窗口未知（0/None）→ 保守 full，不误伤能力。"""
        assert resolve_tool_profile(0) == "full"
        assert resolve_tool_profile(None) == "full"
        assert resolve_tool_profile(-1) == "full"

    def test_below_16k_nano(self):
        assert resolve_tool_profile(8_000) == "nano"
        assert resolve_tool_profile(15_999) == "nano"

    def test_16k_minimal(self):
        assert resolve_tool_profile(16_000) == "minimal"
        assert resolve_tool_profile(31_999) == "minimal"

    def test_32k_core(self):
        assert resolve_tool_profile(32_000) == "core"
        assert resolve_tool_profile(63_999) == "core"

    def test_64k_standard(self):
        assert resolve_tool_profile(64_000) == "standard"
        assert resolve_tool_profile(199_999) == "standard"

    def test_200k_full(self):
        assert resolve_tool_profile(200_000) == "full"
        assert resolve_tool_profile(1_000_000) == "full"

    def test_explicit_profile_priority(self):
        """显式档位优先于窗口推导。"""
        assert resolve_tool_profile(1_000_000, explicit="nano") == "nano"
        assert resolve_tool_profile(8_000, explicit="full") == "full"

    def test_invalid_explicit_falls_back_to_auto(self):
        """非法档位回退 auto（按窗口推导）。"""
        assert resolve_tool_profile(64_000, explicit="bogus") == "standard"
        assert resolve_tool_profile(0, explicit="bogus") == "full"

    def test_case_insensitive(self):
        assert resolve_tool_profile(32_000, explicit="CORE") == "core"


# ═══ #3 档位嵌套不变式 ═════════════════════════════════

class TestProfileNesting:
    """档位须嵌套：nano ⊂ minimal ⊂ core ⊂ standard ⊂ full。"""

    def test_nesting_invariant(self):
        nano = set(PROFILE_TOOLS["nano"] or [])
        minimal = set(PROFILE_TOOLS["minimal"] or [])
        core = set(PROFILE_TOOLS["core"] or [])
        standard = set(PROFILE_TOOLS["standard"] or [])

        assert nano < minimal, "nano 必须是 minimal 的子集"
        assert minimal < core, "minimal 必须是 core 的子集"
        assert core < standard, "core 必须是 standard 的子集"

    def test_full_is_unfiltered(self):
        assert PROFILE_TOOLS["full"] is None

    def test_exec_file_edit_always_present(self):
        """降档不减最后保底：exec/file/edit 在所有非空档位中。"""
        essential = {"toolkit_exec", "toolkit_file", "toolkit_edit"}
        for profile in ("nano", "minimal", "core", "standard"):
            tools = set(PROFILE_TOOLS[profile] or [])
            assert essential <= tools, f"{profile} 缺少保底工具"


# ═══ #4 filter_tools_by_profile ═════════════════════════

class TestFilterToolsByProfile:
    """过滤结果与顺序。"""

    def _make_tools(self, names):
        return [{"type": "function", "function": {"name": n, "description": ""}} for n in names]

    def test_full_returns_all(self):
        tools = self._make_tools(["toolkit_a", "toolkit_b"])
        assert filter_tools_by_profile(tools, "full") == tools

    def test_nano_filters(self):
        tools = self._make_tools(
            ["toolkit_exec", "toolkit_file", "toolkit_edit", "toolkit_memory"]
        )
        result = filter_tools_by_profile(tools, "nano")
        names = [t["function"]["name"] for t in result]
        assert names == ["toolkit_exec", "toolkit_file", "toolkit_edit"]

    def test_empty_input(self):
        assert filter_tools_by_profile([], "nano") == []

    def test_unknown_profile_no_filter(self):
        tools = self._make_tools(["toolkit_a"])
        assert filter_tools_by_profile(tools, "not-a-profile") == tools


# ═══ #5 config round-trip ═══════════════════════════════

class TestConfigToolProfile:
    """ModelConfig.tool_profile 字段默认与读写。"""

    def test_default_auto(self):
        mc = ModelConfig()
        assert mc.tool_profile == "auto"

    def test_field_assignable(self):
        mc = ModelConfig()
        mc.tool_profile = "core"
        assert mc.tool_profile == "core"


# ═══ #6 context_fragments 预算缩放 ═════════════════════

class TestAgentsMdBudgetScaling:
    """AGENTS.md 字节预算按上下文窗口缩放。"""

    def test_default_16k(self):
        assert _agents_md_budget(0) == 16 * 1024
        assert _agents_md_budget(200_000) == 16 * 1024

    def test_small_window_small_budget(self):
        assert _agents_md_budget(8_000) == 2 * 1024
        assert _agents_md_budget(20_000) == 4 * 1024
        assert _agents_md_budget(40_000) == 8 * 1024
        assert _agents_md_budget(80_000) == 12 * 1024

    def test_monotonic(self):
        """已知窗口预算随窗口增大单调不降（未知窗口 0 单独处理：保守用默认 16KB）。"""
        sizes = [_agents_md_budget(x) for x in (8_000, 20_000, 40_000, 80_000, 200_000)]
        assert sizes == sorted(sizes)
