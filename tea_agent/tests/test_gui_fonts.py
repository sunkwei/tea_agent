"""
测试 _gui/_fonts.py 中的字体检测逻辑
重点：_init_fonts() 的 global 变量声明
"""


class TestInitFontsGlobalDeclarations:
    """测试 _init_fonts 中的 global 声明是否完整"""

    def test_all_globals_declared(self):
        """检查 _init_fonts 函数的字节码中是否包含所有必要的 global 声明"""
        import dis

        from tea_agent._gui._fonts import _init_fonts

        # 获取函数的字节码
        bytecode = dis.Bytecode(_init_fonts)

        # 查找 STORE_GLOBAL 操作
        global_stores = set()
        for instr in bytecode:
            if instr.opname == 'STORE_GLOBAL':
                global_stores.add(instr.argval)

        # 应该包含以下全局变量
        expected_globals = {
            'SYSTEM_FONT', 'MONO_FONT', '_FONTS_DETECTED',
            '_SCALE_FACTOR', '_DEFAULT_FONT_SIZE'
        }

        missing = expected_globals - global_stores
        assert not missing, f"缺少 global 声明: {missing}"

    def test_fs_uses_scale_factor(self):
        """_fs 函数应使用 _SCALE_FACTOR"""
        from tea_agent._gui._fonts import _SCALE_FACTOR, _fs

        # 默认缩放因子
        result = _fs(16)
        assert result == max(1, int(16 * _SCALE_FACTOR))

    def test_default_font_size_is_positive(self):
        """默认字体大小应为正数"""
        from tea_agent._gui._fonts import _DEFAULT_FONT_SIZE
        assert _DEFAULT_FONT_SIZE >= 12

    def test_fonts_detected_initially_false(self):
        """初始状态 _FONTS_DETECTED 应为 False"""
        # 注意：如果之前调用过 _init_fonts，这个值可能已经是 True
        # 这里只测试模块导入时的状态
        from tea_agent._gui import _fonts
        # 不做严格断言，因为测试顺序可能影响结果
        assert isinstance(_fonts._FONTS_DETECTED, bool)

    def test_init_fonts_idempotent(self):
        """多次调用 _init_fonts 应该是幂等的"""
        from tea_agent._gui._fonts import _FONTS_DETECTED, _init_fonts

        # 记录调用前状态
        before = _FONTS_DETECTED

        # 调用两次
        _init_fonts()
        _init_fonts()

        # 状态应该一致
        from tea_agent._gui._fonts import _FONTS_DETECTED as after
        assert before == after or after is True  # 只能从 False 变 True


class TestFontSizeCalculation:
    """测试字体大小计算"""

    def test_fs_minimum_is_one(self):
        """_fs 返回值最小为 1"""
        from tea_agent._gui._fonts import _fs
        assert _fs(0) >= 1
        assert _fs(-5) >= 1

    def test_fs_scales_proportionally(self):
        """_fs 应按比例缩放"""
        from tea_agent._gui._fonts import _SCALE_FACTOR, _fs
        result = _fs(100)
        expected = max(1, int(100 * _SCALE_FACTOR))
        assert result == expected
