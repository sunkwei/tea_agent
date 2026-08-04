"""agent_evolution Evaluate 阶段测试 — 借鉴 PenguinHarness rubric 闭环。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tea_agent.agent_evolution import EvolutionEvaluator
from tea_agent.toolkit.toolkit_eval_loop import toolkit_eval_loop


class FakeToolkit:
    """最小 toolkit 桩 — 仅提供 toolkit_eval_loop 与 call_tool。"""

    def __init__(self):
        self.func_map = {"toolkit_eval_loop": True}

    def call_tool(self, name: str, **kwargs):
        assert name == "toolkit_eval_loop"
        return toolkit_eval_loop(**kwargs)


RULES = [
    {"pattern": "def ", "match": "contains", "description": "[code] 含函数定义"},
    {"pattern": '"""', "match": "contains", "description": "[code] 含文档字符串"},
    {"pattern": "TODO", "match": "contains", "description": "[code] 含 TODO 标记"},
]


def _write(path: Path, content: str):
    path.write_text(content, encoding="utf-8")


def test_available_true_with_toolkit():
    ev = EvolutionEvaluator(FakeToolkit())
    assert ev.available() is True


def test_available_false_without_toolkit():
    class EmptyTk:
        func_map = {}

    ev = EvolutionEvaluator(EmptyTk())
    assert ev.available() is False


def test_extract_eval_actions_filters_rubric():
    ev = EvolutionEvaluator(FakeToolkit())
    actions = [
        {"action": "evolve_code", "target": "a.py", "rubric": RULES},
        {"action": "evolve_code", "target": "b.py", "reason": "无 rubric 不评估"},
        {"action": "none", "target": "c.py", "rubric": RULES},
        {"action": "evolve_prompt", "target": "system_prompt", "rubric": RULES},
    ]
    picked = ev.extract_eval_actions(actions)
    targets = [a["target"] for a in picked]
    assert targets == ["a.py", "system_prompt"]


def test_evaluate_target_scores_file(tmp_path):
    ev = EvolutionEvaluator(FakeToolkit())
    f = tmp_path / "code.py"
    _write(f, 'def foo():\n    """doc"""\n    pass  # TODO: improve')
    r = ev.evaluate_target(str(f), RULES, runs=3)
    assert r and r["ok"] and r["mean_score"] == 3 and r["max_score"] == 3


def test_decide_keep_when_improved():
    ev = EvolutionEvaluator(FakeToolkit())
    base = {"ok": True, "mean_score": 1.0}
    cand = {"ok": True, "mean_score": 3.0}
    d = ev.decide(base, cand)
    assert d["decision"] == "keep"


def test_decide_rollback_when_worse():
    ev = EvolutionEvaluator(FakeToolkit())
    base = {"ok": True, "mean_score": 3.0}
    cand = {"ok": True, "mean_score": 1.0}
    d = ev.decide(base, cand)
    assert d["decision"] == "rollback"


def test_decide_no_change_within_threshold():
    ev = EvolutionEvaluator(FakeToolkit())
    base = {"ok": True, "mean_score": 2.0}
    cand = {"ok": True, "mean_score": 2.2}
    d = ev.decide(base, cand, threshold=0.5)
    assert d["decision"] == "no_change"


def test_decide_conservative_when_data_missing():
    ev = EvolutionEvaluator(FakeToolkit())
    d = ev.decide(None, {"ok": True, "mean_score": 3.0})
    assert d["ok"] is False and d["decision"] == "no_change"


def test_full_loop_keep_on_improvement(tmp_path):
    """完整闭环：基线低分 → 改进 → 重评高分 → keep。"""
    ev = EvolutionEvaluator(FakeToolkit())
    f = tmp_path / "code.py"
    _write(f, "x = 1  # no doc, no TODO")

    baseline = ev.evaluate_target(str(f), RULES)
    assert baseline and baseline["ok"]

    # 模拟改进动作：重写文件补齐规范
    _write(f, 'def run():\n    """entry"""\n    # TODO: optimize\n    return 0')
    candidate = ev.evaluate_target(str(f), RULES)

    decision = ev.decide(baseline, candidate)
    assert decision["decision"] == "keep"
    assert candidate["mean_score"] > baseline["mean_score"]


def test_rollback_returns_false_for_untracked_file(tmp_path):
    """未纳入 git 跟踪的文件回滚失败但不应抛异常。"""
    ev = EvolutionEvaluator(FakeToolkit())
    f = tmp_path / "untracked.py"
    _write(f, "x = 1")
    ok = ev.rollback(str(f))
    assert ok is False
