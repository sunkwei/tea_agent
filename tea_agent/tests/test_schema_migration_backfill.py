"""旧结构库自动迁移的回归测试。

背景（用户提问）：老数据库能否自动升级到新结构？

实测确认两件事：
  1. **schema 会自动加列** —— ``migrate()`` 在每次 ``Storage.__init__`` 调用，
     ``ALTER TABLE`` 幂等（try/except 包裹），旧行由 SQLite 回填 DEFAULT。
  2. **但数据层需要显式回填** —— 新增的 ``backfill_rounds_from_json``：
     旧库若只写了 ``conversations.rounds_json`` 而没写 ``agent_rounds``，
     改成「从 agent_rounds 派生」后这些轮次会**静默丢失**。

本文件钉住这两条，尤其是第 2 条（无测试则静默丢数据）。
"""

from __future__ import annotations

import json
import sqlite3

# 改动之前的 schema（无 status/deleted_at/reasoning_content）
OLD_SCHEMA = """
CREATE TABLE topics (
    topic_id TEXT PRIMARY KEY,
    title TEXT NOT NULL DEFAULT '',
    is_active INTEGER DEFAULT 1,
    last_update_stamp TIMESTAMP,
    system_prompt TEXT,
    drift_count INTEGER DEFAULT 0
);
CREATE TABLE conversations (
    id TEXT PRIMARY KEY,
    topic_id TEXT NOT NULL,
    user_msg TEXT NOT NULL,
    ai_msg TEXT NOT NULL,
    is_func_calling INTEGER DEFAULT 0,
    is_summarized INTEGER DEFAULT 0,
    stamp TIMESTAMP,
    rounds_json TEXT
);
CREATE TABLE agent_rounds (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    round_num INTEGER NOT NULL,
    role TEXT NOT NULL,
    content TEXT,
    tool_calls TEXT,
    tool_call_id TEXT,
    stamp TIMESTAMP
);
CREATE TABLE images (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL,
    image_blob BLOB NOT NULL,
    mime_type TEXT DEFAULT 'image/png'
);
"""


ROUNDS = [
    {"role": "assistant", "content": "调工具",
     "tool_calls": [{"id": "c1", "type": "function",
                     "function": {"name": "tk", "arguments": "{}"}}],
     "reasoning_content": "思考"},
    {"role": "tool", "content": "结果", "tool_call_id": "c1"},
]


def _make_old_db(path, with_rounds_json=True, with_agent_rounds=False,
                 rounds_json_raw=None):
    """构造一个「改动之前」的库，可选填充数据。"""
    c = sqlite3.connect(str(path))
    c.executescript(OLD_SCHEMA)
    c.execute("INSERT INTO topics (topic_id, title) VALUES ('t1', '旧主题')")
    raw = rounds_json_raw if rounds_json_raw is not None else json.dumps(ROUNDS, ensure_ascii=False)
    c.execute(
        "INSERT INTO conversations (id, topic_id, user_msg, ai_msg, is_func_calling, rounds_json) "
        "VALUES ('cv1', 't1', '旧问题', '旧回答', 1, ?)",
        (raw if with_rounds_json else None,),
    )
    if with_agent_rounds:
        for i, r in enumerate(ROUNDS):
            c.execute(
                "INSERT INTO agent_rounds "
                "(id, conversation_id, round_num, role, content, tool_calls, tool_call_id) "
                "VALUES (?,?,?,?,?,?,?)",
                ("r%d" % i, "cv1", i, r["role"], r["content"],
                 json.dumps(r.get("tool_calls"), ensure_ascii=False) if r.get("tool_calls") else None,
                 r.get("tool_call_id")),
            )
    c.commit()
    c.close()


def _cols(conn, tbl):
    return [r[1] for r in conn.execute("PRAGMA table_info(%s)" % tbl)]


def _open(path):
    from tea_agent.store import Storage

    return Storage(db_path=str(path))


