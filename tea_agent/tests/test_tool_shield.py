"""tool_shield 策略 + ToolUsageStore 存储层回归测试。

屏蔽是**会让 Agent 失去能力**的操作，因此本文件的重心不是"能屏蔽"，而是
"什么情况下绝不屏蔽"。三条不变式各对应一次真实的自我伤害：

1. 无数据不屏蔽 —— 否则新装机/换新项目目录第一次启动就屏蔽全部工具（Agent 瘫痪）
2. 观测期未满不屏蔽零使用工具 —— 否则"刚装上"被误判成"长期不用"
3. 自愈通路永不屏蔽 —— 否则屏蔽后连改配置/加工具/重载的手段都没了，故障无法自救
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timedelta, timezone

import pytest

from tea_agent.store._tool_usage import ToolUsageStore
from tea_agent.tool_shield import (
    ALWAYS_PINNED,
    DEFAULT_IDLE_DAYS,
    apply_shield,
    evaluate,
    shield_enabled,
)

NOW = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc)


def _ago(days: float) -> str:
    return (NOW - timedelta(days=days)).isoformat(timespec="seconds")


def _row(uses, last_days_ago, first_days_ago=90, pin=None) -> dict:
    return {
        "uses": uses,
        "pin": pin,
        "first_used": _ago(first_days_ago),
        "last_used": _ago(last_days_ago) if last_days_ago is not None else None,
    }


def _tools(*names) -> list[dict]:
    return [{"function": {"name": n}} for n in names]


KNOWN = ["toolkit_exec", "toolkit_file", "toolkit_hot", "toolkit_cold",
         "toolkit_never", "toolkit_config"]


# ═════════════ 不变式 1：无数据 = 不屏蔽 ═════════════
class TestNoDataNeverShields:
    def test_empty_usage_shields_nothing(self):
        v = evaluate({}, known_tools=KNOWN, idle_days=30, now=NOW)
        assert v["shielded"] == {}, f"无数据时发生了屏蔽: {v['shielded']}"
        assert v["reason"], "应给出可观测的不生效原因"

    def test_apply_shield_with_no_data_keeps_all_tools(self):
        tools = _tools(*KNOWN)
        kept, hidden = apply_shield(tools, storage=_StubStorage({}))
        assert hidden == set()
        assert len(kept) == len(tools)

    def test_none_known_tools_is_safe(self):
        v = evaluate({"toolkit_hot": _row(5, 1)}, known_tools=None,
                     idle_days=30, now=NOW)
        assert v["shielded"] == {}


# ═════════════ 不变式 2：观测期未满不屏蔽 ═════════════
class TestWarmupNotShielded:
    def test_recent_install_does_not_shield_unused_tools(self):
        """观测仅 3 天：零使用的工具不能被判定为"长期不用"。"""
        usage = {"toolkit_exec": _row(9, 0.1, first_days_ago=3),
                 "toolkit_never": _row(0, None)}
        v = evaluate(usage, known_tools=KNOWN, idle_days=30, now=NOW,
                     oldest_observed=_ago(3))
        assert "toolkit_never" not in v["shielded"], "新环境的未用工具被误屏蔽"

    def test_full_observation_shields_never_used(self):
        usage = {"toolkit_exec": _row(9, 0.1), "toolkit_hot": _row(7, 2)}
        v = evaluate(usage, known_tools=KNOWN, idle_days=30, now=NOW,
                     oldest_observed=_ago(90))
        assert "toolkit_never" in v["shielded"]
        assert "toolkit_hot" not in v["shielded"]

    def test_idle_beyond_threshold_shielded(self):
        usage = {"toolkit_exec": _row(9, 0.1), "toolkit_cold": _row(4, 45),
                 "toolkit_hot": _row(4, 3)}
        v = evaluate(usage, known_tools=KNOWN, idle_days=30, now=NOW,
                     oldest_observed=_ago(120))
        assert "toolkit_cold" in v["shielded"]
        assert "toolkit_hot" in v["kept"]

    def test_threshold_boundary_is_inclusive(self):
        """恰好等于阈值即屏蔽：边界语义必须显式固定，不随浮点误差漂移。"""
        usage = {"toolkit_exec": _row(9, 0.1), "toolkit_cold": _row(4, 30)}
        v = evaluate(usage, known_tools=KNOWN, idle_days=30, now=NOW,
                     oldest_observed=_ago(120))
        assert "toolkit_cold" in v["shielded"]

    def test_just_inside_threshold_not_shielded(self):
        usage = {"toolkit_exec": _row(9, 0.1), "toolkit_cold": _row(4, 29)}
        v = evaluate(usage, known_tools=KNOWN, idle_days=30, now=NOW,
                     oldest_observed=_ago(120))
        assert "toolkit_cold" not in v["shielded"]

    def test_malformed_timestamps_do_not_crash(self):
        usage = {"toolkit_hot": {"uses": 3, "pin": None,
                                 "first_used": "not-a-date", "last_used": "??"}}
        v = evaluate(usage, known_tools=KNOWN, idle_days=30, now=NOW,
                     oldest_observed="garbage")
        assert v["shielded"] == {}


# ═════════════ 不变式 3：自愈通路永不屏蔽 ═════════════
class TestSelfHealingAlwaysVisible:
    @pytest.mark.parametrize("tool", sorted(ALWAYS_PINNED))
    def test_pinned_survive_even_when_unused(self, tool):
        v = evaluate({"toolkit_hot": _row(9, 1)}, known_tools=[tool],
                     idle_days=30, now=NOW, oldest_observed=_ago(400))
        assert tool not in v["shielded"], f"屏蔽 {tool} 将导致无法自救"

    def test_apply_shield_never_hides_recovery_path(self):
        tools = _tools(*sorted(ALWAYS_PINNED), "toolkit_lsp")
        usage = {"toolkit_lsp": _row(1, 200)}
        _, hidden = apply_shield(tools, storage=_StubStorage(
            usage, oldest=_ago(400)))
        assert hidden == {"toolkit_lsp"}, f"屏蔽集超出预期: {hidden}"


class TestPinOverrides:
    def test_pin_beats_data(self):
        usage = {"toolkit_hot": _row(2, 400, pin=1)}
        v = evaluate(usage, known_tools=KNOWN, idle_days=30, now=NOW,
                     oldest_observed=_ago(500))
        assert "toolkit_hot" not in v["shielded"]

    def test_unpin_forces_shield(self):
        usage = {"toolkit_hot": _row(999, 0, pin=0)}
        v = evaluate(usage, known_tools=KNOWN, idle_days=30, now=NOW,
                     oldest_observed=_ago(500))
        assert "toolkit_hot" in v["shielded"]

    def test_auto_restores_data_driven_judgement(self):
        usage = {"toolkit_hot": _row(999, 0, pin=None)}
        v = evaluate(usage, known_tools=KNOWN, idle_days=30, now=NOW,
                     oldest_observed=_ago(500))
        assert "toolkit_hot" not in v["shielded"]


# ═════════════ 逃生阀与阈值配置 ═════════════
class TestKillSwitch:
    def test_env_disable_shields_nothing(self, monkeypatch):
        monkeypatch.setenv("TEA_TOOL_SHIELD", "0")
        usage = {"toolkit_hot": _row(9, 1), "toolkit_cold": _row(2, 400)}
        v = evaluate(usage, known_tools=KNOWN, idle_days=30, now=NOW,
                     oldest_observed=_ago(500))
        assert v["shielded"] == {}
        assert not shield_enabled()

    @pytest.mark.parametrize("value", ["1", "true", "yes", "on", "", "  "])
    def test_only_explicit_off_disables(self, monkeypatch, value):
        """空值=未设置=默认开。把空串当成"关"会让默认行为反直觉。"""
        monkeypatch.setenv("TEA_TOOL_SHIELD", value)
        assert shield_enabled()

    def test_idle_days_env_override(self, monkeypatch):
        monkeypatch.setenv("TEA_TOOL_SHIELD_IDLE_DAYS", "7")
        usage = {"toolkit_hot": _row(9, 1), "toolkit_cold": _row(2, 10)}
        v = evaluate(usage, known_tools=KNOWN, now=NOW, oldest_observed=_ago(90))
        assert v["idle_days"] == 7
        assert "toolkit_cold" in v["shielded"]

    @pytest.mark.parametrize("bad", ["abc", "0", "-5", "1e999"])
    def test_invalid_idle_days_falls_back_and_warns(self, monkeypatch, bad, caplog):
        monkeypatch.setenv("TEA_TOOL_SHIELD_IDLE_DAYS", bad)
        v = evaluate({"toolkit_hot": _row(1, 1)}, known_tools=KNOWN, now=NOW)
        assert v["idle_days"] == DEFAULT_IDLE_DAYS


# ═════════════ 不破坏前缀缓存 ═════════════
class TestPrefixCacheStability:
    def test_decision_is_deterministic(self):
        """同一数据两次判定必须逐字节一致。

        工具列表顺序是 DeepSeek 前缀缓存的一部分；屏蔽集合若抖动，每轮都会换
        一套 schema → 缓存 100% 失效。
        """
        usage = {"toolkit_hot": _row(9, 1), "toolkit_cold": _row(2, 400),
                 "toolkit_never": _row(0, None)}
        a = evaluate(usage, known_tools=KNOWN, idle_days=30, now=NOW,
                     oldest_observed=_ago(200))
        b = evaluate(usage, known_tools=KNOWN, idle_days=30, now=NOW,
                     oldest_observed=_ago(200))
        assert list(a["shielded"]) == list(b["shielded"])
        assert list(a["kept"]) == list(b["kept"])

    def test_shielded_is_sorted(self):
        v = evaluate({"toolkit_hot": _row(9, 1)}, known_tools=list(reversed(KNOWN)),
                     idle_days=30, now=NOW, oldest_observed=_ago(200))
        assert list(v["shielded"]) == sorted(v["shielded"])


# ═════════════ 意图注入路径不被否决 ═════════════
class TestIntentInjectionBypass:
    def test_storage_read_failure_is_fail_open(self, monkeypatch):
        """屏蔽逻辑出问题时必须"全部放开"，而不是把工具藏掉。"""
        import tea_agent.tool_shield as sh

        class Boom:
            tool_usage = None

        monkeypatch.setattr(sh, "_storage_or_none", lambda: Boom())
        tools = _tools(*KNOWN)
        kept, hidden = sh.apply_shield(tools)
        assert hidden == set()
        assert len(kept) == len(tools)

    def test_no_storage_present_keeps_all(self, monkeypatch):
        import tea_agent.tool_shield as sh

        monkeypatch.setattr(sh, "_storage_or_none", lambda: None)
        tools = _tools(*KNOWN)
        kept, hidden = sh.apply_shield(tools)
        assert hidden == set() and len(kept) == len(tools)


# ═════════════ Store 层（真实 sqlite）═════════════
class _StubUsage:
    def __init__(self, usage, oldest=None):
        self._u, self._o = usage, oldest

    def all_usage(self):
        return self._u

    def oldest_observed(self):
        return self._o or min((v["first_used"] for v in self._u.values()
                               if v.get("first_used")), default=None)


class _StubStorage:
    """只带 tool_usage 的最小替身（apply_shield 只用到这一个属性）。"""

    def __init__(self, usage, oldest=None):
        self.tool_usage = _StubUsage(usage, oldest)


@pytest.fixture
def store(tmp_path):
    s = ToolUsageStore(str(tmp_path / "usage.db"))
    s.ensure_table()
    return s


class TestStoreBehaviour:
    def test_accumulates(self, store):
        store.record_use("toolkit_exec")
        store.record_use("toolkit_exec")
        store.record_use("toolkit_file")
        u = store.all_usage()
        assert u["toolkit_exec"]["uses"] == 2
        assert u["toolkit_file"]["uses"] == 1

    def test_first_used_not_overwritten(self, store):
        """first_used 是观测期基准，被后续调用改写会破坏 warmup 判定。"""
        t1, t2 = _ago(10), _ago(1)
        store.record_use("toolkit_hot", when=t1)
        store.record_use("toolkit_hot", when=t2)
        row = store.all_usage()["toolkit_hot"]
        assert row["first_used"] == t1
        assert row["last_used"] == t2

    def test_empty_tool_is_noop(self, store):
        assert store.record_use("") is False
        assert store.all_usage() == {}

    def test_concurrent_records_do_not_lose_counts(self, store):
        """丢计数会把常用工具误判成不活跃 —— 与其他统计场景代价方向相反。"""
        def worker():
            for _ in range(25):
                store.record_use("toolkit_burst")

        ts = [threading.Thread(target=worker) for _ in range(6)]
        for t in ts:
            t.start()
        for t in ts:
            t.join(timeout=60)
        assert store.all_usage()["toolkit_burst"]["uses"] == 150

    def test_set_pin_on_unseen_tool_survives_later_use(self, store):
        """新工具常需预先 pin=1 保住；若没建行，首次使用会覆盖掉设置。"""
        assert store.set_pin("toolkit_brand_new", 1) is True
        store.record_use("toolkit_brand_new")
        assert store.all_usage()["toolkit_brand_new"]["pin"] == 1

    def test_prune_removes_ghost_rows(self, store):
        store.record_use("toolkit_gone")
        store.record_use("toolkit_stay")
        assert store.prune(["toolkit_stay"]) == 1
        assert set(store.all_usage()) == {"toolkit_stay"}

    def test_prune_empty_keep_is_noop(self, store):
        """keep 传空必须是"什么都不做"，否则等于清空全表。"""
        store.record_use("toolkit_a")
        assert store.prune([]) == 0
        assert "toolkit_a" in store.all_usage()

    def test_report_sorted_desc(self, store):
        for _ in range(3):
            store.record_use("toolkit_b")
        store.record_use("toolkit_a")
        assert [r["tool"] for r in store.report()] == ["toolkit_b", "toolkit_a"]

    def test_unmigrated_db_is_tolerated(self, tmp_path):
        """老库没有该表：读返回 {}，写自动补建，全程不抛。"""
        db = str(tmp_path / "raw.db")
        sqlite3.connect(db).close()
        s = ToolUsageStore(db)
        assert s.all_usage() == {}
        assert s.record_use("toolkit_x") is True
        assert s.all_usage()["toolkit_x"]["uses"] == 1


class TestStorageWiring:
    def test_storage_creates_table_on_init(self, tmp_path):
        """Storage 初始化即建表，不让 record_use 依赖隐式补建。"""
        from tea_agent.store._core import Storage

        path = str(tmp_path / "chat.db")
        st = Storage(path)
        conn = sqlite3.connect(path)
        try:
            names = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
        finally:
            conn.close()
        assert "tool_usage" in names
        assert hasattr(st, "tool_usage")


class TestRecordPointWired:
    """记录点必须在 Toolkit.call_tool，且在缓存判定之前。"""

    def _wire(self, tmp_path, monkeypatch, name):
        import tea_agent.store as store_pkg
        import tea_agent.tlk as tlk_mod

        tus = ToolUsageStore(str(tmp_path / name))
        tus.ensure_table()
        # peek_storage() 约定返回 Storage（要取 .tool_usage）；直接返回
        # ToolUsageStore 会让 st.tool_usage 取不到并静默跳过，测试就只在验证
        # 一个搭错的替身。
        shim = type("Shim", (), {"tool_usage": tus})()
        monkeypatch.setattr(store_pkg, "peek_storage", lambda: shim)
        return tlk_mod.Toolkit(), tus

    def test_call_tool_records_usage(self, tmp_path, monkeypatch):
        tk, tus = self._wire(tmp_path, monkeypatch, "u.db")
        assert tk.call_tool("toolkit_mode", action="status") is not None
        assert "toolkit_mode" in tus.all_usage(), "call_tool 未记录使用统计"

    def test_cache_hit_still_counts(self, tmp_path, monkeypatch):
        """命中缓存同样是一次真实调用；记在缓存之后就少算。"""
        tk, tus = self._wire(tmp_path, monkeypatch, "u2.db")
        assert "toolkit_task_resume" in tk._CACHE_WHITELIST
        for _ in range(3):
            tk.call_tool("toolkit_task_resume", action="check")
        assert tus.all_usage().get("toolkit_task_resume", {}).get("uses", 0) >= 1, \
            "缓存路径未记录（会低估常用工具频率）"

    def test_no_storage_does_not_create_db(self, tmp_path, monkeypatch):
        """裸用 Toolkit（无会话/无库）时，统计写入本身不得建库。

        只断言"记录统计"这一步：某些工具（如 toolkit_mode 读配置）自身有既有的
        建库副作用，把它算到本功能头上会得到与实现无关的失败。
        """
        import tea_agent.store as store_pkg
        import tea_agent.tlk as tlk_mod

        monkeypatch.setattr(store_pkg, "peek_storage", lambda: None)
        cwd = str(tmp_path)
        monkeypatch.chdir(cwd)
        tk = tlk_mod.Toolkit()
        before = set(__import__("pathlib").Path(cwd).rglob("*.db"))

        assert tk._record_usage("toolkit_whatever") is None  # 不抛即可
        assert set(__import__("pathlib").Path(cwd).rglob("*.db")) == before, \
            "统计写入改变了主流程的建库行为"

    def test_broken_store_does_not_break_call(self, tmp_path, monkeypatch):
        import tea_agent.store as store_pkg
        import tea_agent.tlk as tlk_mod

        class Broken:
            tool_usage = None  # 触发 AttributeError

        monkeypatch.setattr(store_pkg, "peek_storage", lambda: Broken())
        tk = tlk_mod.Toolkit()
        assert tk.call_tool("toolkit_mode", action="status") is not None
