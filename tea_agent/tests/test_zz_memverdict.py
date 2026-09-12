"""临时探针：记忆可靠性判定（用后删除）。

用户要求「有可靠的记忆」。发现：记忆 #12702394 已硬删除（toolkit_memory list 为空），
但动态上下文**持续**注入它（多轮之后仍在）→ 要么删错了库，要么缓存未失效。

本探针用数据判定（不猜）：
A. get_storage() 实际 db_path vs 配置 db_path vs 磁盘上的候选 DB（各库活跃记忆数）
B. MemoryManager.select_memories 在「删除后」是否返回已删记忆（缓存 bug？）
C. 记忆增删后 get_active_memories 的即时一致性
"""

import json
import os
import sqlite3
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _db_snapshot(p: Path) -> dict:
    try:
        c = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
        try:
            rows = c.execute("SELECT id, is_active, substr(content,1,50) FROM memories").fetchall()
        except sqlite3.OperationalError as e:
            return {"error": f"无 memories 表: {e}"}
        c.close()
        active = [r for r in rows if r[1]]
        return {"total_rows": len(rows), "active": len(active),
                "active_ids": [r[0] for r in active][:5]}
    except OSError as e:
        return {"error": str(e)}


def test_memory_reliability_verdict():
    from tea_agent.config import get_config
    from tea_agent.store import get_storage

    st = get_storage()
    cfg = get_config()

    out: dict = {"cwd": os.getcwd()}

    # ── A. 到底有几个 DB ──
    st_path = getattr(st, "db_path", None) or getattr(st, "_db_path", None)
    out["get_storage_db_path"] = str(st_path)
    out["config_db_path"] = str(getattr(cfg, "db_path", ""))
    out["config_db_path_abs"] = str(getattr(cfg, "_db_path_abs", ""))
    out["config_data_dir"] = str(getattr(cfg, "data_dir", ""))

    cands = [Path(os.getcwd()) / "chat_history.db",
             Path.home() / ".tea_agent" / "chat_history.db"]
    dd = getattr(cfg, "data_dir", "")
    if dd:
        cands.append(Path(dd) / "chat_history.db")
    if st_path:
        cands.append(Path(str(st_path)))
    out["disk_dbs"] = {str(p): _db_snapshot(p) for p in dict.fromkeys(cands) if p.exists()}

    # ── B. MemoryManager 删除后是否仍返回（缓存 bug 判定）──
    from tea_agent.memory import MemoryManager

    db = get_storage.__module__ and __import__("tea_agent.store", fromlist=["Storage"]).Storage(
        str(Path(tempfile.mkdtemp()) / "fresh.db"))
    tok = "ZZQ_UNIQUE_MEMORY_TOKEN_42"
    mid = db.add_memory(tok, category="instruction", priority=1, importance=5)
    mm = MemoryManager(db)

    sel_before = mm.select_memories(tok, limit=10)
    hit_before = any(tok in (m.get("content") or "") for m in sel_before)

    db.deactivate_memory(mid)
    sel_after_soft = mm.select_memories(tok, limit=10)
    hit_after_soft = any(tok in (m.get("content") or "") for m in sel_after_soft)

    db.delete_memory(mid)
    sel_after_hard = mm.select_memories(tok, limit=10)
    hit_after_hard = any(tok in (m.get("content") or "") for m in sel_after_hard)

    out["B_manager"] = {
        "hit_before_delete": hit_before,
        "hit_after_soft_delete": hit_after_soft,
        "hit_after_hard_delete": hit_after_hard,
        "active_after_hard": len(db.get_active_memories(limit=50)),
    }

    # ── C. 会话真实存储上：硬删后是否立刻从活跃列表消失 ──
    live = st.get_active_memories(limit=50)
    out["C_live_storage"] = {
        "active_count": len(live),
        "ids": [m.get("id") for m in live][:5],
    }

    (ROOT / "_mem_verdict.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    raise AssertionError(json.dumps(out, ensure_ascii=False, default=str)[:1500])
