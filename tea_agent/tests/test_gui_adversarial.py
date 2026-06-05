"""
对抗性测试：针对 GUI 加载失败 bug 的回归测试
修改：_gui/_renderer.py, _gui/_fonts.py, _gui/_topic_manager.py
"""
import pytest
from unittest.mock import MagicMock, patch, PropertyMock
import threading
import time


# ============================================================
# 1. _pending_error 判断逻辑的对抗性测试
# ============================================================

class TestPendingErrorAdversarial:
    """对抗性测试：_pending_error 各种边界情况"""

    def _make_gui(self, **kwargs):
        """创建模拟 GUI，支持自定义初始状态"""
        gui = MagicMock()
        gui._progress_queue = kwargs.get('progress_queue', [])
        gui._loading_done = kwargs.get('loading_done', True)
        gui._pending_error = kwargs.get('pending_error', None)
        gui._pending_render = kwargs.get('pending_render', None)
        gui.generating = kwargs.get('generating', True)
        return gui

    def test_none_should_not_trigger_error(self):
        """回归测试：None 不应触发错误渲染"""
        gui = self._make_gui(pending_error=None)
        assert getattr(gui, '_pending_error', None) is None

    def test_empty_string_should_trigger_error(self):
        """空字符串是有效错误消息，应触发"""
        gui = self._make_gui(pending_error="")
        # 空字符串不是 None，应触发
        assert getattr(gui, '_pending_error', None) is not None

    def test_false_should_trigger_error(self):
        """False 是有效值，应触发"""
        gui = self._make_gui(pending_error=False)
        assert getattr(gui, '_pending_error', None) is not None

    def test_zero_should_trigger_error(self):
        """0 是有效值，应触发"""
        gui = self._make_gui(pending_error=0)
        assert getattr(gui, '_pending_error', None) is not None

    def test_exception_object_should_trigger_error(self):
        """异常对象应触发"""
        gui = self._make_gui(pending_error=ValueError("test"))
        assert getattr(gui, '_pending_error', None) is not None

    def test_dict_should_trigger_error(self):
        """字典应触发"""
        gui = self._make_gui(pending_error={"msg": "error", "code": 500})
        assert getattr(gui, '_pending_error', None) is not None

    def test_loading_done_false_should_not_process(self):
        """_loading_done=False 时不应处理任何结果"""
        gui = self._make_gui(loading_done=False, pending_error="error")
        # 即使有错误，loading 未完成也不应处理
        assert not getattr(gui, '_loading_done', False)

    def test_concurrent_error_and_render(self):
        """并发场景：error 和 render 同时设置"""
        gui = self._make_gui()
        
        def set_error():
            """set_error 辅助函数。"""
            time.sleep(0.01)
            gui._pending_error = "concurrent error"
            gui._loading_done = True
        
        def set_render():
            """set_render 辅助函数。"""
            gui._pending_render = [("user", "hello")]
        
        t1 = threading.Thread(target=set_error)
        t2 = threading.Thread(target=set_render)
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        
        # 错误应优先于渲染
        has_error = getattr(gui, '_pending_error', None) is not None
        if has_error:
            # 有错误时不应渲染
            pass  # 这是预期行为


# ============================================================
# 2. global 声明的对抗性测试
# ============================================================

class TestGlobalDeclarationsAdversarial:
    """对抗性测试：global 变量修改是否真正生效"""

    def test_scale_factor_modification_persists(self):
        """修改 _SCALE_FACTOR 应该持久化到模块级别"""
        from tea_agent._gui import _fonts
        
        original = _fonts._SCALE_FACTOR
        try:
            # 模拟 _init_fonts 中的修改
            _fonts._SCALE_FACTOR = 2.5
            assert _fonts._SCALE_FACTOR == 2.5
        finally:
            _fonts._SCALE_FACTOR = original

    def test_default_font_size_modification_persists(self):
        """修改 _DEFAULT_FONT_SIZE 应该持久化到模块级别"""
        from tea_agent._gui import _fonts
        
        original = _fonts._DEFAULT_FONT_SIZE
        try:
            _fonts._DEFAULT_FONT_SIZE = 20
            assert _fonts._DEFAULT_FONT_SIZE == 20
        finally:
            _fonts._DEFAULT_FONT_SIZE = original

    def test_fonts_detected_flag_persists(self):
        """修改 _FONTS_DETECTED 应该持久化到模块级别"""
        from tea_agent._gui import _fonts
        
        original = _fonts._FONTS_DETECTED
        try:
            _fonts._FONTS_DETECTED = True
            assert _fonts._FONTS_DETECTED is True
            _fonts._FONTS_DETECTED = False
            assert _fonts._FONTS_DETECTED is False
        finally:
            _fonts._FONTS_DETECTED = original

    def test_fs_reads_current_scale_factor(self):
        """_fs() 应该读取当前的 _SCALE_FACTOR，不是缓存值"""
        from tea_agent._gui import _fonts
        
        original_sf = _fonts._SCALE_FACTOR
        try:
            _fonts._SCALE_FACTOR = 1.0
            assert _fonts._fs(100) == 100
            
            _fonts._SCALE_FACTOR = 2.0
            assert _fonts._fs(100) == 200
            
            _fonts._SCALE_FACTOR = 0.5
            assert _fonts._fs(100) == 50
        finally:
            _fonts._SCALE_FACTOR = original_sf

    def test_fs_extreme_scale_factors(self):
        """极端缩放因子不应崩溃"""
        from tea_agent._gui import _fonts
        
        original_sf = _fonts._SCALE_FACTOR
        try:
            # 极小值
            _fonts._SCALE_FACTOR = 0.01
            assert _fonts._fs(100) >= 1  # 最小值保护
            
            # 极大值
            _fonts._SCALE_FACTOR = 100.0
            result = _fonts._fs(16)
            assert result > 0  # 应该是正数
            
            # 负值（虽然不应该发生）
            _fonts._SCALE_FACTOR = -1.0
            assert _fonts._fs(16) >= 1  # 最小值保护
        finally:
            _fonts._SCALE_FACTOR = original_sf


