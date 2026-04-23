"""
配置管理模块
从 $HOME/.tea_agent/config.yaml 加载配置，如果不存在则回退到 tea_agent/config.yaml。

数据结构等价于 C++：
    struct ModelConfig {
        std::string api_key;    // API 访问密钥
        std::string api_url;    // API 访问 URL
        std::string model_name; // 模型名称
        std::map<std::string, std::string> options; // 模型额外参数
    };
    ModelConfig main_model;     // 主模型，完成主任务
    ModelConfig cheap_model;    // 便宜模型，用于摘要、压缩等
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Dict, Any

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False


@dataclass
class ModelConfig:
    """单个 LLM 模型配置"""
    api_key: str = ""
    api_url: str = ""
    model_name: str = ""
    options: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_configured(self) -> bool:
        """检查配置是否完整"""
        return bool(self.api_key and self.api_url and self.model_name)


@dataclass
class AgentConfig:
    """Agent 全局配置"""
    main_model: ModelConfig = field(default_factory=ModelConfig)
    cheap_model: ModelConfig = field(default_factory=ModelConfig)


def load_config(config_path: Optional[str] = None) -> AgentConfig:
    """
    加载配置。优先读取 $HOME/.tea_agent/config.yaml，不存在时回退到 tea_agent/config.yaml。

    Args:
        config_path: 配置文件路径，默认自动查找

    Returns:
        AgentConfig 实例
    """
    cfg = AgentConfig()
    yaml_path: Optional[str] = None

    if config_path:
        yaml_path = config_path
    else:
        # 优先级1: $HOME/.tea_agent/config.yaml
        default_path = str(Path.home() / ".tea_agent" / "config.yaml")
        if os.path.isfile(default_path):
            yaml_path = default_path
        else:
            # 优先级2: tea_agent/config.yaml (相对于本文件所在目录)
            fallback_path = str(Path(__file__).parent / "config.yaml")
            if os.path.isfile(fallback_path):
                yaml_path = fallback_path

    if HAS_YAML and yaml_path and os.path.isfile(yaml_path):
        try:
            with open(yaml_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            
            for m_type in ["main_model", "cheap_model"]:
                m_data = data.get(m_type, {})
                if isinstance(m_data, dict):
                    target = cfg.main_model if m_type == "main_model" else cfg.cheap_model
                    target.api_key = m_data.get("api_key", "")
                    target.api_url = m_data.get("api_url", "")
                    target.model_name = m_data.get("model_name", "")
                    target.options = m_data.get("options", {})
        except Exception:
            pass  # 加载失败时使用默认空配置
            
    return cfg


def ensure_config_dir() -> Path:
    """确保 $HOME/.tea_agent 目录存在，返回路径"""
    cfg_dir = Path.home() / ".tea_agent"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    return cfg_dir


def save_config(cfg: AgentConfig, config_path: Optional[str] = None) -> str:
    """
    保存配置到 YAML 文件。

    Args:
        cfg: AgentConfig 实例
        config_path: 保存路径，默认 $HOME/.tea_agent/config.yaml

    Returns:
        实际保存的文件路径
    """
    if not HAS_YAML:
        raise RuntimeError("需要安装 pyyaml: pip install pyyaml")

    yaml_path = config_path or str(Path.home() / ".tea_agent" / "config.yaml")
    ensure_config_dir()

    data = {}
    for m_type in ["main_model", "cheap_model"]:
        target = cfg.main_model if m_type == "main_model" else cfg.cheap_model
        if target.is_configured:
            m_data = {
                "api_key": target.api_key,
                "api_url": target.api_url,
                "model_name": target.model_name,
            }
            data[m_type] = m_data

    with open(yaml_path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    return yaml_path


def create_default_config(config_path: Optional[str] = None) -> str:
    """
    创建默认配置文件模板。

    Args:
        config_path: 保存路径，默认 $HOME/.tea_agent/config.yaml

    Returns:
        实际创建的文件路径
    """
    yaml_path = config_path or str(Path.home() / ".tea_agent" / "config.yaml")
    ensure_config_dir()

    template = (
        "# Tea Agent 配置文件\n\n"
        "main_model:\n"
        "  api_key: \"\"\n"
        "  api_url: \"\"\n"
        "  model_name: \"\"\n"
        "  options:  # 可选参数，如 {extra_body: {thinking: {type: enabled}}}\n"
        "    key: value\n\n"
        "cheap_model:\n"
        "  api_key: \"\"\n"
        "  api_url: \"\"\n"
        "  model_name: \"\"\n"
        "  options: {}\n"
    )

    with open(yaml_path, "w", encoding="utf-8") as f:
        f.write(template)

    return yaml_path


# 全局单例缓存
_config_cache: Optional[AgentConfig] = None


def get_config(reload: bool = False) -> AgentConfig:
    """
    获取全局配置单例。

    Args:
        reload: 强制重新加载

    Returns:
        AgentConfig 实例
    """
    global _config_cache
    if _config_cache is None or reload:
        _config_cache = load_config()
    return _config_cache
