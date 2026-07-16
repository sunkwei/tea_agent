"""
SessionContext + SessionComponent 单元测试。

测试范围:
- SessionContext dataclass: 默认字段值、自定义初始化
- SessionComponent: 抽象基类约束、save_agent_config 行为
"""

from dataclasses import fields
from unittest.mock import MagicMock

import pytest

# ============================================================
# SessionContext
# ============================================================

class TestSessionContextDefaults:
    """SessionContext 默认值契约测试"""

    def test_can_create_default(self):
        """可无参构造，所有字段应有默认值"""
        from tea_agent.session import SessionContext

        ctx = SessionContext()
        # 核心状态
        assert ctx.messages == []
        assert ctx.model == ""
        assert ctx.enable_thinking is True

        # 客户端
        assert ctx.client is None
        assert ctx.cheap_client is None
        assert ctx.cheap_model == ""

        # 工具相关
        assert ctx.toolkit is None
        assert ctx.tool_log is None
        assert ctx._rounds_collector == []

        # 存储与记忆
        assert ctx.storage is None
        assert ctx.memory is None
        assert ctx.pipeline is None

    def test_default_config_values(self):
        """配置参数应有合理的默认值"""
        from tea_agent.session import SessionContext

        ctx = SessionContext()
        assert ctx.keep_turns == 5
        assert ctx.max_tool_output == 128 * 1024
        assert ctx.max_assistant_content == 128 * 1024
        assert ctx.max_context_tokens == 0
        assert ctx.memory_extraction_threshold == 2
        assert ctx.memory_dedup_threshold == 0.3
        assert ctx.supports_vision is False
        assert ctx.supports_reasoning is True
        assert ctx.disable_summary is False
        assert ctx.no_stream_chunk is False
        assert ctx.extra_iterations_on_continue == 5

    def test_runtime_state_defaults(self):
        """运行时状态字段应有合理的默认值"""
        from tea_agent.session import SessionContext

        ctx = SessionContext()
        assert ctx._thinking_supported is True
        assert ctx._cheap_thinking_supported is None
        assert ctx._last_usage == {
            "total_tokens": 0, "prompt_tokens": 0, "completion_tokens": 0,
            "prompt_cache_hit_tokens": 0, "prompt_cache_miss_tokens": 0,
        }
        assert ctx._last_cheap_usage == {
            "total_tokens": 0, "prompt_tokens": 0, "completion_tokens": 0,
            "prompt_cache_hit_tokens": 0, "prompt_cache_miss_tokens": 0,
        }
        assert ctx._injected_memories_text == ""
        assert ctx._injected_memories == []
        assert ctx._injected_os_info_text == ""
        assert ctx._os_info_injected is False
        assert ctx._history_summary == ""
        assert ctx._semantic_summary == ""
        assert ctx._tool_chain_summary == ""
        assert ctx._level2 == []
        assert ctx._current_trace is None
        assert ctx.reflection_manager is None
        assert ctx._current_mode == "mixed"

    def test_usage_dicts_are_independent_instances(self):
        """_last_usage 和 _last_cheap_usage 应是独立的 dict 实例"""
        from tea_agent.session import SessionContext

        ctx = SessionContext()
        ctx._last_usage["total_tokens"] = 100
        assert ctx._last_cheap_usage["total_tokens"] == 0
        assert ctx._last_usage is not ctx._last_cheap_usage

    def test_rounds_collector_is_independent_per_instance(self):
        """_rounds_collector 应是每个实例独立的 list"""
        from tea_agent.session import SessionContext

        ctx1 = SessionContext()
        ctx2 = SessionContext()
        ctx1._rounds_collector.append("item1")
        assert len(ctx1._rounds_collector) == 1
        assert len(ctx2._rounds_collector) == 0


class TestSessionContextCustomInit:
    """SessionContext 自定义初始化"""

    def test_custom_values(self):
        """传入关键字参数应正确覆盖默认值"""
        from tea_agent.session import SessionContext

        ctx = SessionContext(
            model="gpt-4o",
            enable_thinking=False,
            keep_turns=10,
            supports_vision=True,
            disable_summary=True,
            extra_iterations_on_continue=8,
        )
        assert ctx.model == "gpt-4o"
        assert ctx.enable_thinking is False
        assert ctx.keep_turns == 10
        assert ctx.supports_vision is True
        assert ctx.disable_summary is True
        assert ctx.extra_iterations_on_continue == 8

    def test_custom_messages(self):
        """传入消息列表应正确存储"""
        from tea_agent.session import SessionContext

        msgs = [{"role": "user", "content": "hi"}]
        ctx = SessionContext(messages=msgs)
        assert ctx.messages is msgs
        assert len(ctx.messages) == 1

    def test_dataclass_field_types_match(self):
        """字段类型标注应与实际类型一致"""
        from tea_agent.session import SessionContext

        ctx = SessionContext()
        # 验证 keep_turns 是 int
        assert isinstance(ctx.keep_turns, int)
        assert isinstance(ctx.memory_dedup_threshold, float)
        assert isinstance(ctx.enable_thinking, bool)
        assert isinstance(ctx.model, str)
        assert isinstance(ctx.messages, list)

    def test_all_fields_have_defaults(self):
        """所有字段都应有默认值（无 required 字段）"""
        from tea_agent.session import SessionContext

        for f in fields(SessionContext):
            # 检查 default 或 default_factory
            has_default = (
                f.default is not None
                or f.default_factory is not None
                or f.default is not None
            )
            # default 为 None 或 '' 或 False 也算有默认值
            if f.name == "_last_usage":
                # field with default_factory
                assert f.default_factory is not None or f.default is not None, f"Field {f.name} has no default"
            else:
                assert f.default is not None or f.default_factory is not None, f"Field {f.name} has no default"


