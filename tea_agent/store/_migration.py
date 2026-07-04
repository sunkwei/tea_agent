"""Database migration, rotation, and backup utilities for Storage.

Extracted from _core.py to reduce file size.
"""

import logging
import os
import shutil
import sqlite3
from datetime import datetime

from ._component import DB, Cursor

logger = logging.getLogger("Storage")


# ═══════════════════════════════════════════════
#  Table Initialization
# ═══════════════════════════════════════════════

def init_tables(db):
    """Initialize all database tables.

    Args:
        db: DB instance (lifecycle managed by caller).
    """
    c = db.cursor()

    c.execute("CREATE TABLE IF NOT EXISTS _meta (key TEXT PRIMARY KEY, value TEXT)")

    c.execute('''
        CREATE TABLE IF NOT EXISTS images (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id TEXT NOT NULL,
            image_blob BLOB NOT NULL,
            mime_type TEXT DEFAULT 'image/png',
            FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS topics (
            topic_id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            create_stamp TEXT DEFAULT (datetime('now', 'localtime')),
            last_update_stamp TEXT DEFAULT (datetime('now', 'localtime'))
        )
    ''')
    for col, col_def in [
        ("semantic_summary", "TEXT DEFAULT ''"),
        ("tool_chain_summary", "TEXT DEFAULT ''"),
        ("level2_json", "TEXT DEFAULT '[]'"),
        ("l3_pending_json", "TEXT DEFAULT ''"),
        ("is_active", "INTEGER DEFAULT 1"),
    ]:
        try:
            c.execute(f"ALTER TABLE topics ADD COLUMN {col} {col_def}")
        except Exception:
            pass

    c.execute('''
        CREATE TABLE IF NOT EXISTS conversations (
            id TEXT PRIMARY KEY,
            topic_id TEXT NOT NULL,
            user_msg TEXT NOT NULL,
            ai_msg TEXT NOT NULL,
            is_func_calling INTEGER DEFAULT 0,
            is_summarized INTEGER DEFAULT 0,
            stamp TIMESTAMP DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (topic_id) REFERENCES topics(topic_id)
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS agent_rounds (
            id TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL,
            round_num INTEGER NOT NULL,
            role TEXT NOT NULL,
            content TEXT,
            tool_calls TEXT,
            tool_call_id TEXT,
            stamp TIMESTAMP DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (conversation_id) REFERENCES conversations(id)
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS topic_token_stats (
            topic_id TEXT PRIMARY KEY,
            total_tokens INTEGER DEFAULT 0,
            total_prompt_tokens INTEGER DEFAULT 0,
            total_completion_tokens INTEGER DEFAULT 0,
            conversation_count INTEGER DEFAULT 0,
            last_update TIMESTAMP DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (topic_id) REFERENCES topics(topic_id)
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS t_conv_summary (
            topic_id TEXT PRIMARY KEY,
            summary TEXT NOT NULL,
            last_summarized_id TEXT,
            last_update TIMESTAMP DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (topic_id) REFERENCES topics(topic_id)
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS memories (
            id TEXT PRIMARY KEY,
            content TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT 'general',
            priority INTEGER NOT NULL DEFAULT 2,
            importance INTEGER NOT NULL DEFAULT 3,
            expires_at TEXT,
            is_active INTEGER NOT NULL DEFAULT 1,
            tags TEXT DEFAULT '',
            source_topic_id TEXT,
            content_hash TEXT DEFAULT '',
            embedding BLOB,
            created_at TIMESTAMP DEFAULT (datetime('now', 'localtime')),
            updated_at TIMESTAMP DEFAULT (datetime('now', 'localtime')),
            last_accessed_at TIMESTAMP,
            pinned INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY (source_topic_id) REFERENCES topics(topic_id)
        )
    ''')
    for col, col_def in [('pinned', 'INTEGER NOT NULL DEFAULT 0'),
                           ('content_hash', "TEXT DEFAULT ''"),
                           ('embedding', 'BLOB')]:
        try:
            c.execute(f"ALTER TABLE memories ADD COLUMN {col} {col_def}")
        except Exception:
            pass

    c.execute('''
        CREATE TABLE IF NOT EXISTS system_prompts (
            id TEXT PRIMARY KEY,
            version TEXT NOT NULL,
            content TEXT NOT NULL,
            reason TEXT DEFAULT '',
            source_reflection_id TEXT,
            is_active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT (datetime('now', 'localtime'))
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS reflections (
            id TEXT PRIMARY KEY,
            topic_id TEXT,
            summary TEXT NOT NULL,
            details TEXT DEFAULT '',
            tool_stats TEXT DEFAULT '{}',
            suggestions TEXT DEFAULT '[]',
            is_applied INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (topic_id) REFERENCES topics(topic_id)
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS config_history (
            id TEXT PRIMARY KEY,
            key TEXT NOT NULL,
            old_value TEXT,
            new_value TEXT NOT NULL,
            reason TEXT DEFAULT '',
            source_reflection_id TEXT,
            created_at TIMESTAMP DEFAULT (datetime('now', 'localtime'))
        )
    ''')

    migrate_msg_vectors(c)
    c.execute('''
        CREATE TABLE IF NOT EXISTS msg_vectors (
            conversation_id TEXT PRIMARY KEY,
            embedding BLOB NOT NULL,
            dimension INTEGER DEFAULT 0,
            model_name TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS scheduled_tasks (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            command TEXT NOT NULL,
            schedule TEXT NOT NULL,
            enabled INTEGER DEFAULT 1,
            last_run TIMESTAMP,
            last_result TEXT DEFAULT '',
            last_exit_code INTEGER,
            next_run TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    c.connection.commit()
    c.close()


# ═══════════════════════════════════════════════
#  Migration
# ═══════════════════════════════════════════════

def migrate(db):
    """Execute database migrations.

    Args:
        db: DB instance (lifecycle managed by caller).
    """
    c = db.cursor()
    migrate_int_to_uuid(c)

    for col in ["rounds_json TEXT", "is_summarized INTEGER DEFAULT 0"]:
        try:
            col_name = col.split()[0]
            c.execute(f"ALTER TABLE conversations ADD COLUMN {col}")
            c.connection.commit()
        except sqlite3.OperationalError:
            pass

    try:
        c.execute("ALTER TABLE t_conv_summary ADD COLUMN last_summarized_id TEXT")
        c.connection.commit()
    except sqlite3.OperationalError:
        pass

    for col, col_type in [
        ("total_cheap_tokens", "INTEGER DEFAULT 0"),
        ("total_cheap_prompt_tokens", "INTEGER DEFAULT 0"),
        ("total_cheap_completion_tokens", "INTEGER DEFAULT 0"),
    ]:
        try:
            c.execute(f"ALTER TABLE topic_token_stats ADD COLUMN {col} {col_type}")
            c.connection.commit()
        except sqlite3.OperationalError:
            pass

    for col, col_type in [
        ("total_embedding_tokens", "INTEGER DEFAULT 0"),
        ("total_embedding_prompt_tokens", "INTEGER DEFAULT 0"),
    ]:
        try:
            c.execute(f"ALTER TABLE topic_token_stats ADD COLUMN {col} {col_type}")
            c.connection.commit()
        except sqlite3.OperationalError:
            pass

    try:
        c.execute("ALTER TABLE topic_token_stats ADD COLUMN pending_cheap_tokens_json TEXT DEFAULT ''")
        c.connection.commit()
    except sqlite3.OperationalError:
        pass

    try:
        c.execute("ALTER TABLE topics ADD COLUMN drift_count INTEGER DEFAULT 0")
        c.connection.commit()
    except sqlite3.OperationalError:
        pass

    c.execute('''CREATE TABLE IF NOT EXISTS todo_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        topic_id TEXT NOT NULL,
        idx INTEGER NOT NULL,
        desc TEXT NOT NULL,
        done INTEGER NOT NULL DEFAULT 0,
        created_at TIMESTAMP DEFAULT (datetime('now', 'localtime')),
        FOREIGN KEY (topic_id) REFERENCES topics(topic_id)
    )''')
    c.connection.commit()

    c.close()


def migrate_int_to_uuid(c):
    """Migrate old INTEGER primary keys to TEXT UUID format."""
    c.execute("PRAGMA table_info(topics)")
    topic_cols = {row[1]: row[2].upper() for row in c.fetchall()}
    if topic_cols.get("topic_id", "") != "INTEGER":
        return

    log = logging.getLogger("Store")
    log.warning("检测到旧版 INTEGER 主键，开始迁移为 TEXT UUID 格式...")
    c.connection.execute("PRAGMA foreign_keys = OFF")
    c.connection.execute("PRAGMA legacy_alter_table = ON")

    def _table_columns(table):
        c.execute(f"PRAGMA table_info({table})")
        return [(row[1], row[2].upper()) for row in c.fetchall()]

    def _migrate_table(old_name, new_columns_def, cast_cols=None):
        new_name = f"{old_name}_new"
        new_defs = {}
        for defn in new_columns_def:
            col_name = defn.split()[0]
            new_defs[col_name] = defn
        old_full = _table_columns(old_name)
        full_defs = []
        for col_name, col_type in old_full:
            if col_name in new_defs:
                full_defs.append(new_defs[col_name])
            else:
                full_defs.append(f"{col_name} {col_type}")
        cols_sql = ", ".join(full_defs)
        c.execute(f"CREATE TABLE {new_name} ({cols_sql})")
        old_cols = [col[0] for col in old_full]
        if cast_cols:
            select_parts = []
            for col in old_cols:
                if col in cast_cols:
                    select_parts.append(f"CAST({col} AS TEXT) as {col}")
                else:
                    select_parts.append(col)
            select_sql = ", ".join(select_parts)
        else:
            select_sql = ", ".join(old_cols)
        c.execute(f"INSERT INTO {new_name} SELECT {select_sql} FROM {old_name}")
        c.execute(f"DROP TABLE {old_name}")
        c.execute(f"ALTER TABLE {new_name} RENAME TO {old_name}")
        log.info(f"  迁移表 {old_name}")

    try:
        for leftover in ["topics_new","conversations_new","topic_token_stats_new",
                         "t_conv_summary_new","memories_new","agent_rounds_new",
                         "msg_vectors_new","system_prompts_new","reflections_new",
                         "config_history_new"]:
            try: c.execute(f"DROP TABLE IF EXISTS {leftover}")
            except Exception:
                logger.exception("operation failed")

        _migrate_table("topics", [
            "topic_id TEXT PRIMARY KEY", "title TEXT NOT NULL",
            "create_stamp TIMESTAMP DEFAULT (datetime('now','localtime'))",
            "last_update_stamp TIMESTAMP DEFAULT (datetime('now','localtime'))",
        ], cast_cols={"topic_id"})

        _migrate_table("conversations", [
            "id TEXT PRIMARY KEY", "topic_id TEXT NOT NULL",
            "user_msg TEXT NOT NULL", "ai_msg TEXT NOT NULL",
            "is_func_calling INTEGER DEFAULT 0", "is_summarized INTEGER DEFAULT 0",
            "stamp TIMESTAMP DEFAULT (datetime('now','localtime'))", "rounds_json TEXT",
        ], cast_cols={"id", "topic_id"})

        _migrate_table("topic_token_stats", [
            "topic_id TEXT PRIMARY KEY", "total_tokens INTEGER DEFAULT 0",
            "total_prompt_tokens INTEGER DEFAULT 0", "total_completion_tokens INTEGER DEFAULT 0",
            "conversation_count INTEGER DEFAULT 0", "last_update TIMESTAMP DEFAULT (datetime('now','localtime'))",
            "total_cheap_tokens INTEGER DEFAULT 0", "total_cheap_prompt_tokens INTEGER DEFAULT 0",
            "total_cheap_completion_tokens INTEGER DEFAULT 0",
            "total_embedding_tokens INTEGER DEFAULT 0", "total_embedding_prompt_tokens INTEGER DEFAULT 0",
        ], cast_cols={"topic_id"})

        _migrate_table("t_conv_summary", [
            "topic_id TEXT PRIMARY KEY", "summary TEXT NOT NULL",
            "last_summarized_id TEXT", "last_update TIMESTAMP DEFAULT (datetime('now','localtime'))",
        ], cast_cols={"topic_id", "last_summarized_id"})

        _migrate_table("memories", [
            "id TEXT PRIMARY KEY", "content TEXT NOT NULL",
            "category TEXT NOT NULL DEFAULT 'general'", "priority INTEGER NOT NULL DEFAULT 2",
            "importance INTEGER NOT NULL DEFAULT 3", "expires_at TEXT",
            "is_active INTEGER NOT NULL DEFAULT 1", "tags TEXT DEFAULT ''",
            "source_topic_id TEXT", "created_at TIMESTAMP DEFAULT (datetime('now','localtime'))",
            "updated_at TIMESTAMP DEFAULT (datetime('now','localtime'))", "last_accessed_at TIMESTAMP",
        ], cast_cols={"id", "source_topic_id"})

        _migrate_table("agent_rounds", [
            "id TEXT PRIMARY KEY", "conversation_id TEXT NOT NULL",
            "round_num INTEGER NOT NULL", "role TEXT NOT NULL",
            "content TEXT", "tool_calls TEXT", "tool_call_id TEXT",
            "stamp TIMESTAMP DEFAULT (datetime('now','localtime'))",
        ], cast_cols={"id", "conversation_id"})

        _migrate_table("msg_vectors", [
            "conversation_id TEXT PRIMARY KEY", "embedding BLOB NOT NULL",
            "dimension INTEGER DEFAULT 0", "model_name TEXT DEFAULT ''",
            "created_at TIMESTAMP DEFAULT (datetime('now','localtime'))",
        ], cast_cols={"conversation_id"})

        _migrate_table("system_prompts", [
            "id TEXT PRIMARY KEY", "version TEXT NOT NULL", "content TEXT NOT NULL",
            "reason TEXT DEFAULT ''", "source_reflection_id TEXT",
            "is_active INTEGER DEFAULT 1", "created_at TIMESTAMP DEFAULT (datetime('now','localtime'))",
        ], cast_cols={"id", "source_reflection_id"})

        _migrate_table("reflections", [
            "id TEXT PRIMARY KEY", "topic_id TEXT", "summary TEXT NOT NULL",
            "details TEXT DEFAULT ''", "tool_stats TEXT DEFAULT '{}'",
            "suggestions TEXT DEFAULT '[]'", "is_applied INTEGER DEFAULT 0",
            "created_at TIMESTAMP DEFAULT (datetime('now','localtime'))",
        ], cast_cols={"id", "topic_id"})

        _migrate_table("config_history", [
            "id TEXT PRIMARY KEY", "key TEXT NOT NULL", "old_value TEXT",
            "new_value TEXT NOT NULL", "reason TEXT DEFAULT ''",
            "source_reflection_id TEXT", "created_at TIMESTAMP DEFAULT (datetime('now','localtime'))",
        ], cast_cols={"id", "source_reflection_id"})

        c.connection.commit()
        log.warning("INTEGER→TEXT UUID 主键迁移完成！")
    except Exception as e:
        log.error(f"UUID 迁移失败，回滚: {e}")
        c.connection.rollback()
        raise
    finally:
        c.connection.execute("PRAGMA foreign_keys = ON")
        c.connection.execute("PRAGMA legacy_alter_table = OFF")


def migrate_msg_vectors(c):
    """Migrate msg_vectors from TEXT to BLOB format if needed."""
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='msg_vectors'")
    if not c.fetchone():
        return
    c.execute("PRAGMA table_info(msg_vectors)")
    cols = {row[1]: row[2] for row in c.fetchall()}
    if cols.get("embedding", "").upper() == "BLOB":
        return
    logging.getLogger("Store").info(
        "msg_vectors 表从 TEXT 迁移到 BLOB 格式，旧数据将被丢弃"
    )
    c.execute("DROP TABLE IF EXISTS msg_vectors")
    c.connection.commit()


# ═══════════════════════════════════════════════
#  Weekly Rotation
# ═══════════════════════════════════════════════

def get_week_key():
    """Get the ISO week key string."""
    return datetime.now().strftime("%G-W%V")


def maybe_rotate_db(db_path):
    """Archive the database if the week has changed."""
    if not os.path.exists(db_path):
        return
    db_week = None
    try:
        tmp_conn = sqlite3.connect(db_path)
        c = tmp_conn.cursor()
        c.execute("SELECT value FROM _meta WHERE key = 'week_key'")
        row = c.fetchone()
        db_week = row[0] if row else None
        tmp_conn.close()
    except sqlite3.OperationalError:
        logger.exception("operation failed")

    current_week = get_week_key()
    if db_week == current_week:
        return
    db_dir = os.path.dirname(db_path) or "."
    archive_name = os.path.join(
        db_dir, f"chat_history_{datetime.now().strftime('%Y-%m-%d')}.db"
    )
    if os.path.exists(archive_name):
        archive_name = os.path.join(
            db_dir, f"chat_history_{datetime.now().strftime('%Y-%m-%d_%H%M%S')}.db"
        )
    try:
        shutil.copy2(db_path, archive_name)
        logger.info(f"归档旧数据库: {db_path} -> {archive_name} (保留历史记录)")
    except OSError as e:
        logger.warning(
            f"无法归档旧数据库: {e}。将继续使用当前 db，下次启动时重试。"
        )


def write_week_key(db):
    """Write the current week key into the database."""
    with Cursor(db) as c:
        c.execute(
            "INSERT OR REPLACE INTO _meta (key, value) VALUES ('week_key', ?)",
            (get_week_key(),),
        )
        c.connection.commit()


# ═══════════════════════════════════════════════
#  Backup
# ═══════════════════════════════════════════════

def auto_backup(db_path):
    """Automatically backup the database (max once per hour)."""
    import time as _time
    try:
        now = _time.time()
        last = meta_get(db_path, "last_backup_ts")
        if last:
            try:
                if now - float(last) < 3600:
                    return
            except ValueError:
                logger.exception("operation failed")

        backup_dir = os.path.join(
            os.path.dirname(os.path.abspath(db_path)), "backup"
        )
        os.makedirs(backup_dir, exist_ok=True)
        ts = _time.strftime("%Y-%m-%d_%H%M%S")
        backup_path = os.path.join(backup_dir, f"chat_history_{ts}.db")
        backup_conn = sqlite3.connect(backup_path)
        src_conn = sqlite3.connect(db_path)
        src_conn.backup(backup_conn)
        backup_conn.close()
        src_conn.close()
        meta_set(db_path, "last_backup_ts", str(now))
        cleanup_backups(backup_dir, keep=7)
        size_mb = os.path.getsize(backup_path) / 1024 / 1024
        logger.info(f"数据库已备份: {backup_path} ({size_mb:.1f}MB)")
    except Exception as e:
        logger.debug(f"自动备份跳过: {e}")


def cleanup_backups(backup_dir: str, keep: int = 7):
    """Remove old backup files, keeping only the most recent N."""
    try:
        files = sorted(
            [f for f in os.listdir(backup_dir)
             if f.startswith("chat_history_") and f.endswith(".db")],
            reverse=True,
        )
        for old in files[keep:]:
            p = os.path.join(backup_dir, old)
            os.remove(p)
            logger.debug(f"清理旧备份: {p}")
    except Exception:
        logger.exception("operation failed")


def backup_now(db_path):
    """Force an immediate backup."""
    meta_set(db_path, "last_backup_ts", "0")
    auto_backup(db_path)


# ═══════════════════════════════════════════════
#  Metadata helpers
# ═══════════════════════════════════════════════

def meta_get(db_path, key: str):
    """Read a metadata value (short connection)."""
    try:
        conn = sqlite3.connect(db_path)
        c = conn.execute("SELECT value FROM _meta WHERE key=?", (key,))
        row = c.fetchone()
        conn.close()
        return row[0] if row else None
    except Exception:
        return None


def meta_set(db_path, key: str, value: str):
    """Write a metadata value (short connection)."""
    try:
        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT OR REPLACE INTO _meta (key, value) VALUES (?, ?)", (key, value)
        )
        conn.commit()
        conn.close()
    except Exception:
        logger.exception("operation failed")


# ═══════════════════════════════════════════════
#  Protection
# ═══════════════════════════════════════════════

def protect_db(db_path):
    """Create a marker file to prevent accidental deletion."""
    db_abs = os.path.abspath(db_path)
    db_dir = os.path.dirname(db_abs)
    marker = os.path.join(db_dir, ".chat_history_protected")
    try:
        if not os.path.exists(marker):
            with open(marker, "w") as f:
                f.write("# 此标记文件保护数据库不被意外删除\n")
                f.write(f"# 数据库路径: {db_abs}\n")
                f.write(f"# 创建时间: {datetime.now().isoformat()}\n")
    except Exception:
        logger.exception("operation failed")
