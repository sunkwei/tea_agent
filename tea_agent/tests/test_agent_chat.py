# version: 1.0.0

"""
Agent.chat() 集成测试

测试范围:
- lightweight 模式对话
- full 模式对话
- lite 模式对话
- 流式回调
- 错误处理
"""

import contextlib
import os
import shutil
import tempfile
import time
from unittest.mock import MagicMock, patch

import pytest


@contextlib.contextmanager
def _mock_openai_client():
    """patch 所有 OpenAI 客户端构造点，yield 同一个 mock 类供测试设置 return_value。

    为什么不能只 ``patch("openai.OpenAI")``：``onlinesession`` / ``litesession``
    在 **模块 import 时** 就执行了 ``from openai import OpenAI``，模块内的名字已绑定
    为原类；之后再 patch ``openai.OpenAI`` 不会影响它们，测试于是用**真实客户端**
    发请求、白等几十秒网络重试（用例本身只断言本地消息记录，所以"看起来还过"）。

    这里把三处构造点指向同一个 mock，使 ``MockOpenAI.return_value = mock_client``
    对所有调用点生效。
    """
    with patch("openai.OpenAI") as mock_cls, \
         patch("tea_agent.onlinesession.OpenAI", new=mock_cls), \
         patch("tea_agent.litesession.OpenAI", new=mock_cls):
        yield mock_cls


@pytest.fixture
def tmp_dir():
    """创建临时目录"""
    tmpdir = tempfile.mkdtemp(prefix="tea_agent_chat_test_")
    yield tmpdir
    time.sleep(0.3)
    with contextlib.suppress(Exception):
        shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.fixture
def tmp_yaml_config(tmp_dir):
    """创建临时配置文件"""
    config_path = os.path.join(tmp_dir, "config.yaml")
    return config_path


@pytest.fixture
def tmp_db_path(tmp_dir):
    """获取临时数据库路径"""
    return os.path.join(tmp_dir, "test.db")


def _write_config(path, **overrides):
    """写最小测试配置"""
    db_path = overrides.get("db_path", ":memory:")
    toolkit_dir = overrides.get("toolkit_dir", "./tools")
    kb_dir = overrides.get("kb_dir", "./kb")

    import yaml as _yaml
    config = {
        "main_model": {
            "api_key": "sk-test",
            "api_url": "https://api.test.com/v1",
            "model_name": "test-model",
            "options": {
                "supports_vision": False,
                "supports_reasoning": False,
            },
        },
        "cheap_model": {
            "api_key": "",
            "api_url": "",
            "model_name": "",
        },
        "paths": {
            "toolkit_dir": toolkit_dir,
            "kb_dir": kb_dir,
            "db_path": db_path,
        },
        "max_history": 10,
        "max_iterations": 50,
        "keep_turns": 5,
        "max_tool_output": 131072,
        "max_assistant_content": 131072,
        "memory_extraction_threshold": 2,
    }
    with open(path, "w", encoding="utf-8") as f:
        _yaml.dump(config, f, allow_unicode=True, default_flow_style=False)