class TestSchemaAutoUpgrade:
    """schema 加列必须自动完成（旧库直接打开即可用）。"""

    def test_new_columns_added(self, tmp_path):
        p = tmp_path / "old.db"
        _make_old_db(p)
        s = _open(p)
        assert "status" in _cols(s.conn, "conversations")
        assert "deleted_at" in _cols(s.conn, "conversations")
        assert "reasoning_content" in _cols(s.conn, "agent_rounds")
        assert "deleted_at" in _cols(s.conn, "agent_rounds")
        assert "deleted_at" in _cols(s.conn, "topics")
        assert "deleted_at" in _cols(s.conn, "images")
        s.close()

    def test_existing_rows_get_defaults(self, tmp_path):
        """既有行由 SQLite 回填 DEFAULT，不是 NULL（否则读路径过滤会误伤）。"""
        p = tmp_path / "old.db"
        _make_old_db(p)
        s = _open(p)
        row = s.conn.execute(
            "SELECT status, deleted_at FROM conversations WHERE id='cv1'").fetchone()
        assert row[0] == "done", "status 默认值应为 done（旧数据视为已完成）"
        assert row[1] is None, "deleted_at 默认 NULL（未删除）"
        s.close()

    def test_old_data_still_readable(self, tmp_path):
        """旧主题/图片迁移后仍可读。"""
        p = tmp_path / "old.db"
        _make_old_db(p, with_agent_rounds=True)
        s = _open(p)
        assert s.get_topic("t1") is not None
        assert len(s.list_topics()) == 1
        assert len(s.get_conversations("t1", limit=0)) == 1
        s.close()


class TestRoundsBackfill:
    """rounds_json → agent_rounds 回填（缺此步则旧轮次静默丢失）。"""

    def test_backfill_makes_old_rounds_readable(self, tmp_path):
        """**核心用例**：只有 rounds_json 的旧对话，迁移后轮次必须可读。"""
        p = tmp_path / "old.db"
        _make_old_db(p, with_agent_rounds=False)
        s = _open(p)
        rounds = s.get_rounds("cv1")
        assert len(rounds) == 2, "回填缺失 → 旧轮次丢失"
        assert rounds[0]["role"] == "assistant"
        assert rounds[1]["role"] == "tool"
        # get_conversations 的派生字段也应可用
        convs = s.get_conversations("t1", limit=0, include_rounds=True)
        assert len(convs[0]["rounds_json_parsed"]) == 2
        s.close()

    def test_backfill_preserves_reasoning_content(self, tmp_path):
        p = tmp_path / "old.db"
        _make_old_db(p)
        s = _open(p)
        rc = s.conn.execute(
            "SELECT reasoning_content FROM agent_rounds WHERE conversation_id='cv1' "
            "AND round_num=0").fetchone()[0]
        assert rc == "思考", "reasoning_content 应独立成列保留"
        s.close()

    def test_backfill_is_idempotent(self, tmp_path):
        """多次打开不得重复插入（否则每次启动都膨胀）。"""
        p = tmp_path / "old.db"
        _make_old_db(p)
        counts = []
        for _ in range(4):
            s = _open(p)
            counts.append(s.conn.execute(
                "SELECT COUNT(*) FROM agent_rounds").fetchone()[0])
            s.close()
        assert counts == [2, 2, 2, 2], "回填不幂等: %s" % counts

    def test_no_duplicate_when_agent_rounds_exists(self, tmp_path):
        """已有 agent_rounds 行的对话不重复回填（避免明细翻倍）。"""
        p = tmp_path / "old.db"
        _make_old_db(p, with_agent_rounds=True)
        s = _open(p)
        n = s.conn.execute(
            "SELECT COUNT(*) FROM agent_rounds WHERE conversation_id='cv1'").fetchone()[0]
        assert n == 2, "已有明细的对话被重复回填: %d 行" % n
        s.close()

    def test_corrupt_json_skipped(self, tmp_path):
        """损坏的 rounds_json 跳过，不拖垮迁移（其他对话仍可读）。"""
        p = tmp_path / "old.db"
        _make_old_db(p, rounds_json_raw="{不是合法JSON")
        s = _open(p)
        assert s.conn.execute(
            "SELECT COUNT(*) FROM agent_rounds").fetchone()[0] == 0
        assert s.get_topic("t1") is not None, "损坏数据不应阻断迁移"
        s.close()

    def test_backfill_keeps_rounds_json(self, tmp_path):
        """回填后保留 rounds_json 原文（append-only：不主动销毁事实）。"""
        p = tmp_path / "old.db"
        _make_old_db(p)
        s = _open(p)
        raw = s.conn.execute(
            "SELECT rounds_json FROM conversations WHERE id='cv1'").fetchone()[0]
        assert raw, "回填不应清除原始 rounds_json"
        s.close()
