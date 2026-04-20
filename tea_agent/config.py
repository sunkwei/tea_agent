"""
配置管理模块
从 $HOME/.tea_agent/config.yaml 加载配置，兼容旧环境变量 TEA_AGENT_XXX。

数据结构等价于 C++：
    struct ModelConfig {
        std::string api_key;    // API 访问密钥
        std::string api_url;    // API 访问 URL
        std::string model_name; // 模型名称
    };
    ModelConfig main_model;     // 主模型，完成主任务
    ModelConfig cheap_model;    // 便宜模型，用于摘要、压缩等
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

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

    @property
    def is_configured(self) -> bool:
        """检查配置是否完整"""
        return bool(self.api_key and self.api_url and self.model_name)


@dataclass
class AgentConfig:
    """Agent 全局配置"""
    main_model: ModelConfig = field(default_factory=ModelConfig)
    cheap_model: ModelConfig = field(default_factory=ModelConfig)


def _env_val(name: str) -> Optional[str]:
    """从环境变量取值，空字符串视为未设置"""
    v = os.environ.get(name, "")
    return v if v else None


def load_config(config_path: Optional[str] = None) -> AgentConfig:
    """
    加载配置。优先级：环境变量 > config.yaml > 默认空值。

    旧环境变量映射到 main_model：
        TEA_AGENT_KEY    -> main_model.api_key
        TEA_AGENT_URL    -> main_model.api_url
        TEA_AGENT_MODEL  -> main_model.model_name

    Args:
        config_path: 配置文件路径，默认 $HOME/.tea_agent/config.yaml

    Returns:
        AgentConfig 实例
    """
    cfg = AgentConfig()

    # 1. 先尝试从 YAML 加载
    yaml_path = config_path or str(Path.home() / ".tea_agent" / "config.yaml")
    if HAS_YAML and os.path.isfile(yaml_path):
        try:
            with open(yaml_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}

            # 解析 main_model
            main = data.get("main_model", {})
            if isinstance(main, dict):
                cfg.main_model.api_key = main.get("api_key", "") or cfg.main_model.api_key
                cfg.main_model.api_url = main.get("api_url", "") or cfg.main_model.api_url
                cfg.main_model.model_name = main.get("model_name", "") or cfg.main_model.model_name

            # 解析 cheap_model
            cheap = data.get("cheap_model", {})
            if isinstance(cheap, dict):
                cfg.cheap_model.api_key = cheap.get("api_key", "") or cfg.cheap_model.api_key
                cfg.cheap_model.api_url = cheap.get("api_url", "") or cfg.cheap_model.api_url
                cfg.cheap_model.model_name = cheap.get("model_name", "") or cfg.cheap_model.model_name
        except Exception:
            pass  # YAML 加载失败时静默回退

    # 2. 环境变量覆盖 main_model（兼容旧版）
    env_key = _env_val("TEA_AGENT_KEY")
    env_url = _env_val("TEA_AGENT_URL")
    env_model = _env_val("TEA_AGENT_MODEL")

    if env_key:
        cfg.main_model.api_key = env_key
    if env_url:
        cfg.main_model.api_url = env_url
    if env_model:
        cfg.main_model.model_name = env_model

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
    if cfg.main_model.is_configured:
        data["main_model"] = {
            "api_key": cfg.main_model.api_key,
            "api_url": cfg.main_model.api_url,
            "model_name": cfg.main_model.model_name,
        }
    if cfg.cheap_model.is_configured:
        data["cheap_model"] = {
            "api_key": cfg.cheap_model.api_key,
            "api_url": cfg.cheap_model.api_url,
            "model_name": cfg.cheap_model.model_name,
        }

    with open(yaml_path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    return yaml_path


def create_default_config(config_path: Optional[str] = None) -> str:
    """
    创建默认配置文件模板（带注释说明）。

    Args:
        config_path: 保存路径，默认 $HOME/.tea_agent/config.yaml

    Returns:
        实际创建的文件路径
    """
    yaml_path = config_path or str(Path.home() / ".tea_agent" / "config.yaml")
    ensure_config_dir()

    template = (
        "# Tea Agent 配置文件\n"
        "# 旧环境变量 TEA_AGENT_KEY/URL/MODEL 仍兼容，映射到 main_model\n\n"
        "main_model:\n"
        "  # API 访问密钥\n"
        "  api_key: \"\"\n"
        "  # API 访问地址（OpenAI 兼容格式）\n"
        "  api_url: \"\"\n"
        "  # 模型名称\n"
        "  model_name: \"\"\n\n"
        "cheap_model:\n"
        "  # 用于摘要、压缩等低成本任务的模型\n"
        "  api_key: \"\"\n"
        "  api_url: \"\"\n"
        "  model_name: \"\"\n"
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
