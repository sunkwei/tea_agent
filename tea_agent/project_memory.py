"""
项目记忆管理器 — 存储到项目目录 .tea_agent_run/project_memories.json。

与用户记忆（优先级/衰减/精调）完全独立。
纯 FIFO 队列，最多 30 条，满了自动踢除最旧条目。

用法:
    manager = ProjectMemoryManager(project_root=".")
    manager.add("重要信息", tags="架构,决策")
    all_memories = manager.get_all()
    results = manager.search("关键词")
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import Any

logger = logging.getLogger("ProjectMemory")

__all__ = [
    "ProjectMemoryManager",
]

class ProjectMemoryManager:
    """项目记忆：纯 FIFO，最多 30 条。"""

    MAX_ENTRIES = 30
    STORE_FILE = ".tea_agent_run/project_memories.json"

    def __init__(self, project_root: str = ".") -> None:
        """初始化项目记忆管理器。

        Args:
            project_root: 项目根目录路径，默认为当前目录。
                          记忆文件存储在 {project_root}/.tea_agent_run/project_memories.json
        """
        self.project_root = os.path.abspath(project_root)
        self.store_path = os.path.join(self.project_root, self.STORE_FILE)
        self._ensure_store()

    def _ensure_store(self) -> None:
        """确保存储目录和文件存在。文件不存在时创建空数组 JSON 文件。"""
        os.makedirs(os.path.dirname(self.store_path), exist_ok=True)
        if not os.path.exists(self.store_path):
            self._write([])

    def _read(self) -> list[dict[str, Any]]:
        """从磁盘读取所有项目记忆。

        Returns:
            记忆条目字典列表，文件损坏或不存在时返回空列表
        """
        try:
            with open(self.store_path, encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
        except (json.JSONDecodeError, FileNotFoundError):
            pass
        return []

    def _write(self, data: list[dict[str, Any]]) -> None:
        """将项目记忆写入磁盘（JSON 格式）。

        Args:
            data: 记忆条目字典列表
        """
        with open(self.store_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def add(self, content: str, tags: str = "") -> int:
        """添加一条项目记忆，FIFO 淘汰：超过 MAX_ENTRIES 时自动踢除最旧条目。

        Args:
            content: 记忆内容文本
            tags: 逗号分隔的标签字符串

        Returns:
            当前记忆总数
        """
        data = self._read()
        entry: dict[str, Any] = {
            "id": self._new_id(data),
            "content": content.strip(),
            "tags": tags,
            "created_at": datetime.now().isoformat(),
        }
        data.append(entry)

        # FIFO 淘汰
        while len(data) > self.MAX_ENTRIES:
            removed = data.pop(0)
            logger.info(f"项目记忆 FIFO 淘汰: #{removed['id']} \"{removed['content'][:50]}...\"")

        self._write(data)
        logger.info(f"项目记忆新增 #{entry['id']}, 总数={len(data)}")
        return len(data)

    def get_all(self, limit: int = 30) -> list[dict[str, Any]]:
        """获取所有项目记忆（最新在前）。

        Args:
            limit: 最多返回的条目数，默认 30

        Returns:
            记忆条目字典列表，按创建时间倒序
        """
        data = self._read()
        return list(reversed(data[-limit:]))

    def search(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """关键词搜索项目记忆（不区分大小写，匹配 content 或 tags）。

        Args:
            query: 搜索关键词
            limit: 最多返回的条目数，默认 10

        Returns:
            匹配的记忆条目列表
        """
        if not query:
            return self.get_all(limit)
        data = self._read()
        query_lower = query.lower()
        results: list[dict[str, Any]] = []
        for m in reversed(data):
            content_lower = m.get("content", "").lower()
            tags_lower = (m.get("tags", "") or "").lower()
            if query_lower in content_lower or query_lower in tags_lower:
                results.append(m)
                if len(results) >= limit:
                    break
        return results

    @staticmethod
    def _new_id(data: list[dict[str, Any]]) -> str:
        """生成新的记忆 ID（格式: proj_数字）。

        Args:
            data: 现有记忆列表，用于找到最大 ID

        Returns:
            新的唯一 ID 字符串
        """
        max_id = 0
        for m in data:
            try:
                mid = int(m.get("id", "0").replace("proj_", ""))
                max_id = max(max_id, mid)
            except (ValueError, TypeError):
                pass
        return f"proj_{max_id + 1}"

    @staticmethod
    def format_memories(memories: list[dict[str, Any]]) -> str:
        """格式化项目记忆列表为注入文本（供系统提示词使用）。

        Args:
            memories: 记忆条目列表

        Returns:
            格式化的字符串，无记忆时返回空字符串
        """
        if not memories:
            return ""

        lines: list[str] = [
            f"[项目记忆 — 当前项目相关知识，共 {len(memories)} 条]",
            "",
        ]
        for m in memories:
            tags = m.get("tags", "")
            tag_str = f" [{tags}]" if tags else ""
            lines.append(f"📂 {m['content']}{tag_str}")

        return "\n".join(lines)
