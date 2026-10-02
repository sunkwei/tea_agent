"""invariants 运行时不变式注册表 + tool_shield 不变式闸门回归测试。

重点不是"检查器能跑"，而是**闸门真的兜底**：一旦不变式被将来的改动破坏，
evaluate 必须整体回退成"不屏蔽"，而不是照常屏蔽（那会让 Agent 失去能力）。
"""

from __future__ import annotations

import logging

import pytest

from tea_agent.invariants import (
    InvariantFailure,
    InvariantRegistry,
)
from tea_agent.tool_shield import (
    ALWAYS_PINNED,
    _check_no_data_no_shield,
    _check_observation_window,
    _check_self_heal_never_shielded,
    _check_self_heal_registered,
    evaluate,
)

NOW_KW = {}


# ═════════════ 注册表基础行为 ═════════════
class TestRegistry:
    def test_install_run_enforce(self):
        reg = InvariantRegistry()
        reg.install("demo.fail", "demo.point", lambda **_: "坏了")
        v = reg.run("demo.point")
        assert len(v) == 1 and v[0].invariant == "demo.fail" and v[0].detail == "坏了"
        with pytest.raises(InvariantFailure):
            reg.enforce("demo.point")

    def test_pass_returns_empty(self):
        reg = InvariantRegistry()
        reg.install("demo.ok", "demo.point", lambda **_: None)
        assert reg.run("demo.point") == []
        reg.enforce("demo.point")  # 不抛

    def test_broken_checker_becomes_violation_and_never_raises(self):
        reg = InvariantRegistry()

        def boom(**_):
            raise RuntimeError("检查器自己炸了")

        reg.install("demo.boom", "demo.point", boom)
        v = reg.run("demo.point")
        assert len(v) == 1 and "检查器异常" in v[0].detail

    def test_where_isolation_and_deterministic_order(self):
        reg = InvariantRegistry()
        reg.install("b", "p", lambda **_: "2")
        reg.install("a", "p", lambda **_: "1")
        reg.install("c", "other", lambda **_: "3")
        assert reg.names("p") == ("a", "b")
        assert [x.invariant for x in reg.run("p")] == ["a", "b"]

    def test_uninstall(self):
        reg = InvariantRegistry()
        reg.install("x", "p", lambda **_: "1")
        assert reg.uninstall("x") is True
        assert reg.uninstall("x") is False
        assert reg.run("p") == []


# ═════════════ 三条安全不变式检查器 ═════════════
class TestShieldInvariants:
    def test_no_data_no_shield(self):
        assert _check_no_data_no_shield(verdict={"shielded": {}}, usage={}) is None
        bad = _check_no_data_no_shield(verdict={"shielded": {"toolkit_x": "r"}}, usage={})
        assert bad and "toolkit_x" in bad

    def test_observation_window_blocks_zero_use_shielding(self):
        usage = {"toolkit_x": {"uses": 0, "last_used": None}}
        bad = _check_observation_window(
            verdict={"shielded": {"toolkit_x": "r"}}, usage=usage, observation_full=False)
        assert bad and "toolkit_x" in bad
        # 观测期已满 → 允许
        assert _check_observation_window(
            verdict={"shielded": {"toolkit_x": "r"}}, usage=usage, observation_full=True) is None

    def test_observation_window_exempts_manual_pin_off(self):
        usage = {"toolkit_x": {"uses": 0, "last_used": None, "pin": 0}}
        assert _check_observation_window(
            verdict={"shielded": {"toolkit_x": "手工屏蔽"}}, usage=usage,
            observation_full=False) is None

    def test_self_heal_never_shielded(self):
        assert _check_self_heal_never_shielded(verdict={"shielded": {"toolkit_zzz": "r"}}) is None
        bad = _check_self_heal_never_shielded(
            verdict={"shielded": {"toolkit_exec": "r", "toolkit_save": "r"}})
        assert bad and "toolkit_exec" in bad and "toolkit_save" in bad

    def test_self_heal_registered(self):
        assert _check_self_heal_registered(registered=set(ALWAYS_PINNED)) is None
        bad = _check_self_heal_registered(registered={"toolkit_exec"})
        assert bad and "toolkit_save" in bad
        assert _check_self_heal_registered(registered=None) is None


