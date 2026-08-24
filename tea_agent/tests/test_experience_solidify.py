"""toolkit_experience_solidify 测试 — 经验固化 + 合并的进化经验库（原 toolkit_evolution_exp）。

经验库 JSON 路径经 monkeypatch 指向 tmp，避免污染真实 ~/.tea_agent/。
"""

import pytest


@pytest.fixture
def exp_tool(tmp_path, monkeypatch):
    """指向 tmp 的固化工具模块（经验库写入 tmp）。"""
    import tea_agent.toolkit.toolkit_experience_solidify as es

    monkeypatch.setattr(es, "_get_exp_path", lambda: str(tmp_path / "exp.json"))
    return es


def test_solidify_analyze(exp_tool):
    r = exp_tool.toolkit_experience_solidify(action="analyze", task="T", result="R", success=True)
    assert r["ok"] and r["suggestion"] == "solidify"


def test_record_and_search(exp_tool):
    """record 一条经验后应能 search 到（原 toolkit_evolution_exp 行为）。"""
    r = exp_tool.toolkit_experience_solidify(
        action="record", description="test exp abc", category="test", tags="a,b", notes="n1"
    )
    assert r["ok"], r
    s = exp_tool.toolkit_experience_solidify(action="search", query="abc")
    assert s["ok"] and s["total"] >= 1, s
    assert s["results"][-1]["category"] == "test"


def test_list_returns_recent(exp_tool):
    exp_tool.toolkit_experience_solidify(action="record", description="first", category="c1")
    exp_tool.toolkit_experience_solidify(action="record", description="second", category="c2")
    r = exp_tool.toolkit_experience_solidify(action="list", limit=10)
    assert r["ok"] and r["total"] == 2
    assert r["experiences"][-1]["description"] == "second"


def test_lesson_records_failure(exp_tool):
    """lesson action = 失败教训入库（category=failure）。"""
    r = exp_tool.toolkit_experience_solidify(
        action="lesson", task="deploy", error="boom"
    )
    assert r["ok"], r
    s = exp_tool.toolkit_experience_solidify(action="search", query="boom")
    assert s["total"] >= 1
    assert s["results"][-1]["category"] == "failure"


def test_unknown_action(exp_tool):
    r = exp_tool.toolkit_experience_solidify(action="nope")
    assert not r["ok"] and "unknown_action" in r["error"]
