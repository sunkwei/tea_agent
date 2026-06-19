"""

Storage 类自身管理：连接生命周期、数据库迁移/备份/轮转、表初始化。
业务逻辑委派给 8 个子组件：topics, conversations, summaries, memories,
prompts, reflections, config_history, vectors。

扩展功能：
- SemanticSearch: 语义搜索
- AutoMemoryExtractor: 移入 session_memory_component.py

向后兼容：通过 __getattr__ 自动将方法调用路由到对应委派组件。
"""
import os
import shutil
import sqlite3
import logging
from datetime import datetime

from ._component import StoreComponent, DB, Cursor  # DB 短连接上下文管理器
from ._topics import TopicStore
from ._conversations import ConversationStore
from ._summaries import SummaryStore
from ._memories import MemoryStore
from ._vectors import VectorStore
from ._semantic_search import SemanticSearch
from ._scheduled_tasks import ScheduledTaskStore

logger = logging.getLogger("Storage")


class ConfigHistoryStore(StoreComponent):
    """配置变更追踪：记录每次配置修改的历史。"""

    def add_config_change(self, key: str, new_value: str, old_value=None,
                          reason: str = "", source_reflection_id=None) -> str:
        c = self.conn.cursor()
        cid = self._new_id()
        c.execute(
            "INSERT INTO config_history (id, key, old_value, new_value, reason, source_reflection_id, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, datetime('now', 'localtime'))",
            (cid, key, str(old_value) if old_value is not None else None,
             str(new_value), reason, source_reflection_id),
        )
        c.connection.commit()
        c.close()
        return cid

    def get_config_history(self, key: str = "", limit: int = 20):
        c = self.conn.cursor()
        if key:
            c.execute("SELECT * FROM config_history WHERE key = ? ORDER BY created_at DESC LIMIT ?", (key, limit))
        else:
            c.execute("SELECT * FROM config_history ORDER BY created_at DESC LIMIT ?", (limit,))
        rows = c.fetchall()
        c.close()
        return [dict(r) for r in rows]

    def get_config_changes_since(self, since_id: str = "0"):
        c = self.conn.cursor()
        c.execute("SELECT * FROM config_history WHERE id > ? ORDER BY created_at ASC", (since_id,))
        rows = c.fetchall()
        c.close()
        return [dict(r) for r in rows]


class ReflectionStore(StoreComponent):
    """反思记录：元认知反思的增删查改。"""

    def add_reflection(self, summary: str, details: str = "",
                       tool_stats=None, suggestions=None,
                       topic_id=None) -> str:
        import json as _json_rs
        c = self.conn.cursor()
        rid = self._new_id()
        c.execute(
            "INSERT INTO reflections (id, topic_id, summary, details, tool_stats, suggestions, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, datetime('now', 'localtime'))",
            (rid, topic_id, summary, details,
             _json_rs.dumps(tool_stats or {}, ensure_ascii=False),
             _json_rs.dumps(suggestions or [], ensure_ascii=False)),
        )
        c.connection.commit()
        c.close()
        return rid

    def get_recent_reflections(self, limit: int = 10):
        c = self.conn.cursor()
        c.execute("SELECT * FROM reflections WHERE is_applied = 0 ORDER BY created_at DESC LIMIT ?", (limit,))
        rows = c.fetchall()
        c.close()
        return [dict(r) for r in rows]

    def mark_reflection_applied(self, reflection_id: str):
        c = self.conn.cursor()
        c.execute("UPDATE reflections SET is_applied = 1 WHERE id = ?", (reflection_id,))
        c.connection.commit()
        c.close()

    def get_reflection_stats(self):
        c = self.conn.cursor()
        c.execute("SELECT COUNT(*) as total FROM reflections")
        total = c.fetchone()["total"]
        c.execute("SELECT COUNT(*) as unapplied FROM reflections WHERE is_applied = 0")
        unapplied = c.fetchone()["unapplied"]
        c.close()
        return {"total": total, "unapplied": unapplied}