# ============================================================
# SessionComponent
# ============================================================

class TestSessionComponentAbstract:
    """SessionComponent 抽象基类约束"""

    def test_cannot_instantiate_directly(self):
        """SessionComponent 是抽象类，不能直接实例化"""
        from tea_agent.session import SessionComponent, SessionContext

        ctx = SessionContext()
        with pytest.raises(TypeError, match="abstract"):
            SessionComponent(ctx)

    def test_concrete_subclass_must_implement_abstract_methods(self):
        """子类必须实现 name 和 initialize"""
        from tea_agent.session import SessionComponent, SessionContext

        ctx = SessionContext()
        # name 和 initialize 均为 abstract
        with pytest.raises(TypeError, match="abstract"):
            type("BadComponent", (SessionComponent,), {})(ctx)

    def test_can_create_concrete_subclass(self):
        """实现所有抽象方法后可正常实例化"""
        from tea_agent.session import SessionComponent, SessionContext

        ctx = SessionContext()

        class GoodComponent(SessionComponent):
            @property
            def name(self) -> str:
                return "good"

            def initialize(self) -> None:
                self._initialized = True

        comp = GoodComponent(ctx)
        assert comp.ctx is ctx
        assert comp.name == "good"
        comp.initialize()
        assert comp._initialized is True


class TestSaveAgentConfig:
    """SessionComponent.save_agent_config 测试"""

    @pytest.fixture
    def component(self):
        """提供最小化 SessionComponent 子类"""
        from tea_agent.session import SessionComponent, SessionContext

        ctx = SessionContext()

        class DummyComponent(SessionComponent):
            @property
            def name(self) -> str:
                return "dummy"

            def initialize(self) -> None:
                pass

        return DummyComponent(ctx)

    def test_no_storage_does_nothing(self, component):
        """没有 storage 时应静默返回"""
        component.ctx.storage = None
        # 不应抛出异常
        component.save_agent_config({"max_iterations": 10})

    def test_with_object_config(self, component):
        """传入有 __dict__ 的对象时应提取关键字段"""
        storage = MagicMock()
        component.ctx.storage = storage

        config = MagicMock()
        config.max_iterations = 30
        config.keep_turns = 8
        config.max_tool_output = 256 * 1024
        config.enable_thinking = True

        component.save_agent_config(config)

        storage.add_config_change.assert_called_once()
        call_kwargs = storage.add_config_change.call_args[1]
        assert call_kwargs["key"] == "agent_config_update"
        new_value_str = call_kwargs["new_value"]
        # 验证包含关键字段
        assert "max_iterations" in new_value_str
        assert "keep_turns" in new_value_str
        assert "max_tool_output" in new_value_str
        assert "30" in new_value_str
        assert "8" in new_value_str

    def test_with_dict_config(self, component):
        """传入 dict 时应直接使用"""
        storage = MagicMock()
        component.ctx.storage = storage

        config = {
            "max_iterations": 50,
            "keep_turns": 6,
            "enable_thinking": False,
        }
        component.save_agent_config(config)

        storage.add_config_change.assert_called_once()
        call_kwargs = storage.add_config_change.call_args[1]
        assert "50" in call_kwargs["new_value"]
        assert "6" in call_kwargs["new_value"]

    def test_filters_none_values(self, component):
        """值为 None 的字段应被过滤掉"""
        storage = MagicMock()
        component.ctx.storage = storage

        config = MagicMock()
        config.max_iterations = None  # 应被过滤
        config.keep_turns = 5
        config.max_tool_output = None  # 应被过滤
        config.enable_thinking = True

        component.save_agent_config(config)

        new_value_str = storage.add_config_change.call_args[1]["new_value"]
        assert "keep_turns" in new_value_str
        assert "5" in new_value_str
        # None 值的字段不应出现
        assert "max_iterations" not in new_value_str or "None" not in new_value_str.split("max_iterations")[1].split(",")[0]

    def test_with_non_config_type_does_nothing(self, component):
        """传入非 dict 且无 __dict__ 的对象应静默返回"""
        storage = MagicMock()
        component.ctx.storage = storage

        # 传入字符串（既不是 dict 也没有 __dict__）
        component.save_agent_config("not_a_config")
        storage.add_config_change.assert_not_called()

    def test_storage_exception_is_caught(self, component):
        """storage.add_config_change 抛异常时应被捕获"""
        storage = MagicMock()
        storage.add_config_change.side_effect = RuntimeError("storage error")
        component.ctx.storage = storage

        config = MagicMock()
        config.max_iterations = 20
        config.keep_turns = 5
        config.max_tool_output = 128 * 1024
        config.enable_thinking = None

        # 不应传播异常
        component.save_agent_config(config)

    def test_empty_dict_does_not_call_storage(self, component):
        """所有字段均为 None 时不应调用 storage"""
        storage = MagicMock()
        component.ctx.storage = storage

        config = MagicMock()
        config.max_iterations = None
        config.keep_turns = None
        config.max_tool_output = None
        config.enable_thinking = None

        component.save_agent_config(config)
        storage.add_config_change.assert_not_called()
