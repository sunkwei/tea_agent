"""

向后兼容导出：from tea_agent.store import Storage, get_storage 保持不变。
内部结构：
  _core.py        - Storage 核心（连接、迁移、备份）
  _base.py        - StoreComponent 基类
  _topics.py      - TopicStore（主题 CRUD + Token 统计）
  _conversations.py - ConversationStore（对话 & Agent 轮次）
  _summaries.py   - SummaryStore（摘要 & 三级历史）
  _memories.py    - MemoryStore（长期记忆）
  _auto_memory.py - AutoMemoryExtractor（自动记忆提取）
  _prompts.py     - PromptStore（系统提示词版本）
  _reflections.py - ReflectionStore（反思记录）
  _config.py      - ConfigHistoryStore（配置变更历史）
  _vectors.py     - VectorStore（向量 & 语义搜索）
"""
from ._core import Storage
from ._auto_memory import AutoMemoryExtractor

__all__ = ["Storage", "AutoMemoryExtractor"]

# ── 模块级单例 ──

_storage_instance = None

def get_storage(db_path: str = "") -> Storage:
    """获取或创建 Storage 单例（供工具函数使用）。

    优先从 config.paths.db_path_abs 读取路径，否则回退到 chat_history.db。
    """
    global _storage_instance
    if not db_path:
        try:
            from tea_agent.config import get_config
            db_path = get_config().paths.db_path_abs
        except Exception:
            db_path = "chat_history.db"
    if _storage_instance is None or _storage_instance.db_path != db_path:
        _storage_instance = Storage(db_path)
    return _storage_instance
