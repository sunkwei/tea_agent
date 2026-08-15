"""
自进化流水线测试 — EvolutionTrigger / EvolutionAnalyzer / EvolutionActor
"""



class TestEvolutionTrigger:
    def test_no_events_initially(self):
        from tea_agent.agent_evolution import EvolutionTrigger
        t = EvolutionTrigger()
        assert t.get_pending_events() == []

    def test_success_does_not_trigger(self):
        from tea_agent.agent_evolution import EvolutionTrigger
        t = EvolutionTrigger()
        t.on_tool_result("toolkit_ok", {"ok": True}, 0.5)
        assert t.get_pending_events() == []

    def test_consecutive_failures_trigger(self):
        from tea_agent.agent_evolution import EvolutionTrigger
        t = EvolutionTrigger(consecutive_failure_threshold=2)
        t.on_tool_result("toolkit_fail", {"ok": False, "error": "e1"}, 1.0)
        assert t.get_pending_events() == []
        t.on_tool_result("toolkit_fail", {"ok": False, "error": "e2"}, 1.0)
        assert len(t.get_pending_events()) >= 1

    def test_clear_events(self):
        from tea_agent.agent_evolution import EvolutionTrigger
        t = EvolutionTrigger(consecutive_failure_threshold=1)
        t.on_tool_result("toolkit_fail", {"ok": False}, 1.0)
        assert len(t.get_pending_events()) >= 1
        t.clear_events()
        assert t.get_pending_events() == []

    def test_tuple_result_handling(self):
        from tea_agent.agent_evolution import EvolutionTrigger
        t = EvolutionTrigger(consecutive_failure_threshold=1)
        t.on_tool_result("toolkit_tuple", (0, "ok", ""), 0.5)
        assert t.get_pending_events() == []
        t.on_tool_result("toolkit_tuple", (1, "", "fail"), 0.5)
        assert len(t.get_pending_events()) >= 1

    def test_different_tools_independent(self):
        from tea_agent.agent_evolution import EvolutionTrigger
        t = EvolutionTrigger(consecutive_failure_threshold=3)
        for _ in range(3):
            t.on_tool_result("toolkit_a", {"ok": False}, 1.0)
            t.on_tool_result("toolkit_b", {"ok": True}, 1.0)
        events = t.get_pending_events()
        assert len(events) >= 1
        assert events[0]["tool"] == "toolkit_a"


class TestEvolutionAnalyzer:
    def test_empty_events_returns_empty(self):
        from tea_agent.agent_evolution import EvolutionAnalyzer
        a = EvolutionAnalyzer()
        assert a.analyze([]) == []

    def test_no_client_returns_empty(self):
        from tea_agent.agent_evolution import EvolutionAnalyzer
        a = EvolutionAnalyzer()
        assert a.analyze([{"type": "tool_failure", "tool": "test"}]) == []


class TestEvolutionActor:
    def test_no_toolkit_returns_error(self):
        from tea_agent.agent_evolution import EvolutionActor
        actor = EvolutionActor(None)
        results = actor.execute([{"action": "evolve_code", "target": "x.py", "reason": "fix"}])
        assert len(results) == 1
        assert results[0]["ok"] is False

    def test_empty_actions(self):
        from tea_agent.agent_evolution import EvolutionActor
        from tea_agent.tlk import Toolkit
        tk = Toolkit()
        actor = EvolutionActor(tk)
        assert actor.execute([]) == []

    def test_unknown_action(self):
        from tea_agent.agent_evolution import EvolutionActor
        from tea_agent.tlk import Toolkit
        tk = Toolkit()
        actor = EvolutionActor(tk)
        results = actor.execute([{"action": "none", "target": "", "reason": ""}])
        assert results == []


class TestEvolutionActorEvolveCode:
    """evolve_code 闭环 — LLM 生成新代码 + toolkit_self_evolve 护栏。"""

    def _noop_tk(self):
        """返回一个没有 toolkit_file/自进化工具的假 toolkit（只登记 self_evolve）。"""
        class _Tk:
            func_map = {"toolkit_self_evolve": object()}
            def call_tool(self, name, **kwargs):
                if name == "toolkit_file":
                    return "def foo():\n    return 1\n"
                if name == "toolkit_self_evolve":
                    return {"ok": True, "file": kwargs.get("file_path"),
                            "layers": {"tests": "3/3"}}
                raise KeyError(name)
        return _Tk()

    def _fake_llm(self, new_code: str):
        class _Msg:
            content = new_code
        class _Choice:
            message = _Msg()
        class _Resp:
            choices = [_Choice()]
        class _Completions:
            def create(self, **kwargs):
                return _Resp()
        class _Chat:
            completions = _Completions()
        class _Client:
            chat = _Chat()
        return _Client()

    def test_evolve_code_without_client_skips(self):
        """缺 cheap LLM → 保守跳过，不提交占位符。"""
        from tea_agent.agent_evolution import EvolutionActor
        actor = EvolutionActor(self._noop_tk())
        r = actor._evolve_code("ui.py", "high frequency failure")
        assert r["ok"] is False
        assert "跳过" in r["error"] or "LLM" in r["error"]

    def test_evolve_code_empty_llm_output_skips(self):
        """LLM 无有效输出 → 跳过。"""
        from tea_agent.agent_evolution import EvolutionActor
        actor = EvolutionActor(self._noop_tk(), self._fake_llm(""))
        r = actor._evolve_code("ui.py", "fix crash")
        assert r["ok"] is False

    def test_evolve_code_identical_output_skips(self):
        """LLM 输出与原文相同 → 不提交（避免无效自改）。"""
        from tea_agent.agent_evolution import EvolutionActor
        # 让 LLM 原样返回文件内容（含 markdown 围栏剥离后仍相同）
        actor = EvolutionActor(self._noop_tk(),
                               self._fake_llm("```python\ndef foo():\n    return 1\n```"))
        r = actor._evolve_code("ui.py", "no real fix")
        assert r["ok"] is False

    def test_evolve_code_with_client_goes_through_guards(self):
        """LLM 产出有效新代码 → 走 toolkit_self_evolve 护栏并返回 ok。"""
        from tea_agent.agent_evolution import EvolutionActor
        actor = EvolutionActor(self._noop_tk(),
                               self._fake_llm("def foo():\n    return 42\n"))
        r = actor._evolve_code("ui.py", "make it return 42")
        assert r["ok"] is True

    def test_evolve_code_no_toolkit_returns_error(self):
        """toolkit 缺 self_evolve → 返回错误。"""
        from tea_agent.agent_evolution import EvolutionActor
        actor = EvolutionActor(None, self._fake_llm("def foo():\n    return 42\n"))
        r = actor._evolve_code("ui.py", "fix")
        assert r["ok"] is False
        assert "toolkit_self_evolve" in r["error"]
