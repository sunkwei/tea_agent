# version: 1.0.0

"""
测试记忆系统增强功能：
- AutoMemoryExtractor
- 向量/语义搜索已下线（TestVectorSearchRemoved 钉住其不再复活）
- toolkit_memory actions
"""

import contextlib
import os
import shutil
import tempfile
from unittest.mock import patch

import pytest


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
    with contextlib.suppress(Exception):
        s.close()
    time.sleep(0.2)
    with contextlib.suppress(Exception):
        shutil.rmtree(tmpdir, ignore_errors=True)


def _mock_get_storage(s):
    """返回一个 mock 函数，让 get_storage 返回测试 storage"""
    def _mock(db_path=""):
        return s
    return _mock


class TestAutoMemoryExtractor:
    """测试自动记忆提取器"""

    def test_extractor_init(self, storage):
        """测试提取器初始化"""
        from tea_agent.session_memory_component import AutoMemoryExtractor

        extractor = AutoMemoryExtractor(storage)
        assert extractor.storage == storage

    def test_get_unextracted_conversations(self, storage):
        """测试获取未提取的对话"""
        from tea_agent.session_memory_component import AutoMemoryExtractor

        topic_id = storage.create_topic("测试主题")
        storage.save_msg(topic_id, "用户消息", "AI回复", False)

        extractor = AutoMemoryExtractor(storage)
        conversations = extractor._get_unextracted_conversations(topic_id)

        assert len(conversations) == 1
        assert conversations[0]["user_msg"] == "用户消息"

    def test_merge_conversations(self, storage):
        """测试合并对话"""
        from tea_agent.session_memory_component import AutoMemoryExtractor

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
        from tea_agent.session_memory_component import AutoMemoryExtractor

        extractor = AutoMemoryExtractor(storage)

        sim1 = extractor._calculate_similarity("hello", "hello")
        assert sim1 == 1.0

        sim2 = extractor._calculate_similarity("abc", "xyz")
        assert sim2 < 0.5

        sim3 = extractor._calculate_similarity("hello world", "hello python")
        assert 0.3 < sim3 < 0.8

    def test_is_duplicate(self, storage):
        """测试重复检测"""
        from tea_agent.session_memory_component import AutoMemoryExtractor

        storage.add_memory("这是一条测试记忆", category="general")

        extractor = AutoMemoryExtractor(storage)
        assert extractor._is_duplicate("这是一条测试记忆", threshold=0.5) is True
        assert extractor._is_duplicate("完全不同的内容", threshold=0.9) is False


class TestVectorSearchRemoved:
    """向量/语义搜索已下线 —— 钉住「模块与 action 都不得复活」。

    原 TestSemanticSearch 覆盖 SemanticSearch 的索引/检索/余弦相似度。
    向量能力整体移除后，这些入口不应再存在（保留半套会造成「能调但结果恒空」）。
    """

    def test_semantic_search_module_removed(self):
        import importlib.util

        assert importlib.util.find_spec("tea_agent.store._semantic_search") is None

    def test_vector_store_module_removed(self):
        import importlib.util

        assert importlib.util.find_spec("tea_agent.store._vectors") is None

    def test_storage_has_no_vectors_attribute(self, storage):
        """Storage 不应再暴露 vectors 委派（公开属性也随之下线）。"""
        assert not hasattr(storage, "vectors")

    def test_storage_has_no_embedding_methods(self, storage):
        for name in ("store_embedding", "get_msg_embedding", "search_by_vector"):
            assert not hasattr(storage, name), f"Storage 不应再有 {name}"

    def test_toolkit_memory_rejects_semantic_search(self, storage):
        """已下线的 action 应明确报「未知 action」，而不是静默返回空结果。"""
        from tea_agent.toolkit.toolkit_memory import toolkit_memory

        with patch("tea_agent.store.get_storage", lambda: storage):
            out = toolkit_memory(action="semantic_search", query="任意")
        assert "未知 action" in out, out


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

    def test_stats_action(self, storage):
        """测试 stats action"""
        from tea_agent.toolkit.toolkit_memory import toolkit_memory

        storage.add_memory("测试记忆1", category="general")
        storage.add_memory("测试记忆2", category="fact")

        with patch("tea_agent.store.get_storage", _mock_get_storage(storage)):
            result = toolkit_memory(action="stats")
        assert "记忆统计" in result
        assert "总数:" in result
        # 向量索引统计行应随向量能力下线一起消失
        assert "向量索引" not in result


class TestJiebaRemoved:
    """jieba 分词器已移除 —— 关键词提取改纯正则，且不得被悄悄加回来。

    移除理由：``import jieba`` ≈0.5s、``initialize()`` ≈0.7s（构建前缀词典），
    是启动关键路径上的固定成本，却只服务记忆相关性打分/去重相似度两个用途；
    而这两处只需「哪几个词同时出现在两边」的粗粒度信号。
    """

    def test_no_jieba_import_in_memory_module(self):
        """源码层面不得再出现 jieba（防止依赖被顺手加回）。"""
        import inspect

        from tea_agent import memory

        src = inspect.getsource(memory)
        code_lines = [
            ln for ln in src.splitlines()
            if ln.strip().startswith(("import ", "from ")) and "jieba" in ln
        ]
        assert not code_lines, f"memory.py 不应再 import jieba: {code_lines}"

    def test_no_jieba_warmup_in_server(self):
        from tea_agent.server import server

        assert not hasattr(server, "_warmup_jieba")
        assert not hasattr(server, "_schedule_jieba_warmup")

    def test_chinese_bigram_extraction(self):
        import re as _re

        from tea_agent.memory import MemoryManager

        kws = MemoryManager._extract_keywords("重构存储层")
        for bg in ("重构", "构存", "存储", "储层"):
            assert bg in kws, f"缺少中文 bigram {bg}: {sorted(kws)}"

    def test_no_cross_punctuation_bigram(self):
        """按连续汉字段切分：跨标点不得产出假 bigram（「甲。乙」≠「甲乙」）。"""
        from tea_agent.memory import MemoryManager

        kws = MemoryManager._extract_keywords("甲。乙")
        assert "甲乙" not in kws, f"跨标点产生了假 bigram: {sorted(kws)}"

    def test_english_words_lowercased(self):
        from tea_agent.memory import MemoryManager

        kws = MemoryManager._extract_keywords("Refactor Storage Layer")
        assert "refactor" in kws and "storage" in kws
        # 3 字母以下不取（与旧实现一致）
        assert "of" not in kws

    def test_empty_and_ascii_only_inputs_safe(self):
        from tea_agent.memory import MemoryManager

        assert MemoryManager._extract_keywords("") == set()
        assert MemoryManager._extract_keywords("   ") == set()
        assert MemoryManager._extract_keywords("!!!，。") == set()
