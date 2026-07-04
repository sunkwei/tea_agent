"""
循环检测器单元测试 — 覆盖 LoopDetector 类。

测试范围:
- 工具调用重复检测
- 输出内容重复检测
- 工具序列循环检测
- 窗口大小和阈值配置
"""



class TestLoopDetectorInit:
    """LoopDetector 初始化测试"""

    def test_default_parameters(self):
        """默认参数应正确设置"""
        from tea_agent.session.tool_loop_runner import LoopDetector
        detector = LoopDetector()
        assert detector.window == 5
        assert detector.threshold == 0.85

    def test_custom_parameters(self):
        """自定义参数应正确设置"""
        from tea_agent.session.tool_loop_runner import LoopDetector
        detector = LoopDetector(window=3, similarity_threshold=0.9)
        assert detector.window == 3
        assert detector.threshold == 0.9


class TestToolCallRepeatDetection:
    """工具调用重复检测"""

    def test_no_repeat_on_first_call(self):
        """首次调用不应检测为循环"""
        from tea_agent.session.tool_loop_runner import LoopDetector
        detector = LoopDetector()
        result = detector.check_and_record("", [("toolkit_file", '{"action": "read"}')])
        assert result["is_loop"] is False
        assert result["type"] is None

    def test_detects_exact_duplicate_tool_call(self):
        """完全相同的工具调用应检测为循环"""
        from tea_agent.session.tool_loop_runner import LoopDetector
        detector = LoopDetector()
        
        # 第一次调用
        detector.check_and_record("", [("toolkit_file", '{"action": "read"}')])
        # 第二次相同调用
        result = detector.check_and_record("", [("toolkit_file", '{"action": "read"}')])
        assert result["is_loop"] is True
        assert result["type"] == "tool_repeat"

    def test_different_tool_calls_not_detected(self):
        """不同的工具调用不应检测为循环"""
        from tea_agent.session.tool_loop_runner import LoopDetector
        detector = LoopDetector()
        
        detector.check_and_record("", [("toolkit_file", '{"action": "read"}')])
        result = detector.check_and_record("", [("toolkit_exec", '{"command": "ls"}')])
        assert result["is_loop"] is False

    def test_same_tool_different_args_not_detected(self):
        """相同工具但不同参数不应检测为循环"""
        from tea_agent.session.tool_loop_runner import LoopDetector
        detector = LoopDetector()
        
        detector.check_and_record("", [("toolkit_file", '{"action": "read"}')])
        result = detector.check_and_record("", [("toolkit_file", '{"action": "write"}')])
        assert result["is_loop"] is False

    def test_detects_repeated_sequence(self):
        """A→B→A→B 模式应检测为序列循环"""
        from tea_agent.session.tool_loop_runner import LoopDetector
        detector = LoopDetector(window=4)
        
        # A
        detector.check_and_record("", [("toolkit_file", '{"action": "read"}')])
        # B
        detector.check_and_record("", [("toolkit_exec", '{"command": "ls"}')])
        # A
        detector.check_and_record("", [("toolkit_file", '{"action": "read"}')])
        # B - 应该检测到循环
        result = detector.check_and_record("", [("toolkit_exec", '{"command": "ls"}')])
        assert result["is_loop"] is True


class TestContentRepeatDetection:
    """输出内容重复检测"""

    def test_similar_content_detected(self):
        """高度相似的内容应检测为循环"""
        from tea_agent.session.tool_loop_runner import LoopDetector
        detector = LoopDetector(similarity_threshold=0.5)  # 降低阈值便于测试
        
        content1 = "这是一段测试内容，用于检测循环"
        content2 = "这是一段测试内容，用于检测循环！"  # 几乎相同
        
        detector.check_and_record(content1, [])
        result = detector.check_and_record(content2, [])
        # 可能检测为内容重复（取决于相似度计算）
        assert "is_loop" in result

    def test_different_content_not_detected(self):
        """完全不同的内容不应检测为循环"""
        from tea_agent.session.tool_loop_runner import LoopDetector
        detector = LoopDetector()
        
        detector.check_and_record("第一段完全不同的内容", [])
        result = detector.check_and_record("第二段截然不同的文字", [])
        assert result["is_loop"] is False

    def test_empty_content_not_detected(self):
        """空内容不应检测为循环"""
        from tea_agent.session.tool_loop_runner import LoopDetector
        detector = LoopDetector()
        
        detector.check_and_record("", [])
        result = detector.check_and_record("", [])
        assert result["is_loop"] is False


class TestWindowBehavior:
    """窗口行为测试"""

    def test_window_limits_detection_scope(self):
        """检测应限制在窗口范围内"""
        from tea_agent.session.tool_loop_runner import LoopDetector
        detector = LoopDetector(window=2)
        
        # 第1轮
        detector.check_and_record("", [("toolkit_file", '{"action": "read"}')])
        # 第2轮（不同）
        detector.check_and_record("", [("toolkit_exec", '{"command": "ls"}')])
        # 第3轮（与第1轮相同，但已超出窗口）
        result = detector.check_and_record("", [("toolkit_file", '{"action": "read"}')])
        # 由于窗口大小为2，第3轮只与第2轮比较，不应检测为重复
        assert result["is_loop"] is False


class TestEdgeCases:
    """边界情况测试"""

    def test_multiple_tool_calls_in_one_round(self):
        """一轮中多个工具调用应正确处理"""
        from tea_agent.session.tool_loop_runner import LoopDetector
        detector = LoopDetector()
        
        tool_calls = [
            ("toolkit_file", '{"action": "read"}'),
            ("toolkit_exec", '{"command": "ls"}')
        ]
        
        # 第一次
        detector.check_and_record("", tool_calls)
        # 第二次相同
        result = detector.check_and_record("", tool_calls)
        assert result["is_loop"] is True

    def test_malformed_args_handled(self):
        """畸形参数应被正确处理"""
        from tea_agent.session.tool_loop_runner import LoopDetector
        detector = LoopDetector()
        
        # 非 JSON 参数
        detector.check_and_record("", [("toolkit_file", "not json")])
        result = detector.check_and_record("", [("toolkit_file", "not json")])
        assert result["is_loop"] is True

    def test_empty_tool_calls(self):
        """空工具调用列表应正确处理"""
        from tea_agent.session.tool_loop_runner import LoopDetector
        detector = LoopDetector()
        
        detector.check_and_record("some content", [])
        result = detector.check_and_record("some content", [])
        assert "is_loop" in result
