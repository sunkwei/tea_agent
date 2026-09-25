"""toolkit_history_extract — L0/L1/L2/L3 历史提取回归测试。

审计读取侧的三个关键契约（测试钉这些，而非实现细节）：

1. **作用域不可混淆** —— L0/L1 是回合级，L2/L3 是主题级**滚动当前值**。
   工具输出里必须如实标注 ``historical``，因为把「主题当前 L2/L3」当成
   「某回合当时的 L2/L3」是审计中最容易犯的错，会导致复原结论完全失真。
2. **不可用必须带原因** —— 「没有 L0」有三种截然不同的成因（回合不存在 /
   早于功能上线 / 记录为空），审计必须能区分；静默返回空内容会被误读为
   「当时 L0 就是空的」。
3. **截断必须留痕** —— 静默截断会让审计把「截断后的片段」当作原文。
"""

from __future__ import annotations

import json

import pytest

import tea_agent.toolkit.toolkit_history_extract as hist


@pytest.fixture()
def storage(tmp_path):
    from tea_agent.store import Storage

    s = Storage(db_path=str(tmp_path / "chat.db"))
    yield s
    s.close()


@pytest.fixture()
def wired(storage, monkeypatch):
    """把工具的 storage 解析重定向到临时库（隔离真实库/Agent 单例）。"""
    monkeypatch.setattr(hist, "_resolve_storage", lambda: (storage, "test"))
    return storage


@pytest.fixture()
def seeded(wired):
    """构造一个有完整四级数据的主题 + 回合。"""
    st = wired
    tid = st.create_topic("t")
    cid = st.create_turn(tid, "用户问题")
    st.append_round(cid, 0, "assistant", "我先查文件",
                    tool_calls=[{"id": "c1", "type": "function",
                                 "function": {"name": "toolkit_file", "arguments": "{}"}}],
                    reasoning_content="思考中")
    st.append_round(cid, 1, "tool", "文件内容=abc", tool_call_id="c1")
    st.finalize_turn(cid, "最终答复", is_func_calling=True)
    st.record_l0_snapshot(cid, "【L0】OS信息+AGENTS.md")
    st.set_level2(tid, [{"user": "历史u", "assistant": "历史a", "thinking": "历史思考"}])
    st.set_semantic_summary(tid, "语义摘要内容")
    return {"topic_id": tid, "conversation_id": cid}


def _call(**kw) -> dict:
    return json.loads(hist.toolkit_history_extract(**kw))


# ════════════════════════════════════════════════════════════
# 1. 正常提取四级
# ════════════════════════════════════════════════════════════


class TestExtractAll:
    def test_all_four_levels_available(self, seeded):
        r = _call(action="extract", topic_id=seeded["topic_id"],
                  conversation_id=seeded["conversation_id"])
        assert r["ok"] is True
        assert r["availability"] == {"L0": True, "L1": True, "L2": True, "L3": True}

    def test_l0_content_is_the_enriched_snapshot(self, seeded):
        r = _call(action="extract", topic_id=seeded["topic_id"],
                  conversation_id=seeded["conversation_id"], levels=["L0"])
        assert r["L0"]["content"] == "【L0】OS信息+AGENTS.md"

    def test_l1_has_tool_chain_and_reasoning(self, seeded):
        r = _call(action="extract", topic_id=seeded["topic_id"],
                  conversation_id=seeded["conversation_id"], levels=["L1"])
        msgs = r["L1"]["messages"]
        assert [m["role"] for m in msgs] == ["assistant", "tool"]
        # 工具链必须是**名字**（可读），而非原始 JSON blob
        assert msgs[0]["tool_calls"] == ["toolkit_file"]
        assert msgs[1]["tool_call_id"] == "c1"
        # reasoning_content 必须被提取（DeepSeek thinking 审计要看它）
        assert msgs[0]["reasoning_content"] == "思考中"

    def test_l2_and_l3_content(self, seeded):
        r = _call(action="extract", topic_id=seeded["topic_id"], levels=["L2", "L3"])
        assert r["L2"]["entries"] == 1
        assert r["L2"]["items"][0]["user"] == "历史u"
        assert r["L3"]["semantic_summary"] == "语义摘要内容"


