"""
Agent 类测试 — 验证三种模式 + TeaAgent 工厂 + 生命周期。

覆盖:
- Agent(mode="lightweight") 无 storage
- Agent(mode="full") 有 storage
- Agent(mode="lite") 使用 LiteSession
- TeaAgent() 工厂函数
- 无效 mode 抛 ValueError
- 上下文管理器 __enter__/__exit__
- close() 清理资源
- 属性访问 (config, toolkit, sess, session, db)
"""

import os
import pytest


def _write_config(path, **overrides):
    """写最小测试配置，支持覆盖 db_path 等字段。"""
    db_path = overrides.get("db_path", ":memory:")
    content = f"""
main_model:
  api_key: "sk-test"
  api_url: "https://api.test.com"
  model_name: "test-model"
  options:
    supports_vision: false
    supports_reasoning: false
cheap_model:
  api_key: ""
  api_url: ""
  model_name: ""
paths:
  toolkit_dir: "./tools"
  kb_dir: "./kb"
  db_path: "{db_path}"
max_history: 10
max_iterations: 50
keep_turns: 5
max_tool_output: 131072
max_assistant_content: 131072
extra_iterations_on_continue: 5
memory_extraction_threshold: 2
"""
    with open(path, "w") as f:
        f.write(content)


class TestAgentCreation:
    """Agent 三种模式创建测试"""

    def test_lightweight_mode_creates_agent(self, tmp_yaml_config):
        """lightweight 模式：创建成功，无 storage"""
        from tea_agent.agent import Agent
        _write_config(tmp_yaml_config)

        agent = Agent(mode="lightweight", config_path=tmp_yaml_config)
        assert agent.mode == "lightweight"
        assert agent.db is None
        assert agent.toolkit is not None
        assert agent.sess is not None
        assert agent.config is not None
        agent.close()

    def test_full_mode_creates_agent_with_storage(self, tmp_db_path, tmp_yaml_config):
        """full 模式：创建成功，有 storage"""
        from tea_agent.agent import Agent
        os.makedirs(os.path.dirname(tmp_db_path) or ".", exist_ok=True)
        _write_config(tmp_yaml_config, db_path=tmp_db_path.replace("\\", "/"))

        agent = Agent(mode="full", config_path=tmp_yaml_config)
        assert agent.mode == "full"
        assert agent.db is not None
        assert agent.toolkit is not None
        assert agent.sess is not None
        agent.close()

    def test_lite_mode_creates_lite_session(self, tmp_yaml_config):
        """lite 模式：创建 LiteSession"""
        from tea_agent.agent import Agent
        _write_config(tmp_yaml_config)

        agent = Agent(mode="lite", config_path=tmp_yaml_config)
        assert agent.mode == "lite"
        assert agent.db is None
        assert agent.toolkit is not None
        assert agent.sess is not None
        agent.close()

    def test_invalid_mode_raises_valueerror(self, tmp_yaml_config):
        """无效 mode 应抛出 ValueError"""
        from tea_agent.agent import Agent
        _write_config(tmp_yaml_config)

        with pytest.raises(ValueError, match="mode 必须是"):
            Agent(mode="invalid", config_path=tmp_yaml_config)


class TestTeaAgentFactory:
    """TeaAgent 向后兼容工厂函数"""

    def test_tea_agent_returns_lightweight_agent(self, tmp_yaml_config):
        """TeaAgent() 返回 lightweight 模式的 Agent"""
        from tea_agent.agent import Agent, TeaAgent
        _write_config(tmp_yaml_config)

        agent = TeaAgent(config_path=tmp_yaml_config)
        assert isinstance(agent, Agent)
        assert agent.mode == "lightweight"
        agent.close()


class TestAgentLifecycle:
    """Agent 生命周期测试"""

    def test_context_manager(self, tmp_yaml_config):
        """__enter__ / __exit__ 上下文管理器"""
        from tea_agent.agent import Agent
        _write_config(tmp_yaml_config)

        with Agent(mode="lightweight", config_path=tmp_yaml_config) as agent:
            assert agent.sess is not None
        assert agent.sess is None
        assert agent.toolkit is None

    def test_close_cleans_up_resources(self, tmp_yaml_config):
        """close() 清理所有资源"""
        from tea_agent.agent import Agent
        _write_config(tmp_yaml_config)

        agent = Agent(mode="lightweight", config_path=tmp_yaml_config)
        assert agent.sess is not None
        agent.close()
        assert agent.sess is None
        assert agent.toolkit is None
        assert agent.db is None


class TestAgentProperties:
    """Agent 属性访问"""

    def test_config_property(self, tmp_yaml_config):
        """config 属性返回配置对象"""
        from tea_agent.agent import Agent
        _write_config(tmp_yaml_config)

        agent = Agent(mode="lightweight", config_path=tmp_yaml_config)
        assert agent.config is not None
        assert agent.config.main_model.model_name == "test-model"
        agent.close()

    def test_session_alias(self, tmp_yaml_config):
        """session 是 sess 的别名"""
        from tea_agent.agent import Agent
        _write_config(tmp_yaml_config)

        agent = Agent(mode="lightweight", config_path=tmp_yaml_config)
        assert agent.session is agent.sess
        agent.close()

    def test_current_topic_id_default(self, tmp_yaml_config):
        """current_topic_id 默认为空"""
        from tea_agent.agent import Agent
        _write_config(tmp_yaml_config)

        agent = Agent(mode="lightweight", config_path=tmp_yaml_config)
        assert agent.current_topic_id == ""
        agent.close()