class PromptStore(StoreComponent):
    """系统提示词版本管理：添加、查询、停用、回滚。"""

    def add_system_prompt(self, content: str, reason: str = "",
                           source_reflection_id=None) -> str:
        c = self.conn.cursor()
        c.execute("SELECT MAX(CAST(version AS INTEGER)) FROM system_prompts")
        row = c.fetchone()
        max_ver = (row[0] or 0) if row else 0
        new_ver = str(max_ver + 1)
        pid = self._new_id()
        c.execute(
            "INSERT INTO system_prompts (id, version, content, reason, source_reflection_id, created_at) "
            "VALUES (?, ?, ?, ?, ?, datetime('now', 'localtime'))",
            (pid, new_ver, content, reason, source_reflection_id),
        )
        c.connection.commit()
        c.close()
        return pid

    def get_latest_system_prompt(self):
        c = self.conn.cursor()
        c.execute("SELECT * FROM system_prompts WHERE is_active = 1 ORDER BY CAST(version AS INTEGER) DESC LIMIT 1")
        row = c.fetchone()
        c.close()
        return dict(row) if row else None

    def get_system_prompt_history(self, limit: int = 20):
        c = self.conn.cursor()
        c.execute("SELECT * FROM system_prompts ORDER BY CAST(version AS INTEGER) DESC LIMIT ?", (limit,))
        rows = c.fetchall()
        c.close()
        return [dict(r) for r in rows]

    def deactivate_system_prompt(self, prompt_id: str) -> bool:
        c = self.conn.cursor()
        c.execute("UPDATE system_prompts SET is_active = 0 WHERE id = ?", (prompt_id,))
        c.connection.commit()
        affected = c.rowcount
        c.close()
        return affected > 0

    def rollback_system_prompt(self, prompt_id: str) -> bool:
        c = self.conn.cursor()
        c.execute("UPDATE system_prompts SET is_active = 0 WHERE is_active = 1")
        c.execute("UPDATE system_prompts SET is_active = 1 WHERE id = ?", (prompt_id,))
        c.connection.commit()
        affected = c.rowcount
        c.close()
        return affected > 0

    def get_system_prompt_count(self) -> int:
        c = self.conn.cursor()
        c.execute("SELECT COUNT(*) FROM system_prompts")
        count = c.fetchone()[0]
        c.close()
        return count


