"""临时探针：确认注入是否来自「被持久化的对话历史回放」（用后删除）。

已排除：memories 表（全库 needle=0）、project_memories.json（[]）。
但注入持续发生 → 怀疑该文本已被持久化进对话历史（L2 / rounds / agent_rounds），
每轮作为历史被回放，且其「共 1 条」是冻结在文本里的字面量。

本探针取各载体的原文片段，判定来源形态。
"""

import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NEEDLE = "打断模式"
DB = ROOT / ".tea_agent_run" / "chat_history_2026-09-12.db"


def _snippet(text: str, radius: int = 200) -> str:
    i = text.find(NEEDLE)
    if i < 0:
        return ""
    return text[max(0, i - radius):i + radius]


def test_confirm_history_replay():
    out: dict = {"db": str(DB), "exists": DB.exists()}
    if not DB.exists():
        raise AssertionError(json.dumps(out, ensure_ascii=False))

    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        # 1. agent_rounds
        rows = c.execute(
            "SELECT id, conversation_id, substr(content,1,4000) FROM agent_rounds "
            "WHERE content LIKE ? LIMIT 2", (f"%{NEEDLE}%",)).fetchall()
        out["agent_rounds_hits"] = len(rows)
        out["agent_rounds_snippets"] = [
            _snippet(r[2] or "") for r in rows]

        # 2. conversations.rounds_json
        rows = c.execute(
            "SELECT id, substr(rounds_json,1,20000) FROM conversations "
            "WHERE rounds_json LIKE ? LIMIT 2", (f"%{NEEDLE}%",)).fetchall()
        out["rounds_json_hits"] = len(rows)
        out["rounds_json_snippets"] = [_snippet(r[1] or "") for r in rows]

        # 3. topics.level2_json
        rows = c.execute(
            "SELECT topic_id, substr(level2_json,1,20000) FROM topics "
            "WHERE level2_json LIKE ? LIMIT 2", (f"%{NEEDLE}%",)).fetchall()
        out["level2_hits"] = len(rows)
        out["level2_snippets"] = [_snippet(r[1] or "") for r in rows]

        # 4. conversations.user_msg（注入块是否作为 user 消息入库）
        rows = c.execute(
            "SELECT id, substr(user_msg,1,2000) FROM conversations "
            "WHERE user_msg LIKE ? LIMIT 3", (f"%{NEEDLE}%",)).fetchall()
        out["user_msg_hits"] = len(rows)
        out["user_msg_snippets"] = [_snippet(r[1] or "") for r in rows]
    finally:
        c.close()

    (ROOT / "_replay.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    raise AssertionError(json.dumps(
        {k: v for k, v in out.items() if "snippet" in k or "hits" in k},
        ensure_ascii=False)[:1400])
