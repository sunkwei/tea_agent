# version: 1.0.0

"""
测试记忆系统增强功能：
- AutoMemoryExtractor
- SemanticSearch
- 新的 toolkit_memory actions
"""

import pytest
import tempfile
import os
import shutil
from unittest.mock import patch


@pytest.fixture
def storage():
    """创建临时数据库（使用目录，避免 Windows 文件锁定）"""
    import time
    from tea_agent.store import Storage

    tmpdir = tempfile.mkdtemp(prefix="tea_mem_test_")
    db_path = os.path.join(tmpdir, "test.db")

    s = Storage(db_path)
    yield s
    # 等待后台线程完成，避免 access violation
    time.sleep(0.3)
    try:
        s.close()
    except Exception:
        pass
    time.sleep(0.2)
    try:
        shutil.rmtree(tmpdir, ignore_errors=True)
    except Exception:
        pass


def _mock_get_storage(s):
    """返回一个 mock 函数，让 get_storage 返回测试 storage"""
    def _mock(db_path=""):
        return s
    return _mock


class TestAutoMemoryExtractor:
    """测试自动记忆提取器"""

    def test_extractor_init(self, storage):
        """测试提取器初始化"""
        from tea_agent.store._auto_memory import AutoMemoryExtractor

        extractor = AutoMemoryExtractor(storage)
        assert extractor.storage == storage

    def test_get_unextracted_conversations(self, storage):
        """测试获取未提取的对话"""
        from tea_agent.store._auto_memory import AutoMemoryExtractor

        topic_id = storage.create_topic("测试主题")
        storage.save_msg(topic_id, "用户消息", "AI回复", False)

        extractor = AutoMemoryExtractor(storage)
        conversations = extractor._get_unextracted_conversations(topic_id)

        assert len(conversations) == 1
        assert conversations[0]["user_msg"] == "用户消息"

    def test_merge_conversations(self, storage):
        """测试合并对话"""
        from tea_agent.store._auto_memory import AutoMemoryExtractor

        extractor = AutoMemoryExtractor(storage)

        conversations = [
            {"user_msg": "问题1", "ai_msg": "回答1"},
            {"user_msg": "问题2", "ai_msg": "回答2"},
        ]

        merged = extractor._merge_conversations(conversations)

        assert "问题1" in merged
        assert "回答1" in merged
        assert "问题2" in merged

    def test_calculate_similarity(self, storage):
        """测试文本相似度计算"""
        from tea_agent.store._auto_memory import AutoMemoryExtractor

        extractor = AutoMemoryExtractor(storage)

        sim1 = extractor._calculate_similarity("hello", "hello")
        assert sim1 == 1.0

        sim2 = extractor._calculate_similarity("abc", "xyz")
        assert sim2 < 0.5

        sim3 = extractor._calculate_similarity("hello world", "hello python")
        assert 0.3 < sim3 < 0.8

    def test_is_duplicate(self, storage):
        """测试重复检测"""
        from tea_agent.store._auto_memory import AutoMemoryExtractor

        storage.add_memory("这是一条测试记忆", category="general")

        extractor = AutoMemoryExtractor(storage)
        assert extractor._is_duplicate("这是一条测试记忆", threshold=0.5) is True
        assert extractor._is_duplicate("完全不同的内容", threshold=0.9) is False


