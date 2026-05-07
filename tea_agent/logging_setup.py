"""
日志配置模块 — 统一文件日志输出。

功能：
- 日志文件: $HOME/.tea_agent/tea_agent.log
- 按天轮转，保留最近7天（即最新一周）
- 格式: {asctime}, {levelname}, {filename}:{lineno}, {message}
- 默认等级: INFO；模型调用、工具调用写入 DEBUG 级别
- 失败/异常写入 WARNING 级别
"""

import os
import logging
import logging.handlers
from pathlib import Path

_logging_initialized = False


def setup_logging(force: bool = False) -> None:
    """初始化文件日志系统（幂等，多次调用安全）。

    应在 AgentCore.__init__ 中尽早调用，确保所有后续 logger 都有文件 handler。
    """
    global _logging_initialized
    if _logging_initialized and not force:
        return

    log_dir = Path.home() / ".tea_agent"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = str(log_dir / "tea_agent.log")

    root_logger = logging.getLogger()
    # root 设 DEBUG 以允许各模块的 DEBUG 日志通过；控制台输出由各 handler 的 level 决定
    root_logger.setLevel(logging.DEBUG)

    # 检查是否已有同类型 handler，避免重复添加
    _handler_exists = False
    for h in root_logger.handlers:
        if isinstance(h, logging.handlers.TimedRotatingFileHandler) and h.baseFilename == os.path.abspath(log_file):
            _handler_exists = True
            break

    if not _handler_exists:
        # 文件 handler: DEBUG 级别（捕获所有 debug 及以上日志）
        file_handler = logging.handlers.TimedRotatingFileHandler(
            filename=log_file,
            when='D',           # 每天轮转
            interval=1,
            backupCount=7,      # 保留最近7天
            encoding='utf-8',
        )
        file_handler.setLevel(logging.DEBUG)

        file_formatter = logging.Formatter(
            '%(asctime)s, %(levelname)s, %(filename)s:%(lineno)d, %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S',
        )
        file_handler.setFormatter(file_formatter)
        root_logger.addHandler(file_handler)
    else:
        # 确保已有 handler 也是 DEBUG 级别
        for h in root_logger.handlers:
            if isinstance(h, logging.handlers.TimedRotatingFileHandler):
                h.setLevel(logging.DEBUG)

    _logging_initialized = True
