"""
AgentCore 向后兼容模块

已迁移到 tea_agent.agent.Agent (full 模式)
此模块保留用于向后兼容，新代码请使用 Agent 类。
"""

import warnings
from tea_agent.agent import Agent

warnings.warn(
    "tea_agent.agent_core.AgentCore 已迁移到 tea_agent.Agent，"
    "请更新导入: from tea_agent import Agent",
    DeprecationWarning,
    stacklevel=2
)

# 向后兼容：AgentCore 现在是 Agent 的 full 模式
class AgentCore(Agent):
    """向后兼容类 — 内部使用 Agent(mode='full')。"""

    DRIFT_SUGGEST_THRESHOLD = 3

    def __init__(self, debug: bool = False, config_path=None,
                 disable_summary: bool = False, no_stream_chunk: bool = False):
        super().__init__(
            mode="full",
            config_path=config_path,
            debug=debug,
            disable_summary=disable_summary,
            no_stream_chunk=no_stream_chunk,
        )
