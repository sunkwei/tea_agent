"""L3 摘要版本历史（append-only）回归测试。

背景：L3（semantic_summary / tool_chain_summary / topic_summary）此前只有
**当前值**（UPDATE / ON CONFLICT UPSERT 覆盖），因此无法回答审计最核心的
问题：「T 时刻 Agent 相信的是什么」。本功能保留每次**实际发生变化的**版本。

为什么只版本化 L3、不版本化 L2（实测数据支撑的取舍，测试也钉住这点）：
    - L2 平均 184 KB/主题、单主题最大 1.03 MB，且每回合都写 → 逐版本存储
      会让库按「回合数 × L2 大小」膨胀；
    - L2 内容**完全可从 L1（agent_rounds）重新派生**，而 agent_rounds 本身
      已是 append-only 持久存储 → 再存 L2 版本属重复存储，正是本项目已经
      踩过并修掉的坑（rounds_json 与 agent_rounds 重复，实测占库 38.4%）。
"""

from __future__ import annotations

import pytest


@pytest.fixture()
def storage(tmp_path):
    from tea_agent.store import Storage

    s = Storage(db_path=str(tmp_path / "chat.db"))
    yield s
    s.close()


@pytest.fixture()
def topic(storage):
    return storage.create_topic("t")


# ════════════════════════════════════════════════════════════
# 1. 版本递增
# ════════════════════════════════════════════════════════════


class TestVersionIncrement:
    def test_each_change_creates_new_version(self, storage, topic):
        storage.set_semantic_summary(topic, "v1")
        storage.set_semantic_summary(topic, "v2")
        storage.set_semantic_summary(topic, "v3")

        versions = storage.get_l3_versions(topic, "semantic_summary")
        assert [v["version"] for v in versions] == [3, 2, 1], "版本号非单调递增/非最新在前"

    def test_version_content_is_preserved(self, storage, topic):
        """审计核心：历史版本内容必须原样可读（而非只剩当前值）。"""
        storage.set_semantic_summary(topic, "第一版结论")
        storage.set_semantic_summary(topic, "第二版结论")

        vs = {v["version"]: v["content"] for v in storage.get_l3_versions(topic)}
        assert vs[1] == "第一版结论", "旧版本内容丢失（审计无法回溯）"
        assert vs[2] == "第二版结论"

    def test_chars_recorded(self, storage, topic):
        storage.set_semantic_summary(topic, "12345")
        v = storage.get_l3_versions(topic)[0]
        assert v["chars"] == 5

    def test_newest_first_ordering(self, storage, topic):
        for i in range(1, 5):
            storage.set_semantic_summary(topic, f"v{i}")
        versions = [v["version"] for v in storage.get_l3_versions(topic)]
        assert versions == sorted(versions, reverse=True), "未按最新在前排序"


# ════════════════════════════════════════════════════════════
# 2. 去重：同值重写不产生新版本
# ════════════════════════════════════════════════════════════


class TestDedup:
    def test_same_content_does_not_create_version(self, storage, topic):
        """核心契约：同值重写必须**不**产生新版本。

        这个契约非显而易见但很关键：L3 写入路径（如 generate_l2_to_l3_summary）
        在阈值边界可能对同一内容重复调用 set_*。若每次都记一版，版本号会被
        无意义的重复写撑爆，历史曲线失去可读性 —— 审计价值归零。
        """
        storage.set_semantic_summary(topic, "同一份摘要")
        for _ in range(5):
            storage.set_semantic_summary(topic, "同一份摘要")

        assert len(storage.get_l3_versions(topic)) == 1, "同值重写产生了冗余版本"

    def test_content_flip_flop_each_recorded(self, storage, topic):
        """反向契约：内容来回变化时每**次变化**都要记（不能只比对上一版之外）。"""
        storage.set_semantic_summary(topic, "A")
        storage.set_semantic_summary(topic, "B")
        storage.set_semantic_summary(topic, "A")  # 回到 A，仍是新版本

        versions = [v["content"] for v in storage.get_l3_versions(topic)]
        assert versions == ["A", "B", "A"], f"来回变化未被完整记录: {versions}"


