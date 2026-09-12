"""临时探针：tokens 口径 + 记忆可靠性（用后删除）。

用户四问：逻辑正常 / 记忆可靠 / tokens 用量准确 / 防上溢。本探针只测前三个的
「数据层」部分，输出实际值供判定：
1. add_topic_tokens 各字段能否原样读回（含累计语义）
2. pending cheap tokens 的累加与清零
3. 记忆 add→search→forget 闭环 + 重开数据库后的持久性
"""

import json
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_tokens_and_memory_roundtrip():
    from tea_agent.store import Storage

    db = Storage(str(Path(tempfile.mkdtemp()) / "probe.db"))
    tid = db.create_topic("probe")

    # ── 1. token 字段往返 ──
    payload = {"total_tokens": 100, "prompt_tokens": 60, "completion_tokens": 40,
               "cheap_tokens": 10, "cheap_prompt_tokens": 6, "cheap_completion_tokens": 4,
               "embedding_tokens": 5, "embedding_prompt_tokens": 5}
    db.add_topic_tokens(tid, **payload)
    got1 = db.get_topic_tokens(tid)

    db.add_topic_tokens(tid, total_tokens=100, prompt_tokens=60, completion_tokens=40)
    got2 = db.get_topic_tokens(tid)

    # ── 2. pending cheap tokens ──
    db.accumulate_pending_cheap_tokens(tid, {"total_tokens": 7, "prompt_tokens": 3,
                                             "completion_tokens": 4})
    db.accumulate_pending_cheap_tokens(tid, {"total_tokens": 5, "prompt_tokens": 2,
                                             "completion_tokens": 3})
    pending = db.get_and_clear_pending_cheap_tokens(tid)
    after_clear = db.get_and_clear_pending_cheap_tokens(tid)

    # ── 3. 记忆闭环 + 持久性 ──
    mid = db.add_memory("探针记忆内容", category="general", priority=2, importance=3)
    listed = db.get_active_memories(limit=50)
    found = [m for m in listed if str(m.get("id")) == str(mid)]
    searched = db.search_memories(query="探针记忆")
    db.forget_memory(mid)
    after_forget = [m for m in db.get_active_memories(limit=50)
                    if str(m.get("id")) == str(mid)]
    stats = db.get_memory_stats()

    db2 = Storage(str(db.db_path))
    reopened = [m for m in db2.get_active_memories(limit=50)
                if str(m.get("id")) == str(mid)]
    tokens_persist = db2.get_topic_tokens(tid)

    out = {
        "tokens_first": got1, "tokens_after_second_add": got2,
        "pending_sum": pending, "pending_after_clear": after_clear,
        "memory_id": str(mid), "memory_listed": len(found),
        "memory_searched": len(searched), "memory_after_forget": len(after_forget),
        "memory_stats": stats, "memory_reopened": len(reopened),
        "tokens_persist_total": tokens_persist.get("total_tokens"),
    }
    (ROOT / "_tokens_probe.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    raise AssertionError(json.dumps(out, ensure_ascii=False))
