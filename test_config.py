import unittest
import os
from pathlib import Path
import yaml
import tea_agent.config as config_module
from tea_agent.config import (
    load_config, 
    save_config, 
    create_default_config, 
    get_config, 
    AgentConfig, 
    ModelConfig,
    ensure_config_dir
)

class TestConfigModule(unittest.TestCase):
    def setUp(self):
        # 使用一个临时的配置文件路径进行测试，避免污染用户的真实配置
        self.test_config_dir = Path.home() / ".tea_agent_test"
        self.test_config_path = self.test_config_dir / "config.yaml"
        self.test_config_dir.mkdir(parents=True, exist_ok=True)
        
        # 确保测试前环境干净
        if self.test_config_path.exists():
            self.test_config_path.unlink()
            
        # 重置全局单例缓存
        config_module._config_cache = None

    def tearDown(self):
        # 清理测试数据
        if self.test_config_path.exists():
            self.test_config_path.unlink()
        if self.test_config_dir.exists():
            try:
                self.test_config_dir.rmdir()
            except:
                pass
        
        # 重置全局单例缓存
        config_module._config_cache = None

    def test_create_default_config(self):
        """测试创建默认配置"""
        created_path = create_default_config(str(self.test_config_path))
        self.assertEqual(str(self.test_config_path), created_path)
        self.assertTrue(self.test_config_path.exists())
        
        with open(self.test_config_path, "r", encoding="utf-8") as f:
            content = f.read()
            self.assertIn("main_model:", content)
            self.assertIn("cheap_model:", content)

    def test_save_and_load_config(self):
        """测试保存和加载配置"""
        cfg = AgentConfig(
            main_model=ModelConfig(
                api_key="test_key_main",
                api_url="https://api.test.com/v1",
                model_name="gpt-4"
            ),
            cheap_model=ModelConfig(
                api_key="test_key_cheap",
                api_url="https://api.test.com/v1",
                model_name="gpt-3.5-turbo"
            )
        )
        
        # 保存
        save_config(cfg, str(self.test_config_path))
        self.assertTrue(self.test_config_path.int_exists := self.test_config_path.exists())
        
        # 加载并验证
        loaded_cfg = load_config(str(self.test_config_path))
        self.assertEqual(loaded_cfg.main_model.api_key, "test_key_main")
        self.assertEqual(loaded_cfg.main_model.model_name, "gpt-4")
        self.assertEqual(loaded_cfg.cheap_model.api_key, "test_key_cheap")
        self.assertEqual(loaded_cfg.cheap_model.api_url, "https://api.test.com/v1")

    def test_load_non_existent_file(self):
        """测试加载不存在的文件应返回默认配置"""
        fake_path = str(self.test_config_dir / "non_existent.yaml")
        cfg = load_config(fake_path)
        self.assertEqual(cfg.main_model.api_key, "")
        self.assertEqual(cfg.cheap_model.model_name, "")

    def test_get_config_singleton(self):
        """测试单例 get_config"""
        # 预设一个实例
        test_cfg_instance = AgentConfig(main_model=ModelConfig(api_key="singleton_test"))
        
        # 手动注入缓存，绕过 get_config 内部的 load_config() 逻辑
        config_module._config_cache = test_cfg_instance
        
        c1 = get_config()
        c2 = get_config()
        
        self.assertIs(c1, c2)
        self.assertEqual(c2.main_model.api_key, "singleton_test")

def run_config_report():
    """执行配置读取并以 Markdown 格式输出内容"""
    print("\n# Current Agent Configuration Report\n")
    try:
        from tea_agent.config import get_config
        cfg = get_config()
        
        print("## Main Model")
        print(f"- **API Key**: `{cfg.main_model.api_key[:8] if cfg.main_model.api_key else 'N/A'}...`")
        print(f"- **API URL**: `{cfg.main_model.api_url if cfg.main_model.api_url else 'N/A'}`")
        print(f"- **Model Name**: `{cfg.main_model.model_name if cfg.main_model.model_name else 'N/A'}`")
        print(f"- **Status**: {'✅ Configured' if cfg.main_model.is_configured else '❌ Not Configured'}")
        
        print("\n## Cheap Model")
        print(f"- **API Key**: `{cfg.cheap_model.api_key[:8] if cfg.cheap_model.api_key else 'N/A'}...`")
        print(f"- **API URL**: `{cfg.cheap_model.api_url if cfg.cheap_model.api_url else 'N/A'}`")
        print(f"- **Model Name**: `{cfg.cheap_model.model_name if cfg.cheap_model.model_name else 'N/A'}`")
        print(f"- **Status**: {'✅ Configured' if cfg.cheap_model.is_configured else '❌ Not Configured'}")
        
    except Exception as e:
        print(f"Error generating report: {e}")

if __name__ == "__main__":
    # Run tests
    suite = unittest.TestLoader().loadTestsFromTestCase(TestConfigModule)
    runner = unittest        # Error here
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    # If tests passed, run report
    if result.wasSuccessful():
        run_config_report()
    else:
        print("\nTests failed. Skipping report.")
        exit(1)
