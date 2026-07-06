# version: 1.0.0

"""
SystemPromptManager 单元测试

测试范围:
- 初始化和默认提示词
- 版本管理
- 提示词进化
- 配置调整
"""

import contextlib
import os
import shutil
import tempfile
import time

import pytest


@pytest.fixture
def storage():
    """创建临时数据库"""
    from tea_agent.store import Storage

    tmpdir = tempfile.mkdtemp(prefix="tea_prompt_test_")
    db_path = os.path.join(tmpdir, "test.db")

    s = Storage(db_path)
    yield s
    time.sleep(0.3)
    with contextlib.suppress(Exception):
        s.close()
    time.sleep(0.2)
    with contextlib.suppress(Exception):
        shutil.rmtree(tmpdir, ignore_errors=True)


class TestSystemPromptManager:
    """SystemPromptManager 核心功能测试"""

    def test_init(self, storage):
        """测试初始化"""
        from tea_agent.prompt_manager import SystemPromptManager

        manager = SystemPromptManager(storage)
        assert manager.storage == storage
        assert manager._cheap_client is None
        assert manager._cheap_model == ""
        assert manager._initialized is False

    def test_initialize_creates_default(self, storage):
        """测试初始化创建默认提示词"""
        from tea_agent.prompt_manager import DEFAULT_SYSTEM_PROMPT, SystemPromptManager

        manager = SystemPromptManager(storage)
        prompt = manager.initialize()

        assert prompt == DEFAULT_SYSTEM_PROMPT
        assert manager.current_version == "1"
        assert manager._initialized is True

    def test_initialize_loads_existing(self, storage):
        """测试初始化加载已有提示词"""
        from tea_agent.prompt_manager import SystemPromptManager

        # 先添加一个提示词
        storage.add_system_prompt(content="Custom prompt", reason="test")

        manager = SystemPromptManager(storage)
        prompt = manager.initialize()

        assert prompt == "Custom prompt"
        assert manager.current_version == "1"  # 第一个版本

    def test_current_prompt_property(self, storage):
        """测试 current_prompt 属性"""
        from tea_agent.prompt_manager import SystemPromptManager

        manager = SystemPromptManager(storage)
        # 访问属性会触发初始化
        prompt = manager.current_prompt

        assert prompt is not None
        assert len(prompt) > 0
        assert manager._initialized is True

    def test_reload(self, storage):
        """测试重新加载"""
        from tea_agent.prompt_manager import SystemPromptManager

        manager = SystemPromptManager(storage)
        manager.initialize()

        # 添加新版本
        storage.add_system_prompt(content="Updated prompt", reason="update")

        # 重新加载
        prompt = manager.reload()
        assert prompt == "Updated prompt"
        assert manager.current_version == "2"

    def test_build_evolve_prompt(self, storage):
        """测试构建进化 prompt"""
        from tea_agent.prompt_manager import SystemPromptManager

        manager = SystemPromptManager(storage)
        manager.initialize()

        messages = manager.build_evolve_prompt(reflection_suggestion="Add more security checks")

        assert isinstance(messages, list)
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
        assert "Security checks" in messages[1]["content"] or "security" in messages[1]["content"].lower()

    def test_build_evolve_prompt_with_reflections(self, storage):
        """测试带反思建议构建进化 prompt"""
        from tea_agent.prompt_manager import SystemPromptManager

        manager = SystemPromptManager(storage)
        manager.initialize()

        # 添加反思记录
        storage.add_reflection(
            summary="Test reflection",
            suggestions=["Improve error handling", "Add more tests"]
        )

        messages = manager.build_evolve_prompt()

        assert isinstance(messages, list)
        # 检查反思建议被包含
        user_content = messages[1]["content"]
        assert "error handling" in user_content.lower() or "tests" in user_content.lower()

    def test_default_system_prompt_exists(self):
        """测试默认提示词存在"""
        from tea_agent.prompt_manager import DEFAULT_SYSTEM_PROMPT

        assert DEFAULT_SYSTEM_PROMPT is not None
        assert len(DEFAULT_SYSTEM_PROMPT) > 0
        assert "Agent" in DEFAULT_SYSTEM_PROMPT or "agent" in DEFAULT_SYSTEM_PROMPT.lower()

    def test_multiple_versions(self, storage):
        """测试多版本管理"""
        from tea_agent.prompt_manager import SystemPromptManager

        manager = SystemPromptManager(storage)
        manager.initialize()

        # 添加多个版本
        storage.add_system_prompt(content="Version 2 prompt", reason="v2")
        storage.add_system_prompt(content="Version 3 prompt", reason="v3")

        # 重新加载最新版本
        prompt = manager.reload()
        assert prompt == "Version 3 prompt"
        assert manager.current_version == "3"

    def test_version_history(self, storage):
        """测试版本历史"""
        from tea_agent.prompt_manager import SystemPromptManager

        manager = SystemPromptManager(storage)
        manager.initialize()

        # 添加多个版本
        storage.add_system_prompt(content="Version 2", reason="v2")
        storage.add_system_prompt(content="Version 3", reason="v3")

        # 获取历史
        history = storage.get_system_prompt_history(limit=10)

        assert len(history) >= 3
        # 验证版本顺序（最新在前）
        versions = [h["version"] for h in history]
        assert versions == ["3", "2", "1"]
