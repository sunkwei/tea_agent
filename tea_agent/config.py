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
# NOTE: 2026-04-30 16:22:42, self-evolved by tea_agent --- config.py添加List/Dict导入，修复NameError
from typing import Optional, Dict, Any, List

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


# NOTE: 2026-04-30 16:17:53, self-evolved by tea_agent --- AgentConfig增加运行时get/set/apply/reload方法，支持自我配置调优
# NOTE: 2026-05-04 08:30:13, self-evolved by tea_agent --- 添加 MqttConfig dataclass 并在 AgentConfig / load_config / save_config 中集成
@dataclass
class MqttConfig:
    """MQTT 连接配置"""
    enabled: bool = False
    broker_host: str = "localhost"
    broker_port: int = 1883
    username: str = ""
    password: str = ""
    topic_prefix: str = "tea"

    @property
    def is_configured(self) -> bool:
        """至少指定了 broker 地址才视为已配置"""
        return self.enabled and bool(self.broker_host)


@dataclass
class AgentConfig:
    """Agent 全局配置"""
    main_model: ModelConfig = field(default_factory=ModelConfig)
    cheap_model: ModelConfig = field(default_factory=ModelConfig)
    mqtt: MqttConfig = field(default_factory=MqttConfig)
    
    # 会话参数
    max_history: int = 10  # 最大历史消息数
    max_iterations: int = 50  # 最大工具调用迭代次数
    enable_thinking: bool = True  # 是否启用 thinking 功能
    
    # Token 优化参数
    keep_turns: int = 5  # 保留最近N轮完整对话，更早的对话自动摘要
    max_tool_output: int = 128 * 1024  # 工具输出截断字符数
    max_assistant_content: int = 128 * 1024  # 助手回复截断字符数

    # 交互与控制参数
    extra_iterations_on_continue: int = 5  # 续命时追加的工具调用轮数
# NOTE: 2026-04-30 14:36:14, self-evolved by tea_agent --- AppConfig增加memory_dedup_threshold字段
    memory_extraction_threshold: int = 2  # 触发记忆提取的最低未摘要消息数
# NOTE: 2026-04-30 14:38:53, self-evolved by tea_agent --- 去重阈值默认从0.5降到0.3，适配中文bigram相似度特点
    memory_dedup_threshold: float = 0.3  # 记忆去重相似度阈值 (0~1)，bigram Jaccard
# NOTE: 2026-04-30 09:47:45, self-evolved by tea_agent --- GUI单页加载对话数默认从30改为50，防止加载过多导致卡顿
    chat_page_size: int = 50  # GUI 单页加载的对话轮数（最多50条）

    # 2026-04-30 gen by deepseek-v4-pro, 运行时配置读写方法（支持自我调优）

    # 可运行时修改的配置键白名单
    _RUNTIME_CONFIG_KEYS = {
        "max_history", "max_iterations", "enable_thinking",
        "keep_turns", "max_tool_output", "max_assistant_content",
        "extra_iterations_on_continue", "memory_extraction_threshold",
        "memory_dedup_threshold", "chat_page_size",
    }

    # 类型映射
    _CONFIG_TYPES = {
        "max_history": int, "max_iterations": int, "enable_thinking": bool,
        "keep_turns": int, "max_tool_output": int, "max_assistant_content": int,
        "extra_iterations_on_continue": int, "memory_extraction_threshold": int,
        "memory_dedup_threshold": float, "chat_page_size": int,
    }

    def get(self, key: str, default=None):
        """读取配置值"""
        if hasattr(self, key):
            return getattr(self, key)
        return default

    def set(self, key: str, value) -> bool:
        """
        运行时修改配置值（仅白名单内的键可修改）。

        Args:
            key: 配置键
            value: 新值（会自动转换类型）

        Returns:
            是否成功
        """
        if key not in self._RUNTIME_CONFIG_KEYS:
            return False

        expected_type = self._CONFIG_TYPES.get(key)
        if expected_type:
            try:
                if expected_type == bool and isinstance(value, str):
                    value = value.lower() in ("true", "1", "yes", "on")
                else:
                    value = expected_type(value)
            except (ValueError, TypeError):
                return False

        setattr(self, key, value)
        return True

    def apply_changes(self, changes: List[Dict]) -> List[Dict]:
        """
        批量应用配置变更。

        Args:
            changes: [{"key": "max_iterations", "value": 60}, ...]

        Returns:
            每项变更的结果: [{"key": "...", "ok": bool, "error": ""}, ...]
        """
        results = []
        for ch in changes:
            key = ch.get("key", "")
            value = ch.get("value")
            ok = self.set(key, value)
            results.append({
                "key": key,
                "ok": ok,
                "new_value": str(getattr(self, key, "")) if ok else "",
                "error": "" if ok else f"无效的配置键: {key}" if key not in self._RUNTIME_CONFIG_KEYS else f"值类型错误: {value}",
            })
        return results

    def reload_from_dict(self, data: Dict):
        """从字典重新加载配置"""
        for key in self._RUNTIME_CONFIG_KEYS:
            if key in data:
                self.set(key, data[key])

    def to_dict(self) -> Dict:
        """导出运行时配置为字典"""
        return {key: getattr(self, key) for key in self._RUNTIME_CONFIG_KEYS if hasattr(self, key)}


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

