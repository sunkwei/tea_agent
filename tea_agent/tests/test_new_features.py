"""
@2026-07-07 gen by tea_agent, 新增功能测试
覆盖: estimate_tokens, _progressive_trim, search_conversations
"""

from unittest.mock import MagicMock


# ============================================================
# estimate_tokens / estimate_messages_tokens / _progressive_trim
# ============================================================

class TestTokenEstimation:
    """token 估算功能测试"""

    def test_empty_text(self):
        from tea_agent.session._history_builder import estimate_tokens
        assert estimate_tokens("") == 0
        assert estimate_tokens(None) == 0

    def test_english_text(self):
        from tea_agent.session._history_builder import estimate_tokens
        text = "Hello world, this is a test message with some English words."
        tokens = estimate_tokens(text)
        assert tokens > 0
        # 约 50 字符 / 4 = ~12.5 + 4 overhead
        assert 10 <= tokens <= 25

    def test_chinese_text(self):
        from tea_agent.session._history_builder import estimate_tokens
        text = "这是一个中文测试消息，用于验证估算函数"
        tokens = estimate_tokens(text)
        assert tokens > 0
        # 约 21 中文字 / 1.5 = ~14 + 4 overhead
        assert 10 <= tokens <= 30

    def test_mixed_text(self):
        from tea_agent.session._history_builder import estimate_tokens
        text = "Hello 你好 world 世界 test 测试"
        tokens = estimate_tokens(text)
        assert tokens > 0

    def test_messages_list(self):
        from tea_agent.session._history_builder import estimate_messages_tokens
        messages = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Hello!"},
            {"role": "assistant", "content": "Hi there!"},
        ]
        total = estimate_messages_tokens(messages)
        assert total > 0
        # 3 messages * 4 overhead = 12, plus content
        assert total > 12


class TestProgressiveTrim:
    """渐进式裁剪测试"""

    def test_no_trim_needed(self):
        from tea_agent.session._history_builder import _progressive_trim, estimate_messages_tokens
        messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi"},
        ]
        budget = estimate_messages_tokens(messages) * 2  # 宽松预算
        result = _progressive_trim(messages, budget, None)
        assert len(result) == len(messages)

    def test_trim_long_tool_output(self):
        from tea_agent.session._history_builder import _progressive_trim
        long_output = "x" * 10000
        messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "List files"},
            {"role": "assistant", "content": "Sure", "tool_calls": [
                {"id": "call_1", "type": "function",
                 "function": {"name": "list", "arguments": "{}"}}
            ]},
            {"role": "tool", "tool_call_id": "call_1", "content": long_output},
        ]
        budget = 200  # 很小，一定会触发裁剪
        result = _progressive_trim(messages, budget, None)
        # 工具输出被替换为占位符
        tool_msgs = [m for m in result if m.get("role") == "tool"]
        assert len(tool_msgs) > 0
        assert "[工具结果已省略" in tool_msgs[0]["content"]

    def test_trim_reasoning_content(self):
        from tea_agent.session._history_builder import _progressive_trim, estimate_tokens
        messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Tell me a story"},
            {"role": "assistant", "content": "Once upon a time...",
             "reasoning_content": "x" * 5000},
        ]
        budget = estimate_tokens(messages[2]["content"]) + 50
        result = _progressive_trim(messages, budget, None)
        # reasoning_content 被清除
        for m in result:
            if m.get("role") == "assistant":
                assert m.get("reasoning_content", "") == ""

    def test_trim_old_user_turns(self):
        from tea_agent.session._history_builder import _progressive_trim
        messages = [
            {"role": "system", "content": "You are helpful."},
        ]
        # 添加 10 轮对话
        for i in range(10):
            messages.append({"role": "user", "content": f"Question {i}"})
            messages.append({"role": "assistant", "content": f"Answer {i}"})

        budget = 100  # 极紧预算
        result = _progressive_trim(messages, budget, None)
        # 保留 system 和部分最近轮次
        assert len(result) > 0
        assert result[0]["role"] == "system"

    def test_l2_entry_removal(self):
        from tea_agent.session._history_builder import _progressive_trim
        messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "[历史记录]\n用户: old question"},
            {"role": "assistant", "content": "old answer"},
            {"role": "user", "content": "current question"},
            {"role": "assistant", "content": "current answer"},
        ]
        budget = 20  # 极小预算，一定会删除 L2
        result = _progressive_trim(messages, budget, None)
        l2_items = [m for m in result
                    if isinstance(m.get("content"), str)
                    and "[历史记录]" in m["content"]]
        assert len(l2_items) == 0, "L2 条目应被优先删除"


# ============================================================
# search_conversations
# ============================================================

