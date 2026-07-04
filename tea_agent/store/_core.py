"""

Storage 类自身管理：连接生命周期、数据库迁移/备份/轮转、表初始化。
业务逻辑委派给 8 个子组件：topics, conversations, summaries, memories,
prompts, reflections, config_history, vectors。

扩展功能：
- SemanticSearch: 语义搜索
- AutoMemoryExtractor: 移入 session_memory_component.py

向后兼容：通过 __getattr__ 自动将方法调用路由到对应委派组件。
"""
import json as _json_rs
import logging

from ._component import StoreComponent, DB  # DB 短连接上下文管理器
from ._topics import TopicStore
from ._conversations import ConversationStore
from ._summaries import SummaryStore
from ._memories import MemoryStore
from ._vectors import VectorStore
from ._semantic_search import SemanticSearch
from ._scheduled_tasks import ScheduledTaskStore
from ._migration import (
    init_tables, migrate,
    maybe_rotate_db, write_week_key,
    auto_backup, cleanup_backups, backup_now,
    meta_get, meta_set,
    protect_db,
)

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
        maybe_rotate_db(db_path)
        logger.info(f"load database {db_path}")

        with DB(db_path) as db:
            init_tables(db)
            migrate(db)
            write_week_key(db)

        protect_db(db_path)

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

    def accumulate_pending_cheap_tokens(self, topic_id: str, usage: dict):
        """累加待显示的便宜模型 token（异步摘要产生）。"""
        return self._topics.accumulate_pending_cheap_tokens(topic_id, usage)

    def get_and_clear_pending_cheap_tokens(self, topic_id: str) -> dict:
        """读取并清零待显示的便宜模型 token。"""
        return self._topics.get_and_clear_pending_cheap_tokens(topic_id)

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

    def search_conversations(self, query: str, limit: int = 30,
                              include_ai: bool = True, include_rounds: bool = True,
                              date_from: str = "", date_to: str = "") -> list:
        """全文搜索对话。"""
        return self._conversations.search_conversations(
            query, limit=limit, include_ai=include_ai,
            include_rounds=include_rounds, date_from=date_from, date_to=date_to,
        )

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
