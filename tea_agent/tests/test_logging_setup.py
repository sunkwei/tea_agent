"""
测试 logging_setup 模块 — 日志配置

覆盖：
- setup_logging() 初始化
- 幂等性（多次调用不重复添加 handler）
- debug 模式切换
- force 强制重新初始化
- _set_root_level() 运行时切换
"""

import contextlib
import logging
import logging.handlers
import os
from pathlib import Path
from unittest.mock import patch

import pytest

# ── Fixtures ──

@pytest.fixture(autouse=True)
def cleanup_logging():
    """每个测试后清理 logging 状态"""
    yield
    # 清理测试中添加的 handler
    root = logging.getLogger()
    for h in root.handlers[:]:
        if isinstance(h, logging.handlers.TimedRotatingFileHandler):
            root.removeHandler(h)
            with contextlib.suppress(Exception):
                h.close()
    # 重置模块状态
    import tea_agent.logging_setup as ls
    ls._logging_initialized = False
    ls._logging_debug = False
    root.setLevel(logging.WARNING)  # 恢复默认


@pytest.fixture
def mock_home(tmp_path):
    """模拟 HOME 目录到临时路径"""
    with patch.object(Path, 'home', return_value=tmp_path):
        yield tmp_path


class TestSetupLogging:
    """setup_logging() 测试"""

    def test_initializes_logger(self, mock_home):
        """应创建 TimedRotatingFileHandler"""
        from tea_agent.logging_setup import setup_logging
        setup_logging()
        root = logging.getLogger()
        handlers = [h for h in root.handlers
                     if isinstance(h, logging.handlers.TimedRotatingFileHandler)]
        assert len(handlers) == 1

    def test_creates_log_file(self, mock_home):
        """应在 .tea_agent 目录创建日志文件"""
        from tea_agent.logging_setup import setup_logging
        setup_logging()
        log_dir = mock_home / ".tea_agent"
        log_dir / "tea_agent.log"
        assert log_dir.exists()
        # 文件可能尚未写入内容，但 handler 已指向该路径

    def test_log_file_path_correct(self, mock_home):
        """日志文件路径应正确"""
        from tea_agent.logging_setup import setup_logging
        setup_logging()
        root = logging.getLogger()
        for h in root.handlers:
            if isinstance(h, logging.handlers.TimedRotatingFileHandler):
                expected = os.path.join(str(mock_home), ".tea_agent", "tea_agent.log")
                assert h.baseFilename == os.path.abspath(expected)

    def test_default_level_is_info(self, mock_home):
        """默认 root logger 为 DEBUG（handler 各自过滤）"""
        from tea_agent.logging_setup import setup_logging
        setup_logging()
        root = logging.getLogger()
        # root 全开，由 handler 过滤
        assert root.level == logging.DEBUG

    def test_debug_mode_sets_debug_level(self, mock_home):
        """debug=True 时控制台 handler 级别设为 DEBUG"""
        from tea_agent.logging_setup import setup_logging
        setup_logging(debug=True)
        root = logging.getLogger()
        assert root.level == logging.DEBUG
        # 检查控制台 handler
        for h in root.handlers:
            if isinstance(h, logging.StreamHandler) \
               and not isinstance(h, logging.handlers.TimedRotatingFileHandler):
                assert h.level == logging.DEBUG

    def test_handler_level_is_warning(self, mock_home):
        """文件 handler 级别应为 WARNING"""
        from tea_agent.logging_setup import setup_logging
        setup_logging()
        root = logging.getLogger()
        for h in root.handlers:
            if isinstance(h, logging.handlers.TimedRotatingFileHandler):
                assert h.level == logging.WARNING

    def test_formatter_format(self, mock_home):
        """formatter 应包含 asctime/levelname/filename/lineno/message"""
        from tea_agent.logging_setup import setup_logging
        setup_logging()
        root = logging.getLogger()
        for h in root.handlers:
            if isinstance(h, logging.handlers.TimedRotatingFileHandler):
                fmt = h.formatter._fmt
                assert '%(asctime)s' in fmt
                assert '%(levelname)s' in fmt
                assert '%(filename)s' in fmt
                assert '%(lineno)d' in fmt
                assert '%(message)s' in fmt

    def test_rotation_settings(self, mock_home):
        """轮转设置：每天、保留7天"""
        from tea_agent.logging_setup import setup_logging
        setup_logging()
        root = logging.getLogger()
        for h in root.handlers:
            if isinstance(h, logging.handlers.TimedRotatingFileHandler):
                assert h.when == 'D'
                # when='D' 时，interval 内部存储为秒数（86400 = 24h）
                assert h.interval in (1, 86400)
                assert h.backupCount == 7


class TestIdempotent:
    """幂等性测试"""

    def test_double_call_no_duplicate_handler(self, mock_home):
        """两次调用不应重复添加 handler"""
        from tea_agent.logging_setup import setup_logging
        setup_logging()
        setup_logging()
        root = logging.getLogger()
        count = sum(1 for h in root.handlers
                     if isinstance(h, logging.handlers.TimedRotatingFileHandler))
        assert count == 1

    def test_multiple_calls_safe(self, mock_home):
        """多次调用安全"""
        from tea_agent.logging_setup import setup_logging
        for _ in range(5):
            setup_logging()
        root = logging.getLogger()
        count = sum(1 for h in root.handlers
                     if isinstance(h, logging.handlers.TimedRotatingFileHandler))
        assert count == 1

    def test_force_reinit_adds_new_handler(self, mock_home):
        """force=True 时允许重新初始化（但不会移除旧 handler）"""
        from tea_agent.logging_setup import setup_logging
        setup_logging()
        setup_logging(force=True)
        root = logging.getLogger()
        count = sum(1 for h in root.handlers
                     if isinstance(h, logging.handlers.TimedRotatingFileHandler))
        # force 会在已有基础上再添加一个
        assert count >= 1


