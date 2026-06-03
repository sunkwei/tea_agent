"""

Storage 类自身管理：连接生命周期、数据库迁移/备份/轮转、表初始化。
业务逻辑委派给 8 个子组件：topics, conversations, summaries, memories,
prompts, reflections, config_history, vectors。

扩展功能：
- AutoMemoryExtractor: 自动记忆提取
- SemanticSearch: 语义搜索

向后兼容：通过 __getattr__ 自动将方法调用路由到对应委派组件。
"""
import os
import shutil
import sqlite3
import logging
from datetime import datetime

from ._topics import TopicStore
from ._conversations import ConversationStore
from ._summaries import SummaryStore
from ._memories import MemoryStore
from ._prompts import PromptStore
from ._reflections import ReflectionStore
from ._config import ConfigHistoryStore
from ._vectors import VectorStore
from ._base import StoreComponent
from ._auto_memory import AutoMemoryExtractor
from ._semantic_search import SemanticSearch

logger = logging.getLogger("Storage")

class Storage:
    """主存储类 — 组合 8 个委派组件 + 扩展功能，管理数据库连接与生命周期。"""

    # 委派组件名列表，用于 __getattr__ 路由
    _delegate_attrs = (
        "_topics", "_conversations", "_summaries", "_memories",
        "_prompts", "_reflections", "_config_history", "_vectors",
    )

    def __init__(self, db_path="chat_history.db"):
        """Initialize  .
        
        Args:
            db_path: Description.
        """
        self.db_path = db_path
        self._maybe_rotate_db()
        logger.info(f"load database {db_path}")
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self._init_tables()
        self._migrate()
        self._write_week_key()
        self._auto_backup()
        self._protect_db()

        # ── 创建所有委派组件 ──
        self._topics = TopicStore(self.conn)
        self._conversations = ConversationStore(self.conn)
        self._summaries = SummaryStore(self.conn)
        self._memories = MemoryStore(self.conn)
        self._prompts = PromptStore(self.conn)
        self._reflections = ReflectionStore(self.conn)
        self._config_history = ConfigHistoryStore(self.conn)
        self._vectors = VectorStore(self.conn)
        
        # ── 扩展功能组件 ──
        self._auto_memory = AutoMemoryExtractor(self)
        self._semantic_search = SemanticSearch(self)

    # ── 自动委派：未匹配的方法路由到子组件 ──

    def __getattr__(self, name):
        # 避免私有属性递归查找
        if name.startswith("_"):
            raise AttributeError(
                f"'{type(self).__name__}' object has no attribute '{name}'"
            )
        for attr in self._delegate_attrs:
            delegate = object.__getattribute__(self, attr)
            if hasattr(delegate, name):
                return getattr(delegate, name)
        raise AttributeError(
            f"'{type(self).__name__}' object has no attribute '{name}'"
        )

    # ── 特殊桥接：save_msg 需要回调其他组件的 update_active ──

    def save_msg(self, topic_id: str, user_msg, ai_msg: str, is_func: bool) -> str:
        """桥接方法：save_msg 需要 update_topic_active 回调。"""
        return self._conversations.save_msg(
            topic_id, user_msg, ai_msg, is_func,
            update_active_cb=self._topics.update_topic_active,
            auto_embed_cb=None,  # 使用 _conversations 内置的 _auto_embed_async
        )

    # ── 表初始化 ──

    def _init_tables(self):
        """Internal: initialize tables."""
        c = self.conn.cursor()

        # 元数据表
        c.execute("CREATE TABLE IF NOT EXISTS _meta (key TEXT PRIMARY KEY, value TEXT)")

        # images 表
        c.execute('''
            CREATE TABLE IF NOT EXISTS images (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL,
                image_blob BLOB NOT NULL,
                mime_type TEXT DEFAULT 'image/png',
                FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
            )
        ''')

        # topics 表
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
            ("l3_pending_json", "TEXT DEFAULT ''"),  # 2026-05-20 gen by Tea Agent, L3批处理缓冲
            ("is_active", "INTEGER DEFAULT 1"),
        ]:
            try:
                c.execute(f"ALTER TABLE topics ADD COLUMN {col} {col_def}")
            except Exception:
                pass        # conversations 表
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

        # agent_rounds 表
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

        # topic_token_stats 表
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

        # t_conv_summary 表
        c.execute('''
            CREATE TABLE IF NOT EXISTS t_conv_summary (
                topic_id TEXT PRIMARY KEY,
                summary TEXT NOT NULL,
                last_summarized_id TEXT,
                last_update TIMESTAMP DEFAULT (datetime('now', 'localtime')),
                FOREIGN KEY (topic_id) REFERENCES topics(topic_id)
            )
        ''')

        # memories 表
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
                created_at TIMESTAMP DEFAULT (datetime('now', 'localtime')),
                updated_at TIMESTAMP DEFAULT (datetime('now', 'localtime')),
                last_accessed_at TIMESTAMP,
                pinned INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY (source_topic_id) REFERENCES topics(topic_id)
            )
        ''')
        # 兼容旧表：尝试新增 pinned 列
        try:
            c.execute("ALTER TABLE memories ADD COLUMN pinned INTEGER NOT NULL DEFAULT 0")
        except Exception:
            pass

        # system_prompts 表
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

        # reflections 表
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

        # config_history 表
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

        # msg_vectors 表（先尝试迁移旧格式）
        self._migrate_msg_vectors(c)
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

        self.conn.commit()
        c.close()

    # ── 数据库迁移 ──

    def _migrate(self):
        """Internal: migrate."""
        c = self.conn.cursor()
        self._migrate_int_to_uuid(c)

        # 添加 rounds_json 列
        try:
            c.execute("ALTER TABLE conversations ADD COLUMN rounds_json TEXT")
            self.conn.commit()
        except sqlite3.OperationalError:
            pass

        # 添加 is_summarized 列
        try:
            c.execute("ALTER TABLE conversations ADD COLUMN is_summarized INTEGER DEFAULT 0")
            self.conn.commit()
        except sqlite3.OperationalError:
            pass

        # t_conv_summary 添加 last_summarized_id
        try:
            c.execute("ALTER TABLE t_conv_summary ADD COLUMN last_summarized_id TEXT")
            self.conn.commit()
        except sqlite3.OperationalError:
            pass

        # topic_token_stats 便宜模型列
        for col, col_type in [
            ("total_cheap_tokens", "INTEGER DEFAULT 0"),
            ("total_cheap_prompt_tokens", "INTEGER DEFAULT 0"),
            ("total_cheap_completion_tokens", "INTEGER DEFAULT 0"),
        ]:
            try:
                c.execute(f"ALTER TABLE topic_token_stats ADD COLUMN {col} {col_type}")
                self.conn.commit()
            except sqlite3.OperationalError:
                pass

        # topic_token_stats 嵌入模型列
        for col, col_type in [
            ("total_embedding_tokens", "INTEGER DEFAULT 0"),
            ("total_embedding_prompt_tokens", "INTEGER DEFAULT 0"),
        ]:
            try:
                c.execute(f"ALTER TABLE topic_token_stats ADD COLUMN {col} {col_type}")
                self.conn.commit()
            except sqlite3.OperationalError:
                pass

        try:
            c.execute("ALTER TABLE topics ADD COLUMN drift_count INTEGER DEFAULT 0")
            self.conn.commit()
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
        self.conn.commit()

        c.close()

    def _migrate_int_to_uuid(self, c):
        """Internal: migrate int to uuid.
        
        Args:
            c: Description.
        """
        c.execute("PRAGMA table_info(topics)")
        topic_cols = {row[1]: row[2].upper() for row in c.fetchall()}
        if topic_cols.get("topic_id", "") != "INTEGER":
            return

        log = logging.getLogger("Store")
        log.warning("检测到旧版 INTEGER 主键，开始迁移为 TEXT UUID 格式...")
        self.conn.execute("PRAGMA foreign_keys = OFF")
        self.conn.execute("PRAGMA legacy_alter_table = ON")

        def _table_columns(table):
            """Internal: table columns.
            
            Args:
                table: Description.
            """
            c.execute(f"PRAGMA table_info({table})")
            return [(row[1], row[2].upper()) for row in c.fetchall()]

        def _migrate_table(old_name, new_columns_def, cast_cols=None):
            """Internal: migrate table.
            
            Args:
                old_name: Description.
                new_columns_def: Description.
                cast_cols: Description.
            """
            new_name = f"{old_name}_new"
            # 动态补全列定义：new_columns_def 只定义需要改类型的列，其他列从旧表继承
            new_defs = {}
            for defn in new_columns_def:
                col_name = defn.split()[0]
                new_defs[col_name] = defn
            old_full = _table_columns(old_name)  # [(name, type), ...]
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
            # 清理之前失败迁移可能残留的 _new 表
            for leftover in ["topics_new","conversations_new","topic_token_stats_new",
                             "t_conv_summary_new","memories_new","agent_rounds_new",
                             "msg_vectors_new","system_prompts_new","reflections_new",
                             "config_history_new"]:
                try: c.execute(f"DROP TABLE IF EXISTS {leftover}")
                except: pass
            _migrate_table("topics", [
                "topic_id TEXT PRIMARY KEY",
                "title TEXT NOT NULL",
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

            self.conn.commit()
            log.warning("INTEGER→TEXT UUID 主键迁移完成！")
        except Exception as e:
            log.error(f"UUID 迁移失败，回滚: {e}")
            self.conn.rollback()
            raise
        finally:
            self.conn.execute("PRAGMA foreign_keys = ON")
            self.conn.execute("PRAGMA legacy_alter_table = OFF")

    def _migrate_msg_vectors(self, c):
        """Internal: migrate msg vectors.
        
        Args:
            c: Description.
        """
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
        self.conn.commit()

    # ── 周轮转 ──

    @staticmethod
    def _get_week_key():
        """Internal: get the week key."""
        return datetime.now().strftime("%G-W%V")

    def _maybe_rotate_db(self):
        """Internal: maybe rotate db."""
        if not os.path.exists(self.db_path):
            return
        db_week = None
        try:
            tmp_conn = sqlite3.connect(self.db_path)
            c = tmp_conn.cursor()
            c.execute("SELECT value FROM _meta WHERE key = 'week_key'")
            row = c.fetchone()
            db_week = row[0] if row else None
            tmp_conn.close()
        except sqlite3.OperationalError:
            pass
        current_week = self._get_week_key()
        if db_week == current_week:
            return
        db_dir = os.path.dirname(self.db_path) or "."
        archive_name = os.path.join(
            db_dir, f"chat_history_{datetime.now().strftime('%Y-%m-%d')}.db"
        )
        if os.path.exists(archive_name):
            archive_name = os.path.join(
                db_dir, f"chat_history_{datetime.now().strftime('%Y-%m-%d_%H%M%S')}.db"
            )
        try:
            shutil.copy2(self.db_path, archive_name)
            logger.info(f"归档旧数据库: {self.db_path} -> {archive_name} (保留历史记录)")
        except OSError as e:
            logger.warning(
                f"无法归档旧数据库: {e}。将继续使用当前 db，下次启动时重试。"
            )

    def _write_week_key(self):
        """Internal: write week key."""
        c = self.conn.cursor()
        c.execute(
            "INSERT OR REPLACE INTO _meta (key, value) VALUES ('week_key', ?)",
            (self._get_week_key(),),
        )
        self.conn.commit()
        c.close()

    # ── 自动备份 ──

    def _auto_backup(self):
        """Internal: auto backup."""
        import time
        try:
            now = time.time()
            last = self._meta_get("last_backup_ts")
            if last:
                try:
                    if now - float(last) < 3600:
                        return
                except ValueError:
                    pass
            backup_dir = os.path.join(
                os.path.dirname(os.path.abspath(self.db_path)), "backup"
            )
            os.makedirs(backup_dir, exist_ok=True)
            ts = time.strftime("%Y-%m-%d_%H%M%S")
            backup_path = os.path.join(backup_dir, f"chat_history_{ts}.db")
            backup_conn = sqlite3.connect(backup_path)
            self.conn.backup(backup_conn)
            backup_conn.close()
            self._meta_set("last_backup_ts", str(now))
            self._cleanup_backups(backup_dir, keep=7)
            size_mb = os.path.getsize(backup_path) / 1024 / 1024
            logger.info(f"数据库已备份: {backup_path} ({size_mb:.1f}MB)")
        except Exception as e:
            logger.debug(f"自动备份跳过: {e}")

    def _cleanup_backups(self, backup_dir: str, keep: int = 7):
        """Internal: cleanup backups.
        
        Args:
            backup_dir: Description.
            keep: Description.
        """
        try:
            files = sorted(
                [
                    f for f in os.listdir(backup_dir)
                    if f.startswith("chat_history_") and f.endswith(".db")
                ],
                reverse=True,
            )
            for old in files[keep:]:
                p = os.path.join(backup_dir, old)
                os.remove(p)
                logger.debug(f"清理旧备份: {p}")
        except Exception:
            pass

    def backup_now(self):
        """Backup now."""
        self._meta_set("last_backup_ts", "0")
        self._auto_backup()

    # ── 元数据 ──

    def _meta_get(self, key: str):
        """Internal: meta get.
        
        Args:
            key: Description.
        """
        try:
            c = self.conn.execute("SELECT value FROM _meta WHERE key=?", (key,))
            row = c.fetchone()
            return row[0] if row else None
        except Exception:
            return None

    def _meta_set(self, key: str, value: str):
        """Internal: meta set.
        
        Args:
            key: Description.
            value: Description.
        """
        try:
            self.conn.execute(
                "INSERT OR REPLACE INTO _meta (key, value) VALUES (?, ?)", (key, value)
            )
            self.conn.commit()
        except Exception:
            pass

    # ── 保护标记 ──

    def _protect_db(self):
        """Internal: protect db."""
        db_abs = os.path.abspath(self.db_path)
        db_dir = os.path.dirname(db_abs)
        marker = os.path.join(db_dir, ".chat_history_protected")
        try:
            if not os.path.exists(marker):
                with open(marker, "w") as f:
                    f.write("# 此标记文件保护数据库不被意外删除\n")
                    f.write(f"# 数据库路径: {db_abs}\n")
                    f.write(f"# 创建时间: {datetime.now().isoformat()}\n")
        except Exception:
            pass

    # ── 生命周期 ──

    def close(self):
        """Close."""
        try:
            self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            logger.info("WAL checkpoint(TRUNCATE) 完成")
        except Exception as e:
            logger.warning(f"WAL checkpoint 失败 (非致命): {e}")
        finally:
            try:
                self.conn.close()
                logger.info(f"数据库连接已关闭: {self.db_path}")
            except Exception:
                pass

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass
