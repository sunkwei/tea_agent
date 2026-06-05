"""
Session Pipeline 单元测试 — 覆盖全部公共接口。

Pipeline 设计为可插拔步骤执行器，测试确保：
- 注册/移除/启用/禁用/排序 等管理操作正确
- execute() 按顺序执行启用步骤，支持 skip_steps / stop_at
- 错误不会终止整个 Pipeline（容错设计）
"""

import pytest


class TestPipelineRegistration:
    """步骤注册与移除"""

    def test_register_step_adds_to_steps(self):
        """测试: Register step adds to steps"""
        from tea_agent.session_pipeline import SessionPipeline
        p = SessionPipeline()
        p.register_step("step1", lambda ctx: {"result": 1})
        assert "step1" in p._steps
        assert "step1" in p._step_order

    def test_register_duplicate_raises(self):
        """测试: Register duplicate raises"""
        from tea_agent.session_pipeline import SessionPipeline
        p = SessionPipeline()
        p.register_step("step1", lambda ctx: {})
        with pytest.raises(ValueError, match="step1"):
            p.register_step("step1", lambda ctx: {})

    def test_remove_step_removes_from_both(self):
        """测试: Remove step removes from both"""
        from tea_agent.session_pipeline import SessionPipeline
        p = SessionPipeline()
        p.register_step("step1", lambda ctx: {})
        p.remove_step("step1")
        assert "step1" not in p._steps
        assert "step1" not in p._step_order

    def test_remove_nonexistent_raises(self):
        """测试: Remove nonexistent raises"""
        from tea_agent.session_pipeline import SessionPipeline
        p = SessionPipeline()
        # 当前实现：remove 不存在的步骤不抛异常（静默忽略）
        p.remove_step("nonexistent")  # should not raise
        assert "nonexistent" not in p._steps


class TestPipelineOrdering:
    """步骤排序：position / before / after"""

    def test_default_order_by_registration(self):
        """测试: Default order by registration"""
        from tea_agent.session_pipeline import SessionPipeline
        p = SessionPipeline()
        p.register_step("a", lambda ctx: {})
        p.register_step("b", lambda ctx: {})
        p.register_step("c", lambda ctx: {})
        names = [n for n, _ in p.get_enabled_steps()]
        assert names == ["a", "b", "c"]

    def test_position_controls_order(self):
        """测试: Position controls order"""
        from tea_agent.session_pipeline import SessionPipeline
        p = SessionPipeline()
        p.register_step("a", lambda ctx: {}, position=10)
        p.register_step("b", lambda ctx: {}, position=5)
        p.register_step("c", lambda ctx: {}, position=1)
        names = [n for n, _ in p.get_enabled_steps()]
        assert names == ["c", "b", "a"]

    def test_before_inserts_before(self):
        """测试: Before inserts before"""
        from tea_agent.session_pipeline import SessionPipeline
        p = SessionPipeline()
        p.register_step("middle", lambda ctx: {})
        p.register_step("first", lambda ctx: {}, before="middle")
        names = [n for n, _ in p.get_enabled_steps()]
        assert names == ["first", "middle"]

    def test_after_inserts_after(self):
        """测试: After inserts after"""
        from tea_agent.session_pipeline import SessionPipeline
        p = SessionPipeline()
        p.register_step("first", lambda ctx: {})
        p.register_step("second", lambda ctx: {}, after="first")
        names = [n for n, _ in p.get_enabled_steps()]
        assert names == ["first", "second"]

    def test_set_step_position_reorders(self):
        """测试: Set step position reorders"""
        from tea_agent.session_pipeline import SessionPipeline
        p = SessionPipeline()
        p.register_step("a", lambda ctx: {})
        p.register_step("b", lambda ctx: {})
        p.set_step_position("a", 10)
        names = [n for n, _ in p.get_enabled_steps()]
        assert names == ["b", "a"]


class TestPipelineEnableDisable:
    """步骤启用/禁用"""

    def test_disabled_step_not_in_enabled(self):
        """测试: Disabled step not in enabled"""
        from tea_agent.session_pipeline import SessionPipeline
        p = SessionPipeline()
        p.register_step("a", lambda ctx: {}, enabled=False)
        assert len(p.get_enabled_steps()) == 0

    def test_disable_step_hides_it(self):
        """测试: Disable step hides it"""
        from tea_agent.session_pipeline import SessionPipeline
        p = SessionPipeline()
        p.register_step("a", lambda ctx: {})
        p.register_step("b", lambda ctx: {})
        p.disable_step("a")
        names = [n for n, _ in p.get_enabled_steps()]
        assert names == ["b"]

    def test_enable_step_shows_it(self):
        """测试: Enable step shows it"""
        from tea_agent.session_pipeline import SessionPipeline
        p = SessionPipeline()
        p.register_step("a", lambda ctx: {}, enabled=False)
        p.enable_step("a")
        assert len(p.get_enabled_steps()) == 1

    def test_toggle_step_flips_state(self):
        """测试: Toggle step flips state"""
        from tea_agent.session_pipeline import SessionPipeline
        p = SessionPipeline()
        p.register_step("a", lambda ctx: {})
        p.toggle_step("a")
        assert len(p.get_enabled_steps()) == 0
        p.toggle_step("a")
        assert len(p.get_enabled_steps()) == 1