class TestSearchConversations:
    """对话全文搜索测试"""

    def _make_mock_db(self, results):
        """创建模拟 Storage 对象"""
        mock_db = MagicMock()
        mock_db.search_conversations.return_value = results
        return mock_db

    def test_empty_query_returns_empty(self):
        from tea_agent.store._conversations import ConversationStore
        store = ConversationStore(":memory:")
        result = store.search_conversations("")
        assert result == []
        result = store.search_conversations("   ")
        assert result == []

    def test_make_snippet_centered(self):
        from tea_agent.store._conversations import ConversationStore
        text = "This is a long text with the keyword embedded in the middle somewhere"
        snippet = ConversationStore._make_snippet(text, "keyword", context_chars=20)
        assert "keyword" in snippet
        assert "..." not in snippet or (snippet.startswith("...") or snippet.endswith("..."))

    def test_make_snippet_exact_match(self):
        from tea_agent.store._conversations import ConversationStore
        text = "keyword"
        snippet = ConversationStore._make_snippet(text, "keyword")
        assert snippet == "keyword"

    def test_make_snippet_not_found(self):
        from tea_agent.store._conversations import ConversationStore
        text = "Hello world"
        snippet = ConversationStore._make_snippet(text, "nothing")
        assert snippet == "Hello world"

    def test_search_ranks_by_relevance(self):
        """验证搜索结果按相关性排序"""
        from tea_agent.store._conversations import ConversationStore
        import sqlite3
        # 使用临时文件数据库并初始化表
        import tempfile, os
        tmpf = tempfile.mktemp(suffix='.db')
        try:
            conn = sqlite3.connect(tmpf)
            conn.row_factory = sqlite3.Row
            conn.execute('''
                CREATE TABLE topics (topic_id TEXT PRIMARY KEY, title TEXT NOT NULL,
                    create_stamp TEXT DEFAULT (datetime('now','localtime')))
            ''')
            conn.execute('''
                CREATE TABLE conversations (
                    id TEXT PRIMARY KEY, topic_id TEXT NOT NULL,
                    user_msg TEXT NOT NULL, ai_msg TEXT NOT NULL,
                    is_func_calling INTEGER DEFAULT 0, is_summarized INTEGER DEFAULT 0,
                    rounds_json TEXT,
                    stamp TIMESTAMP DEFAULT (datetime('now','localtime')),
                    FOREIGN KEY (topic_id) REFERENCES topics(topic_id))
            ''')
            conn.execute('''
                CREATE TABLE agent_rounds (
                    id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL,
                    round_num INTEGER NOT NULL, role TEXT NOT NULL,
                    content TEXT, tool_calls TEXT, tool_call_id TEXT,
                    stamp TIMESTAMP DEFAULT (datetime('now','localtime')),
                    FOREIGN KEY (conversation_id) REFERENCES conversations(id))
            ''')
            conn.execute("INSERT INTO topics (topic_id, title) VALUES ('t1', 'Test Topic')")
            conn.execute("INSERT INTO conversations (id, topic_id, user_msg, ai_msg) VALUES ('c1','t1','hello test world','reply with test')")
            conn.commit()
            conn.close()

            store = ConversationStore(tmpf)
            results = store.search_conversations("test", limit=10)
            assert isinstance(results, list)
            assert len(results) > 0
            assert all("rank_score" in r for r in results)
            # order check
            scores = [r["rank_score"] for r in results]
            assert scores == sorted(scores, reverse=True), "必须按分数降序排列"
        finally:
            try: os.unlink(tmpf)
            except: pass


# ============================================================
# _find_prune_cutoff
# ============================================================

class TestPruneCutoff:
    """裁剪分界点检测测试"""

    def test_find_cutoff_basic(self):
        from tea_agent.session._history_builder import _find_prune_cutoff
        msgs = [
            {"role": "user"}, {"role": "assistant"},
            {"role": "user"}, {"role": "assistant"},
            {"role": "user"}, {"role": "assistant"},
        ]
        # 从后往前数 3 个 user，应该索引 0
        assert _find_prune_cutoff(msgs, tail_turns=3) == 0

    def test_find_cutoff_less_than_tail(self):
        from tea_agent.session._history_builder import _find_prune_cutoff
        msgs = [
            {"role": "user"}, {"role": "assistant"},
        ]
        # 只有 1 个 user，不足 3 轮，返回 0（不裁剪）
        assert _find_prune_cutoff(msgs, tail_turns=3) == 0

    def test_find_cutoff_many_users(self):
        from tea_agent.session._history_builder import _find_prune_cutoff
        msgs = []
        for i in range(10):
            msgs.append({"role": "user"})
            msgs.append({"role": "assistant"})
        # 从后往前数 3 个 user: i=7,8,9 → 索引 14 (user 7 在 14)
        assert _find_prune_cutoff(msgs, tail_turns=3) == 14
