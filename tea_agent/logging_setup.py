"""
日志配置模块 — 统一文件日志输出。

功能：
- 日志文件: $HOME/.tea_agent/tea_agent.log
- 按天轮转，保留最近7天（即最新一周）
- 格式: {asctime}, {levelname}, {filename}:{lineno}, {message}
- 默认等级: INFO（DEBUG 消息被过滤）；debug=True 时放开 DEBUG
- 失败/异常写入 WARNING 级别
"""

import os
import logging
import logging.handlers
from pathlib import Path

_logging_initialized = False
_logging_debug = False

def setup_logging(debug: bool = False, force: bool = False) -> None:
    """初始化文件日志系统（幂等，多次调用安全）。

    应在 AgentCore.__init__ 中尽早调用，确保所有后续 logger 都有文件 handler。

    Args:
        debug: True 时 root logger 级别设为 DEBUG，否则 INFO
        force: 强制重新初始化（允许覆盖已有 handler）
    """
    global _logging_initialized, _logging_debug
    if _logging_initialized and not force:
        # 即使已初始化，如果 debug 参数与当前不同，更新 root level
        if debug != _logging_debug:
            _set_root_level(debug)
        return

    _logging_debug = debug

    log_dir = Path.home() / ".tea_agent"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = str(log_dir / "tea_agent.log")

    root_logger = logging.getLogger()
    # root 默认 INFO，debug=True 时设为 DEBUG
    root_logger.setLevel(logging.DEBUG if debug else logging.INFO)

    # 检查是否已有同类型 handler，避免重复添加
    _handler_exists = False
    for h in root_logger.handlers:
        if isinstance(h, logging.handlers.TimedRotatingFileHandler) and h.baseFilename == os.path.abspath(log_file):
            _handler_exists = True
            break

    if not _handler_exists:
        # 文件 handler: DEBUG 级别（当 root 升级到 DEBUG 时自然捕获所有消息）
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

def _set_root_level(debug: bool) -> None:
    """运行时切换 root logger 级别，不重启进程。"""
    global _logging_debug
    _logging_debug = debug
    logging.getLogger().setLevel(logging.DEBUG if debug else logging.INFO)

def set_debug(enabled: bool = True) -> None:
    """运行时开关 DEBUG 日志（已初始化后调用）。

    Args:
        enabled: True 开启 DEBUG，False 回到 INFO
    """
    global _logging_debug
    _setup_done = _logging_initialized
    if not _setup_done:
        # 尚未初始化，先执行一次默认初始化再切换
        setup_logging(debug=False)
    _set_root_level(enabled)
