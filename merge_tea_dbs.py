#!/usr/bin/env python3
"""
合并两个 tea_agent 存储数据库（chat_history.db 格式）。

将源数据库中的 topics、conversations、memories 合并到目标数据库。

用法: python merge_tea_dbs.py <source.db> <target.db> [--strategy skip|overwrite|keep_both]

策略:
  keep_both  - 冲突时重命名冲突条目（默认，保留两端数据）
  overwrite  - 用源数据覆盖目标中冲突的行
  skip       - 跳过冲突条目，只合并不冲突的

注意:
  - 合并前自动备份目标为 .bak
  - keep_both 策略下重命名的 topic，其关联的 conversations 和 memories 的 FK 也会同步更新
  - 只合并 topoics/conversations/memories 三张表，其他表（vectors/images等）不处理
"""
import argparse
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = OFF")
    return conn


def _make_ts() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


# ─────────── 读取 ───────────

def read_topics(db_path: str) -> List[dict]:
    conn = _connect(db_path)
    rows = conn.execute("SELECT * FROM topics ORDER BY create_stamp").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def read_conversations(db_path: str) -> List[dict]:
    conn = _connect(db_path)
    rows = conn.execute("SELECT * FROM conversations ORDER BY stamp").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def read_memories(db_path: str) -> List[dict]:
    conn = _connect(db_path)
    rows = conn.execute("SELECT * FROM memories ORDER BY created_at").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_topic_ids(db_path: str) -> set:
    conn = _connect(db_path)
    ids = {r[0] for r in conn.execute("SELECT topic_id FROM topics").fetchall()}
    conn.close()
    return ids


def get_conv_ids(db_path: str) -> set:
    conn = _connect(db_path)
    ids = {r[0] for r in conn.execute("SELECT id FROM conversations").fetchall()}
    conn.close()
    return ids


def get_memory_ids(db_path: str) -> set:
    conn = _connect(db_path)
    ids = {r[0] for r in conn.execute("SELECT id FROM memories").fetchall()}
    conn.close()
    return ids


# ─────────── 写入 ───────────

def insert_topic(conn: sqlite3.Connection, topic: dict):
    conn.execute("""
        INSERT OR REPLACE INTO topics
        (topic_id, title, create_stamp, last_update_stamp, semantic_summary,
         tool_chain_summary, level2_json, l3_pending_json, drift_count, is_active)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        topic["topic_id"], topic["title"],
        topic["create_stamp"], topic.get("last_update_stamp", ""),
        topic.get("semantic_summary", ""), topic.get("tool_chain_summary", ""),
        topic.get("level2_json", "[]"), topic.get("l3_pending_json", ""),
        topic.get("drift_count", 0), topic.get("is_active", 1),
    ))


def insert_conversation(conn: sqlite3.Connection, conv: dict):
    conn.execute("""
        INSERT OR REPLACE INTO conversations
        (id, topic_id, user_msg, ai_msg, is_func_calling, is_summarized, stamp, rounds_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        conv["id"], conv["topic_id"],
        conv["user_msg"], conv["ai_msg"],
        conv.get("is_func_calling", 0), conv.get("is_summarized", 0),
        conv["stamp"], conv.get("rounds_json"),
    ))


