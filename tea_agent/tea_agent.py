"""
TeaAgent 向后兼容模块

已迁移到 tea_agent.agent.Agent (lightweight 模式)
此模块保留用于向后兼容，新代码请使用 Agent 类。
"""

import warnings
from tea_agent.agent import Agent

warnings.warn(
    "tea_agent.tea_agent.TeaAgent 已迁移到 tea_agent.Agent，"
    "请更新导入: from tea_agent import Agent",
    DeprecationWarning,
    stacklevel=2
)

# 向后兼容：TeaAgent 现在是 Agent 的 lightweight 模式
TeaAgent = Agent