# NOTE: 2026-05-04 08:30:28, self-evolved by tea_agent --- load_config() 中解析 mqtt 配置块
            # 加载 MQTT 配置
            mqtt_data = data.get("mqtt", {})
            if isinstance(mqtt_data, dict):
                cfg.mqtt.enabled = bool(mqtt_data.get("enabled", cfg.mqtt.enabled))
                cfg.mqtt.broker_host = str(mqtt_data.get("broker_host", cfg.mqtt.broker_host))
                cfg.mqtt.broker_port = int(mqtt_data.get("broker_port", cfg.mqtt.broker_port))
                cfg.mqtt.username = str(mqtt_data.get("username", cfg.mqtt.username))
                cfg.mqtt.password = str(mqtt_data.get("password", cfg.mqtt.password))
                cfg.mqtt.topic_prefix = str(mqtt_data.get("topic_prefix", cfg.mqtt.topic_prefix))

            # 加载会话参数
            cfg.max_history = int(data.get("max_history", cfg.max_history))
            cfg.max_iterations = int(data.get("max_iterations", cfg.max_iterations))
            cfg.enable_thinking = bool(data.get("enable_thinking", cfg.enable_thinking))
            
            # 加载 Token 优化参数
            cfg.keep_turns = int(data.get("keep_turns", cfg.keep_turns))
            cfg.max_tool_output = int(data.get("max_tool_output", cfg.max_tool_output))
            cfg.max_assistant_content = int(data.get("max_assistant_content", cfg.max_assistant_content))

            # 加载交互与控制参数
            cfg.extra_iterations_on_continue = int(data.get("extra_iterations_on_continue", cfg.extra_iterations_on_continue))
# NOTE: 2026-04-30 14:36:23, self-evolved by tea_agent --- load_config解析memory_dedup_threshold
            cfg.memory_extraction_threshold = int(data.get("memory_extraction_threshold", cfg.memory_extraction_threshold))
            cfg.memory_dedup_threshold = float(data.get("memory_dedup_threshold", cfg.memory_dedup_threshold))
            cfg.chat_page_size = int(data.get("chat_page_size", cfg.chat_page_size))
            
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
    