# ════════════════════════════════════════════════════════════
# 2. 契约 1：作用域与历史性标注
# ════════════════════════════════════════════════════════════


class TestScopeLabelling:
    def test_scope_split_is_reported(self, seeded):
        """L0/L1=conversation，L2/L3=topic —— 混用会导致复原结论失真。"""
        r = _call(action="extract", topic_id=seeded["topic_id"],
                  conversation_id=seeded["conversation_id"])
        assert r["L0"]["scope"] == "conversation"
        assert r["L1"]["scope"] == "conversation"
        assert r["L2"]["scope"] == "topic"
        assert r["L3"]["scope"] == "topic"

    def test_topic_levels_declared_non_historical(self, seeded):
        """L2/L3 必须标 historical=False —— 它们是滚动覆盖值，无法回看。"""
        r = _call(action="extract", topic_id=seeded["topic_id"], levels=["L2", "L3"])
        assert r["L2"]["historical"] is False
        assert r["L3"]["historical"] is False
        assert "caveat" in r["L2"] and "caveat" in r["L3"]

    def test_conversation_levels_declared_historical(self, seeded):
        r = _call(action="extract", topic_id=seeded["topic_id"],
                  conversation_id=seeded["conversation_id"], levels=["L0", "L1"])
        assert r["L0"]["historical"] is True
        assert r["L1"]["historical"] is True

    def test_top_level_scope_note_present(self, seeded):
        r = _call(action="extract", topic_id=seeded["topic_id"])
        assert "L2/L3" in r["scope_note"]


# ════════════════════════════════════════════════════════════
# 3. 契约 2：不可用必须带原因，且成因可区分
# ════════════════════════════════════════════════════════════


class TestUnavailableReasons:
    def test_nonexistent_conversation_says_wrong_id(self, seeded):
        """ID 打错 → 必须说「不存在」，不能误述成「历史回合」。"""
        r = _call(action="extract", topic_id=seeded["topic_id"],
                  conversation_id="no-such-id", levels=["L0"])
        assert r["L0"]["available"] is False
        reason = r["L0"]["reason"]
        assert "不存在" in reason, f"未区分「问错 ID」: {reason}"

    def test_existing_but_unrecorded_says_pre_feature(self, wired):
        """回合存在但未记录 L0（旧数据）→ 说「上线前」，与问错 ID 区分开。"""
        st = wired
        tid = st.create_topic("t")
        cid = st.create_turn(tid, "问题")  # 刻意不记录 L0
        r = _call(action="extract", topic_id=tid, conversation_id=cid, levels=["L0"])
        assert r["L0"]["available"] is False
        reason = r["L0"]["reason"]
        assert "未记录" in reason, f"未识别「存在但未记录」: {reason}"
        assert "不存在（" not in reason, "把「存在但未记录」误报成了「不存在」"

    def test_empty_topic_has_reasons_for_l2_l3(self, wired):
        tid = wired.create_topic("empty")
        r = _call(action="extract", topic_id=tid, levels=["L2", "L3"])
        assert r["L2"]["available"] is False and r["L2"]["reason"]
        assert r["L3"]["available"] is False and r["L3"]["reason"]

    def test_missing_conversation_id_for_l0(self, wired):
        tid = wired.create_topic("t")
        r = _call(action="extract", topic_id=tid, levels=["L0"])
        assert r["L0"]["available"] is False
        assert "conversation_id" in r["L0"]["reason"]

    def test_missing_topic_id_for_l2(self, wired):
        r = _call(action="extract", levels=["L2"])
        assert r["L2"]["available"] is False
        assert "topic_id" in r["L2"]["reason"]

    def test_no_rounds_gives_reason(self, wired):
        tid = wired.create_topic("t")
        cid = wired.create_turn(tid, "问题")  # 无轮次
        r = _call(action="extract", topic_id=tid, conversation_id=cid, levels=["L1"])
        assert r["L1"]["available"] is False and r["L1"]["reason"]

    def test_topic_without_conversations(self, wired):
        tid = wired.create_topic("t")
        r = _call(action="extract", topic_id=tid, levels=["L1"])
        assert r["L1"]["available"] is False


