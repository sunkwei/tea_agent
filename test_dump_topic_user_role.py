import unittest
import os
import json
import tempfile
import shutil
from pathlib import Path
from datetime import datetime


class TestToolkitDumpTopicUserRole(unittest.TestCase):
    """测试 toolkit_dump_topic 工具函数 role='user' 模式的导出结果。"""

    def setUp(self):
        # 确保数据库路径存在
        self.db_path = Path.home() / ".tea_agent" / "chat_history.db"
        if not self.db_path.exists():
            self.skipTest(f"数据库文件不存在: {self.db_path}")

        # 记录测试前的 dump 目录状态
        self.base_dir = os.getcwd()
        self.date_str = datetime.now().strftime("%Y%m%d")
        self.dump_dir = os.path.join(self.base_dir, f"dump_{self.date_str}")

    def _run_dump_topic(self, role="user"):
        from tea_agent.toolkit.toolkit_dump_topic import toolkit_dump_topic
        return toolkit_dump_topic(role=role)

    def _find_exported_files(self):
        """获取 dump 目录下所有 md 文件。"""
        if not os.path.exists(self.dump_dir):
            return []
        return [f for f in os.listdir(self.dump_dir) if f.endswith(".md")]

    def test_role_user_returns_success(self):
        """测试 role='user' 返回成功状态。"""
        result = self._run_dump_topic(role="user")
        self.assertIn(result["status"], ["success", "info"])

        if result["status"] == "success":
            self.assertIn("成功导出", result["message"])
            self.assertIn("path", result)
            self.assertTrue(os.path.isdir(result["path"]))

    def test_role_user_export_mode_label(self):
        """测试导出文件头部标注'仅用户输入'。"""
        self._run_dump_topic(role="user")
        files = self._find_exported_files()

        if not files:
            self.skipTest("没有找到任何 topic，跳过内容校验")

        for filename in files:
            filepath = os.path.join(self.dump_dir, filename)
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()

            # 检查导出模式标注
            self.assertIn("仅用户输入", content,
                          f"{filename} 应标注'仅用户输入'")

    def test_role_user_contains_only_user_messages(self):
        """测试 role='user' 模式下不包含 AI 回复和工具调用链。"""
        self._run_dump_topic(role="user")
        files = self._find_exported_files()

        if not files:
            self.skipTest("没有找到任何 topic，跳过内容校验")

        for filename in files:
            filepath = os.path.join(self.dump_dir, filename)
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()

            # 不应包含 AI 回复行
            self.assertNotIn("**AI:**", content,
                             f"{filename} 不应包含 **AI:** 行")

            # 不应包含工具调用链
            self.assertNotIn("**工具调用链:**", content,
                             f"{filename} 不应包含 **工具调用链:** 行")

            # 不应包含工具调用/结果的标记
            self.assertNotIn("🔧 调用工具", content,
                             f"{filename} 不应包含工具调用记录")
            self.assertNotIn("📋 工具结果", content,
                             f"{filename} 不应包含工具结果记录")

    def test_role_user_preserves_user_messages(self):
        """测试 role='user' 模式下保留所有用户输入。"""
        self._run_dump_topic(role="user")
        files = self._find_exported_files()

        if not files:
            self.skipTest("没有找到任何 topic，跳过内容校验")

        for filename in files:
            filepath = os.path.join(self.dump_dir, filename)
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()

            # 至少包含一个用户输入
            user_msg_count = content.count("**用户:**")
            self.assertGreaterEqual(user_msg_count, 1,
                                    f"{filename} 应至少包含一条用户输入")

    def test_role_user_topic_file_naming(self):
        """测试导出的文件命名格式为 {topic_id}_{title}.md。"""
        self._run_dump_topic(role="user")
        files = self._find_exported_files()

        if not files:
            self.skipTest("没有找到任何 topic，跳过命名校验")

        for filename in files:
            # 文件名应以 topic_id_ 开头，以 .md 结尾
            self.assertTrue(filename.endswith(".md"),
                            f"{filename} 应以 .md 结尾")
            # 文件名中应包含下划线分隔的 topic_id 前缀
            parts = filename.split("_", 1)
            self.assertGreaterEqual(len(parts), 2,
                                    f"{filename} 格式应为 {{topic_id}}_{{title}}.md")


if __name__ == "__main__":
    unittest.main()
