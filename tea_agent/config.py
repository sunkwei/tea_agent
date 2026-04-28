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
    
    # 会话参数
    max_history: int = 10  # 最大历史消息数
    max_iterations: int = 50  # 最大工具调用迭代次数
    enable_thinking: bool = True  # 是否启用 thinking 功能
    
    # Token 优化参数
    keep_turns: int = 2  # 保留最近N轮完整对话，更早的对话自动摘要
    max_tool_output: int = 128 * 1024  # 工具输出截断字符数
    max_assistant_content: int = 128 * 1024  # 助手回复截断字符数
    
    # 记忆参数
    memory_inject_limit: int = 8  # 记忆注入条数上限
    memory_extract_rounds: int = 6  # 记忆提取窗口轮数
    memory_extract_threshold: int = 4  # 记忆提取消息数阈值


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

            # 加载模型配置
            for m_type in ["main_model", "cheap_model"]:
                m_data = data.get(m_type, {})
                if isinstance(m_data, dict):
                    target = cfg.main_model if m_type == "main_model" else cfg.cheap_model
                    target.api_key = m_data.get("api_key", "")
                    target.api_url = m_data.get("api_url", "")
                    target.model_name = m_data.get("model_name", "")
                    target.options = m_data.get("options", {})

            # 加载会话参数
            cfg.max_history = int(data.get("max_history", cfg.max_history))
            cfg.max_iterations = int(data.get("max_iterations", cfg.max_iterations))
            cfg.enable_thinking = bool(data.get("enable_thinking", cfg.enable_thinking))
            
            # 加载 Token 优化参数
            cfg.keep_turns = int(data.get("keep_turns", cfg.keep_turns))
            cfg.max_tool_output = int(data.get("max_tool_output", cfg.max_tool_output))
            cfg.max_assistant_content = int(data.get("max_assistant_content", cfg.max_assistant_content))
            
            # 加载记忆参数
            cfg.memory_inject_limit = int(data.get("memory_inject_limit", cfg.memory_inject_limit))
            cfg.memory_extract_rounds = int(data.get("memory_extract_rounds", cfg.memory_extract_rounds))
            cfg.memory_extract_threshold = int(data.get("memory_extract_threshold", cfg.memory_extract_threshold))
            
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
    
    # 保存模型配置
    for m_type in ["main_model", "cheap_model"]:
        target = cfg.main_model if m_type == "main_model" else cfg.cheap_model
        if target.is_configured:
            m_data = {
                "api_key": target.api_key,
                "api_url": target.api_url,
                "model_name": target.model_name,
            }
            if target.options:
                m_data["options"] = target.options
            data[m_type] = m_data
    
    # 保存会话参数
    data["max_history"] = cfg.max_history
    data["max_iterations"] = cfg.max_iterations
    data["enable_thinking"] = cfg.enable_thinking
    
    # 保存 Token 优化参数
    data["keep_turns"] = cfg.keep_turns
    data["max_tool_output"] = cfg.max_tool_output
    data["max_assistant_content"] = cfg.max_assistant_content
    
    # 保存记忆参数
    data["memory_inject_limit"] = cfg.memory_inject_limit
    data["memory_extract_rounds"] = cfg.memory_extract_rounds
    data["memory_extract_threshold"] = cfg.memory_extract_threshold

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
        "# 主模型配置（用于核心对话、代码生成、记忆提取等）\n"
        "main_model:\n"
        "  api_key: \"\"\n"
        "  api_url: \"\"\n"
        "  model_name: \"\"\n"
        "  options:  # 可选参数，如 {extra_body: {thinking: {type: enabled}}}\n"
        "    key: value\n\n"
        "# 便宜模型配置（用于摘要生成、信息压缩等场景）\n"
        "cheap_model:\n"
        "  api_key: \"\"\n"
        "  api_url: \"\"\n"
        "  model_name: \"\"\n"
        "  options: {}\n\n"
        "# ==================== 会话参数 ====================\n"
        "# 最大历史消息数（保留的对话历史条数）\n"
        "max_history: 10\n\n"
        "# 最大工具调用迭代次数（单次对话中最多允许的工具调用循环数）\n"
        "max_iterations: 50\n\n"
        "# 是否启用 thinking 功能（模型思考过程展示）\n"
        "enable_thinking: true\n\n"
        "# ==================== Token 优化参数 ====================\n"
        "# 保留最近 N 轮完整对话，更早的对话自动摘要（使用 cheap_model）\n"
        "keep_turns: 3\n\n"
        "# 工具输出截断字符数（超过此长度的工具结果会被截断）\n"
        "max_tool_output: 131072  # 128KB\n\n"
        "# 助手回复截断字符数（超过此长度的助手回复会被截断）\n"
        "max_assistant_content: 131072  # 128KB\n\n"
        "# ==================== 记忆参数 ====================\n"
        "# 记忆注入条数上限（会话开始时注入的记忆数量）\n"
        "memory_inject_limit: 8\n\n"
        "# 记忆提取窗口轮数（从此数量的最近对话中提取记忆）\n"
        "memory_extract_rounds: 6\n\n"
        "# 记忆提取消息数阈值（达到此数量才触发记忆提取）\n"
        "memory_extract_threshold: 4\n"
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