class TestAgentChatIntegration:
    """Agent.chat() 集成测试"""

    def test_lightweight_chat_mock(self, tmp_yaml_config):
        """测试 lightweight 模式对话（mock API）"""
        from tea_agent.agent import Agent

        _write_config(tmp_yaml_config)

        # Mock OpenAI 客户端
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Hello! I'm a test response."
        mock_response.choices[0].message.tool_calls = None
        mock_response.usage.total_tokens = 100
        mock_response.usage.prompt_tokens = 50
        mock_response.usage.completion_tokens = 50

        with _mock_openai_client() as MockOpenAI:  # noqa: N806
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = mock_response
            MockOpenAI.return_value = mock_client

            agent = Agent(mode="lightweight", config_path=tmp_yaml_config)
            result = agent.chat("Hello")

            assert isinstance(result, list)
            assert len(result) >= 1
            assert result[0]["role"] == "user"
            assert result[0]["content"] == "Hello"

            agent.close()

    def test_full_mode_chat_mock(self, tmp_yaml_config, tmp_db_path):
        """测试 full 模式对话（mock API）"""
        from tea_agent.agent import Agent

        os.makedirs(os.path.dirname(tmp_db_path) or ".", exist_ok=True)
        _write_config(tmp_yaml_config, db_path=tmp_db_path.replace("\\", "/"))

        # Mock OpenAI 客户端
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Full mode response"
        mock_response.choices[0].message.tool_calls = None
        mock_response.usage.total_tokens = 100
        mock_response.usage.prompt_tokens = 50
        mock_response.usage.completion_tokens = 50

        with _mock_openai_client() as MockOpenAI:  # noqa: N806
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = mock_response
            MockOpenAI.return_value = mock_client

            agent = Agent(mode="full", config_path=tmp_yaml_config)
            # 创建测试主题
            topic_id = agent._db.create_topic("Test Topic")

            result = agent.chat("Test message", topic_id=topic_id)

            assert isinstance(result, list)
            assert len(result) >= 1

            agent.close()

    def test_chat_with_callback(self, tmp_yaml_config):
        """测试带回调的对话"""
        from tea_agent.agent import Agent

        _write_config(tmp_yaml_config)

        # Mock OpenAI 客户端
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Response"
        mock_response.choices[0].message.tool_calls = None
        mock_response.usage.total_tokens = 100
        mock_response.usage.prompt_tokens = 50
        mock_response.usage.completion_tokens = 50

        callback_data = []

        def callback(data):
            callback_data.append(data)

        with _mock_openai_client() as MockOpenAI:  # noqa: N806
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = mock_response
            MockOpenAI.return_value = mock_client

            agent = Agent(mode="lightweight", config_path=tmp_yaml_config, callback=callback)
            agent.chat("Hello")

            # 验证回调被调用
            assert len(callback_data) >= 1
            assert any(d.get("type") == "done" for d in callback_data)

            agent.close()

    def test_chat_generating_lock(self, tmp_yaml_config):
        """测试生成锁（防止并发生成）"""
        from tea_agent.agent import Agent

        _write_config(tmp_yaml_config)

        with _mock_openai_client() as MockOpenAI:  # noqa: N806
            mock_client = MagicMock()
            MockOpenAI.return_value = mock_client

            agent = Agent(mode="lightweight", config_path=tmp_yaml_config)
            agent._generating = True  # 模拟正在生成

            with pytest.raises(RuntimeError, match="正在生成中"):
                agent.chat("Hello")

            agent._generating = False
            agent.close()

    def test_chat_lite_mode_mock(self, tmp_yaml_config):
        """测试 lite 模式对话（mock API）"""
        from tea_agent.agent import Agent

        _write_config(tmp_yaml_config)

        # Mock OpenAI 客户端
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Lite response"
        mock_response.choices[0].message.tool_calls = None
        mock_response.usage.total_tokens = 50
        mock_response.usage.prompt_tokens = 25
        mock_response.usage.completion_tokens = 25

        with _mock_openai_client() as MockOpenAI:  # noqa: N806
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = mock_response
            MockOpenAI.return_value = mock_client

            agent = Agent(mode="lite", config_path=tmp_yaml_config)
            result = agent.chat("Hello")

            # Lite 模式返回 dict
            assert isinstance(result, dict)
            assert "assistant" in result or "response" in result

            agent.close()

    def test_post_chat_pipeline_mock(self, tmp_yaml_config, tmp_db_path):
        """测试后处理流水线"""
        from tea_agent.agent import Agent

        os.makedirs(os.path.dirname(tmp_db_path) or ".", exist_ok=True)
        _write_config(tmp_yaml_config, db_path=tmp_db_path.replace("\\", "/"))

        with _mock_openai_client() as MockOpenAI:  # noqa: N806
            mock_client = MagicMock()
            MockOpenAI.return_value = mock_client

            agent = Agent(mode="full", config_path=tmp_yaml_config)
            topic_id = agent._db.create_topic("Pipeline Test")

            # 测试 _post_chat_pipeline
            agent._post_chat_pipeline(
                ai_msg="AI response",
                used_tools=True,
                user_msg="User message",
                topic_id=topic_id
            )

            # 验证对话已保存
            conversations = agent._db.get_conversations(topic_id, limit=5)
            assert len(conversations) >= 1

            agent.close()

    def test_load_topic_history_mock(self, tmp_yaml_config, tmp_db_path):
        """测试加载历史"""
        from tea_agent.agent import Agent

        os.makedirs(os.path.dirname(tmp_db_path) or ".", exist_ok=True)
        _write_config(tmp_yaml_config, db_path=tmp_db_path.replace("\\", "/"))

        with _mock_openai_client() as MockOpenAI:  # noqa: N806
            mock_client = MagicMock()
            MockOpenAI.return_value = mock_client

            agent = Agent(mode="full", config_path=tmp_yaml_config)
            topic_id = agent._db.create_topic("History Test")

            # 添加一些对话
            agent._db.save_msg(topic_id, "msg1", "response1", False)
            agent._db.save_msg(topic_id, "msg2", "response2", False)

            # 加载历史
            agent.load_topic_history(topic_id)

            # 验证历史已加载
            assert len(agent._sess.messages) >= 1

            agent.close()


class TestAgentChatErrorHandling:
    """Agent.chat() 错误处理测试"""

    def test_chat_api_error(self, tmp_yaml_config):
        """测试 API 错误处理：Agent 捕获异常并返回包含 error 的结果"""
        from tea_agent.agent import Agent

        _write_config(tmp_yaml_config)

        with _mock_openai_client() as MockOpenAI:  # noqa: N806
            mock_client = MagicMock()
            mock_client.chat.completions.create.side_effect = Exception("API Error")
            MockOpenAI.return_value = mock_client

            agent = Agent(mode="lightweight", config_path=tmp_yaml_config)

            # lightweight 模式下 API 异常会被 session 捕获，返回含 error 的 dict
            result = agent.chat("Hello")
            assert isinstance(result, list | dict)

            agent.close()

    def test_chat_invalid_config(self):
        """测试无效配置"""
        from tea_agent.agent import Agent

        with pytest.raises(FileNotFoundError):
            Agent(mode="lightweight", config_path="/nonexistent/config.yaml")
