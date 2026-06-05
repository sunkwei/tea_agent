"""
Config 测试套件 — ModelConfig / PathsConfig / AgentConfig / load_config / save_config。
"""

import os
from pathlib import Path

import pytest


class TestModelConfig:
    """ModelConfig 测试"""

    def test_default_not_configured(self):
        """测试: Default not configured"""
        from tea_agent.config import ModelConfig
        mc = ModelConfig()
        assert not mc.is_configured

    def test_configured_when_all_set(self):
        """测试: Configured when all set"""
        from tea_agent.config import ModelConfig
        mc = ModelConfig(api_key="sk-xxx", api_url="http://api.example.com/v1", model_name="test-model")
        assert mc.is_configured

    def test_not_configured_when_partial(self):
        """测试: Not configured when partial"""
        from tea_agent.config import ModelConfig
        mc = ModelConfig(api_key="sk-xxx", api_url="", model_name="test-model")
        assert not mc.is_configured

    def test_options_default_empty(self):
        """测试: Options default empty"""
        from tea_agent.config import ModelConfig
        mc = ModelConfig()
        assert mc.options == {}


class TestPathsConfig:
    """PathsConfig 路径解析测试"""

    def test_resolve_defaults(self):
        """默认值解析到 ~/.tea_agent"""
        from tea_agent.config import PathsConfig
        pc = PathsConfig()
        pc.resolve("/tmp")

        home = str(Path.home())
        assert pc.data_dir_abs == os.path.join(home, ".tea_agent")
        assert pc.db_path_abs == os.path.join(home, ".tea_agent", "chat_history.db")
        assert pc.toolkit_dir_abs == os.path.join(home, ".tea_agent", "toolkit")
        assert pc.kb_dir_abs == os.path.join(home, ".tea_agent", "kb")
        assert pc.skills_dir_abs == os.path.join(home, ".tea_agent", "skills")

    def test_resolve_relative_data_dir(self):
        """相对 data_dir 解析"""
        from tea_agent.config import PathsConfig
        import os as _os
        import tempfile, shutil as _shutil
        # 使用临时目录的绝对路径作为 config_dir，确保跨平台
        tmpd = tempfile.mkdtemp(prefix="tea_test_")
        config_dir = _os.path.join(tmpd, "config")
        _os.makedirs(config_dir, exist_ok=True)
        try:
            pc = PathsConfig(data_dir="my_agent_data")
            pc.resolve(config_dir)

            exp_data = _os.path.join(config_dir, "my_agent_data")
            assert pc.data_dir_abs == _os.path.abspath(exp_data)
            exp_db = _os.path.join(exp_data, "chat_history.db")
            assert pc.db_path_abs == _os.path.abspath(exp_db)
        finally:
            _shutil.rmtree(tmpd, ignore_errors=True)

    def test_resolve_absolute_data_dir(self):
        """绝对 data_dir 解析"""
        from tea_agent.config import PathsConfig
        import os as _os
        # 使用平台无关的绝对路径
        abs_dir = _os.path.abspath("/var/lib/tea_agent")
        pc = PathsConfig(data_dir=abs_dir)
        pc.resolve(_os.path.abspath("/tmp"))

        assert pc.data_dir_abs == abs_dir
        exp_db = _os.path.join(abs_dir, "chat_history.db")
        assert pc.db_path_abs == exp_db

    def test_resolve_tilde_expansion(self):
        """~ 展开为用户目录"""
        from tea_agent.config import PathsConfig
        pc = PathsConfig(data_dir="~/my_agent")
        pc.resolve("/tmp")

        home = str(Path.home())
        assert pc.data_dir_abs == os.path.join(home, "my_agent")

    def test_resolve_explicit_paths(self):
        """显式指定子路径"""
        from tea_agent.config import PathsConfig
        import os as _os
        pc = PathsConfig(
            db_path="my_db/agent.db",
            toolkit_dir="/opt/tools",
            kb_dir="~/.kb",
        )
        pc.resolve(_os.path.abspath("/tmp"))

        # db_path 相对于 data_dir（默认 ~/.tea_agent）
        home = str(Path.home())
        expected_db = _os.path.join(home, ".tea_agent", "my_db", "agent.db")
        assert pc.db_path_abs == expected_db
        # toolkit_dir 绝对路径
        assert pc.toolkit_dir_abs == _os.path.abspath("/opt/tools")
        # kb_dir 展开 ~
        expected_kb = _os.path.join(home, ".kb")
        assert pc.kb_dir_abs == expected_kb

    def test_property_accessors(self):
        """属性访问器可用"""
        from tea_agent.config import PathsConfig
        pc = PathsConfig()
        pc.resolve("/tmp")

        assert pc.data_dir_abs == pc.data_dir_abs
        assert pc.toolkit_dir_abs == pc.toolkit_dir_abs
        assert pc.skills_dir_abs == pc.skills_dir_abs


