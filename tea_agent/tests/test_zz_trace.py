"""临时探针：判定「已删记忆仍被注入」的来源（用后删除）。

已确认：记忆 #12702394 在所有 DB 的 memories 表均已不存在（has_target=0），
但它**每轮仍被注入**。两种可能：
 (a) 实时读库 → 不可能（库已空）→ 说明读的是别的存储
 (b) 从**已持久化的对话历史**回放 → 该文本已写进 conversations 表，每轮重放
     （这同时解释「浪费 token」：陈旧注入块被永久携带）

本探针在 conversations 表里搜该文本，判定是 (b) 还是别的。
"""

import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NEEDLE = "打断模式"


def _scan(db: Path) -> dict:
    out: dict = {}
    try:
        c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    except sqlite3.Error as e:
        return {"error": str(e)}
    try:
        tabs = {r[0] for r in c.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        if "conversations" in tabs:
            cols = [r[1] for r in c.execute("PRAGMA table_info(conversations)").fetchall()]
            rows = c.execute(
                "SELECT id, topic_id, substr(user_msg,1,120), substr(ai_msg,1,120) "
                "FROM conversations WHERE user_msg LIKE ? OR ai_msg LIKE ? "
                "ORDER BY id DESC LIMIT 5", (f"%{NEEDLE}%", f"%{NEEDLE}%")).fetchall()
            out["conv_hits"] = len(rows)
            out["conv_cols"] = cols
            out["samples"] = [[str(x)[:120] for x in r] for r in rows]
        if "agent_rounds" in tabs:
            try:
                n = c.execute("SELECT COUNT(*) FROM agent_rounds WHERE content LIKE ?",
                              (f"%{NEEDLE}%",)).fetchone()[0]
                out["round_hits"] = n
            except sqlite3.Error as e:
                out["round_err"] = str(e)
        return out
    except sqlite3.Error as e:
        return {"error": str(e)}
    finally:
        c.close()


def test_trace_injection_source():
    out: dict = {}
    for db in [ROOT / ".tea_agent_run" / "ds_flash.db",
               ROOT / ".tea_agent_run" / "chat_history_2026-09-08.db",
               ROOT / ".tea_agent_run" / "chat_history.db",
               Path.home() / ".tea_agent" / "ds_flash.db"]:
        if db.exists():
            out[str(db)] = _scan(db)

    # 反向校验：注入文本的标记是否出现在记忆表（排除（a））
    out["memories_has_needle"] = {}
    for db in list((ROOT / ".tea_agent_run").glob("*.db")):
        try:
            c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            n = c.execute("SELECT COUNT(*) FROM memories WHERE content LIKE ?",
                          (f"%{NEEDLE}%",)).fetchone()[0]
            c.close()
            out["memories_has_needle"][db.name] = n
        except sqlite3.Error as e:
            out["memories_has_needle"][db.name] = f"err:{e}"

    (ROOT / "_inject_source.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    raise AssertionError(json.dumps(out, ensure_ascii=False, default=str)[:1600])
