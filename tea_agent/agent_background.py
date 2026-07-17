# version: 1.1.0
"""
Agent 后台服务模块

从 agent.py 提取的后台服务启动逻辑：
- 定时任务调度器
"""

import logging

logger = logging.getLogger("agent.background")


def start_scheduler() -> bool:
    """启动定时任务调度器 daemon 线程。

    Returns:
        是否成功启动
    """
    try:
        from tea_agent.toolkit.toolkit_scheduler import toolkit_scheduler
        toolkit_scheduler("start")
        return True
    except Exception as e:
        logger.debug(f"定时任务调度器启动跳过: {e}")
    return False
