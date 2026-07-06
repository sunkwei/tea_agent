# version: 1.0.0
"""
Agent 后台服务模块

从 agent.py 提取的后台服务启动逻辑：
- 自进化引擎线程
- 定时任务调度器
"""

import logging
import os

logger = logging.getLogger("agent.background")


def start_self_evolve_thread(toolkit_root_dir: str) -> bool:
    """启动自进化引擎 daemon 线程。

    Args:
        toolkit_root_dir: toolkit 根目录路径

    Returns:
        是否成功启动
    """
    try:
        import importlib.util
        fpath = os.path.join(toolkit_root_dir, "toolkit_self_evolve_thread.py")
        if not os.path.exists(fpath):
            return False
        spec = importlib.util.spec_from_file_location("_self_evolve_thread_startup", fpath)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        result = mod.toolkit_self_evolve_thread("start")
        if result.get("status") == "started":
            logger.info("🔄 自进化引擎已自动启动")
            return True
    except Exception as e:
        logger.debug(f"自进化引擎启动跳过: {e}")
    return False


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
