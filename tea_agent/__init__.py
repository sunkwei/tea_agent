# 2026-05-06 gen by claude, 添加包版本号
# 2026-05-29 refactor: 统一 Agent 类

__version__ = "0.9.20"

__all__ = [
    "Agent",
    "TeaAgent",      # 向后兼容别名
    "BaseChatSession",
    "OnlineToolSession",
    "Storage",
    "load_config",
    "get_config",
    "save_config",
]

from tea_agent.agent import Agent, TeaAgent