# NOTE: 2026-05-04 08:30:38, self-evolved by tea_agent --- save_config() 中保存 mqtt 配置
    # 保存 MQTT 配置
    data["mqtt"] = {
        "enabled": cfg.mqtt.enabled,
        "broker_host": cfg.mqtt.broker_host,
        "broker_port": cfg.mqtt.broker_port,
        "username": cfg.mqtt.username,
        "password": cfg.mqtt.password,
        "topic_prefix": cfg.mqtt.topic_prefix,
    }

    # 保存会话参数
    data["max_history"] = cfg.max_history
    data["max_iterations"] = cfg.max_iterations
    data["enable_thinking"] = cfg.enable_thinking
    
    # 保存 Token 优化参数
    data["keep_turns"] = cfg.keep_turns
    data["max_tool_output"] = cfg.max_tool_output
    data["max_assistant_content"] = cfg.max_assistant_content

    # 保存交互与控制参数
    data["extra_iterations_on_continue"] = cfg.extra_iterations_on_continue
# NOTE: 2026-04-30 14:36:30, self-evolved by tea_agent --- save_config保存memory_dedup_threshold
    data["memory_extraction_threshold"] = cfg.memory_extraction_threshold
    data["memory_dedup_threshold"] = cfg.memory_dedup_threshold
    data["chat_page_size"] = cfg.chat_page_size
    
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
        "# 主模型配置（用于核心对话、代码生成等）\n"
        "main_model:\n"
        "  api_key: \"\"\n"
        "  api_url: \"\"\n"
        "  model_name: \"\"\n"
        "  options:  # 可选参数，如 {extra_body: {thinking: {type: enabled}}}\n"
        "    key: value\n\n"
# NOTE: 2026-05-04 08:30:52, self-evolved by tea_agent --- create_default_config() 模板中增加 mqtt 配置块
        "# 便宜模型配置（用于摘要生成、信息压缩等场景）\n"
        "cheap_model:\n"
        "  api_key: \"\"\n"
        "  api_url: \"\"\n"
        "  model_name: \"\"\n"
        "  options: {}\n\n"
        "# ==================== MQTT 配置 ====================\n"
        "# tea_agent 可作为 MQTT client 注册到 broker，与外部客户端交互\n"
        "mqtt:\n"
        "  enabled: false\n"
        "  broker_host: \"localhost\"\n"
        "  broker_port: 1883\n"
        "  username: \"\"\n"
        "  password: \"\"\n"
        "  topic_prefix: \"tea\"\n\n"
        "# ==================== 会话参数 ====================\n"
        "# 最大历史消息数（保留的对话历史条数）\n"
        "max_history: 10\n\n"
        "# 最大工具调用迭代次数（单次对话中最多允许的工具调用循环数）\n"
        "max_iterations: 50\n\n"
        "# 是否启用 thinking 功能（模型思考过程展示）\n"
        "enable_thinking: true\n\n"
        "# ==================== Token 优化参数 ====================\n"
        "# 保留最近 N 轮完整对话，更早的对话自动摘要（使用 cheap_model）\n"
        "keep_turns: 5\n\n"
        "# 工具输出截断字符数（超过此长度的工具结果会被截断）\n"
        "max_tool_output: 131072  # 128KB\n\n"
        "# 助手回复截断字符数（超过此长度的助手回复会被截断）\n"
        "max_assistant_content: 131072  # 128KB\n\n"
        "# ==================== 交互与控制参数 ====================\n"
        "# 工具调用达到上限后续命时追加的轮数\n"
        "extra_iterations_on_continue: 5\n\n"
        "# 触发自动记忆提取的最少未摘要消息数\n"
# NOTE: 2026-04-30 14:36:36, self-evolved by tea_agent --- create_default_config模板增加memory_dedup_threshold
        "memory_extraction_threshold: 2\n\n"
        "# 记忆去重相似度阈值，超过此值视为重复并合并(0~1)\n"
        "memory_dedup_threshold: 0.5\n\n"
# NOTE: 2026-04-30 09:47:45, self-evolved by tea_agent --- create_default_config模板同步更新chat_page_size默认值30→50
        "# GUI 单页加载的最大对话轮数（超过则省略更早的对话）\n"
        "chat_page_size: 50\n"
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
