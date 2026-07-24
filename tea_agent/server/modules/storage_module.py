"""
StorageModule — 热重载 Storage 模块。

管理持久化存储（SQLite 数据库）。
热重载时重建数据库连接。
依赖：无（但通常需要先于 AgentModule 加载）
"""

from __future__ import annotations

import logging
from typing import Any

from ..module import HotReloadModule, ModuleRegistry, _module_path_for

logger = logging.getLogger("hot_reload.storage")


class StorageModule(HotReloadModule):
    """Storage 热重载模块。

    封装 tea_agent.store.Storage，提供数据库访问能力。
    热重载时关闭旧连接，创建新连接。
    """

    name: str = "storage"
    dependencies: list[str] = []

    _instance: Any = None  # Storage 实例

    @classmethod
    def _load(cls, registry: ModuleRegistry) -> bool:
        """加载 Storage 模块。

        热重载时先重载 tea_agent.store 模块（仅 __init__.py），
        确保对 get_storage() 等底层函数的修改立即生效，无需重启 server。
        注意：不重载 _core / _component 等子模块——它们未变更，
        重载会创建新的类对象，破坏已有 Storage 实例的 isinstance 检查。
        """
        import importlib
        import sys as _sys

        # 重载 tea_agent.store（仅 __init__.py），使 get_storage() 变更生效
        _store_mod = _sys.modules.get('tea_agent.store')
        if _store_mod is not None:
            try:
                importlib.reload(_store_mod)
                logger.debug("Hot-reloaded tea_agent.store module")
            except Exception as e:
                logger.warning(f"Reload tea_agent.store failed (non-fatal): {e}")

        from tea_agent.store import get_storage

        storage = get_storage()
        cls._instance = storage
        logger.info(f"Storage loaded | db: {getattr(storage, '_db_path', 'unknown')}")
        return True

    @classmethod
    def _unload(cls) -> None:
        """卸载 Storage 模块。"""
        cls._instance = None

    # ── 公开接口 ──

    @classmethod
    def get_storage(cls) -> Any:
        """获取 Storage 实例。"""
        return cls._instance

    # ── 话题/会话管理 ──

    @classmethod
    def list_topics(cls, limit: int = 20) -> list[dict]:
        """列出所有话题。"""
        storage = cls._instance
        if storage is None:
            return []
        topics = storage.list_topics()
        result = []
        for t in topics[:limit]:
            tid = t["topic_id"]
            tokens = storage.get_topic_tokens(tid)
            result.append({
                "id": tid,
                "title": t.get("title", "") or tid[:8],
                "created": str(t.get("create_stamp", ""))[:19],
                "updated": str(t.get("last_update_stamp", ""))[:19],
                "total_tokens": (tokens or {}).get("total_tokens", 0),
            })
        return result

    @classmethod
    def create_topic(cls, title: str = "新话题") -> dict:
        """创建新话题。"""
        storage = cls._instance
        if storage is None:
            return {"error": "Storage not loaded"}
        tid = storage.create_topic(title)
        return {"id": tid, "title": title}

    @classmethod
    def get_topic(cls, topic_id: str) -> dict | None:
        """获取话题详情。"""
        storage = cls._instance
        if storage is None:
            return None
        topic = storage.get_topic(topic_id)
        if not topic:
            return None
        tokens = storage.get_topic_tokens(topic_id)
        convs = storage.get_conversations(topic_id, limit=0, include_rounds=True)
        return {
            "id": topic["topic_id"],
            "title": topic.get("title", ""),
            "created": str(topic.get("create_stamp", "")),
            "updated": str(topic.get("last_update_stamp", "")),
            "total_tokens": (tokens or {}).get("total_tokens", 0),
            "conversations": [
                {"id": c["id"], "user": c["user_msg"],
                 "assistant": c["ai_msg"], "stamp": c["stamp"]}
                for c in convs
            ],
        }

    @classmethod
    def delete_topic(cls, topic_id: str) -> bool:
        """删除话题。"""
        storage = cls._instance
        if storage is None:
            return False
        try:
            storage.delete_topic(topic_id)
            return True
        except Exception:
            return False

    @classmethod
    def rename_topic(cls, topic_id: str, new_title: str) -> bool:
        """重命名话题。"""
        storage = cls._instance
        if storage is None:
            return False
        try:
            storage.update_topic_title(topic_id, new_title)
            return True
        except Exception:
            return False

    @classmethod
    def get_topic_conversations(cls, topic_id: str, limit: int = 0) -> list[dict]:
        """获取话题对话历史。"""
        storage = cls._instance
        if storage is None:
            return []
        convs = storage.get_conversations(topic_id, limit=limit, include_rounds=True)
        result = []
        for c in convs:
            result.append({
                "id": c["id"],
                "topic_id": c["topic_id"],
                "user_msg": c["user_msg"],
                "ai_msg": c["ai_msg"],
                "is_func_calling": c.get("is_func_calling", 0),
                "stamp": str(c.get("stamp", "")),
            })
        return result

    @classmethod
    def get_topic_info(cls, topic_id: str) -> dict | None:
        """获取话题概要信息。"""
        storage = cls._instance
        if storage is None:
            return None
        topic = storage.get_topic(topic_id)
        if not topic:
            return None
        tokens = storage.get_topic_tokens(topic_id)
        return {
            "id": topic["topic_id"],
            "title": topic.get("title", ""),
            "created": str(topic.get("create_stamp", "")),
            "updated": str(topic.get("last_update_stamp", "")),
            "total_tokens": (tokens or {}).get("total_tokens", 0),
            "conversation_count": (tokens or {}).get("conversation_count", 0),
        }

    @classmethod
    def get_session_messages(cls, topic_id: str, limit: int = 50) -> list[dict]:
        """获取话题的 messages 格式。"""
        storage = cls._instance
        if storage is None:
            return []
        convs = storage.get_conversations(topic_id, limit=limit, include_rounds=True)
        result = []
        for c in convs:
            result.append({
                "id": c["id"], "role": "user",
                "content": c["user_msg"],
                "stamp": str(c.get("stamp", ""))[:26],
            })
            result.append({
                "id": c["id"], "role": "assistant",
                "content": c["ai_msg"],
                "stamp": str(c.get("stamp", ""))[:26],
            })
        return result

    # ── 记忆管理 ──

    @classmethod
    def list_memories(cls, limit: int = 50) -> list[dict]:
        """列出记忆。"""
        storage = cls._instance
        if storage is None:
            return []
        return _sanitize(storage.get_active_memories(limit=limit))

    @classmethod
    def create_memory(cls, content: str, category: str = "general",
                      priority: int = 2) -> dict:
        """创建记忆。"""
        storage = cls._instance
        if storage is None:
            return {"error": "Storage not loaded"}
        mem_id = storage.add_memory(
            content, category=category, priority=priority,
            tags="", importance=3,
        )
        return {"id": mem_id, "content": content, "category": category}

    @classmethod
    def delete_memory(cls, mem_id: int | str) -> bool:
        """删除记忆。"""
        storage = cls._instance
        if storage is None:
            return False
        try:
            return storage.delete_memory(mem_id)
        except Exception:
            return False

    # ── 搜索 ──

    @classmethod
    def search(cls, query: str, limit: int = 20) -> dict:
        """跨实体搜索。"""
        storage = cls._instance
        if storage is None:
            return {"conversations": [], "memories": []}
        convs = _sanitize(storage.search_conversations(query, limit=limit))
        mems = _sanitize(storage.search_memories(query, limit=limit))
        return {"conversations": convs, "memories": mems}


def _sanitize(obj):
    """移除不可 JSON 序列化的字段（如 bytes）。"""
    if isinstance(obj, dict):
        return {
            k: _sanitize(v) for k, v in obj.items()
            if not isinstance(v, bytes | bytearray)
        }
    if isinstance(obj, list):
        return [_sanitize(item) for item in obj]
    return obj


# 设置模块路径
_module_path_for(StorageModule)