# ════════════════════════════════════════════════════════════
# 4. 契约 3：截断必须留痕
# ════════════════════════════════════════════════════════════


class TestTruncationTrace:
    def test_l0_truncation_marked(self, seeded):
        r = _call(action="extract", topic_id=seeded["topic_id"],
                  conversation_id=seeded["conversation_id"],
                  levels=["L0"], max_chars=5)
        assert r["L0"]["truncated"] is True
        assert "已截断" in r["L0"]["content"], "截断未留痕（会被当成原文）"

    def test_l1_truncation_marked(self, seeded):
        r = _call(action="extract", topic_id=seeded["topic_id"],
                  conversation_id=seeded["conversation_id"],
                  levels=["L1"], max_chars=3)
        assert r["L1"]["truncated"] is True

    def test_no_truncation_when_under_limit(self, seeded):
        r = _call(action="extract", topic_id=seeded["topic_id"],
                  conversation_id=seeded["conversation_id"],
                  levels=["L0"], max_chars=100000)
        assert r["L0"]["truncated"] is False
        assert "已截断" not in r["L0"]["content"]

    def test_max_rounds_truncation_note(self, wired):
        tid = wired.create_topic("t")
        cid = wired.create_turn(tid, "q")
        for i in range(5):
            wired.append_round(cid, i, "assistant", f"r{i}")
        r = _call(action="extract", topic_id=tid, conversation_id=cid,
                  levels=["L1"], max_rounds=2)
        assert r["L1"]["truncated"] is True
        assert len(r["L1"]["messages"]) == 2
        assert "truncated_note" in r["L1"]


# ════════════════════════════════════════════════════════════
# 5. levels 选择解析
# ════════════════════════════════════════════════════════════


class TestLevelParsing:
    @pytest.mark.parametrize("raw,expected", [
        (None, ["L0", "L1", "L2", "L3"]),
        ("", ["L0", "L1", "L2", "L3"]),
        ([], ["L0", "L1", "L2", "L3"]),
        ("L0", ["L0"]),
        ("L0,L1", ["L0", "L1"]),
        ("l0, l2", ["L0", "L2"]),
        (["L1", "L3"], ["L1", "L3"]),
        (["0", "2"], ["L0", "L2"]),
        ("L0; L3", ["L0", "L3"]),
        (["L0", "L0"], ["L0"]),  # 去重
    ])
    def test_parse_levels(self, raw, expected):
        assert hist._parse_levels(raw) == expected

    def test_only_requested_levels_returned(self, seeded):
        r = _call(action="extract", topic_id=seeded["topic_id"],
                  conversation_id=seeded["conversation_id"], levels=["L0"])
        assert "L0" in r
        assert "L1" not in r and "L2" not in r and "L3" not in r
        assert r["levels_requested"] == ["L0"]

    def test_invalid_levels_falls_back_to_all(self, seeded):
        r = _call(action="extract", topic_id=seeded["topic_id"], levels=["L9", "xx"])
        assert set(r["levels_requested"]) == {"L0", "L1", "L2", "L3"}


# ════════════════════════════════════════════════════════════
# 6. 辅助 action
# ════════════════════════════════════════════════════════════


