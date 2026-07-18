"""
日志配置模块 — 双通道日志输出。

功能：
- 终端（控制台）:  输出 INFO 及以上级别，彩色等级标识
- 文件:            $HOME/.tea_agent/tea_agent.log，输出 WARNING 及以上级别
- 文件按天轮转，保留最近7天
- 格式: {asctime}, {levelname}, {filename}:{lineno}, {message}
- debug=True 时终端放开 DEBUG，但文件仍保持 WARNING
"""

import logging
import logging.handlers
import os
from pathlib import Path

_logging_initialized = False
_logging_debug = False

def setup_logging(debug: bool = False, force: bool = False) -> None:
    """初始化双通道日志系统（幂等，多次调用安全）。

    在 AgentCore.__init__ 或 server 启动时尽早调用。

    Args:
        debug: True 时终端输出 DEBUG 级别（否则 INFO），文件始终 WARNING
        force: 强制重新初始化（允许覆盖已有 handler）
    """
    global _logging_initialized, _logging_debug
    if _logging_initialized and not force:
        if debug != _logging_debug:
            _set_root_level(debug)
        return

    _logging_debug = debug
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)  # root 全开，由 handler 各自过滤

    log_dir = Path.home() / ".tea_agent"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = str(log_dir / "tea_agent.log")

    # ── 文件 handler（WARNING+，写入文件） ──
    _file_handler_exists = any(
        isinstance(h, logging.handlers.TimedRotatingFileHandler)
        and h.baseFilename == os.path.abspath(log_file)
        for h in root_logger.handlers
    )
    if not _file_handler_exists:
        file_handler = logging.handlers.TimedRotatingFileHandler(
            filename=log_file,
            when='D',
            interval=1,
            backupCount=7,
            encoding='utf-8',
        )
        file_handler.setLevel(logging.WARNING)
        file_handler.setFormatter(logging.Formatter(
            '%(asctime)s, %(levelname)s, %(filename)s:%(lineno)d, %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S',
        ))
        root_logger.addHandler(file_handler)
    else:
        for h in root_logger.handlers:
            if isinstance(h, logging.handlers.TimedRotatingFileHandler):
                h.setLevel(logging.WARNING)

    # ── 控制台 handler（INFO+ 或 DEBUG+，输出到终端） ──
    _console_handler_exists = any(
        isinstance(h, logging.StreamHandler)
        and not isinstance(h, logging.handlers.TimedRotatingFileHandler)
        for h in root_logger.handlers
    )
    if not _console_handler_exists:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.DEBUG if debug else logging.INFO)
        console_handler.setFormatter(logging.Formatter(
            '%(asctime)s [%(levelname)-7s] %(name)s: %(message)s',
            datefmt='%H:%M:%S',
        ))
        root_logger.addHandler(console_handler)
    else:
        for h in root_logger.handlers:
            if isinstance(h, logging.StreamHandler) \
               and not isinstance(h, logging.handlers.TimedRotatingFileHandler):
                h.setLevel(logging.DEBUG if debug else logging.INFO)

    _logging_initialized = True

def _set_root_level(debug: bool) -> None:
    """运行时切换控制台日志级别，不重启进程。

    文件 handler 始终保持 WARNING，不受此函数影响。
    """
    global _logging_debug
    _logging_debug = debug
    target = logging.DEBUG if debug else logging.INFO
    root_logger = logging.getLogger()
    for h in root_logger.handlers:
        if isinstance(h, logging.StreamHandler) \
           and not isinstance(h, logging.handlers.TimedRotatingFileHandler):
            h.setLevel(target)

def set_debug(enabled: bool = True) -> None:
    """运行时开关终端 DEBUG 日志（已初始化后调用）。

    Args:
        enabled: True 在终端输出 DEBUG 级别，False 回到 INFO
    """
    global _logging_debug
    _setup_done = _logging_initialized
    if not _setup_done:
        setup_logging(debug=False)
    _set_root_level(enabled)
