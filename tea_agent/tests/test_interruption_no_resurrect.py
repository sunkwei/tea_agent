"""可靠记忆：用户删除的自动沉淀记忆不得被后台线程重建。

背景（真实缺陷，由「删除记忆后仍持续注入」暴露，实测连续 20+ 轮）：
`agent_background.analyze_interruptions` 每小时聚合打断事件，达到阈值即写入
preference 记忆。其幂等此前**仅靠「是否已有同名记忆」**判断：
    用户删除该记忆 → 下一轮聚合发现「没有」→ 重新创建 → 每轮注入 → 删除永不生效。
后果：记忆不可靠（用户无法删掉它）+ 每轮白烧 token。

修复：沉淀后把这些事件标记为 `precipitated`，移出聚合池 —— 删除随之长期生效。
"""

from __future__ import annotations

from tea_agent.agent_background import analyze_interruptions


def _seed(db, tool: str = "toolkit_exec", n: int = 2):
    """造 n 条已分类的打断事件（同一工具）。"""
    for i in range(n):
        db.insert_interruption_event({
            "topic_id": "t1",
            "timestamp": f"2026-09-12 10:0{i}:00",
            "iteration": i + 1,
            "tool_name": tool,
            "status": "classified",
            "classification": "corrected",
        })


def test_deleted_memory_is_not_resurrected(tmp_path):
    """核心回归：删除后再次聚合，不得重建该记忆（删除必须长期生效）。"""
    from tea_agent.store import Storage

    db = Storage(str(tmp_path / "t.db"))
    _seed(db, n=2)

    first = analyze_interruptions(storage=db, min_count=2, skill_min_count=99)
    assert first, "首次应沉淀一条打断模式记忆"

    mems = db.get_active_memories(limit=10)
    assert len(mems) == 1, f"应有 1 条沉淀记忆，实际 {len(mems)}"
    target_id = mems[0]["id"]

    # 用户删除它
    assert db.delete_memory(target_id) is True
    assert db.get_active_memories(limit=10) == [], "删除后应为空"

    # 模拟下一小时后后台再次运行
    second = analyze_interruptions(storage=db, min_count=2, skill_min_count=99)
    assert second == [], "已删除的记忆不得被自动重建（可靠记忆）"
    assert db.get_active_memories(limit=10) == [], "删除后仍应保持为空"


def test_precipitated_events_leave_aggregate_pool(tmp_path):
    """沉淀后事件状态转为 precipitated，不再出现在 classified 查询中。"""
    from tea_agent.store import Storage

    db = Storage(str(tmp_path / "t.db"))
    _seed(db, n=3)
    assert len(db.query_interruptions(status="classified")) == 3

    analyze_interruptions(storage=db, min_count=2, skill_min_count=99)

    assert db.query_interruptions(status="classified") == [], "事件应已移出聚合池"
    assert len(db.query_interruptions(status="precipitated")) == 3


def test_positive_control_analyzer_still_precipitates(tmp_path):
    """阳性对照：正常情况下沉淀仍会发生（防止把功能整体关死）。"""
    from tea_agent.store import Storage

    db = Storage(str(tmp_path / "t.db"))
    _seed(db, tool="toolkit_edit", n=2)
    written = analyze_interruptions(storage=db, min_count=2, skill_min_count=99)
    assert len(written) == 1
    assert "toolkit_edit" in written[0]


def test_below_threshold_does_not_precipitate(tmp_path):
    """阈值以下不沉淀（阴性对照）。"""
    from tea_agent.store import Storage

    db = Storage(str(tmp_path / "t.db"))
    _seed(db, n=1)
    assert analyze_interruptions(storage=db, min_count=2, skill_min_count=99) == []
    assert db.get_active_memories(limit=10) == []


def test_analyzer_disabled_by_config(monkeypatch):
    """进化暂停开关：interruption.enabled=false 时不启动分析线程。"""
    from tea_agent import agent_background as ab

    monkeypatch.setattr(ab, "_get_icfg", lambda: {"enabled": False})
    assert ab.start_interruption_analyzer() is None, "禁用时应返回 None（不启动线程）"


def test_analyzer_starts_when_enabled(monkeypatch):
    """阳性对照：默认（enabled 缺省 True）应能启动线程，并可优雅停止。"""
    from tea_agent import agent_background as ab

    monkeypatch.setattr(ab, "_get_icfg", lambda: {"enabled": True})
    t = ab.start_interruption_analyzer(interval_h=24.0)
    try:
        assert t is not None and t.is_alive()
    finally:
        assert ab.stop_interruption_analyzer(t, timeout=5.0) is True
