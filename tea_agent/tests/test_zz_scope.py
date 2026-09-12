"""临时探针：定位「删的库 vs 读的库」不一致（用后删除）。

已确认：get_storage() → .tea_agent_run/ds_flash.db（0 条），
而 ~/.tea_agent/chat_history.db 有 3630 条活跃。若后者含同一条「打断模式」记忆，
则「删除记忆」在用户视角不生效 = 记忆不可靠（且每轮白烧 token 注入已删内容）。
"""

import json
import sqlite3
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
USER_DB = Path.home() / ".tea_agent" / "chat_history.db"


def _ro(db: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{db}?mode=ro", uri=True)


def test_which_db_holds_the_memory():
    out: dict = {}

    # ── 1. 用户库里是否含「打断模式」记忆 ──
    if USER_DB.exists():
        c = _ro(USER_DB)
        cols = [r[1] for r in c.execute("PRAGMA table_info(memories)").fetchall()]
        out["user_db_memories_columns"] = cols
        hits = c.execute(
            "SELECT id, is_active, category, priority, substr(content,1,60) "
            "FROM memories WHERE content LIKE '%打断模式%'"
        ).fetchall()
        out["user_db_hits_打断模式"] = [list(h) for h in hits]
        out["user_db_active_total"] = c.execute(
            "SELECT COUNT(*) FROM memories WHERE is_active = 1").fetchone()[0]
        out["user_db_priority_breakdown"] = dict(c.execute(
            "SELECT priority, COUNT(*) FROM memories WHERE is_active=1 GROUP BY priority"
        ).fetchall())
        c.close()

    # ── 2. ds_flash.db 的表结构（确认是否有 memories 表）──
    ds = Path(ROOT) / ".tea_agent_run" / "ds_flash.db"
    if ds.exists():
        c = _ro(ds)
        out["ds_flash_tables"] = [r[0] for r in c.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        try:
            out["ds_flash_memories_cols"] = [r[1] for r in c.execute(
                "PRAGMA table_info(memories)").fetchall()]
            out["ds_flash_memory_rows"] = c.execute(
                "SELECT COUNT(*) FROM memories").fetchone()[0]
        except sqlite3.OperationalError as e:
            out["ds_flash_memories_error"] = str(e)
        c.close()

    # ── 3. 校验写入/读取一致性：新记忆写进 get_storage() 后，能否在用户库看到 ──
    from tea_agent.store import get_storage
    st = get_storage()
    token = "ZZ_SCOPE_TOKEN_777"
    mid = st.add_memory(token, category="fact", priority=2, importance=3)
    out["wrote_to"] = str(getattr(st, "db_path", "?"))
    out["mid"] = str(mid)

    if USER_DB.exists():
        c = _ro(USER_DB)
        found_user = c.execute(
            "SELECT COUNT(*) FROM memories WHERE content LIKE ?", (f"%{token}%",)
        ).fetchone()[0]
        c.close()
        out["visible_in_user_db"] = found_user
    out["visible_in_get_storage"] = sum(
        1 for m in st.get_active_memories(limit=5000) if token in (m.get("content") or ""))
    st.delete_memory(mid)

    (ROOT / "_scope_verdict.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    raise AssertionError(json.dumps(out, ensure_ascii=False, default=str)[:1600])
