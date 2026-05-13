#!/usr/bin/env python3
"""Test three-level history management.

Tests:
  - Storage: Level 2 push, Level 3 read/write
  - Keyword relevance scoring (pure function)
  - load_history with new signature
"""

import unittest
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tea_agent.store import Storage
from tea_agent.basesession import BaseChatSession


class TestStorageLevel2(unittest.TestCase):
    """Test Level 2 storage operations."""

    def setUp(self):
        self.db = Storage(":memory:")
        self.tid = self.db.create_topic("Test Topic")

    def test_push_and_get_level2(self):
        self.db.push_to_level2(self.tid, "hello", "hi there")
        l2 = self.db.get_level2(self.tid)
        self.assertEqual(len(l2), 1)
        self.assertEqual(l2[0]["user"], "hello")
        self.assertEqual(l2[0]["assistant"], "hi there")

    def test_level2_max_5(self):
        for i in range(10):
            overflow = self.db.push_to_level2(self.tid, f"user{i}", f"ai{i}")
            if i >= 5:
                self.assertTrue(len(overflow) > 0)
        l2 = self.db.get_level2(self.tid)
        self.assertLessEqual(len(l2), 5)
        # Should have the most recent 5
        self.assertEqual(l2[-1]["user"], "user9")

    def test_level2_empty(self):
        l2 = self.db.get_level2(self.tid)
        self.assertEqual(l2, [])


class TestStorageLevel3(unittest.TestCase):
    """Test Level 3 summary storage."""

    def setUp(self):
        self.db = Storage(":memory:")
        self.tid = self.db.create_topic("Test")

    def test_semantic_summary(self):
        self.db.set_semantic_summary(self.tid, "- 偏好: python\n- 背景: web开发")
        result = self.db.get_semantic_summary(self.tid)
        self.assertIn("偏好", result)

    def test_tool_chain_summary(self):
        self.db.set_tool_chain_summary(self.tid, "- 任务: 修复bug\n- 工具: exec -> save")
        result = self.db.get_tool_chain_summary(self.tid)
        self.assertIn("exec", result)

    def test_empty_summaries(self):
        self.assertEqual(self.db.get_semantic_summary(self.tid), "")
        self.assertEqual(self.db.get_tool_chain_summary(self.tid), "")


class TestKeywordRelevance(unittest.TestCase):
    """Test keyword-based relevance scoring logic.
    
    Mirrors the logic in _filter_level2_by_relevance of OnlineToolSession.
    """

    def _key_words(self, text):
        import re
        cn = re.findall(r'[\u4e00-\u9fff]{2,}', text)
        en = re.findall(r'[a-zA-Z_]{3,}', text.lower())
        return set(cn + en)

    def _score(self, current, pair_user, pair_ai):
        k_current = self._key_words(current)
        k_pair = self._key_words(pair_user + " " + pair_ai)
        if not k_current or not k_pair:
            return 0.5
        intersection = k_current & k_pair
        union = k_current | k_pair
        return len(intersection) / max(len(union), 1)

    def test_high_relevance(self):
        score = self._score(
            "修复 thinkpad x1 屏幕闪烁问题",
            "thinkpad x1 屏幕出现闪屏",
            "这是屏幕驱动问题，需要更新驱动"
        )
        self.assertGreater(score, 0.15)

    def test_low_relevance(self):
        score = self._score(
            "如何配置 git ssh key",
            "今天天气真好，适合出去玩",
            "是的，阳光明媚"
        )
        self.assertLess(score, 0.10)

    def test_medium_relevance(self):
        score = self._score(
            "修复 zk_demuxer 的阻塞和卡顿问题",
            "zk_demuxer 的配置文件中日志级别设置",
            "需要修改 zk_demuxer 的配置文件"
        )
        # Overlapping on "zk_demuxer" but different topics
        self.assertGreater(score, 0.05)
        self.assertLess(score, 0.50)

    def test_exact_match(self):
        score = self._score(
            "hello world",
            "hello world",
            "hi there"
        )
        self.assertGreater(score, 0.3)


class TestLoadHistoryNewSignature(unittest.TestCase):
    """Test load_history with new 3-level parameters."""

    def setUp(self):
        # Create a minimal concrete subclass for testing
        class TestSession(BaseChatSession):
            def chat_stream(self, msg, callback):
                return "", False
        self.session = TestSession(
            model="test-model",
            system_prompt="test prompt",
        )

    def _make_conv(self, user_msg, ai_msg, rounds=None):
        conv = {
            "user_msg": user_msg,
            "ai_msg": ai_msg,
            "is_func_calling": bool(rounds),
            "rounds_json_parsed": rounds,
        }
        return conv

    def test_load_with_level2_and_l3(self):
        conv = self._make_conv("user1", "ai1")
        level2 = [{"user": "old_user", "assistant": "old_ai"}]
        sem = "- 偏好: 测试\n- 背景: 单元测试"
        tc = "- 任务: 测试工具链\n- 工具: exec"

        self.session.load_history(
            [conv], summary="",
            level2=level2, semantic_summary=sem, tool_chain_summary=tc,
        )

        self.assertEqual(self.session._semantic_summary, sem)
        self.assertEqual(self.session._tool_chain_summary, tc)
        self.assertEqual(len(self.session._level2), 1)
        self.assertEqual(self.session._level2[0]["user"], "old_user")

        # Level 1: the conversation should be in self.messages
        roles = [m["role"] for m in self.session.messages]
        self.assertIn("user", roles)
        self.assertIn("assistant", roles)

    def test_load_with_tool_chain(self):
        rounds = [
            {"role": "assistant", "content": None,
             "tool_calls": [{"id": "t1", "function": {"name": "toolkit_exec", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "t1", "content": "result ok"},
            {"role": "assistant", "content": "done"},
        ]
        conv = self._make_conv("run test", "done", rounds)
        self.session.load_history([conv], summary="")
        # Should have user + assistant(tool_call) + tool + assistant
        roles = [m["role"] for m in self.session.messages]
        self.assertIn("tool", roles)

    def test_empty_conversations(self):
        self.session.load_history([], summary="")
        self.assertEqual(len(self.session.messages), 1)  # only system
        self.assertEqual(self.session._level2, [])

    def test_legacy_summary_fallback(self):
        """Old code using only summary (no level2/l3) should still work."""
        conv = self._make_conv("user1", "ai1")
        self.session.load_history([conv], summary="old summary")
        # _history_summary is empty in new code; semantic_summary gets the summary
        self.assertEqual(self.session._semantic_summary, "old summary")


if __name__ == "__main__":
    unittest.main(verbosity=2)
