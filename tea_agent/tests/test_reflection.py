# version: 1.0.0

"""
ReflectionManager 单元测试

测试范围:
- ToolCallRecord 数据类
- SessionTrace 数据类
- ReflectionManager 核心功能
"""

import pytest
import tempfile
import os
import shutil
import time


@pytest.fixture
def storage():
    """创建临时数据库"""
    from tea_agent.store import Storage

    tmpdir = tempfile.mkdtemp(prefix="tea_reflection_test_")
    db_path = os.path.join(tmpdir, "test.db")

    s = Storage(db_path)
    yield s
    time.sleep(0.3)
    try:
        s.close()
    except Exception:
        pass
    time.sleep(0.2)
    try:
        shutil.rmtree(tmpdir, ignore_errors=True)
    except Exception:
        pass


class TestToolCallRecord:
    """ToolCallRecord 数据类测试"""

    def test_init_defaults(self):
        """测试默认值"""
        from tea_agent.reflection import ToolCallRecord

        record = ToolCallRecord(name="test_tool", success=True)
        assert record.name == "test_tool"
        assert record.success is True
        assert record.error == ""
        assert record.duration_ms == 0.0

    def test_init_with_error(self):
        """测试带错误信息初始化"""
        from tea_agent.reflection import ToolCallRecord

        record = ToolCallRecord(
            name="test_tool",
            success=False,
            error="File not found",
            duration_ms=150.5
        )
        assert record.success is False
        assert record.error == "File not found"
        assert record.duration_ms == 150.5


class TestSessionTrace:
    """SessionTrace 数据类测试"""

    def test_init_defaults(self):
        """测试默认值"""
        from tea_agent.reflection import SessionTrace

        trace = SessionTrace()
        assert trace.topic_id == ""
        assert trace.user_msg == ""
        assert trace.tool_calls == []
        assert trace.total_iterations == 0
        assert trace.used_tools is False
        assert trace.interrupted is False
        assert trace.error is None
        assert trace.start_time == 0.0
        assert trace.end_time == 0.0

    def test_success_rate_empty(self):
        """测试空工具调用的成功率"""
        from tea_agent.reflection import SessionTrace

        trace = SessionTrace()
        assert trace.success_rate == 1.0

    def test_success_rate_all_success(self):
        """测试全部成功的成功率"""
        from tea_agent.reflection import SessionTrace, ToolCallRecord

        trace = SessionTrace()
        trace.tool_calls = [
            ToolCallRecord(name="t1", success=True),
            ToolCallRecord(name="t2", success=True),
        ]
        assert trace.success_rate == 1.0

    def test_success_rate_mixed(self):
        """测试混合成功/失败的成功率"""
        from tea_agent.reflection import SessionTrace, ToolCallRecord

        trace = SessionTrace()
        trace.tool_calls = [
            ToolCallRecord(name="t1", success=True),
            ToolCallRecord(name="t2", success=False),
            ToolCallRecord(name="t3", success=True),
        ]
        assert trace.success_rate == pytest.approx(2/3)

    def test_duration_seconds_no_end(self):
        """测试未结束的持续时间"""
        from tea_agent.reflection import SessionTrace

        trace = SessionTrace(start_time=100.0)
        assert trace.duration_seconds == 0.0

    def test_duration_seconds_with_end(self):
        """测试已结束的持续时间"""
        from tea_agent.reflection import SessionTrace

        trace = SessionTrace(start_time=100.0, end_time=105.0)
        assert trace.duration_seconds == 5.0


