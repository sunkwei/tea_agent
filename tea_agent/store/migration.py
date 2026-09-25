"""Database migration, rotation, and backup utilities for Storage.

Extracted from _core.py to reduce file size.
"""

import contextlib
import json
import logging
import os
import shutil
import sqlite3
import uuid
from datetime import datetime

from ._component import Cursor
from ._tool_usage import CREATE_SQL as _TOOL_USAGE_CREATE
from ._sql_safety import safe_ddl, safe_ident, safe_sql_fragment

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
        ("system_prompt", "TEXT DEFAULT NULL"),
    ]:
        with contextlib.suppress(Exception):
            c.execute(f"ALTER TABLE topics ADD COLUMN {safe_ident(col)} {safe_ddl(col_def)}")

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

    # fork lineage：conversations 记录来源分支（session fork 支持）
    # status/deleted_at：回合生命周期 + 软删除（append-only 语义，见下）
    for col, col_def in [
        ("fork_source_id", "TEXT DEFAULT NULL"),
        ("fork_stamp", "TEXT DEFAULT NULL"),
        # 回合状态：pending=进行中（回合开始即建行）/ done / error / interrupted
        ("status", "TEXT DEFAULT 'done'"),
        # 软删除标记（append-only：删除是标记，不是物理删除）
        ("deleted_at", "TEXT DEFAULT NULL"),
    ]:
        with contextlib.suppress(Exception):
            c.execute(f"ALTER TABLE conversations ADD COLUMN {safe_ident(col)} {safe_ddl(col_def)}")

    # agent_rounds：单轮明细的 append-only 存储（conversations.rounds_json 的替代）
    for col, col_def in [
        # reasoning_content 独立成列：此前被拼进 content 的 "[思考] " 前缀，
        # 无法还原为结构化 rounds（DeepSeek thinking 模式要求 RC 原样回传）
        ("reasoning_content", "TEXT DEFAULT ''"),
        ("deleted_at", "TEXT DEFAULT NULL"),
    ]:
        with contextlib.suppress(Exception):
            c.execute(f"ALTER TABLE agent_rounds ADD COLUMN {safe_ident(col)} {safe_ddl(col_def)}")

    # ── L0 富化系统提示词快照（严格审计补口）──
    # 背景：发给模型的 system 消息并非裸 system_prompt，而是
    # build_api_messages → _build_l0_enriched_system() **运行时合成**的结果
    # （OS 信息 / AGENTS.md / context_fragments / 小模型约束等）。该合成结果
    # 此前从不落盘 → 历史任一回合都**无法复原「它当时看到的 L0」**，因为
    # 配置与 AGENTS.md 早已变化。这是 L0-L3 提取里唯一完全缺失的一层。
    #
    # 设计取舍：
    # 1) **内容寻址**（hash 作主键）而非每回合存一份全文 —— 同一 topic 内
    #    L0 逐字节稳定（这正是前缀缓存能命中的前提），去重后实际只有
    #    少数几个版本，避免把每回合的同一份大文本重复存 N 遍。
    # 2) conversations.l0_hash 只是**指纹指针**（TEXT，可空），不占空间；
    #    旧回合为 NULL 表示"该回合未记录"，与新回合的"记录为空"可区分。
    # 3) 刻意只在**回合首次构建**时写（见 history_builder 接线）：工具循环内
    #    多轮请求复用同一版本，避免每轮重算 hash 与冗余写入。
    c.execute('''
        CREATE TABLE IF NOT EXISTS l0_snapshots (
            hash TEXT PRIMARY KEY,
            content TEXT NOT NULL,
            chars INTEGER NOT NULL DEFAULT 0,
            first_topic_id TEXT DEFAULT NULL,
            first_conversation_id TEXT DEFAULT NULL,
            created_at TIMESTAMP DEFAULT (datetime('now', 'localtime'))
        )
    ''')

    # conversations.l0_hash：指向 l0_snapshots.hash 的指纹（可空=未记录）
    # l0_recorded：区分「本回合未尝试记录」与「尝试过但无 L0 可记」
    for col, col_def in [
        ("l0_hash", "TEXT DEFAULT NULL"),
        ("l0_recorded", "INTEGER DEFAULT 0"),
    ]:
        with contextlib.suppress(Exception):
            c.execute(f"ALTER TABLE conversations ADD COLUMN {safe_ident(col)} {safe_ddl(col_def)}")

    # ── L3 摘要版本历史（append-only）──
    # 背景：L3（semantic_summary / tool_chain_summary / topic_summary）此前只有
    # **当前值**（UPDATE/ON CONFLICT UPSERT 覆盖），无法回答审计最核心的问题
    # 「T 时刻 Agent 相信的是什么」。本表记录每次变更的历史版本。
    #
    # 为什么只版本化 L3、**不**版本化 L2（实测数据支撑的取舍）：
    #   - L2 平均 184 KB/主题、单主题最大 1.03 MB，且 push_to_level2 每回合
    #     都写 → 逐版本存储会让库按「回合数 × L2 大小」膨胀（百回合即百 MB 级）；
    #   - L2 内容**完全可从 L1（agent_rounds）重新派生**，而 agent_rounds 本身
    #     已是 append-only 且持久 —— 再存一份 L2 版本属重复存储，正是本项目
    #     已经踩过并修掉的坑（conversations.rounds_json 与 agent_rounds 重复，
    #     实测占库 38.4%）。
    #   - L3 恰好相反：总量 4.7 KB / 平均 392 B，且只在摘要阈值触发时写入，
    #     版本化成本可忽略，而它承载的正是「长期结论/偏好」这类审计对象。
    c.execute('''
        CREATE TABLE IF NOT EXISTS history_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            version INTEGER NOT NULL,
            content TEXT NOT NULL,
            chars INTEGER NOT NULL DEFAULT 0,
            conversation_id TEXT DEFAULT NULL,
            created_at TIMESTAMP DEFAULT (datetime('now', 'localtime'))
        )
    ''')
    for ddl in [
        "CREATE INDEX IF NOT EXISTS idx_history_versions_topic "
        "ON history_versions(topic_id, kind, version)",
    ]:
        with contextlib.suppress(Exception):
            c.execute(ddl)

    # 软删除标记：topics / images 同样改为标记删除
    for tbl, col, col_def in [
        ("topics", "deleted_at", "TEXT DEFAULT NULL"),
        ("images", "deleted_at", "TEXT DEFAULT NULL"),
    ]:
        with contextlib.suppress(Exception):
            c.execute(f"ALTER TABLE {safe_ident(tbl)} ADD COLUMN {safe_ident(col)} {safe_ddl(col_def)}")

    # fork 元数据表：记录 fork 操作（源 topic → 目标 topic）
    c.execute('''
        CREATE TABLE IF NOT EXISTS forks (
            id TEXT PRIMARY KEY,
            source_topic_id TEXT NOT NULL,
            target_topic_id TEXT NOT NULL,
            boundary_conv_id TEXT DEFAULT NULL,
            created_at TIMESTAMP DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (source_topic_id) REFERENCES topics(topic_id),
            FOREIGN KEY (target_topic_id) REFERENCES topics(topic_id)
        )
    ''')

    # P2 事件溯源：append-only 会话事件日志（唯一事实源的渐进式改造）
    # 事件类型: turn/start, user/message, assistant/chunk, assistant/message,
    #           tool/call, tool/result, turn/end, compaction/*, session/fork
    c.execute('''
        CREATE TABLE IF NOT EXISTS session_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic_id TEXT NOT NULL,
            conversation_id TEXT DEFAULT NULL,
            event_type TEXT NOT NULL,
            payload_json TEXT NOT NULL DEFAULT '{}',
            seq INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT (datetime('now', 'localtime')),
            UNIQUE (topic_id, seq)
        )
    ''')
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_session_events_topic ON session_events(topic_id, seq)"
    )
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_session_events_type ON session_events(event_type)"
    )

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
            created_at TIMESTAMP DEFAULT (datetime('now', 'localtime')),
            updated_at TIMESTAMP DEFAULT (datetime('now', 'localtime')),
            last_accessed_at TIMESTAMP,
            pinned INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY (source_topic_id) REFERENCES topics(topic_id)
        )
    ''')
    for col, col_def in [('pinned', 'INTEGER NOT NULL DEFAULT 0'),
                           ('content_hash', "TEXT DEFAULT ''")]:
        with contextlib.suppress(Exception):
            c.execute(f"ALTER TABLE memories ADD COLUMN {safe_ident(col)} {safe_ddl(col_def)}")

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

    # ── 工具使用统计（tool_shield 的数据源）：一行一工具，只增计数 ──
    c.execute(_TOOL_USAGE_CREATE)

    # ── 打断知识闭环（M2）：打断事件持久化 ──
    c.execute('''
        CREATE TABLE IF NOT EXISTS interruption_events (
            id TEXT PRIMARY KEY,
            topic_id TEXT,
            conversation_id TEXT,
            timestamp TEXT,
            iteration INTEGER,
            tool_name TEXT,
            tool_args_summary TEXT,
            partial_reply TEXT,
            phase TEXT DEFAULT 'tool_loop',
            status TEXT DEFAULT 'pending',
            classification TEXT,
            similarity REAL,
            followup_user_msg TEXT,
            followup_ts TEXT
        )
    ''')
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_interrupt_topic ON interruption_events(topic_id)"
    )
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_interrupt_status ON interruption_events(status)"
    )

    c.connection.commit()
    c.close()


def backfill_rounds_from_json(c) -> int:
    """把遗留 ``conversations.rounds_json`` 回填进 ``agent_rounds``（幂等）。

    只为「agent_rounds 中没有任何行」的对话补写 —— 已有行的对话不动（避免
    与既有明细重复）。回填成功后**保留** rounds_json 原文：它是原始记录，
    清理由后续按保留期统一处理（append-only 精神：不主动销毁事实）。

    Args:
        c: 已打开的 DB cursor（事务由调用方管理）。

    Returns:
        回填的轮次总数（0 表示无需回填）。
    """
    try:
        rows = c.execute(
            "SELECT id, rounds_json FROM conversations "
            "WHERE rounds_json IS NOT NULL AND rounds_json != '' "
            "AND id NOT IN (SELECT DISTINCT conversation_id FROM agent_rounds)"
        ).fetchall()
    except sqlite3.Error:
        return 0
    total = 0
    for row in rows:
        conv_id, raw = row[0], row[1]
        try:
            rounds = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue          # 损坏的 JSON：跳过，不影响其他对话
        if not isinstance(rounds, list):
            continue
        for i, r in enumerate(rounds):
            if not isinstance(r, dict):
                continue
            try:
                tc = r.get("tool_calls")
                c.execute(
                    "INSERT INTO agent_rounds "
                    "(id, conversation_id, round_num, role, content, tool_calls, "
                    " tool_call_id, reasoning_content, stamp) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now', 'localtime'))",
                    (uuid.uuid4().hex, conv_id, i, r.get("role", "") or "",
                     r.get("content", "") or "",
                     json.dumps(tc, ensure_ascii=False) if tc else None,
                     r.get("tool_call_id"),
                     r.get("reasoning_content", "") or ""),
                )
                total += 1
            except sqlite3.Error:
                continue      # 单项失败隔离：不拖垮整次迁移
    if total:
        c.connection.commit()
        log = logging.getLogger("Store")
        log.warning("已回填 %d 个轮次（%d 个对话）: rounds_json → agent_rounds",
                    total, len(rows))
    return total


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

    for col in ["rounds_json TEXT", "is_summarized INTEGER DEFAULT 0",
                "memory_extracted INTEGER DEFAULT 0"]:
        try:
            c.execute(f"ALTER TABLE conversations ADD COLUMN {safe_ddl(col)}")
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
            c.execute(f"ALTER TABLE topic_token_stats ADD COLUMN {safe_ident(col)} {safe_ddl(col_type)}")
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

    # ── 数据回填：rounds_json → agent_rounds ──
    # schema 加列是自动的，但**数据层需要显式回填**：旧库若只写了
    # conversations.rounds_json 而没写 agent_rounds，改成「从 agent_rounds
    # 派生」后这些轮次就读不出来了（实测：有 rounds_json 但无 agent_rounds
    # 行的对话，rounds_json_parsed 返回 None → 轮次静默丢失）。
    # 必须放在 migrate 里（init_tables 阶段 rounds_json 列可能尚不存在）。
    backfill_rounds_from_json(c)

    # 索引：deleted_at 过滤与按会话查轮次都是热点（agent_rounds 已万行级）。
    # 依赖 deleted_at 列，故必须在加列之后建。
    # idx_l0_snapshots_conv 支撑「按会话反查其 L0 快照」；l0_snapshots 本身
    # 以 hash 为主键（内容寻址），该索引只服务 first_conversation_id 回查。
    for ddl in [
        "CREATE INDEX IF NOT EXISTS idx_agent_rounds_conv "
        "ON agent_rounds(conversation_id, deleted_at)",
        "CREATE INDEX IF NOT EXISTS idx_conversations_topic "
        "ON conversations(topic_id, deleted_at)",
        "CREATE INDEX IF NOT EXISTS idx_l0_snapshots_conv "
        "ON l0_snapshots(first_conversation_id)",
        "CREATE INDEX IF NOT EXISTS idx_l0_snapshots_topic "
        "ON l0_snapshots(first_topic_id)",
    ]:
        with contextlib.suppress(Exception):
            c.execute(ddl)
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
        # SAFETY: `old_name`/`new_name` come from _next_table_name() which uses internal counter
        # `select_sql` is built from column names discovered via PRAGMA table_info
        # Neither involves user input - safe for f-string SQL construct
        c.execute(f"INSERT INTO {safe_ident(new_name)} SELECT {safe_sql_fragment(select_sql)} FROM {safe_ident(old_name)}")
        c.execute(f"DROP TABLE {safe_ident(old_name)}")
        c.execute(f"ALTER TABLE {safe_ident(new_name)} RENAME TO {safe_ident(old_name)}")
        log.info(f"  迁移表 {old_name}")

    try:
        for leftover in ["topics_new","conversations_new","topic_token_stats_new",
                         "t_conv_summary_new","memories_new","agent_rounds_new",
                         "system_prompts_new","reflections_new",
                         "config_history_new"]:
            try:
                c.execute(f"DROP TABLE IF EXISTS {safe_ident(leftover)}")
            except Exception:
                logger.exception('op_failed')

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
        logger.exception('op_failed')

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
                logger.exception('op_failed')

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
        logger.exception('op_failed')


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
        logger.exception('op_failed')


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
        logger.exception('op_failed')
