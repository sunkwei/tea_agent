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
from pathlib import Path

_logging_initialized = False
_logging_debug = False
_file_warning_logged = False  # 文件日志降级告警只提示一次

def _ensure_file_handler(root_logger: logging.Logger) -> None:
    """(重)尝试挂载文件 handler；HOME 不可写时降级为"仅终端"，绝不抛异常。

    为什么每次 setup_logging 都重试而不是记住失败：HOME 不可写（只读 rootfs /
    权限受限 / 磁盘暂时满）在嵌入式设备上是**运行时状态**，之后可能恢复可写；
    一旦把失败也标记为"已初始化"，恢复后再也不会补上文件日志。

    去重规则是"已有任何文件 handler 就不再挂载"（而非比较当前 HOME 路径）：
    后者会在 HOME 变化时叠加 handler，导致同一条日志写进多个文件并持续泄漏
    handler。
    """
    global _file_warning_logged
    existing = [
        h for h in root_logger.handlers if isinstance(h, logging.handlers.TimedRotatingFileHandler)
    ]
    if existing:
        for h in existing:
            h.setLevel(logging.WARNING)
        return

    log_dir = Path.home() / ".tea_agent"
    log_file = str(log_dir / "tea_agent.log")
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
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
        _file_warning_logged = False  # 恢复成功后允许再次告警
    except Exception as e:
        # 只告警一次，避免每次 Agent 创建都刷屏
        if not _file_warning_logged:
            logging.getLogger("logging_setup").warning(
                "文件日志不可用，已降级为仅终端输出 | path=%s | error=%s: %s",
                log_file, type(e).__name__, e,
            )
            _file_warning_logged = True


def setup_logging(debug: bool = False, force: bool = False) -> None:
    """初始化双通道日志系统（幂等，多次调用安全）。

    在 AgentCore.__init__ 或 server 启动时尽早调用。文件日志不可写时
    自动降级为"仅终端"（不会抛出，不阻塞 Agent 启动），并在后续调用中重试。

    Args:
        debug: True 时终端输出 DEBUG 级别（否则 INFO），文件始终 WARNING
        force: 强制重新初始化（允许覆盖已有 handler）
    """
    global _logging_initialized, _logging_debug
    if _logging_initialized and not force:
        if debug != _logging_debug:
            _set_root_level(debug)
        # 文件 handler 可能因 HOME 暂不可写而缺失，这里补挂
        _ensure_file_handler(logging.getLogger())
        return

    _logging_debug = debug
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)  # root 全开，由 handler 各自过滤

    # ── 文件 handler（WARNING+，写入文件） ──
    # HOME 不可写（只读 rootfs / 权限受限 / 磁盘满）在嵌入式设备上很常见。
    # 日志失败**绝不能**阻止 Agent 启动，因此降级为"仅终端"而不是抛异常。
    _ensure_file_handler(root_logger)

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
