"""
toolkit_self_report / 进化可观测层测试
- _build_evolution_summary 聚合并脱敏进化日志
- 日志追加/裁剪在 agent_evolution 层已测，这里测展示聚合
"""

import os
import shutil


def _setup_log_dir():
    """工作区临时目录 + 指向它的进化日志环境变量。"""
    d = "sr_log_test"
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d, exist_ok=True)
    os.environ["TEA_AGENT_EVOLUTION_LOG"] = os.path.abspath(os.path.join(d, "el.json"))
    return d


def _teardown_log_dir(d: str):
    shutil.rmtree(d, ignore_errors=True)
    os.environ.pop("TEA_AGENT_EVOLUTION_LOG", None)


def test_summary_empty_db():
    d = _setup_log_dir()
    try:
        from tea_agent.toolkit.toolkit_self_report import _build_evolution_summary
        s = _build_evolution_summary()
        assert s["available"] is True and s["total"] == 0
        assert s["recent"] == []
    finally:
        _teardown_log_dir(d)


def test_summary_computes_stats_and_sanitizes():
    from tea_agent.agent_evolution import _append_evolution_log
    d = _setup_log_dir()
    try:
        from tea_agent.toolkit.toolkit_self_report import _build_evolution_summary
        _append_evolution_log({"action": "create_tool", "ok": True, "target": "toolkit_foo",
                               "error": "secret_detail_load_happens_here"})
        _append_evolution_log({"action": "prune", "ok": False, "target": "skills",
                               "error": "deleting_failed"})
        s = _build_evolution_summary(limit=5)
        assert s["total"] == 2
        assert s["ok_rate"] == 0.5
        assert set(s["by_action"]) == {"create_tool", "prune"}
        recent = s["recent"]
        assert len(recent) == 2
        # 已脱敏：recent 条目不含 error 字段本身，只含脱敏 detail
        for rec in recent:
            assert "error" not in rec
            assert isinstance(rec.get("detail"), str)
    finally:
        _teardown_log_dir(d)


def test_self_report_embeds_evolution():
    from tea_agent.agent_evolution import _append_evolution_log
    d = _setup_log_dir()
    try:
        import tea_agent.toolkit.toolkit_self_report as sr
        _append_evolution_log({"action": "create_tool", "ok": True})
        rep = sr.toolkit_self_report()
        assert "evolution" in rep
        assert rep["evolution"]["total"] == 1
        assert rep["evolution"]["available"] is True
    finally:
        _teardown_log_dir(d)
