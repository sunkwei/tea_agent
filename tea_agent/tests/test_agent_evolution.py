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