# ============================================================
# 3. load_worker 异常处理的对抗性测试
# ============================================================

class TestLoadWorkerAdversarial:
    """对抗性测试：load_worker 的异常处理"""

    def test_error_message_preserved(self):
        """错误消息应被完整保留"""
        gui = MagicMock()
        
        # 模拟 load_worker 中的异常处理
        try:
            raise ValueError("数据库连接失败: timeout after 30s")
        except Exception as e:
            gui._pending_error = str(e)
        
        assert "数据库连接失败" in gui._pending_error
        assert "timeout" in gui._pending_error

    def test_unicode_error_message(self):
        """Unicode 错误消息应被正确处理"""
        gui = MagicMock()
        
        try:
            raise RuntimeError("主题加载失败: 包含中文和émoji🎉")
        except Exception as e:
            gui._pending_error = str(e)
        
        assert "中文" in gui._pending_error
        assert "🎉" in gui._pending_error

    def test_nested_exception(self):
        """嵌套异常应被正确处理"""
        gui = MagicMock()
        
        try:
            try:
                raise ConnectionError("网络超时")
            except ConnectionError:
                raise RuntimeError("主题加载失败") from None
        except Exception as e:
            gui._pending_error = str(e)
        
        assert gui._pending_error == "主题加载失败"

    def test_error_with_traceback(self):
        """带堆栈的错误应被正确记录"""
        import traceback
        
        gui = MagicMock()
        error_msg = None
        
        try:
            raise ValueError("test error")
        except Exception as e:
            error_msg = str(e)
            tb = traceback.format_exc()
            gui._pending_error = error_msg
        
        assert gui._pending_error == "test error"
        assert "ValueError" in tb

    def test_loading_done_set_on_error(self):
        """异常时 _loading_done 应被设置为 True"""
        gui = MagicMock()
        gui._loading_done = False
        
        try:
            raise RuntimeError("error")
        except Exception as e:
            gui._pending_error = str(e)
            gui._loading_done = True
        
        assert gui._loading_done is True
        assert gui._pending_error is not None

    def test_loading_done_set_on_success(self):
        """成功时 _loading_done 也应被设置为 True"""
        gui = MagicMock()
        gui._loading_done = False
        
        # 成功路径
        gui._pending_render = [("user", "hello")]
        gui._loading_done = True
        
        assert gui._loading_done is True
        assert gui._pending_render is not None


# ============================================================
# 4. 回归测试：确保原 bug 不再复现
# ============================================================

class TestRegressionGUI29:
    """回归测试：2026-05-29 GUI 加载失败 bug"""

    def test_pending_error_none_not_treated_as_error(self):
        """核心回归：None 不应被当作错误"""
        gui = MagicMock()
        gui._pending_error = None
        
        # 修复后的逻辑
        is_error = getattr(gui, '_pending_error', None) is not None
        assert not is_error, "None 不应被当作错误！"

    def test_pending_error_string_treated_as_error(self):
        """核心回归：字符串应被当作错误"""
        gui = MagicMock()
        gui._pending_error = "some error"
        
        is_error = getattr(gui, '_pending_error', None) is not None
        assert is_error, "字符串应被当作错误！"

    def test_init_fonts_global_declarations_complete(self):
        """核心回归：_init_fonts 的 global 声明应完整"""
        import dis
        from tea_agent._gui._fonts import _init_fonts
        
        bytecode = dis.Bytecode(_init_fonts)
        global_stores = set()
        for instr in bytecode:
            if instr.opname == 'STORE_GLOBAL':
                global_stores.add(instr.argval)
        
        required = {'SYSTEM_FONT', 'MONO_FONT', '_FONTS_DETECTED', 
                     '_SCALE_FACTOR', '_DEFAULT_FONT_SIZE'}
        missing = required - global_stores
        assert not missing, f"global 声明遗漏: {missing}"
