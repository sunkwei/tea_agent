"""
PiFeaturesModule — 借鉴 Pi Agent Harness 的功能模块（热重载）。

将已就绪的底层能力暴露为 server 可调 API：
  - 会话树 + 分支（session.session_tree.SessionTree）
  - Steering/Follow-up 消息队列（session.message_queue.MessageQueue）
  - 手动上下文压缩（auto_compact.CompactionPipeline）

用法（route_handlers 中）：
    from ..modules.pi_features_module import PiFeaturesModule
    result = PiFeaturesModule.tree_get(topic_id)
"""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any

from ..module import HotReloadModule, ModuleRegistry

logger = logging.getLogger("hot_reload.pi_features")

# 模块级缓存：topic_id -> SessionTree / MessageQueue（惰性创建）
_trees: dict[str, Any] = {}
_queues: dict[str, Any] = {}
_cache_lock = threading.Lock()

_TREE_DIR = "session_trees"


class PiFeaturesModule(HotReloadModule):
    """Pi 功能模块：会话树 + 消息队列 + 手动压缩。"""

    name: str = "pi_features"
    dependencies: list[str] = ["agent", "storage"]

    _instance: Any = None

    # ── 热重载接口 ──────────────────────────────────────

    @classmethod
    def _load(cls, registry: ModuleRegistry) -> bool:
        cls._instance = cls
        logger.info("🧩 PiFeaturesModule loaded（会话树/消息队列/压缩）")
        return True

    @classmethod
    def _unload(cls) -> None:
        # 落盘所有会话树
        try:
            for tid, tree in list(_trees.items()):
                cls._persist_tree(tid, tree)
        except Exception as e:
            logger.warning(f"卸载时持久化会话树失败: {e}")
        cls._instance = None

    # ── 树持久化辅助 ────────────────────────────────────

    @staticmethod
    def _tree_dir() -> Path:
        base = Path(os.environ.get("TEA_AGENT_HOME", Path.home() / ".tea_agent"))
        d = base / _TREE_DIR
        d.mkdir(parents=True, exist_ok=True)
        return d

    @classmethod
    def _tree_path(cls, topic_id: str) -> Path:
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in topic_id)
        return cls._tree_dir() / f"{safe}.jsonl"

    @classmethod
    def _persist_tree(cls, topic_id: str, tree: Any) -> None:
        try:
            tree.save_jsonl(cls._tree_path(topic_id))
        except Exception as e:
            logger.warning(f"会话树持久化失败 {topic_id}: {e}")

    # ── 会话树 API ──────────────────────────────────────

    @classmethod
    def _get_tree(cls, topic_id: str) -> Any:
        """惰性获取（或创建）topic 的会话树。"""
        with _cache_lock:
            tree = _trees.get(topic_id)
            if tree is not None:
                return tree
        # 尝试从 JSONL 加载
        from tea_agent.session.session_tree import SessionTree
        path = cls._tree_path(topic_id)
        if path.exists():
            try:
                tree = SessionTree.load_jsonl(path)
                with _cache_lock:
                    _trees[topic_id] = tree
                return tree
            except Exception as e:
                logger.warning(f"会话树加载失败 {topic_id}: {e}")
        tree = SessionTree(tree_id=topic_id[:8])
        with _cache_lock:
            _trees[topic_id] = tree
        return tree

    @classmethod
    def tree_get(cls, topic_id: str) -> dict:
        """获取会话树结构 + 当前路径 + 分支列表。"""
        tree = cls._get_tree(topic_id)
        stats = tree.get_tree_stats()
        path = tree.get_path_to_root()
        return {
            "ok": True,
            "topic_id": topic_id,
            "stats": stats,
            "current_path": [
                {"id": n.id[:8], "role": n.role,
                 "content": (n.content[:80] if isinstance(n.content, str) else str(n.content)[:80])}
                for n in path
            ],
            "branches": [
                {"node_id": b.node_id[:8], "label": b.label,
                 "summary": b.summary[:200], "message_count": b.message_count}
                for b in tree.branches.values()
            ],
        }

    @classmethod
    def tree_append(cls, topic_id: str, role: str, content: str, **meta) -> dict:
        """向会话树当前分支追加一条消息。"""
        tree = cls._get_tree(topic_id)
        node = tree.append(role, content, **meta)
        cls._persist_tree(topic_id, tree)
        return {"ok": True, "node_id": node.id[:8], "role": node.role,
                "parent_id": (node.parent_id or "")[:8]}

    @classmethod
    def tree_branch(cls, topic_id: str, content: str, label: str = "") -> dict:
        """从当前位置创建分支（内容通常是用户的新输入）。"""
        tree = cls._get_tree(topic_id)
        if tree.current_id is None:
            node = tree.append("user", content)
            return {"ok": True, "node_id": node.id[:8], "branch": True, "created_root": True}
        node = tree.branch("user", content, label=label)
        cls._persist_tree(topic_id, tree)
        return {"ok": True, "node_id": node.id[:8],
                "parent_id": (node.parent_id or "")[:8],
                "label": label or "分支", "branch": True}

    @classmethod
    def tree_switch(cls, topic_id: str, node_id: str) -> dict:
        """切换到指定节点（后续 append 从该节点继续）。"""
        tree = cls._get_tree(topic_id)
        # 支持短 ID 匹配（前 8 位）
        full_id = node_id
        if node_id not in tree.nodes:
            for nid in tree.nodes:
                if nid.startswith(node_id):
                    full_id = nid
                    break
        ok = tree.switch_to(full_id)
        cls._persist_tree(topic_id, tree)
        if not ok:
            return {"ok": False, "error": f"节点 {node_id} 不存在"}
        return {"ok": True, "node_id": full_id[:8], "depth": tree.get_current_depth()}

    @classmethod
    def tree_summary(cls, topic_id: str, node_id: str | None = None) -> dict:
        """获取（或生成本地摘要）分支摘要。"""
        tree = cls._get_tree(topic_id)
        if node_id is None:
            node_id = tree.current_id or ""
        full_id = node_id
        if full_id and full_id not in tree.nodes:
            for nid in tree.nodes:
                if nid.startswith(node_id):
                    full_id = nid
                    break
        summary = tree.get_branch_summary(full_id)
        if not summary:
            summary = tree.generate_branch_summary_text(full_id, max_length=500)
            tree.set_branch_summary(full_id, summary)
            cls._persist_tree(topic_id, tree)
        return {"ok": True, "node_id": full_id[:8], "summary": summary}

    @classmethod
    def tree_fork(cls, topic_id: str, node_id: str) -> dict:
        """从指定节点分叉出新树（返回新树 ID）。"""
        tree = cls._get_tree(topic_id)
        if node_id not in tree.nodes:
            for nid in tree.nodes:
                if nid.startswith(node_id):
                    node_id = nid
                    break
        try:
            new_tree = tree.fork(node_id)
        except ValueError as e:
            return {"ok": False, "error": str(e)}
        new_tid = f"{topic_id}_fork_{new_tree.tree_id}"
        with _cache_lock:
            _trees[new_tid] = new_tree
        cls._persist_tree(new_tid, new_tree)
        return {"ok": True, "forked_topic_id": new_tid,
                "node_id": node_id[:8], "nodes": len(new_tree.nodes)}

    # ── 消息队列 API ────────────────────────────────────

    @classmethod
    def _get_queue(cls, topic_id: str) -> Any:
        """惰性获取（或创建）topic 的消息队列。"""
        from tea_agent.session.message_queue import MessageQueue
        with _cache_lock:
            q = _queues.get(topic_id)
            if q is not None:
                return q
            q = MessageQueue(mode="one-at-a-time")
            _queues[topic_id] = q
            return q

    @classmethod
    def queue_push(cls, topic_id: str, content: str, msg_type: str = "steering") -> dict:
        """推送 steering / followup 消息。"""
        q = cls._get_queue(topic_id)
        if msg_type == "followup":
            msg = q.push_followup(content)
        else:
            msg = q.push_steering(content)
        return {"ok": True, "message_id": msg.id, "type": msg.type.value,
                "content": msg.content, "queued_at": msg.timestamp}

    @classmethod
    def queue_status(cls, topic_id: str) -> dict:
        """查看队列状态。"""
        q = cls._get_queue(topic_id)
        d = q.to_dict()
        d["ok"] = True
        return d

    @classmethod
    def queue_clear(cls, topic_id: str) -> dict:
        """清空队列。"""
        q = cls._get_queue(topic_id)
        q.clear()
        return {"ok": True, "cleared": True}

    @classmethod
    def queue_drain(cls, topic_id: str, msg_type: str = "steering") -> dict:
        """消费队列消息（供 agent 循环注入用）。"""
        q = cls._get_queue(topic_id)
        if msg_type == "followup":
            msgs = q.get_followup()
        else:
            msgs = q.get_steering()
        return {"ok": True, "messages": [m.to_dict() for m in msgs]}

    # ── 手动压缩 API ────────────────────────────────────

    @classmethod
    def compact_topic(cls, topic_id: str, force: bool = False, instructions: str = "") -> dict:
        """手动压缩 topic 的上下文（基于 auto_compact）。

        从 storage 拉取对话 → 跑 CompactionPipeline → 返回压缩结果。
        """
        try:
            from tea_agent.auto_compact import CompactionSettings, CompactionPipeline
            from ..modules.storage_module import StorageModule

            storage = StorageModule.get_storage()
            if storage is None:
                return {"ok": False, "error": "Storage not loaded"}
            convs = storage.get_conversations(topic_id, limit=0, include_rounds=True)
            messages = []
            for c in convs:
                um = c.get("user_msg")
                am = c.get("ai_msg")
                if isinstance(um, str) and um.strip():
                    messages.append({"role": "user", "content": um})
                if isinstance(am, str) and am.strip():
                    messages.append({"role": "assistant", "content": am})
            if not messages:
                return {"ok": False, "error": "该 topic 暂无对话可压缩", "messages": 0}

            settings = CompactionSettings()
            if instructions:
                settings.compaction_instructions = instructions
            pipeline = CompactionPipeline(settings=settings)
            result = pipeline.run(messages, config=None, force=force)
            result["ok"] = True
            result["topic_id"] = topic_id
            result["conversations"] = len(convs)
            return result
        except Exception as e:
            logger.exception(f"压缩失败 {topic_id}: {e}")
            return {"ok": False, "error": str(e)}

    # ── 统计 ────────────────────────────────────────────

    @classmethod
    def stats(cls) -> dict:
        return {
            "ok": True,
            "trees": {tid: t.get_tree_stats() for tid, t in _trees.items()},
            "queues": {tid: q.to_dict() for tid, q in _queues.items()},
        }