# ═════════════ 闸门兜底（回归：闸门失效时本类用例必须变红）════════════
class TestGuardFallback:
    def test_evaluate_passes_guard_untouched(self):
        v = evaluate({"toolkit_cold": {"uses": 3, "pin": None,
                                       "first_used": "2020-01-01T00:00:00+00:00",
                                       "last_used": "2020-01-01T00:00:00+00:00"}},
                     known_tools=["toolkit_cold"], idle_days=30)
        assert "toolkit_cold" in v["shielded"], "闲置工具应正常屏蔽（闸门不干扰正常判定）"

    def test_violation_rolls_back_all_shielding(self, monkeypatch):
        from tea_agent import tool_shield

        tool_shield._invariants.install(
            "test.hostile", "tool_shield.evaluate", lambda **_: "故意违例")
        try:
            v = evaluate({"toolkit_cold": {"uses": 3, "pin": None,
                                           "first_used": "2020-01-01T00:00:00+00:00",
                                           "last_used": "2020-01-01T00:00:00+00:00"}},
                         known_tools=["toolkit_cold", "toolkit_exec"], idle_days=30)
        finally:
            tool_shield._invariants.uninstall("test.hostile")
        assert v["shielded"] == {}, "违例时必须整体回退为不屏蔽"
        assert "toolkit_cold" in v["kept"], "被屏蔽者应并回 kept"
        assert "不变式违例" in v["reason"]

    def test_broken_guard_check_rolls_back_too(self):
        from tea_agent import tool_shield

        def boom(**_):
            raise RuntimeError("闸门检查器炸了")

        tool_shield._invariants.install("test.boom", "tool_shield.evaluate", boom)
        try:
            v = evaluate({"toolkit_cold": {"uses": 3, "pin": None,
                                           "first_used": "2020-01-01T00:00:00+00:00",
                                           "last_used": "2020-01-01T00:00:00+00:00"}},
                         known_tools=["toolkit_cold"], idle_days=30)
        finally:
            tool_shield._invariants.uninstall("test.boom")
        assert v["shielded"] == {}

    def test_guard_logs_error_on_violation(self, caplog):
        from tea_agent import tool_shield

        tool_shield._invariants.install(
            "test.hostile", "tool_shield.evaluate", lambda **_: "故意违例")
        try:
            with caplog.at_level(logging.ERROR, logger="tool_shield"):
                evaluate({"toolkit_cold": {"uses": 1, "pin": None,
                                           "first_used": "2020-01-01T00:00:00+00:00",
                                           "last_used": "2020-01-01T00:00:00+00:00"}},
                         known_tools=["toolkit_cold"], idle_days=30)
        finally:
            tool_shield._invariants.uninstall("test.hostile")
        assert "不变式违例" in caplog.text


# ═════════════ call_tool 检查点（旁路，永不改写控制流）════════════
class TestCallToolCheckpoint:
    def test_check_invariants_logs_missing_self_heal_tool(self, caplog):
        from tea_agent.tlk import Toolkit

        tk = Toolkit()
        tk.func_map.pop("toolkit_save", None)
        with caplog.at_level(logging.ERROR, logger="tlk"):
            tk._check_invariants("toolkit_file")
        assert "toolkit_save" in caplog.text

    def test_check_invariants_never_raises(self):
        from tea_agent.tlk import Toolkit

        class Stub:
            pass

        tk = Toolkit()
        tk._check_invariants("toolkit_file")  # 正常路径不抛
        # 鸭子替身/缺属性也不抛（旁路不得改写控制流）
        Stub._check_invariants = Toolkit._check_invariants
        Stub._check_invariants(Stub(), "toolkit_file")
