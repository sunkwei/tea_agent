"""
@2026-05-17 gen by tea_agent, 修正 chat_history.db 中所有时间戳 +8 小时 (UTC→UTC+8)
用法: python fix_history_timezone.py [db_path]
默认路径: $HOME/.tea_agent/chat_history.db
"""
import os
import sys
import sqlite3
import shutil
from datetime import datetime

# ── 所有 (表, 时间列) ──
TIME_COLUMNS = [
    ("topics",              ["create_stamp", "last_update_stamp"]),
    ("conversations",       ["stamp"]),
    ("agent_rounds",        ["stamp"]),
    ("topic_token_stats",   ["last_update"]),
    ("t_conv_summary",      ["last_update"]),
    ("memories",            ["created_at", "updated_at", "last_accessed_at"]),
    ("system_prompts",      ["created_at"]),
    ("reflections",         ["created_at"]),
    ("config_history",      ["created_at"]),
    ("msg_vectors",         ["created_at"]),
]


def fix(db_path: str, dry_run: bool = False):
    if not os.path.exists(db_path):
        print(f"✗ 数据库不存在: {db_path}")
        return 1

    # 备份
    bak = db_path + f".bak.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    shutil.copy2(db_path, bak)
    print(f"✓ 备份: {bak}")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # 获取所有表名
    c.execute("SELECT name FROM sqlite_master WHERE type='table'")
    existing_tables = {r["name"] for r in c.fetchall()}

    total_affected = 0

    for table, cols in TIME_COLUMNS:
        if table not in existing_tables:
            print(f"  - {table}: 表不存在，跳过")
            continue

        for col in cols:
            # 检查列是否存在
            c.execute(f"PRAGMA table_info({table})")
            col_names = {r["name"] for r in c.fetchall()}
            if col not in col_names:
                print(f"  - {table}.{col}: 列不存在，跳过")
                continue

            # 统计非空行数
            c.execute(f"SELECT COUNT(*) as cnt FROM {table} WHERE {col} IS NOT NULL")
            cnt = c.fetchone()["cnt"]
            if cnt == 0:
                print(f"  - {table}.{col}: 无数据，跳过")
                continue

            if dry_run:
                # 显示示例
                c.execute(f"SELECT {col} FROM {table} WHERE {col} IS NOT NULL LIMIT 3")
                samples = [r[col] for r in c.fetchall()]
                print(f"  ? {table}.{col}: {cnt} 行, 示例: {samples}")
            else:
                c.execute(f"UPDATE {table} SET {col} = datetime({col}, '+8 hours') WHERE {col} IS NOT NULL")
                print(f"  ✓ {table}.{col}: {cnt} 行已修正 (+8h)")
            total_affected += cnt

    if not dry_run:
        conn.commit()
        print(f"\n✓ 总计修正 {total_affected} 个时间戳")

    conn.close()
    return 0


if __name__ == "__main__":
    default_path = os.path.join(os.path.expanduser("~"), ".tea_agent", "chat_history.db")

    db_path = sys.argv[1] if len(sys.argv) > 1 else default_path
    dry_run = "--dry-run" in sys.argv or "-n" in sys.argv

    print("=" * 60)
    print(f"{'[DRY RUN] ' if dry_run else ''}修正时区: UTC → UTC+8")
    print(f"数据库: {db_path}")
    print("=" * 60)

    sys.exit(fix(db_path, dry_run=dry_run))