# ════════════════════════════════════════════════════════════
# 3. 空内容不记录
# ════════════════════════════════════════════════════════════


class TestEmptyContent:
    @pytest.mark.parametrize("blank", ["", "   ", "\n", "\t\n "])
    def test_blank_not_recorded(self, storage, topic, blank):
        storage.set_semantic_summary(topic, blank)
        assert storage.get_l3_versions(topic) == [], "空内容被记录成了版本"

    def test_none_not_recorded(self, storage, topic):
        storage.set_semantic_summary(topic, None)
        assert storage.get_l3_versions(topic) == []

    def test_blank_after_real_does_not_add_version(self, storage, topic):
        storage.set_semantic_summary(topic, "有效内容")
        storage.set_semantic_summary(topic, "")
        assert len(storage.get_l3_versions(topic)) == 1


# ════════════════════════════════════════════════════════════
# 4. kind 之间版本序列独立
# ════════════════════════════════════════════════════════════


class TestIndependentSequences:
    def test_each_kind_has_own_sequence(self, storage, topic):
        """三类摘要各自的版本号必须独立，不能互相挤占。"""
        storage.set_semantic_summary(topic, "s1")
        storage.set_semantic_summary(topic, "s2")
        storage.set_tool_chain_summary(topic, "t1")

        sem = [v["version"] for v in storage.get_l3_versions(topic, "semantic_summary")]
        tc = [v["version"] for v in storage.get_l3_versions(topic, "tool_chain_summary")]
        assert sem == [2, 1], f"semantic 版本序列受干扰: {sem}"
        assert tc == [1], f"tool_chain 版本序列受干扰: {tc}"

    def test_topic_summary_recorded(self, storage, topic):
        storage.update_topic_summary(topic, "ts-1")
        storage.update_topic_summary(topic, "ts-2")
        vs = [v["version"] for v in storage.get_l3_versions(topic, "topic_summary")]
        assert vs == [2, 1]

    def test_all_three_kinds_coexist(self, storage, topic):
        storage.set_semantic_summary(topic, "sem")
        storage.set_tool_chain_summary(topic, "tc")
        storage.update_topic_summary(topic, "ts")
        kinds = {v["kind"] for v in storage.get_l3_versions(topic)}
        assert kinds == {"semantic_summary", "tool_chain_summary", "topic_summary"}

    def test_filter_by_kind(self, storage, topic):
        storage.set_semantic_summary(topic, "sem")
        storage.set_tool_chain_summary(topic, "tc")
        assert len(storage.get_l3_versions(topic, "semantic_summary")) == 1
        assert len(storage.get_l3_versions(topic)) == 2

    def test_limit_respected(self, storage, topic):
        for i in range(10):
            storage.set_semantic_summary(topic, f"v{i}")
        assert len(storage.get_l3_versions(topic, "semantic_summary", limit=3)) == 3
        assert len(storage.get_l3_versions(topic, "semantic_summary", limit=0)) == 10


# ════════════════════════════════════════════════════════════
# 5. 隔离与向下兼容
# ════════════════════════════════════════════════════════════


class TestIsolation:
    def test_topics_do_not_share_versions(self, storage):
        t1 = storage.create_topic("t1")
        t2 = storage.create_topic("t2")
        storage.set_semantic_summary(t1, "a")
        storage.set_semantic_summary(t2, "b")
        assert len(storage.get_l3_versions(t1)) == 1
        assert len(storage.get_l3_versions(t2)) == 1
        assert storage.get_l3_versions(t1)[0]["content"] == "a"

    def test_no_topic_returns_empty(self, storage):
        assert storage.get_l3_versions("") == []
        assert storage.get_l3_versions("nonexistent") == []

    def test_summary_main_flow_still_works(self, storage, topic):
        """向下兼容：版本记录不得影响原有 set/get 语义。"""
        storage.set_semantic_summary(topic, "内容")
        assert storage.get_semantic_summary(topic) == "内容"
        storage.set_tool_chain_summary(topic, "tc")
        assert storage.get_tool_chain_summary(topic) == "tc"

    def test_versioning_failure_does_not_break_write(self, storage, topic):
        """fail-open：版本记录失败绝不能带崩摘要写入主流程。

        用「真实失败」而非替换方法：把版本表**删掉**，使 _record_version 内部
        的 INSERT 真的抛 OperationalError —— 由它自己的 try/except 兜住。
        （不能直接把 _record_version 替换成抛错的桩：那会绕过其内部保护，
        测的是一个在真实代码里不可能发生的场景。）
        """
        c = storage.conn.cursor()
        c.execute("DROP TABLE history_versions")
        storage.conn.commit()
        c.close()

        # 不应抛出（版本表已不存在 → 内部 INSERT 失败被兜住）
        storage.set_semantic_summary(topic, "内容")

        # 主流程仍生效（UPDATE + commit 在 _record_version 之前）
        assert storage.get_semantic_summary(topic) == "内容"


