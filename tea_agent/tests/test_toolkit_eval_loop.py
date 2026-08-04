"""toolkit_eval_loop 测试 — 确定性 Rubric 评分闭环（借鉴 PenguinHarness self-evolve）。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tea_agent.toolkit.toolkit_eval_loop import toolkit_eval_loop as el


RULES = [
    {"pattern": r"<!-- ACME -->", "match": "line", "description": "[convention] marker"},
    {"pattern": r"^# Report:", "match": "regex", "description": "[convention] title"},
    {"pattern": "Classification: INTERNAL", "match": "contains", "description": "[convention] meta"},
    {"pattern": "Reviewed-by: Aurora Team", "match": "line", "description": "[convention] sign-off"},
    {"pattern": r"120ms", "match": "contains", "description": "[content] p99"},
    {"pattern": r"^\s*[-*]\s+", "match": "regex", "description": "[content] bullets"},
]

GOOD = (
    "<!-- ACME -->\n# Report: Aurora Quarterly\nClassification: INTERNAL\n"
    "- p99 cut to 120ms\nReviewed-by: Aurora Team"
)
BAD = "# Report: Aurora Quarterly\nSome summary without convention."


def test_score_full_pass():
    r = el(action="score", text=GOOD, rules=RULES)
    assert r["ok"] and r["score"] == 6 and r["max_score"] == 6
    assert r["passed_ratio"] == 1.0


def test_score_partial():
    r = el(action="score", text=BAD, rules=RULES)
    assert r["ok"] and r["score"] == 1 and r["max_score"] == 6


def test_score_requires_text():
    r = el(action="score", rules=RULES)
    assert not r["ok"] and "text" in r["error"]


def test_rules_string_format():
    rules_str = "<!-- ACME -->|line|[convention] marker\n^# Report:|regex|[convention] title"
    r = el(action="score", text=GOOD, rules=rules_str)
    assert r["ok"] and r["score"] == 2 and r["max_score"] == 2


def test_rules_dict_format():
    rules_dict = {"marker": {"pattern": "<!-- ACME -->", "match": "line", "description": "m"}}
    r = el(action="score", text=GOOD, rules=rules_dict)
    assert r["ok"] and r["score"] == 1


def test_evaluate_average():
    texts = [GOOD, GOOD, BAD]
    r = el(action="evaluate", texts=texts, rules=RULES)
    assert r["ok"] and r["runs"] == 3
    assert abs(r["mean_score"] - (6 + 6 + 1) / 3) < 0.0001
    assert len(r["per_run"]) == 3
    # rule_stats 按规则统计命中率
    assert r["rule_stats"][0]["hits"] == 2  # marker 在 2 轮中命中


def test_compare_keep_rollback_nochange():
    keep = el(action="compare", baseline=2, candidate=6, threshold=0)
    assert keep["decision"] == "keep"
    roll = el(action="compare", baseline=6, candidate=2, threshold=0)
    assert roll["decision"] == "rollback"
    nc = el(action="compare", baseline=4, candidate=4.2, threshold=0.5)
    assert nc["decision"] == "no_change"


def test_compare_with_evaluate_dicts():
    """完整闭环：evaluate 输出 dict 直接喂给 compare。"""
    base = el(action="evaluate", texts=[BAD], rules=RULES)
    cand = el(action="evaluate", texts=[GOOD, GOOD], rules=RULES)
    r = el(action="compare", baseline=base, candidate=cand, threshold=0)
    assert r["ok"] and r["decision"] == "keep"
    assert r["baseline"] == 1.0 and r["candidate"] == 6.0


def test_template():
    r = el(action="template")
    assert r["ok"] and "pattern" in r["template"] and "match" in r["template"]


def test_unknown_action():
    r = el(action="nope")
    assert not r["ok"] and "未知 action" in r["error"]