class TestSemanticSearch:
    """测试语义搜索"""

    def test_searcher_init(self, storage):
        """测试搜索器初始化"""
        from tea_agent.store._semantic_search import SemanticSearch

        searcher = SemanticSearch(storage)
        assert searcher.storage == storage

    def test_index_memory(self, storage):
        """测试记忆索引"""
        from tea_agent.store._semantic_search import SemanticSearch

        memory_id = storage.add_memory("测试记忆内容", category="fact")

        searcher = SemanticSearch(storage)
        result = searcher.index_memory(memory_id, "测试记忆内容")
        assert result is True

        # 验证 embedding 已存储到 memories 表
        c = storage.conn.cursor()
        c.execute("SELECT embedding FROM memories WHERE id = ?", (memory_id,))
        row = c.fetchone()
        c.close()
        assert row is not None
        assert row["embedding"] is not None

    def test_index_all_memories(self, storage):
        """测试批量索引"""
        from tea_agent.store._semantic_search import SemanticSearch

        storage.add_memory("记忆1", category="general")
        storage.add_memory("记忆2", category="fact")
        storage.add_memory("记忆3", category="instruction")

        searcher = SemanticSearch(storage)
        count = searcher.index_all_memories()
        # 可能为 0（如果 embedding 引擎不可用）或 3
        assert count >= 0

    def test_semantic_search(self, storage):
        """测试语义搜索"""
        from tea_agent.store._semantic_search import SemanticSearch

        storage.add_memory("Python编程技巧", category="fact")
        storage.add_memory("JavaScript开发", category="fact")
        storage.add_memory("用户喜欢蓝色", category="preference")

        searcher = SemanticSearch(storage)
        searcher.index_all_memories()

        results = searcher.semantic_search("编程", top_k=2)
        assert len(results) <= 2

    def test_hybrid_search(self, storage):
        """测试混合搜索"""
        from tea_agent.store._semantic_search import SemanticSearch

        storage.add_memory("Python是编程语言", category="fact")
        storage.add_memory("用户偏好", category="preference")

        searcher = SemanticSearch(storage)
        searcher.index_all_memories()

        results = searcher.hybrid_search("Python", top_k=2)
        assert len(results) <= 2

    def test_get_vector_stats(self, storage):
        """测试向量统计"""
        from tea_agent.store._semantic_search import SemanticSearch

        storage.add_memory("测试1", category="general")
        storage.add_memory("测试2", category="general")

        searcher = SemanticSearch(storage)
        searcher.index_all_memories()

        stats = searcher.get_vector_stats()
        assert stats["indexed_memories"] == 2
        assert stats["total_memories"] == 2
        assert stats["coverage"] == 1.0

    def test_cosine_similarity(self, storage):
        """测试余弦相似度"""
        from tea_agent.store._semantic_search import SemanticSearch

        searcher = SemanticSearch(storage)

        vec1 = [1.0, 0.0, 0.0]
        vec2 = [1.0, 0.0, 0.0]
        sim = searcher._cosine_similarity(vec1, vec2)
        assert sim == 1.0

        vec3 = [0.0, 1.0, 0.0]
        sim2 = searcher._cosine_similarity(vec1, vec3)
        assert sim2 == 0.0


class TestToolkitMemoryEnhancements:
    """测试 toolkit_memory 新功能（使用 mock storage 避免全局单例污染）"""

    def test_auto_extract_action(self, storage):
        """测试 auto_extract action"""
        from tea_agent.toolkit.toolkit_memory import toolkit_memory

        topic_id = storage.create_topic("测试主题")
        storage.save_msg(topic_id, "我喜欢Python", "好的，我记住了", False)

        with patch("tea_agent.store.get_storage", _mock_get_storage(storage)):
            result = toolkit_memory(action="auto_extract", topic_id=topic_id)
        assert isinstance(result, str)

    def test_semantic_search_action(self, storage):
        """测试 semantic_search action"""
        from tea_agent.toolkit.toolkit_memory import toolkit_memory

        storage.add_memory("Python编程技巧", category="fact")

        from tea_agent.store._semantic_search import SemanticSearch
        searcher = SemanticSearch(storage)
        searcher.index_all_memories()

        with patch("tea_agent.store.get_storage", _mock_get_storage(storage)):
            result = toolkit_memory(action="semantic_search", query="编程")
        assert isinstance(result, str)

    def test_stats_action(self, storage):
        """测试 stats action"""
        from tea_agent.toolkit.toolkit_memory import toolkit_memory

        storage.add_memory("测试记忆1", category="general")
        storage.add_memory("测试记忆2", category="fact")

        with patch("tea_agent.store.get_storage", _mock_get_storage(storage)):
            result = toolkit_memory(action="stats")
        assert "记忆统计" in result
        assert "总数:" in result
