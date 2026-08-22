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


class TestEvolutionActorAutoExtend:
    """A/C/B：自主造工具 + 修剪 + 进化日志可观测。"""

    def _make_toolkit(self):
        """带 save/self_evolve 的假 toolkit。不写盘。"""
        class _Tk:
            saved = []
            func_map = {"toolkit_self_evolve": object()}
            def call_tool(self, name, **kwargs):
                if name == "toolkit_self_evolve":
                    return {"ok": True}
                if name == "toolkit_file":
                    return "def foo():\n    return 1\n"
                raise KeyError(name)
            def save(self, name, meta, pycode):
                self.saved.append((name, meta, pycode))
                return (0, "ok")
        return _Tk()

    def _fake_llm_json(self, payload: str):
        """fake LLM 返回给定 JSON 文本。"""
        class _Msg: content = payload
        class _Choice: message = _Msg()
        class _Resp: choices = [_Choice()]
        class _C:
            def create(self, **kwargs): return _Resp()
        class _Chat: completions = _C()
        class _Client: chat = _Chat()
        return _Client()

    def test_create_tool_valid_flow(self):
        """LLM 返回合法工具定义 → toolkit.save 被调用并返回 ok。"""
        import json as _json

        from tea_agent.agent_evolution import EvolutionActor
        tk = self._make_toolkit()
        payload = _json.dumps({
            "name": "toolkit_parse_table",
            "description": "解析表格",
            "properties": {"path": {"type": "string", "description": "路径"}},
            "required": ["path"],
            "pycode": (
                "def toolkit_parse_table(path=''):\n"
                "    if not path:\n"
                "        return {'ok': False, 'error': 'no path'}\n"
                "    return {'ok': True, 'parsed': True}\n"
                "\n\n"
                "def meta_toolkit_parse_table():\n"
                "    return {'type': 'function', 'function': {'name': 'toolkit_parse_table', 'description': '', 'parameters': {'type': 'object', 'properties': {}, 'required': []}}}\n"
            ),
        })
        actor = EvolutionActor(tk, self._fake_llm_json(payload))
        r = actor._create_tool("需要解析表格数据")
        assert r["ok"] is True, r
        assert r["tool"] == "toolkit_parse_table"
        assert len(tk.saved) == 1
        name, meta, pycode = tk.saved[0]
        assert name == "toolkit_parse_table"
        assert meta["type"] == "function"
        assert "def toolkit_parse_table" in pycode

    def test_create_tool_illegal_name_skips(self):
        """工具名不合法（非 toolkit_ 前缀）→ 不调 save。"""
        import json as _json

        from tea_agent.agent_evolution import EvolutionActor
        tk = self._make_toolkit()
        payload = _json.dumps({
            "name": "bad_name",
            "description": "x",
            "properties": {},
            "required": [],
            "pycode": "def bad_name():\n    return {'ok': True}\n",
        })
        actor = EvolutionActor(tk, self._fake_llm_json(payload))
        r = actor._create_tool("缺口")
        assert r["ok"] is False
        assert "非法工具名" in r["error"]
        assert tk.saved == []

    def test_create_tool_syntax_error_skips(self):
        """LLM 生成的 pycode 语法错误 → 跳过，不污染工具目录。"""
        import json as _json

        from tea_agent.agent_evolution import EvolutionActor
        tk = self._make_toolkit()
        payload = _json.dumps({
            "name": "toolkit_bad_syntax",
            "description": "x",
            "properties": {},
            "required": [],
            "pycode": "def toolkit_bad_syntax(:\n    return 1\n",
        })
        actor = EvolutionActor(tk, self._fake_llm_json(payload))
        r = actor._create_tool("缺口")
        assert r["ok"] is False
        assert "语法错误" in r["error"]
        assert tk.saved == []

    def test_create_tool_no_llm_skips(self):
        """无 cheap LLM → 保守跳过。"""
        from tea_agent.agent_evolution import EvolutionActor
        actor = EvolutionActor(self._make_toolkit())
        r = actor._create_tool("缺口")
        assert r["ok"] is False

    def test_execute_distributes_create_tool_and_prune(self, monkeypatch):
        """execute() 正确分发 create_tool / prune 到对应处理函数。"""
        import json as _json
        import os

        from tea_agent.agent_evolution import EvolutionActor
        # 日志写到工作区临时文件，避免污染 ~/.tea_agent
        monkeypatch.setenv("TEA_AGENT_EVOLUTION_LOG",
                           os.path.abspath("evlog_tmp_dist.json"))
        tk = self._make_toolkit()
        payload = _json.dumps({
            "name": "toolkit_new_a",
            "description": "d",
            "properties": {},
            "required": [],
            "pycode": "def toolkit_new_a():\n    return {'ok': True}\n",
        })
        actor = EvolutionActor(tk, self._fake_llm_json(payload))
        results = actor.execute([
            {"action": "create_tool", "target": "", "reason": "造一个工具"},
            {"action": "prune", "target": "no_such", "reason": ""},
            {"action": "none", "target": "", "reason": ""},
        ])
        acts = [r["action"] for r in results]
        assert acts == ["create_tool", "prune"]
        assert results[0]["ok"] is True
        assert results[1]["ok"] is True
        monkeypatch.delenv("TEA_AGENT_EVOLUTION_LOG", raising=False)

    def test_record_and_load_evolution_log(self, monkeypatch):
        """B: 进化日志追加与裁剪（注入环境变量指向临时文件）。

        关注：数据层 append/load/prune 逻辑。写文件系统，需本地环境执行。
        """
        import os
        import shutil

        from tea_agent import agent_evolution as ae
        # 用工作区临时文件（避 tmp_path sandbox 限制），走环境变量
        d = "evlog_test"
        os.makedirs(d, exist_ok=True)
        logpath = os.path.join(d, "evolution_log.json")
        monkeypatch.setenv("TEA_AGENT_EVOLUTION_LOG", os.path.abspath(logpath))
        try:
            ae._append_evolution_log({"action": "create_tool", "ok": True})
            ae._append_evolution_log({"action": "prune", "ok": True})
            log = ae._load_evolution_log()
            assert len(log) == 2
            assert log[0]["action"] == "create_tool"
            # 裁剪到 1 条
            r = ae._prune_evolution_log(1)
            assert r["ok"] is True and r["pruned"] == 1
            assert len(ae._load_evolution_log()) == 1
            assert ae._load_evolution_log()[0]["action"] == "prune"
        finally:
            shutil.rmtree(d, ignore_errors=True)
            monkeypatch.delenv("TEA_AGENT_EVOLUTION_LOG", raising=False)

    def test_prune_unknown_target_returns_ok(self):
        """prune 未知 target → 不删除任何东西，返回 ok。"""
        from tea_agent.agent_evolution import EvolutionActor
        actor = EvolutionActor(self._make_toolkit())
        r = actor._prune("something_else", "reason")
        assert r["ok"] is True and r["pruned"] == 0

    def test_prune_skills_keeps_recent(self, monkeypatch):
        """prune skills → 只删超龄 interrupt 技能，保留最近 keep 份。"""
        import os
        import shutil

        from tea_agent.agent_evolution import EvolutionActor
        d = "pruneskills_test"
        os.makedirs(d, exist_ok=True)
        # 造 5 个自动打断技能目录（含 SKILL.md 内容文件，模拟可删目录）
        for name in ("interrupt-avoid-toolkit_exec",
                     "interrupt-avoid-toolkit_edit",
                     "interrupt-avoid-toolkit_file",
                     "interrupt-avoid-toolkit_diff",
                     "interrupt-avoid-toolkit_search"):
            os.makedirs(os.path.join(d, name), exist_ok=True)
            open(os.path.join(d, name, "SKILL.md"), "w", encoding="utf-8").write("x\n")
        # 一个人工技能目录，不应被删
        os.makedirs(os.path.join(d, "writing-style"), exist_ok=True)
        open(os.path.join(d, "writing-style", "SKILL.md"), "w", encoding="utf-8").write("y\n")

        monkeypatch.setenv("TEA_AGENT_SKILLS_DIR", os.path.abspath(d))
        try:
            actor = EvolutionActor(self._make_toolkit())
            r = actor._prune("skills", "keep=3")
            assert r["ok"] is True
            # 5 个自动技能保留最晚 3 个（名字序），删除最早的 2 个
            assert r["pruned"] == 2, r
            remaining = [n for n in os.listdir(d) if n.startswith("interrupt-avoid-")]
            assert len(remaining) == 3
            assert "writing-style" in os.listdir(d)  # 人工技能不受影响
        finally:
            monkeypatch.delenv("TEA_AGENT_SKILLS_DIR", raising=False)
            shutil.rmtree(d, ignore_errors=True)