class TestReflectionManager:
    """ReflectionManager 核心功能测试"""

    def test_init(self, storage):
        """测试初始化"""
        from tea_agent.reflection import ReflectionManager

        manager = ReflectionManager(storage)
        assert manager.storage == storage
        assert manager._cheap_client is None
        assert manager._cheap_model == ""
        assert manager._pending_traces == []

    def test_start_trace(self, storage):
        """测试开始追踪"""
        from tea_agent.reflection import ReflectionManager

        manager = ReflectionManager(storage)
        trace = manager.start_trace(topic_id="topic1", user_msg="Hello")

        assert trace.topic_id == "topic1"
        assert trace.user_msg == "Hello"
        assert trace.start_time > 0
        assert len(manager._pending_traces) == 1
        assert manager._pending_traces[0] is trace

    def test_record_tool_call(self, storage):
        """测试记录工具调用"""
        from tea_agent.reflection import ReflectionManager

        manager = ReflectionManager(storage)
        trace = manager.start_trace(topic_id="topic1", user_msg="Hello")

        manager.record_tool_call(trace, name="toolkit_file", success=True, duration_ms=50.0)
        manager.record_tool_call(trace, name="toolkit_exec", success=False, error="Command failed")

        assert len(trace.tool_calls) == 2
        assert trace.tool_calls[0].name == "toolkit_file"
        assert trace.tool_calls[0].success is True
        assert trace.tool_calls[1].success is False
        assert trace.tool_calls[1].error == "Command failed"

    def test_finish_trace(self, storage):
        """测试结束追踪"""
        from tea_agent.reflection import ReflectionManager

        manager = ReflectionManager(storage)
        trace = manager.start_trace(topic_id="topic1", user_msg="Hello")

        time.sleep(0.1)
        manager.finish_trace(
            trace,
            total_iterations=5,
            used_tools=True,
            interrupted=False,
            error=None
        )

        assert trace.end_time > trace.start_time
        assert trace.total_iterations == 5
        assert trace.used_tools is True
        assert trace.interrupted is False
        assert trace.error is None

    def test_should_reflect_no_traces(self, storage):
        """测试无追踪时不触发反思"""
        from tea_agent.reflection import ReflectionManager

        manager = ReflectionManager(storage)
        assert manager.should_reflect() is False

    def test_should_reflect_with_failed_tool(self, storage):
        """测试有失败工具调用时触发反思"""
        from tea_agent.reflection import ReflectionManager

        manager = ReflectionManager(storage)
        trace = manager.start_trace(topic_id="topic1", user_msg="Hello")
        manager.record_tool_call(trace, name="tool1", success=False)

        assert manager.should_reflect() is True

    def test_should_reflect_accumulated_traces(self, storage):
        """测试累积 3+ 追踪时触发反思"""
        from tea_agent.reflection import ReflectionManager

        manager = ReflectionManager(storage)
        for i in range(3):
            manager.start_trace(topic_id=f"topic{i}", user_msg=f"Msg {i}")

        assert manager.should_reflect() is True

    def test_build_reflection_prompt(self, storage):
        """测试构建反思 prompt"""
        from tea_agent.reflection import ReflectionManager

        manager = ReflectionManager(storage)
        trace = manager.start_trace(topic_id="topic1", user_msg="Test message")
        manager.record_tool_call(trace, name="toolkit_file", success=True, duration_ms=100.0)
        manager.finish_trace(trace, total_iterations=3, used_tools=True)

        prompt_text, messages = manager.build_reflection_prompt()

        assert "topic1" in prompt_text
        assert "Test message" in prompt_text
        assert "toolkit_file" in prompt_text
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"

    def test_build_reflection_prompt_empty(self, storage):
        """测试空追踪时构建 prompt"""
        from tea_agent.reflection import ReflectionManager

        manager = ReflectionManager(storage)
        prompt_text, messages = manager.build_reflection_prompt()

        assert prompt_text == ""
        assert messages == []

    def test_parse_reflection_result_valid_json(self):
        """测试解析有效 JSON 结果"""
        from tea_agent.reflection import ReflectionManager

        manager = ReflectionManager(None)
        result_text = '{"summary": "Test summary", "details": "Test details"}'

        parsed = manager.parse_reflection_result(result_text)

        assert parsed is not None
        assert parsed["summary"] == "Test summary"
        assert parsed["details"] == "Test details"

    def test_parse_reflection_result_with_code_block(self):
        """测试解析带代码块的 JSON"""
        from tea_agent.reflection import ReflectionManager

        manager = ReflectionManager(None)
        result_text = '''```json
{"summary": "Test summary", "details": "Test details"}
```'''

        parsed = manager.parse_reflection_result(result_text)

        assert parsed is not None
        assert parsed["summary"] == "Test summary"

    def test_parse_reflection_result_invalid_json(self):
        """测试解析无效 JSON"""
        from tea_agent.reflection import ReflectionManager

        manager = ReflectionManager(None)
        result_text = 'This is not JSON'

        parsed = manager.parse_reflection_result(result_text)

        assert parsed is None

    def test_generate_reflection_no_client(self, storage):
        """测试无客户端时跳过反思生成"""
        from tea_agent.reflection import ReflectionManager

        manager = ReflectionManager(storage)
        manager.start_trace(topic_id="topic1", user_msg="Hello")

        result = manager.generate_reflection()
        assert result is None

    def test_multiple_traces(self, storage):
        """测试多个追踪"""
        from tea_agent.reflection import ReflectionManager

        manager = ReflectionManager(storage)

        manager.start_trace(topic_id="topic1", user_msg="Hello")
        manager.start_trace(topic_id="topic2", user_msg="World")

        assert len(manager._pending_traces) == 2
        assert manager._pending_traces[0].topic_id == "topic1"
        assert manager._pending_traces[1].topic_id == "topic2"