# ════════════════════════════════════════════════════════════
# 6. 工具 action=l3_versions
# ════════════════════════════════════════════════════════════


class TestToolAction:
    @pytest.fixture()
    def wired(self, storage, monkeypatch):
        import tea_agent.toolkit.toolkit_history_extract as hist

        monkeypatch.setattr(hist, "_resolve_storage", lambda: (storage, "test"))
        return storage

    def test_l3_versions_action(self, wired):
        import json

        import tea_agent.toolkit.toolkit_history_extract as hist

        tid = wired.create_topic("t")
        wired.set_semantic_summary(tid, "v1")
        wired.set_semantic_summary(tid, "v2")

        r = json.loads(hist.toolkit_history_extract(action="l3_versions", topic_id=tid))
        assert r["ok"] is True
        assert r["count"] == 2
        assert [v["version"] for v in r["versions"]] == [2, 1]

    def test_action_in_meta_enum(self):
        import tea_agent.toolkit.toolkit_history_extract as hist

        enum = hist.meta_toolkit_history_extract()["function"]["parameters"]["properties"]["action"]["enum"]
        assert "l3_versions" in enum, "meta enum 未暴露 l3_versions（模型看不到该能力）"

    def test_requires_topic(self, wired):
        import json

        import tea_agent.toolkit.toolkit_history_extract as hist

        r = json.loads(hist.toolkit_history_extract(action="l3_versions", topic_id=""))
        assert r["ok"] is False

    def test_unsupported_storage_reports_clearly(self, monkeypatch):
        """旧库/替身无该能力 → 明确报错，不静默返回空（会误读成「无历史」）。"""
        import json

        import tea_agent.toolkit.toolkit_history_extract as hist

        class OldStorage:
            pass

        monkeypatch.setattr(hist, "_resolve_storage", lambda: (OldStorage(), "test"))
        r = json.loads(hist.toolkit_history_extract(action="l3_versions", topic_id="t"))
        assert r["ok"] is False
        assert "不支持" in r["error"]

    def test_truncation_traced(self, wired):
        import json

        import tea_agent.toolkit.toolkit_history_extract as hist

        tid = wired.create_topic("t")
        wired.set_semantic_summary(tid, "x" * 500)

        r = json.loads(hist.toolkit_history_extract(
            action="l3_versions", topic_id=tid, max_chars=10))
        assert r["versions"][0]["truncated"] is True
        assert "已截断" in r["versions"][0]["content"]


# ════════════════════════════════════════════════════════════
# 7. 迁移：表存在且可空库升级
# ════════════════════════════════════════════════════════════


class TestMigration:
    def test_table_created(self, storage):
        c = storage.conn.cursor()
        try:
            row = c.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name='history_versions'"
            ).fetchone()
        finally:
            c.close()
        assert row is not None, "history_versions 表未创建"

    def test_index_created(self, storage):
        c = storage.conn.cursor()
        try:
            row = c.execute(
                "SELECT name FROM sqlite_master WHERE type='index' "
                "AND name='idx_history_versions_topic'"
            ).fetchone()
        finally:
            c.close()
        assert row is not None, "history_versions 索引未创建"

    def test_l0_columns_created(self, storage):
        c = storage.conn.cursor()
        try:
            cols = {r[1] for r in c.execute("PRAGMA table_info(conversations)")}
        finally:
            c.close()
        assert {"l0_hash", "l0_recorded"} <= cols, "L0 指纹列未创建"