class TestAuxiliaryActions:
    def test_list_conversations_finds_turn(self, seeded):
        """list_conversations 的存在意义：让审计能定位 conversation_id。"""
        r = _call(action="list_conversations", topic_id=seeded["topic_id"])
        assert r["ok"] is True and r["count"] == 1
        assert r["conversations"][0]["conversation_id"] == seeded["conversation_id"]

    def test_list_conversations_requires_topic(self, wired, monkeypatch):
        """无 topic 且无活动主题 → 明确报错（而非静默返回空列表）。"""
        monkeypatch.setattr(hist, "_resolve_topic_id", lambda storage, tid: "")
        r = _call(action="list_conversations", topic_id="")
        assert r["ok"] is False

    def test_l0_versions_lists_snapshots(self, seeded):
        r = _call(action="l0_versions", topic_id=seeded["topic_id"])
        assert r["ok"] is True and r["count"] == 1
        assert r["snapshots"][0]["hash"]

    def test_levels_action_documents_scope(self, wired):
        r = _call(action="levels")
        assert r["ok"] is True
        assert r["levels"]["L0"]["scope"] == "conversation"
        assert r["levels"]["L2"]["scope"] == "topic"
        assert r["levels"]["L2"]["historical"] is False
        assert r["levels"]["L0"]["historical"] is True


# ════════════════════════════════════════════════════════════
# 7. 健壮性
# ════════════════════════════════════════════════════════════


class TestRobustness:
    def test_no_storage_returns_error_not_crash(self, monkeypatch):
        monkeypatch.setattr(hist, "_resolve_storage", lambda: (None, ""))
        r = _call(action="extract", topic_id="t")
        assert r["ok"] is False and "error" in r

    def test_bad_max_chars_falls_back(self, seeded):
        """max_chars 传非数字 → 回落默认，不炸。"""
        r = _call(action="extract", topic_id=seeded["topic_id"],
                  conversation_id=seeded["conversation_id"],
                  levels=["L0"], max_chars="abc")
        assert r["ok"] is True and r["L0"]["available"] is True

    def test_single_level_failure_isolated(self, seeded, wired, monkeypatch):
        """某层读取抛错只影响该层（失败隔离），其余层照常返回。"""

        def _boom(self, tid):
            raise RuntimeError("boom")

        monkeypatch.setattr(type(wired), "get_level2", _boom, raising=False)
        r = _call(action="extract", topic_id=seeded["topic_id"],
                  conversation_id=seeded["conversation_id"])
        assert r["ok"] is True
        assert r["L2"]["available"] is False
        # 其他层不受影响
        assert r["L0"]["available"] is True

    def test_corrupt_tool_calls_does_not_crash(self, wired):
        """tool_calls 是坏 JSON 时，L1 仍可读（store 层已降级为空）。"""
        st = wired
        tid = st.create_topic("t")
        cid = st.create_turn(tid, "q")
        st.append_round(cid, 0, "assistant", "正文",
                        tool_calls=[{"id": "c1", "type": "function",
                                     "function": {"name": "toolkit_exec", "arguments": "{}"}}])
        c = st.conn.cursor()
        c.execute("UPDATE agent_rounds SET tool_calls = ? WHERE conversation_id = ?",
                  ("{坏JSON", cid))
        st.conn.commit()
        c.close()
        r = _call(action="extract", topic_id=tid, conversation_id=cid, levels=["L1"])
        assert r["L1"]["available"] is True


# ════════════════════════════════════════════════════════════
# 8. 工具注册元数据（防止 schema 写错导致模型看不到）
# ════════════════════════════════════════════════════════════


class TestToolRegistration:
    def test_meta_is_valid_openai_schema(self):
        meta = hist.meta_toolkit_history_extract()
        assert meta["type"] == "function"
        fn = meta["function"]
        assert fn["name"] == "toolkit_history_extract"
        assert fn["description"]
        params = fn["parameters"]
        assert params["type"] == "object"
        assert "action" in params["properties"]
        for key in ("topic_id", "conversation_id", "levels", "max_chars", "max_rounds"):
            assert key in params["properties"], f"schema 缺参数 {key}"

    def test_toolkit_module_is_discoverable(self):
        """文件必须在 toolkit/ 下且以 toolkit_ 前缀命名（tlk 扫描约定）。"""
        import os

        path = os.path.join(os.path.dirname(hist.__file__), "toolkit_history_extract.py")
        assert os.path.isfile(path)
        assert os.path.basename(path).startswith("toolkit_")