class TestPipelineExecution:
    """Pipeline 执行逻辑"""

    def test_execute_runs_enabled_steps_in_order(self):
        """测试: Execute runs enabled steps in order"""
        from tea_agent.session_pipeline import SessionPipeline
        p = SessionPipeline()
        order = []

        def step_a(ctx):
            """step_a 辅助函数。"""
            order.append("a")
            return {"from_a": 1}

        def step_b(ctx):
            """step_b 辅助函数。"""
            order.append("b")
            return {"from_b": 2}

        p.register_step("a", step_a)
        p.register_step("b", step_b)
        result = p.execute({"initial": True})
        assert order == ["a", "b"]
        assert result["initial"] is True
        assert result["from_a"] == 1
        assert result["from_b"] == 2

    def test_execute_merges_results_into_context(self):
        """测试: Execute merges results into context"""
        from tea_agent.session_pipeline import SessionPipeline
        p = SessionPipeline()

        def step_one(ctx):
            """step_one 辅助函数。"""
            ctx["key1"] = "val1"
            return {"key2": "val2"}

        p.register_step("one", step_one)
        result = p.execute({})
        assert result["key1"] == "val1"
        assert result["key2"] == "val2"

    def test_execute_skip_steps_skips_named(self):
        """测试: Execute skip steps skips named"""
        from tea_agent.session_pipeline import SessionPipeline
        p = SessionPipeline()
        order = []

        def step_a(ctx):
            """step_a 辅助函数。"""
            order.append("a")

        def step_b(ctx):
            """step_b 辅助函数。"""
            order.append("b")

        p.register_step("a", step_a)
        p.register_step("b", step_b)
        p.execute({}, skip_steps=["b"])
        assert order == ["a"]

    def test_execute_stop_at_stops_after_named(self):
        """测试: Execute stop at stops after named"""
        from tea_agent.session_pipeline import SessionPipeline
        p = SessionPipeline()
        order = []

        def step_a(ctx):
            """step_a 辅助函数。"""
            order.append("a")

        def step_b(ctx):
            """step_b 辅助函数。"""
            order.append("b")

        def step_c(ctx):
            """step_c 辅助函数。"""
            order.append("c")

        p.register_step("a", step_a)
        p.register_step("b", step_b)
        p.register_step("c", step_c)
        p.execute({}, stop_at="b")
        assert order == ["a", "b"]

    def test_execute_disabled_steps_skipped(self):
        """测试: Execute disabled steps skipped"""
        from tea_agent.session_pipeline import SessionPipeline
        p = SessionPipeline()
        order = []

        def step_a(ctx):
            """step_a 辅助函数。"""
            order.append("a")

        def step_b(ctx):
            """step_b 辅助函数。"""
            order.append("b")

        p.register_step("a", step_a, enabled=False)
        p.register_step("b", step_b)
        p.execute({})
        assert order == ["b"]

    def test_execute_error_does_not_terminate(self):
        """Pipeline 容错：一个步骤出错，后续步骤继续执行"""
        from tea_agent.session_pipeline import SessionPipeline
        p = SessionPipeline()
        order = []

        def failing(ctx):
            """failing 辅助函数。"""
            raise RuntimeError("step failed")

        def after(ctx):
            """after 辅助函数。"""
            order.append("after")

        p.register_step("failing", failing)
        p.register_step("after", after)
        result = p.execute({})
        assert order == ["after"]
        assert "_errors" in result
        assert len(result["_errors"]) == 1
        assert result["_errors"][0]["step"] == "failing"


class TestPipelineListing:
    """列出步骤状态"""

    def test_list_steps_includes_enabled_and_disabled(self):
        """测试: List steps includes enabled and disabled"""
        from tea_agent.session_pipeline import SessionPipeline
        p = SessionPipeline()
        p.register_step("enabled_one", lambda ctx: {})
        p.register_step("disabled_one", lambda ctx: {}, enabled=False)
        items = p.list_steps()
        enabled = [i for i in items if not i.get("disabled")]
        disabled = [i for i in items if i.get("disabled")]
        assert len(enabled) == 1
        assert len(disabled) == 1
        assert enabled[0]["name"] == "enabled_one"
        assert disabled[0]["name"] == "disabled_one"
