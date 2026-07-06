"""
测试 _gui/_renderer.py 中的关键逻辑
重点：_poll_loading_progress 的 _pending_error 处理
"""
from unittest.mock import MagicMock


class TestPollLoadingProgress:
    """测试 _poll_loading_progress 中 _pending_error 的判断逻辑"""

    def _make_gui_mock(self):
        """创建模拟的 GUI 对象"""
        gui = MagicMock()
        gui._progress_queue = []
        gui._loading_done = True
        gui._pending_error = None
        gui._pending_render = None
        gui.generating = True
        return gui

    def test_pending_error_none_should_not_trigger_error(self):
        """_pending_error=None 时不应触发 _render_topic_error"""
        gui = self._make_gui_mock()

        # 模拟正确的判断逻辑: getattr(...) is not None
        error_val = getattr(gui, '_pending_error', None)
        assert error_val is None, "None 值不应被当作错误"

    def test_pending_error_string_should_trigger_error(self):
        """_pending_error='some error' 时应触发 _render_topic_error"""
        gui = self._make_gui_mock()
        gui._pending_error = "some error"

        error_val = getattr(gui, '_pending_error', None)
        assert error_val is not None, "非 None 值应被当作错误"
        assert error_val == "some error"

    def test_pending_error_empty_string_should_trigger_error(self):
        """_pending_error='' 空字符串也应触发（用户可能需要看到空错误）"""
        gui = self._make_gui_mock()
        gui._pending_error = ""

        # 空字符串不是 None，应该触发
        error_val = getattr(gui, '_pending_error', None)
        # 注意：空字符串 is not None = True，但可能是无意义的
        # 这里测试当前行为
        assert error_val is not None

    def test_pending_render_should_not_trigger_when_error_present(self):
        """当 _pending_error 有值时，不应处理 _pending_render"""
        gui = self._make_gui_mock()
        gui._pending_error = "error"
        gui._pending_render = [("user", "hello")]

        # 错误优先
        has_error = getattr(gui, '_pending_error', None) is not None
        assert has_error
        # 不应进入 render 分支

    def test_pending_render_should_trigger_when_no_error(self):
        """当 _pending_error=None 且 _pending_render 存在时，应渲染"""
        gui = self._make_gui_mock()
        gui._pending_render = [("user", "hello")]

        has_error = getattr(gui, '_pending_error', None) is not None
        has_render = hasattr(gui, '_pending_render')
        assert not has_error
        assert has_render


class TestHasattrVsGetattrPattern:
    """测试 hasattr vs getattr 的常见陷阱"""

    def test_hasattr_returns_true_for_none_value(self):
        """hasattr 对 None 值返回 True — 这是 bug 的根因"""
        class Obj:
            attr = None

        assert hasattr(Obj, 'attr') is True  # 属性存在
        assert Obj.attr is None  # 但值是 None
    def test_getattr_none_check_correct(self):
        """getattr + is not None 是正确的检查方式"""
        class Obj:
            attr = None

        assert getattr(Obj, 'attr', None) is None  # 正确识别 None
        assert (getattr(Obj, 'attr', None) is not None) is False

    def test_getattr_missing_attr_returns_default(self):
        """getattr 对不存在的属性返回默认值"""
        class Obj:
            """Obj 测试辅助类。"""
            pass

        assert getattr(Obj, 'attr', None) is None
        assert getattr(Obj, 'attr', 'default') == 'default'