class Storage:
    """主存储类 — 组合 8 个委派组件，管理数据库连接与生命周期。"""

    # 委派组件名列表，用于 __getattr__ 路由
    _delegate_attrs = (
        "_topics", "_conversations", "_summaries", "_memories",
        "_prompts", "_reflections", "_config_history", "_vectors",
        "_scheduled_tasks",
    )

    def __init__(self, db_path="chat_history.db"):
        """初始化存储，每次操作独立连接（短连接模式）。
        
        Args:
            db_path: 数据库文件路径。
        """
        self.db_path = db_path
        self._maybe_rotate_db()
        logger.info(f"load database {db_path}")

        # 临时连接初始化表结构
        with DB(db_path) as db:
            self._init_tables(db)
            self._migrate(db)
            self._write_week_key(db)

        self._auto_backup()
        self._protect_db()

        # ── 创建所有委派组件（传入 db_path，无持久连接）──
        self._topics = TopicStore(db_path)
        self._conversations = ConversationStore(db_path)
        self._summaries = SummaryStore(db_path)
        self._memories = MemoryStore(db_path)
        self._prompts = PromptStore(db_path)
        self._reflections = ReflectionStore(db_path)
        self._config_history = ConfigHistoryStore(db_path)
        self._vectors = VectorStore(db_path)
        self._scheduled_tasks = ScheduledTaskStore(db_path)

        # ── 注入 EmbeddingEngine 到 MemoryStore ──
        try:
            from tea_agent.embedding_util import EmbeddingEngine
            from tea_agent.config import get_config
            cfg = get_config()
            engine = EmbeddingEngine(cfg.embedding)
            self._memories.embedding_engine = engine
            logger.info("EmbeddingEngine injected into MemoryStore")
        except Exception as e:
            logger.warning(f"Inject EmbeddingEngine failed (non-fatal): {e}")

        # ── 显式公开属性，便于 IDE 跳转和代码导航 ──
        self.topics = self._topics
        self.conversations = self._conversations
        self.summaries = self._summaries
        self.memories = self._memories
        self.prompts = self._prompts
        self.reflections = self._reflections
        self.config_history = self._config_history
        self.vectors = self._vectors
        self.scheduled_tasks = self._scheduled_tasks

    # ── 显式委托方法（IDE 可跳转，文档可索引）──

    # ── Topic 操作 ──
    def create_topic(self, title: str, topic_id: str = None) -> str:
        """创建新主题。"""
        return self._topics.create_topic(title, topic_id)

    def get_topic(self, topic_id: str) -> dict:
        """获取主题信息。"""
        return self._topics.get_topic(topic_id)

    def list_topics(self) -> list:
        """列出所有主题。"""
        return self._topics.list_topics()

    def delete_topic(self, topic_id: str) -> bool:
        """删除主题。"""
        return self._topics.delete_topic(topic_id)

    def update_topic_title(self, topic_id: str, title: str):
        """更新主题标题。"""
        return self._topics.update_topic_title(topic_id, title)

    def update_topic_active(self, topic_id: str, is_active: bool = True):
        """更新主题活跃状态。"""
        return self._topics.update_topic_active(topic_id, is_active)

    # ── Topic Token 统计 ──
    def get_topic_tokens(self, topic_id: str) -> dict:
        """获取主题 token 统计。"""
        return self._topics.get_topic_tokens(topic_id)

    def add_topic_tokens(self, topic_id: str, **kwargs):
        """累加主题 token 统计。支持 total_tokens, prompt_tokens, completion_tokens,
        cheap_tokens, cheap_prompt_tokens, cheap_completion_tokens,
        embedding_tokens, embedding_prompt_tokens 等关键字参数。"""
        return self._topics.add_topic_tokens(topic_id, **kwargs)

    # ── Conversation 操作 ──
    def get_conversations(self, topic_id: str, limit: int = 5, include_rounds: bool = True) -> list:
        """获取主题下的对话记录。"""
        return self._conversations.get_conversations(topic_id, limit=limit, include_rounds=include_rounds)

    def get_recent_conversations(self, topic_id: str, limit: int = 10) -> list:
        """获取最近的对话记录。"""
        return self._conversations.get_recent_conversations(topic_id, limit)

    def update_msg_rounds(self, conversation_id: str, ai_msg: str, is_func_calling: bool, rounds: list = None):
        """更新消息的 rounds 数据。"""
        return self._conversations.update_msg_rounds(conversation_id, ai_msg, is_func_calling, rounds)

    def get_agent_rounds(self, conversation_id: str) -> list:
        """获取对话的 agent rounds。"""
        return self._conversations.get_agent_rounds(conversation_id)

    # ── 特殊桥接：save_msg 需要回调其他组件的 update_active ──
    def save_msg(self, topic_id: str, user_msg, ai_msg: str, is_func: bool) -> str:
        """桥接方法：save_msg 需要 update_topic_active 回调。"""
        return self._conversations.save_msg(
            topic_id, user_msg, ai_msg, is_func,
            update_active_cb=self._topics.update_topic_active,
            auto_embed_cb=None,  # 使用 _conversations 内置的 _auto_embed_async
        )

    # ── Memory 操作 ──
    def add_memory(self, content: str, category: str = "general", priority: int = 2,
                   importance: int = 3, expires_at: str = None, tags: str = "",
                   source_topic_id: str = None, pinned: int = 0,
                   embedding: list = None) -> str:
        """添加记忆。"""
        return self._memories.add_memory(content, category, priority, importance,
                                         expires_at=expires_at, tags=tags,
                                         source_topic_id=source_topic_id,
                                         pinned=pinned, embedding=embedding)

    def get_active_memories(self, limit: int = 50) -> list:
        """获取活跃记忆。"""
        return self._memories.get_active_memories(limit)

    def search_memories(self, query: str = "", category: str = "",
                        tags: list = None, min_importance: int = 0, limit: int = 10) -> list:
        """搜索记忆。"""
        return self._memories.search_memories(query, category=category,
                                              tags=tags, min_importance=min_importance,
                                              limit=limit)

    def get_memory_stats(self) -> dict:
        """获取记忆统计。"""
        return self._memories.get_memory_stats()

    # ── Summary 操作 ──
    def get_topic_summary(self, topic_id: str) -> str:
        """获取主题摘要。"""
        return self._summaries.get_topic_summary(topic_id)

    def update_topic_summary(self, topic_id: str, summary: str,
                             last_summarized_id=None):
        """更新主题摘要。"""
        return self._summaries.update_topic_summary(topic_id, summary, last_summarized_id=last_summarized_id)

    def get_unsummarized_conversations(self, topic_id: str) -> list:
        """获取未摘要的对话。"""
        return self._summaries.get_unsummarized_conversations(topic_id)

    def mark_as_summarized(self, conversation_id: str):
        """标记对话为已摘要。"""
        return self._summaries.mark_as_summarized(conversation_id)

    def get_semantic_summary(self, topic_id: str) -> str:
        """获取语义摘要。"""
        return self._summaries.get_semantic_summary(topic_id)

    def set_semantic_summary(self, topic_id: str, summary: str):
        """设置语义摘要。"""
        return self._summaries.set_semantic_summary(topic_id, summary)

    def get_tool_chain_summary(self, topic_id: str) -> str:
        """获取工具链摘要。"""
        return self._summaries.get_tool_chain_summary(topic_id)

    def set_tool_chain_summary(self, topic_id: str, summary: str):
        """设置工具链摘要。"""
        return self._summaries.set_tool_chain_summary(topic_id, summary)

    # ── Prompt 操作 ──
    def add_system_prompt(self, content: str, reason: str = "", source_reflection_id=None) -> str:
        """添加系统提示词。"""
        return self._prompts.add_system_prompt(content, reason, source_reflection_id)

    def get_latest_system_prompt(self) -> dict:
        """获取最新系统提示词。"""
        return self._prompts.get_latest_system_prompt()

    def get_system_prompt_history(self, limit: int = 20) -> list:
        """获取系统提示词历史。"""
        return self._prompts.get_system_prompt_history(limit)

    def deactivate_system_prompt(self, prompt_id: str) -> bool:
        """停用系统提示词。"""
        return self._prompts.deactivate_system_prompt(prompt_id)

    def rollback_system_prompt(self, prompt_id: str) -> bool:
        """回滚系统提示词。"""
        return self._prompts.rollback_system_prompt(prompt_id)

    def get_system_prompt_count(self) -> int:
        """获取系统提示词数量。"""
        return self._prompts.get_system_prompt_count()

    # ── Reflection 操作 ──
    def add_reflection(self, summary: str, details: str = "", tool_stats=None,
                       suggestions=None, topic_id=None) -> str:
        """添加反思记录。"""
        return self._reflections.add_reflection(summary, details, tool_stats, suggestions, topic_id)

    def get_recent_reflections(self, limit: int = 10) -> list:
        """获取最近的反思记录。"""
        return self._reflections.get_recent_reflections(limit)

    def mark_reflection_applied(self, reflection_id: str):
        """标记反思为已应用。"""
        return self._reflections.mark_reflection_applied(reflection_id)

    def get_reflection_stats(self) -> dict:
        """获取反思统计。"""
        return self._reflections.get_reflection_stats()

    # ── Config History 操作 ──
    def add_config_change(self, key: str, new_value: str, old_value=None,
                          reason: str = "", source_reflection_id=None) -> str:
        """添加配置变更记录。"""
        return self._config_history.add_config_change(key, new_value, old_value, reason, source_reflection_id)

    def get_config_history(self, key: str = "", limit: int = 20) -> list:
        """获取配置变更历史。"""
        return self._config_history.get_config_history(key, limit)

    # ── Vector 操作 ──
    def store_embedding(self, conversation_id: str, embedding: bytes, dimension: int = 0, model_name: str = ""):
        """存储对话嵌入向量。"""
        return self._vectors.store_embedding(conversation_id, embedding, dimension, model_name)

    def get_msg_embedding(self, conversation_id: str) -> bytes:
        """获取对话嵌入向量。"""
        return self._vectors.get_msg_embedding(conversation_id)

    def search_by_keyword(self, query: str, limit: int = 10) -> list:
        """关键词搜索对话。"""
        return self._vectors.search_by_keyword(query, limit)

    # ── Scheduled Task 操作 ──
    def add_task(self, name: str, command: str, schedule: str) -> str:
        """添加定时任务。"""
        return self._scheduled_tasks.add_task(name, command, schedule)

    def list_tasks(self) -> list:
        """列出所有定时任务。"""
        return self._scheduled_tasks.list_tasks()

    def get_task(self, task_id: str) -> dict:
        """获取定时任务。"""
        return self._scheduled_tasks.get_task(task_id)

    def delete_task(self, task_id: str) -> bool:
        """删除定时任务。"""
        return self._scheduled_tasks.delete_task(task_id)

    def update_task(self, task_id: str, **kwargs):
        """更新定时任务。"""
        return self._scheduled_tasks.update_task(task_id, **kwargs)

    # ── 向后兼容：自动委派（fallback）──
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

    # ── 表初始化 ──

    def _init_tables(self, db):
        """初始化所有数据库表。
        
        Args:
            db: DB 实例（由调用方管理生命周期）。
        """
        c = db.cursor()

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
                content_hash TEXT DEFAULT '',
                embedding BLOB,
                created_at TIMESTAMP DEFAULT (datetime('now', 'localtime')),
                updated_at TIMESTAMP DEFAULT (datetime('now', 'localtime')),
                last_accessed_at TIMESTAMP,
                pinned INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY (source_topic_id) REFERENCES topics(topic_id)
            )
        ''')
        # 兼容旧表：尝试新增新列
        for col, col_def in [('pinned', 'INTEGER NOT NULL DEFAULT 0'),
                              ('content_hash', "TEXT DEFAULT ''"),
                              ('embedding', 'BLOB')]:
            try:
                c.execute(f"ALTER TABLE memories ADD COLUMN {col} {col_def}")
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

        # scheduled_tasks 表（定时任务）
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

    # ── 数据库迁移 ──

    def _migrate(self, db):
        """执行数据库迁移。
        
        Args:
            db: DB 实例（由调用方管理生命周期）。
        """
        c = db.cursor()
        self._migrate_int_to_uuid(c)

        # 添加 rounds_json 列
        try:
            c.execute("ALTER TABLE conversations ADD COLUMN rounds_json TEXT")
            c.connection.commit()
        except sqlite3.OperationalError:
            pass

        # 添加 is_summarized 列
        try:
            c.execute("ALTER TABLE conversations ADD COLUMN is_summarized INTEGER DEFAULT 0")
            c.connection.commit()
        except sqlite3.OperationalError:
            pass

        # t_conv_summary 添加 last_summarized_id
        try:
            c.execute("ALTER TABLE t_conv_summary ADD COLUMN last_summarized_id TEXT")
            c.connection.commit()
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
                c.connection.commit()
            except sqlite3.OperationalError:
                pass

        # topic_token_stats 嵌入模型列
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
        c.connection.execute("PRAGMA foreign_keys = OFF")
        c.connection.execute("PRAGMA legacy_alter_table = ON")

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

            c.connection.commit()
            log.warning("INTEGER→TEXT UUID 主键迁移完成！")
        except Exception as e:
            log.error(f"UUID 迁移失败，回滚: {e}")
            c.connection.rollback()
            raise
        finally:
            c.connection.execute("PRAGMA foreign_keys = ON")
            c.connection.execute("PRAGMA legacy_alter_table = OFF")

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
        c.connection.commit()

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

    def _write_week_key(self, db):
        """写入当前周标识。
        
        Args:
            db: DB 实例（由调用方管理生命周期）。
        """
        with Cursor(db) as c:
            c.execute(
                "INSERT OR REPLACE INTO _meta (key, value) VALUES ('week_key', ?)",
                (self._get_week_key(),),
            )
            c.connection.commit()

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
            src_conn = sqlite3.connect(self.db_path)
            src_conn.backup(backup_conn)
            backup_conn.close()
            src_conn.close()
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
        """读取元数据（短连接）。"""
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.execute("SELECT value FROM _meta WHERE key=?", (key,))
            row = c.fetchone()
            conn.close()
            return row[0] if row else None
        except Exception:
            return None

    def _meta_set(self, key: str, value: str):
        """写入元数据（短连接）。"""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.execute(
                "INSERT OR REPLACE INTO _meta (key, value) VALUES (?, ?)", (key, value)
            )
            conn.commit()
            conn.close()
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
        """关闭存储（关闭线程局部连接 + WAL checkpoint）。"""
        StoreComponent.close_thread_conn()
        try:
            with DB(self.db_path) as db:
                db.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            logger.info("WAL checkpoint(TRUNCATE) 完成")
        except Exception as e:
            logger.warning(f"WAL checkpoint 失败 (非致命): {e}")
        finally:
            logger.info(f"存储已关闭: {self.db_path}")

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass
