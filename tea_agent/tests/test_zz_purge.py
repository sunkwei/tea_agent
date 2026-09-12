"""临时探针：清掉卡在旧库里的那条记忆（用后删除）。

注入文本「共 1 条」与 .tea_agent_run/chat_history_2026-09-08.db 的
(mem_total=1, mem_active=1, has_target=1) 完全吻合 —— 当前会话读的就是这个库。
用 store 层 API（而非裸 SQL）删除，使注入即刻停止。
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STALE = ROOT / ".tea_agent_run" / "chat_history_2026-09-08.db"
NEEDLE = "打断模式"


def test_purge_stale_memory_from_old_db():
    from tea_agent.store import Storage

    out: dict = {"db": str(STALE), "exists": STALE.exists()}
    if not STALE.exists():
        raise AssertionError(json.dumps(out, ensure_ascii=False))

    db = Storage(str(STALE))
    before = db.get_active_memories(limit=100)
    out["active_before"] = len(before)
    out["contents_before"] = [(m.get("id"), (m.get("content") or "")[:60]) for m in before]

    removed = []
    for m in before:
        if NEEDLE in (m.get("content") or ""):
            ok = db.delete_memory(m["id"])
            removed.append((m["id"], ok))
    out["removed"] = removed
    after = db.get_active_memories(limit=100)
    out["active_after"] = len(after)
    out["contents_after"] = [(m.get("id"), (m.get("content") or "")[:60]) for m in after]

    (ROOT / "_purge.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    raise AssertionError(json.dumps(out, ensure_ascii=False, default=str)[:1200])