class TestMqttConfig:
    """MqttConfig 测试"""

    def test_default_disabled(self):
        """测试: Default disabled"""
        from tea_agent.config import MqttConfig
        mc = MqttConfig()
        assert not mc.enabled
        assert not mc.is_configured

    def test_configured_when_enabled(self):
        """测试: Configured when enabled"""
        from tea_agent.config import MqttConfig
        mc = MqttConfig(enabled=True, broker_host="localhost")
        assert mc.is_configured

    def test_not_configured_without_host(self):
        """测试: Not configured without host"""
        from tea_agent.config import MqttConfig
        mc = MqttConfig(enabled=True, broker_host="")
        assert not mc.is_configured


class TestEmbeddingConfig:
    """EmbeddingConfig 测试"""

    def test_default_not_configured(self):
        """测试: Default not configured"""
        from tea_agent.config import EmbeddingConfig
        ec = EmbeddingConfig()
        assert not ec.is_configured

    def test_configured_when_url_and_model_set(self):
        """测试: Configured when url and model set"""
        from tea_agent.config import EmbeddingConfig
        ec = EmbeddingConfig(api_url="http://localhost:11434/v1", model_name="bge-m3")
        assert ec.is_configured


class TestAgentConfig:
    """AgentConfig 运行时配置测试"""

    def test_default_values(self, default_agent_config):
        """验证默认值"""
        cfg = default_agent_config
        assert cfg.max_iterations == 50
        assert cfg.max_history == 10
        assert cfg.keep_turns == 5
        assert cfg.chat_page_size == 50
        assert cfg.memory_dedup_threshold == 0.3
        assert cfg.enable_thinking is True

    def test_get_method(self, default_agent_config):
        """get() 方法读取配置"""
        assert default_agent_config.get("max_iterations") == 50
        assert default_agent_config.get("no_such_key", "default") == "default"

    def test_set_valid_key(self, default_agent_config):
        """set() 有效键"""
        assert default_agent_config.set("max_iterations", 80)
        assert default_agent_config.max_iterations == 80

    def test_set_invalid_key(self, default_agent_config):
        """set() 无效键返回 False"""
        assert not default_agent_config.set("no_such_key", "value")

    def test_set_type_coercion(self, default_agent_config):
        """set() 自动类型转换"""
        assert default_agent_config.set("max_iterations", "60")
        assert default_agent_config.max_iterations == 60
        assert isinstance(default_agent_config.max_iterations, int)

    def test_set_bool_from_string(self, default_agent_config):
        """set() 布尔值转换"""
        assert default_agent_config.set("enable_thinking", "false")
        assert default_agent_config.enable_thinking is False

    def test_apply_changes(self, default_agent_config):
        """批量应用配置变更"""
        changes = [
            {"key": "max_iterations", "value": 100},
            {"key": "keep_turns", "value": 3},
            {"key": "bad_key", "value": "x"},
        ]
        results = default_agent_config.apply_changes(changes)
        assert results[0]["ok"] is True
        assert results[1]["ok"] is True
        assert results[2]["ok"] is False
        assert default_agent_config.max_iterations == 100
        assert default_agent_config.keep_turns == 3

    def test_to_dict(self, default_agent_config):
        """导出运行时配置字典"""
        d = default_agent_config.to_dict()
        assert isinstance(d, dict)
        assert d["max_iterations"] == 50
        assert "keep_turns" in d

    def test_reload_from_dict(self, default_agent_config):
        """从字典重新加载"""
        default_agent_config.reload_from_dict({"max_iterations": 200, "keep_turns": 10})
        assert default_agent_config.max_iterations == 200
        assert default_agent_config.keep_turns == 10


class TestLoadSaveConfig:
    """load_config / save_config 测试"""

    def test_load_default_no_file(self, tmp_yaml_config):
        """无配置文件时返回默认值"""
        # 临时目录中无 config.yaml，应返回默认配置
        with pytest.MonkeyPatch.context() as mp:
            # 强制使用临时路径
            from tea_agent.config import load_config, AgentConfig
            cfg = load_config(config_path=tmp_yaml_config)  # 文件不存在时返回默认值
            assert isinstance(cfg, AgentConfig)
            assert cfg.max_iterations == 50

    def test_load_and_save_roundtrip(self, tmp_yaml_config):
        """加载-保存-再加载 一致性"""
        from tea_agent.config import AgentConfig, save_config, load_config

        cfg1 = AgentConfig()
        cfg1.set("max_iterations", 123)
        cfg1.set("keep_turns", 7)
        cfg1.main_model.api_key = "sk-test"
        cfg1.main_model.api_url = "http://test/v1"
        cfg1.main_model.model_name = "test-model"

        # 先确保 yaml 可用
        import yaml
        save_config(cfg1, config_path=tmp_yaml_config)

        cfg2 = load_config(config_path=tmp_yaml_config)
        assert cfg2.max_iterations == 123
        assert cfg2.keep_turns == 7
        assert cfg2.main_model.api_key == "sk-test"
        assert cfg2.main_model.model_name == "test-model"

    def test_create_default_config(self, tmp_yaml_config):
        """创建默认配置文件"""
        from tea_agent.config import create_default_config
        path = create_default_config(config_path=tmp_yaml_config)

        assert os.path.exists(path)
        with open(path, "r") as f:
            content = f.read()

        assert "main_model:" in content
        assert "cheap_model:" in content
        assert "mqtt:" in content
        assert "paths:" in content
        assert "max_iterations: 50" in content
