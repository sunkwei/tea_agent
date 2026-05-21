"""
项目记忆管理器
存储到项目目录 .tea_agent_run/project_memories.json，纯 FIFO。
与用户记忆（优先级/衰减/精调）完全独立。
"""

import json
import logging
import os
from typing import Dict, List, Optional
from datetime import datetime

logger = logging.getLogger("ProjectMemory")

class ProjectMemoryManager:
    """项目记忆：纯 FIFO，最多 30 条。"""

    MAX_ENTRIES = 30
    STORE_FILE = ".tea_agent_run/project_memories.json"

    def __init__(self, project_root: str = "."):
        """Initialize  .
        
        Args:
            project_root: Description.
        """
        self.project_root = os.path.abspath(project_root)
        self.store_path = os.path.join(self.project_root, self.STORE_FILE)
        self._ensure_store()

    def _ensure_store(self):
        """确保存储目录和文件存在"""
        os.makedirs(os.path.dirname(self.store_path), exist_ok=True)
        if not os.path.exists(self.store_path):
            self._write([])

    def _read(self) -> List[Dict]:
        """读取所有项目记忆"""
        try:
            with open(self.store_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
        except (json.JSONDecodeError, FileNotFoundError):
            pass
        return []

    def _write(self, data: List[Dict]):
        """写入项目记忆"""
        with open(self.store_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def add(self, content: str, tags: str = "") -> int:
        """
        添加项目记忆（FIFO：满了踢最旧）。

        Args:
            content: 记忆内容
            tags: 逗号分隔标签

        Returns:
            当前记忆总数
        """
        data = self._read()
        entry = {
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

    def get_all(self, limit: int = MAX_ENTRIES) -> List[Dict]:
        """获取所有项目记忆（最新在前）"""
        data = self._read()
        return list(reversed(data[-limit:]))

    def search(self, query: str, limit: int = 10) -> List[Dict]:
        """关键词搜索项目记忆"""
        if not query:
            return self.get_all(limit)
        data = self._read()
        query_lower = query.lower()
        results = []
        for m in reversed(data):
            content_lower = m.get("content", "").lower()
            tags_lower = (m.get("tags", "") or "").lower()
            if query_lower in content_lower or query_lower in tags_lower:
                results.append(m)
                if len(results) >= limit:
                    break
        return results

    @staticmethod
    def _new_id(data: List[Dict]) -> str:
        """生成新的记忆 ID"""
        max_id = 0
        for m in data:
            try:
                mid = int(m.get("id", "0").replace("proj_", ""))
                max_id = max(max_id, mid)
            except (ValueError, TypeError):
                pass
        return f"proj_{max_id + 1}"

    @staticmethod
    def format_memories(memories: List[Dict]) -> str:
        """格式化项目记忆为注入文本"""
        if not memories:
            return ""

        lines = [
            f"[项目记忆 — 当前项目相关知识，共 {len(memories)} 条]",
            ""
        ]
        for m in memories:
            tags = m.get("tags", "")
            tag_str = f" [{tags}]" if tags else ""
            lines.append(f"📂 {m['content']}{tag_str}")

        return "\n".join(lines)