def insert_memory(conn: sqlite3.Connection, mem: dict):
    conn.execute("""
        INSERT OR REPLACE INTO memories
        (id, content, category, priority, importance, expires_at,
         is_active, tags, source_topic_id, created_at, updated_at,
         last_accessed_at, pinned)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        mem["id"], mem["content"], mem.get("category", "general"),
        mem.get("priority", 2), mem.get("importance", 3),
        mem.get("expires_at"), mem.get("is_active", 1),
        mem.get("tags", ""), mem.get("source_topic_id"),
        mem.get("created_at", ""), mem.get("updated_at", ""),
        mem.get("last_accessed_at"), mem.get("pinned", 0),
    ))


# ─────────── 合并核心 ───────────

def merge_dbs(source_path: str, target_path: str, strategy: str) -> Dict:
    target_topic_ids = get_topic_ids(target_path)
    target_conv_ids  = get_conv_ids(target_path)
    target_mem_ids   = get_memory_ids(target_path)

    topic_rename_map: Dict[str, str] = {}  # old_topic_id → new_topic_id

    stats = {"topics": 0, "conversations": 0, "memories": 0, "skipped": 0, "renamed": 0}

    conn = sqlite3.connect(target_path)
    conn.execute("PRAGMA foreign_keys = OFF")

    # ── 1. 合并 topics ──
    for t in read_topics(source_path):
        tid = t["topic_id"]
        if tid in target_topic_ids:
            if strategy == "skip":
                stats["skipped"] += 1
                print(f"  ⏭ 跳过 topic: {tid} [{t.get('title','')}]")
                continue
            elif strategy == "keep_both":
                new_tid = f"{tid}_merged_{_make_ts()}"
                topic_rename_map[tid] = new_tid
                t["topic_id"] = new_tid
                stats["renamed"] += 1
                print(f"  ⚡ 重命名 topic: {tid} → {new_tid}")
            # overwrite: 直接用 INSERT OR REPLACE
        insert_topic(conn, t)
        stats["topics"] += 1
        target_topic_ids.add(t["topic_id"])

    # ── 2. 合并 conversations ──
    for c in read_conversations(source_path):
        if c["topic_id"] in topic_rename_map:
            c["topic_id"] = topic_rename_map[c["topic_id"]]
        cid = c["id"]
        if cid in target_conv_ids:
            if strategy == "skip":
                stats["skipped"] += 1
                continue
            elif strategy == "keep_both":
                c["id"] = f"{cid}_merged_{_make_ts()}"
                stats["renamed"] += 1
        insert_conversation(conn, c)
        stats["conversations"] += 1
        target_conv_ids.add(c["id"])

    # ── 3. 合并 memories ──
    for m in read_memories(source_path):
        if m.get("source_topic_id") and m["source_topic_id"] in topic_rename_map:
            m["source_topic_id"] = topic_rename_map[m["source_topic_id"]]
        mid = m["id"]
        if mid in target_mem_ids:
            if strategy == "skip":
                stats["skipped"] += 1
                continue
            elif strategy == "keep_both":
                m["id"] = f"{mid}_merged_{_make_ts()}"
                stats["renamed"] += 1
        insert_memory(conn, m)
        stats["memories"] += 1
        target_mem_ids.add(m["id"])

    conn.commit()
    conn.close()
    return stats


# ─────────── CLI ───────────

def main():
    parser = argparse.ArgumentParser(
        description="合并两个 tea_agent 存储数据库（topics / conversations / memories）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python merge_tea_dbs.py old.db chat_history.db
  python merge_tea_dbs.py remote.db local.db --strategy overwrite
  python merge_tea_dbs.py backup.db main.db --strategy skip --no-backup
        """,
    )
    parser.add_argument("source", help="源数据库路径")
    parser.add_argument("target", help="目标数据库路径")
    parser.add_argument(
        "--strategy", "-s", default="keep_both",
        choices=["keep_both", "overwrite", "skip"],
        help="冲突处理策略 (默认: keep_both)",
    )
    parser.add_argument("--no-backup", action="store_true", help="合并前不备份目标数据库")
    args = parser.parse_args()

    if not Path(args.source).is_file():
        print(f"❌ 源数据库不存在: {args.source}")
        sys.exit(1)

    target = Path(args.target)
    if not target.is_file():
        print(f"⚠ 目标数据库不存在，将创建: {args.target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        # 初始化表结构（从源复制 schema）
        src_conn = _connect(args.source)
        dst_conn = _connect(args.target)
        for tbl in ["topics", "conversations", "memories"]:
            sql = src_conn.execute(f"SELECT sql FROM sqlite_master WHERE type='table' AND name='{tbl}'").fetchone()
            if sql:
                dst_conn.execute(sql[0])
        dst_conn.commit()
        src_conn.close()
        dst_conn.close()
    elif not args.no_backup:
        bak = args.target + ".bak"
        shutil.copy2(args.target, bak)
        print(f"💾 已备份 → {bak}")

    print(f"\n📦 源   : {args.source}")
    print(f"📦 目标 : {args.target}")
    print(f"🔀 策略 : {args.strategy}\n")

    stats = merge_dbs(args.source, args.target, args.strategy)

    print(f"\n✅ 合并完成:")
    print(f"   topics:        {stats['topics']}")
    print(f"   conversations: {stats['conversations']}")
    print(f"   memories:      {stats['memories']}")
    print(f"   重命名:        {stats['renamed']}")
    print(f"   跳过:          {stats['skipped']}")


if __name__ == "__main__":
    main()