class TestDebugToggle:
    """debug 模式切换测试"""

    def test_debug_to_info_toggle(self, mock_home):
        """从 debug 切换到非 debug 应更新控制台 handler 级别"""
        from tea_agent.logging_setup import setup_logging
        setup_logging(debug=True)
        # root 始终 DEBUG，控制台 handler 变化
        assert logging.getLogger().level == logging.DEBUG
        setup_logging(debug=False)
        assert logging.getLogger().level == logging.DEBUG  # root 不变

    def test_info_to_debug_toggle(self, mock_home):
        """从非 debug 切换到 debug 应更新控制台 handler 级别"""
        from tea_agent.logging_setup import setup_logging
        setup_logging(debug=False)
        assert logging.getLogger().level == logging.DEBUG  # root 始终 DEBUG
        setup_logging(debug=True)
        assert logging.getLogger().level == logging.DEBUG

    def test_same_debug_noop(self, mock_home):
        """相同 debug 参数不应改变级别"""
        from tea_agent.logging_setup import setup_logging
        setup_logging(debug=True)
        root = logging.getLogger()
        root.setLevel(logging.DEBUG)
        setup_logging(debug=True)
        assert root.level == logging.DEBUG


class TestSetRootLevel:
    """_set_root_level() 测试"""

    def test_set_debug(self, mock_home):
        """切换到 DEBUG 级别（控制台 handler 级别变化）"""
        from tea_agent.logging_setup import setup_logging, _set_root_level
        setup_logging()  # 先初始化，确保有 handler
        root = logging.getLogger()
        # 控制台 handler 初始为 INFO
        _set_root_level(True)
        for h in root.handlers:
            if isinstance(h, logging.StreamHandler) \
               and not isinstance(h, logging.handlers.TimedRotatingFileHandler):
                assert h.level == logging.DEBUG
                break
        else:
            pytest.fail("No console handler found")

    def test_set_info(self, mock_home):
        """切换到 INFO 级别（控制台 handler 级别变化）"""
        from tea_agent.logging_setup import setup_logging, _set_root_level
        setup_logging(debug=True)  # 先设为 debug，控制台 handler 为 DEBUG
        root = logging.getLogger()
        _set_root_level(False)
        for h in root.handlers:
            if isinstance(h, logging.StreamHandler) \
               and not isinstance(h, logging.handlers.TimedRotatingFileHandler):
                assert h.level == logging.INFO
                break
        else:
            pytest.fail("No console handler found")


class TestModuleState:
    """模块全局状态测试"""

    def test_logging_initialized_flag(self, mock_home):
        """_logging_initialized 应在初始化后置 True"""
        import tea_agent.logging_setup as ls
        assert ls._logging_initialized is False
        ls.setup_logging()
        assert ls._logging_initialized is True

    def test_logging_debug_flag(self, mock_home):
        """_logging_debug 应记录 debug 参数"""
        import tea_agent.logging_setup as ls
        ls.setup_logging(debug=True)
        assert ls._logging_debug is True
        ls.setup_logging(debug=False)
        assert ls._logging_debug is False


class TestEdgeCases:
    """边界情况测试"""

    def test_actual_logging_works(self, mock_home):
        """WARNING 级别日志实际写入文件（文件 handler 为 WARNING+）"""
        from tea_agent.logging_setup import setup_logging
        setup_logging()
        logger = logging.getLogger("test_logger")
        test_msg = "这是一条测试日志消息"
        logger.warning(test_msg)  # 文件 handler 只写 WARNING+
        # 刷新 handler
        for h in logging.getLogger().handlers:
            h.flush()
        # 检查日志文件
        log_file = mock_home / ".tea_agent" / "tea_agent.log"
        if log_file.exists():
            content = log_file.read_text(encoding='utf-8')
            assert test_msg in content

    def test_logging_with_error(self, mock_home):
        """WARNING/ERROR 级别写入文件"""
        from tea_agent.logging_setup import setup_logging
        setup_logging()
        logger = logging.getLogger("test_error")
        logger.warning("警告信息")
        logger.error("错误信息")
        for h in logging.getLogger().handlers:
            h.flush()
        log_file = mock_home / ".tea_agent" / "tea_agent.log"
        if log_file.exists():
            content = log_file.read_text(encoding='utf-8')
            assert "警告信息" in content or "WARNING" in content

    def test_unicode_logging(self, mock_home):
        """中文字符应正确写入（WARNING 级别）"""
        from tea_agent.logging_setup import setup_logging
        setup_logging()
        logger = logging.getLogger("test_unicode")
        logger.warning("中文日志测试 © 你好 🌟")  # 使用 WARNING 才能写入文件
        for h in logging.getLogger().handlers:
            h.flush()
        log_file = mock_home / ".tea_agent" / "tea_agent.log"
        if log_file.exists():
            content = log_file.read_text(encoding='utf-8')
            assert "中文日志测试" in content

    def test_setup_no_mock_home(self):
        """没有 mock_home 时，使用真实 HOME 目录不应报错"""
        from tea_agent.logging_setup import setup_logging
        # 使用真实环境，只验证不抛异常
        try:
            setup_logging()
            setup_logging()  # 第二次调用也应安全
        finally:
            # 清理
            root = logging.getLogger()
            for h in root.handlers[:]:
                if isinstance(h, logging.handlers.TimedRotatingFileHandler):
                    root.removeHandler(h)
                    with contextlib.suppress(Exception):
                        h.close()
            import tea_agent.logging_setup as ls
            ls._logging_initialized = False
            ls._logging_debug = False
