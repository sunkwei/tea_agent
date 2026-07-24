"""
配置管理模块 — 加载/保存/运行时修改 Agent 配置。

配置来源（优先级）：
1. 显式指定路径
2. $HOME/.tea_agent/config.yaml
3. tea_agent/config.yaml（包内置回退）
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import yaml

    HAS_YAML: bool = True
except ImportError:
    HAS_YAML = False

__all__ = [
    "ModelConfig",
    "PathsConfig",
    "EmbeddingConfig",
    "AgentConfig",
    "load_config",
    "save_config",
    "get_config",
    "create_default_config",
    "ensure_config_dir",
    "set_active_config_path",
    "get_active_config_path",
]


@dataclass
class ModelConfig:
    """单个 LLM 模型配置"""

    api_key: str = ""
    api_url: str = ""
    model_name: str = ""
    options: dict[str, Any] = field(default_factory=dict)
    temperature: float = 0.7
    max_tokens: int = 4096
    max_context_tokens: int = 0
    top_p: float = 0.9

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key and self.api_url and self.model_name)

    @property
    def supports_vision(self) -> bool:
        return self.options.get("supports_vision", False)


@dataclass
class PathsConfig:
    """路径配置。相对路径相对于 config.yaml 所在目录。"""

    data_dir: str = ""
    db_path: str = ""
    toolkit_dir: str = ""
    kb_dir: str = ""
    skills_dir: str = ""
    _data_dir_abs: str = ""
    _db_path_abs: str = ""
    _toolkit_dir_abs: str = ""
    _kb_dir_abs: str = ""

    def resolve(self, config_dir: str) -> None:
        """解析所有路径为绝对路径。"""
        default_root = str(Path.home() / ".tea_agent")

        if self.data_dir:
            expanded_data = os.path.expanduser(self.data_dir)
            if os.path.isabs(expanded_data):
                self._data_dir_abs = os.path.abspath(expanded_data)
            else:
                self._data_dir_abs = os.path.abspath(
                    os.path.join(config_dir, expanded_data)
                )
        else:
            self._data_dir_abs = default_root

        def _resolve(value: str, default_rel: str) -> str:
            if not value:
                return os.path.join(self._data_dir_abs, default_rel)
            expanded = os.path.expanduser(value)
            if os.path.isabs(expanded):
                return os.path.abspath(expanded)
            return os.path.abspath(os.path.join(self._data_dir_abs, expanded))

        self._db_path_abs = _resolve(self.db_path, "chat_history.db")
        self._toolkit_dir_abs = _resolve(self.toolkit_dir, "toolkit")
        self._kb_dir_abs = _resolve(self.kb_dir, "kb")

    @property
    def db_path_abs(self) -> str:
        return self._db_path_abs

    @property
    def toolkit_dir_abs(self) -> str:
        return self._toolkit_dir_abs

    @property
    def kb_dir_abs(self) -> str:
        return self._kb_dir_abs

    @property
    def data_dir_abs(self) -> str:
        return self._data_dir_abs


@dataclass
class EmbeddingConfig:
    """文本向量模型配置。"""

    api_url: str = ""
    model_name: str = ""
    api_key: str = ""
    dimension: int = 0

    @property
    def is_configured(self) -> bool:
        return bool(self.api_url and self.model_name)


@dataclass
class AgentConfig:
    """Agent 全局配置"""

    main_model: ModelConfig = field(default_factory=ModelConfig)
    cheap_model: ModelConfig = field(default_factory=ModelConfig)
    embedding: EmbeddingConfig = field(default_factory=EmbeddingConfig)
    paths: PathsConfig = field(default_factory=PathsConfig)
    mode_params: dict[str, dict[str, Any]] = field(default_factory=dict)

    def get_effective_params(
        self, model_type: str = "main", mode: str = "mixed"
    ) -> dict[str, Any]:
        """获取最终生效的模型推理参数。mode_params 覆盖 model 默认值。"""
        model_cfg = self.main_model if model_type == "main" else self.cheap_model
        params = {
            "temperature": model_cfg.temperature,
            "max_tokens": model_cfg.max_tokens,
            "top_p": model_cfg.top_p,
        }
        # 模式覆盖
        overrides = self.mode_params.get(mode, {})
        for k in ("temperature", "max_tokens", "top_p"):
            if k in overrides:
                params[k] = overrides[k]
        return params

    # 会话参数
    max_history: int = 10  # 最大历史消息数
    max_iterations: int = 50  # 最大工具调用迭代次数
    enable_thinking: bool = True  # 是否启用 thinking 功能
    thinking_strength: float = 0.7  # 思考强度 0.0-1.0（0=最弱/最省token, 1=最强/最深度思考）
    reasoning_effort: str = "auto"  # 推理努力程度: "auto"/"low"/"medium"/"high"，映射到 OpenAI reasoning_effort

    # Token 优化参数
    keep_turns: int = 5  # 保留最近N轮完整对话，更早的对话自动摘要
    max_tool_output: int = 128 * 1024  # 工具输出截断字符数
    max_assistant_content: int = 128 * 1024  # 助手回复截断字符数

    # 交互与控制参数
    extra_iterations_on_continue: int = 5  # 续命时追加的工具调用轮数
    memory_extraction_threshold: int = 2  # 触发记忆提取的最低未摘要消息数
    memory_dedup_threshold: float = 0.3  # 记忆去重相似度阈值 (0~1)，bigram Jaccard
    chat_page_size: int = 50  # GUI 单页加载的对话轮数（最多50条）
    history_l2_max: int = 8  # L2最大保留轮数，超出时溢出 keep=5 条至 L3 摘要
    history_l3_batch: int = 5  # L3摘要批处理：每次溢出至少 N 条才触发便宜模型摘要
    font_size: int = 16  # HtmlFrame 字体大小（px）
    app_font_size: int = (
        12  # App GUI 字体大小（pt，控制 label/input/treeview 等原生组件）
    )

    # 可运行时修改的配置键白名单
    _RUNTIME_CONFIG_KEYS = {
        "max_history",
        "max_iterations",
        "enable_thinking",
        "thinking_strength",
        "reasoning_effort",
        "keep_turns",
        "max_tool_output",
        "max_assistant_content",
        "extra_iterations_on_continue",
        "memory_extraction_threshold",
        "memory_dedup_threshold",
        "chat_page_size",
        "history_l2_max",
        "history_l3_batch",  # 2026-05-20 gen by Tea Agent, L2/L3分层压缩
        "font_size",  # HtmlFrame 字体大小
        "app_font_size",  # App GUI 字体大小
    }

    # 类型映射
    _CONFIG_TYPES = {
        "max_history": int,
        "max_iterations": int,
        "enable_thinking": bool,
        "thinking_strength": float,
        "reasoning_effort": str,
        "keep_turns": int,
        "max_tool_output": int,
        "max_assistant_content": int,
        "extra_iterations_on_continue": int,
        "memory_extraction_threshold": int,
        "memory_dedup_threshold": float,
        "chat_page_size": int,
        "history_l2_max": int,
        "history_l3_batch": int,
        "font_size": int,
        "app_font_size": int,
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
                value = (
                    value.lower() in ("true", "1", "yes", "on")
                    if expected_type is bool and isinstance(value, str)
                    else expected_type(value)
                )
            except (ValueError, TypeError):
                return False

        setattr(self, key, value)
        return True

    def apply_changes(self, changes: list[dict]) -> list[dict]:
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
            results.append(
                {
                    "key": key,
                    "ok": ok,
                    "new_value": str(getattr(self, key, "")) if ok else "",
                    "error": (
                        ""
                        if ok
                        else (
                            f"无效的配置键: {key}"
                            if key not in self._RUNTIME_CONFIG_KEYS
                            else f"值类型错误: {value}"
                        )
                    ),
                }
            )
        return results

    def reload_from_dict(self, data: dict):
        """从字典重新加载配置"""
        for key in self._RUNTIME_CONFIG_KEYS:
            if key in data:
                self.set(key, data[key])

    def to_dict(self) -> dict:
        """导出运行时配置为字典"""
        return {
            key: getattr(self, key)
            for key in self._RUNTIME_CONFIG_KEYS
            if hasattr(self, key)
        }

    def to_full_dict(self) -> dict:
        """导出所有配置为字典（含模型/路径等完整配置）"""
        data = {}
        _prepare_model_data(self, data)
        _prepare_embedding_data(self, data)
        _prepare_paths_data(self, data)
        _prepare_session_data(self, data)
        _prepare_token_data(self, data)
        _prepare_control_data(self, data)
        return data


_last_config_path = None
_config_lock = threading.Lock()

# ── 全局活跃配置路径（跨 GUI/Web/CLI 共享） ──
_active_config_path: str | None = None


def set_active_config_path(config_path: str) -> None:
    """设置全局活跃配置路径（GUI/Web 切换配置时调用）。"""
    global _active_config_path
    with _config_lock:
        _active_config_path = os.path.abspath(config_path)


def get_active_config_path() -> str | None:
    """获取全局活跃配置路径。优先返回此值，None 时回退到 _last_config_path。"""
    with _config_lock:
        return _active_config_path or _last_config_path


def load_config(config_path: str | None = None) -> AgentConfig:
    """
    加载配置。优先读取 $HOME/.tea_agent/config.yaml，不存在时回退到 tea_agent/config.yaml。

    Args:
        config_path: 配置文件路径，默认自动查找

    Returns:
        AgentConfig 实例
    """
    global _last_config_path, _config_cache

    # 步骤1: 解析配置文件路径
    yaml_path = resolve_config_path(config_path)

    # 步骤2: 创建默认配置
    cfg = AgentConfig()

    # 步骤3: 如果找到配置文件，加载并解析
    if HAS_YAML and yaml_path and os.path.isfile(yaml_path):
        try:
            data = _load_yaml_data(yaml_path)
            if data:
                # 解析模型配置
                _parse_model_configs(cfg, data)

                # 解析嵌入模型配置
                _parse_embedding_config(cfg, data)

                # 解析模式参数
                _parse_mode_params(cfg, data)

                # 解析路径配置
                _parse_paths_config(cfg, data, yaml_path)

                # 解析会话参数
                _parse_session_params(cfg, data)

                # 解析Token优化参数
                _parse_token_params(cfg, data)

                # 解析交互控制参数
                _parse_control_params(cfg, data)
        except Exception:
            pass  # 加载失败时使用默认空配置

    # 步骤4: 更新全局缓存
    _update_config_cache(cfg, yaml_path)

    return cfg


def resolve_config_path(config_path: str | None = None) -> str | None:
    """解析配置文件路径（公共函数，供 agent/server 复用）。

    优先级: config_path > _last_config_path > ~/.tea_agent/config.yaml > 内置默认

    Args:
        config_path: 指定的配置文件路径

    Returns:
        实际使用的配置文件路径，找不到返回 None
    """
    global _last_config_path

    with _config_lock:
        if config_path is None:
            config_path = _last_config_path
        else:
            _last_config_path = config_path

    if config_path:
        return config_path

    # 优先级1: $HOME/.tea_agent/config.yaml
    default_path = str(Path.home() / ".tea_agent" / "config.yaml")
    if os.path.isfile(default_path):
        return default_path

    # 优先级2: tea_agent/config.yaml (相对于本文件所在目录)
    fallback_path = str(Path(__file__).parent / "config.yaml")
    if os.path.isfile(fallback_path):
        return fallback_path

    return None


def _load_yaml_data(yaml_path: str) -> dict | None:
    """加载YAML配置文件数据。

    Args:
        yaml_path: YAML文件路径

    Returns:
        解析后的字典数据，如果加载失败返回None
    """
    if not HAS_YAML or not os.path.isfile(yaml_path):
        return None

    try:
        with open(yaml_path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return None


def _parse_model_configs(cfg: AgentConfig, data: dict) -> None:
    """解析模型配置。

    Args:
        cfg: AgentConfig实例
        data: 配置数据字典
    """
    for m_type in ["main_model", "cheap_model"]:
        m_data = data.get(m_type, {})
        if not isinstance(m_data, dict):
            continue

        target = cfg.main_model if m_type == "main_model" else cfg.cheap_model
        target.api_key = m_data.get("api_key", "")
        target.api_url = m_data.get("api_url", "")
        target.model_name = m_data.get("model_name", "")
        target.options = m_data.get("options", {})
        target.temperature = float(m_data.get("temperature", target.temperature))
        target.max_tokens = int(m_data.get("max_tokens", target.max_tokens))
        target.top_p = float(m_data.get("top_p", target.top_p))


def _parse_embedding_config(cfg: AgentConfig, data: dict) -> None:
    """解析嵌入模型配置。

    Args:
        cfg: AgentConfig实例
        data: 配置数据字典
    """
    emb_data = data.get("embedding_model", {})
    if not isinstance(emb_data, dict):
        return

    cfg.embedding.api_url = str(emb_data.get("api_url", cfg.embedding.api_url))
    cfg.embedding.model_name = str(emb_data.get("model_name", cfg.embedding.model_name))
    cfg.embedding.api_key = str(emb_data.get("api_key", cfg.embedding.api_key))
    cfg.embedding.dimension = int(emb_data.get("dimension", cfg.embedding.dimension))


def _parse_mode_params(cfg: AgentConfig, data: dict) -> None:
    """解析模式参数配置。

    Args:
        cfg: AgentConfig实例
        data: 配置数据字典
    """
    mp_data = data.get("mode_params", {})
    if not isinstance(mp_data, dict):
        return

    for mode_name in ("pragmatic", "creative", "mixed"):
        mode_cfg = mp_data.get(mode_name, {})
        if isinstance(mode_cfg, dict):
            cfg.mode_params[mode_name] = {
                k: v
                for k, v in mode_cfg.items()
                if k in ("temperature", "max_tokens", "top_p")
            }


def _parse_paths_config(cfg: AgentConfig, data: dict, yaml_path: str) -> None:
    """解析路径配置。

    Args:
        cfg: AgentConfig实例
        data: 配置数据字典
        yaml_path: 配置文件路径，用于解析相对路径
    """
    paths_data = data.get("paths", {})
    if isinstance(paths_data, dict):
        cfg.paths.data_dir = str(paths_data.get("data_dir", cfg.paths.data_dir))
        cfg.paths.db_path = str(paths_data.get("db_path", cfg.paths.db_path))
        cfg.paths.toolkit_dir = str(paths_data.get("toolkit_dir", cfg.paths.toolkit_dir))
        cfg.paths.kb_dir = str(paths_data.get("kb_dir", cfg.paths.kb_dir))
        cfg.paths.skills_dir = str(paths_data.get("skills_dir", cfg.paths.skills_dir))

    # 解析路径：相对于 config.yaml 所在目录
    if yaml_path:
        cfg.paths.resolve(os.path.dirname(os.path.abspath(yaml_path)))


def _parse_session_params(cfg: AgentConfig, data: dict) -> None:
    """解析会话参数。

    Args:
        cfg: AgentConfig实例
        data: 配置数据字典
    """
    cfg.max_history = int(data.get("max_history", cfg.max_history))
    cfg.max_iterations = int(data.get("max_iterations", cfg.max_iterations))
    val = data.get("enable_thinking", cfg.enable_thinking)
    if isinstance(val, str):
        cfg.enable_thinking = val.lower() in ("true", "1", "yes")
    else:
        cfg.enable_thinking = bool(val)
    cfg.thinking_strength = float(data.get("thinking_strength", cfg.thinking_strength))
    cfg.reasoning_effort = str(data.get("reasoning_effort", cfg.reasoning_effort))


def _parse_token_params(cfg: AgentConfig, data: dict) -> None:
    """解析Token优化参数。

    Args:
        cfg: AgentConfig实例
        data: 配置数据字典
    """
    cfg.keep_turns = int(data.get("keep_turns", cfg.keep_turns))
    cfg.max_tool_output = int(data.get("max_tool_output", cfg.max_tool_output))
    cfg.max_assistant_content = int(
        data.get("max_assistant_content", cfg.max_assistant_content)
    )


def _parse_control_params(cfg: AgentConfig, data: dict) -> None:
    """解析交互控制参数。

    Args:
        cfg: AgentConfig实例
        data: 配置数据字典
    """
    cfg.extra_iterations_on_continue = int(
        data.get("extra_iterations_on_continue", cfg.extra_iterations_on_continue)
    )
    cfg.memory_extraction_threshold = int(
        data.get("memory_extraction_threshold", cfg.memory_extraction_threshold)
    )
    cfg.memory_dedup_threshold = float(
        data.get("memory_dedup_threshold", cfg.memory_dedup_threshold)
    )
    cfg.chat_page_size = int(data.get("chat_page_size", cfg.chat_page_size))
    cfg.history_l2_max = int(data.get("history_l2_max", cfg.history_l2_max))
    cfg.history_l3_batch = int(data.get("history_l3_batch", cfg.history_l3_batch))
    cfg.font_size = int(data.get("font_size", cfg.font_size))
    cfg.app_font_size = int(data.get("app_font_size", cfg.app_font_size))


def _update_config_cache(cfg: AgentConfig, yaml_path: str | None) -> None:
    """更新全局配置缓存。

    Args:
        cfg: AgentConfig实例
        yaml_path: 配置文件路径
    """
    global _config_cache, _active_config_path

    with _config_lock:
        _config_cache = cfg
        if yaml_path:
            _active_config_path = os.path.abspath(yaml_path)


def ensure_config_dir() -> Path:
    """确保数据目录存在（从 config 读取，回退 ~/.tea_agent），返回路径"""
    try:
        cfg = get_config()
        cfg_dir = Path(cfg.paths.data_dir_abs)
    except Exception:
        cfg_dir = Path.home() / ".tea_agent"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    return cfg_dir


def save_config(cfg: AgentConfig, config_path: str | None = None) -> str:
    """
    保存配置到 YAML 文件。

    Args:
        cfg: AgentConfig 实例
        config_path: 保存路径，默认 $HOME/.tea_agent/config.yaml

    Returns:
        实际保存的文件路径
    """
    global _last_config_path

    # 步骤1: 解析保存路径
    yaml_path = _resolve_save_path(config_path)

    # 步骤2: 确保配置目录存在
    ensure_config_dir()

    # 步骤3: 准备配置数据
    data = _prepare_config_data(cfg)

    # 步骤4: 写入YAML文件
    _write_yaml_file(yaml_path, data)

    return yaml_path


def _resolve_save_path(config_path: str | None) -> str:
    """解析配置文件保存路径。

    Args:
        config_path: 指定的保存路径

    Returns:
        实际保存路径
    """
    global _last_config_path

    return (
        config_path
        or _last_config_path
        or str(Path.home() / ".tea_agent" / "config.yaml")
    )


def _prepare_config_data(cfg: AgentConfig) -> dict:
    """准备配置数据字典。

    Args:
        cfg: AgentConfig实例

    Returns:
        配置数据字典
    """
    data = {}

    # 准备模型配置
    _prepare_model_data(cfg, data)

    # 准备嵌入模型配置
    _prepare_embedding_data(cfg, data)

    # 准备模式参数
    if cfg.mode_params:
        data["mode_params"] = cfg.mode_params

    # 准备路径配置
    _prepare_paths_data(cfg, data)

    # 准备会话参数
    _prepare_session_data(cfg, data)

    # 准备Token优化参数
    _prepare_token_data(cfg, data)

    # 准备交互控制参数
    _prepare_control_data(cfg, data)

    return data


def _prepare_model_data(cfg: AgentConfig, data: dict) -> None:
    """准备模型配置数据。

    Args:
        cfg: AgentConfig实例
        data: 配置数据字典（会被修改）
    """
    for m_type in ["main_model", "cheap_model"]:
        target = cfg.main_model if m_type == "main_model" else cfg.cheap_model
        if target.is_configured:
            m_data = {
                "api_key": target.api_key,
                "api_url": target.api_url,
                "model_name": target.model_name,
            }
            if target.temperature != 0.7:
                m_data["temperature"] = target.temperature
            if target.max_tokens != 4096:
                m_data["max_tokens"] = target.max_tokens
            if target.top_p != 0.9:
                m_data["top_p"] = target.top_p
            if target.options:
                m_data["options"] = target.options
            data[m_type] = m_data


def _prepare_embedding_data(cfg: AgentConfig, data: dict) -> None:
    """准备嵌入模型配置数据。

    Args:
        cfg: AgentConfig实例
        data: 配置数据字典（会被修改）
    """
    data["embedding_model"] = {
        "api_url": cfg.embedding.api_url,
        "model_name": cfg.embedding.model_name,
        "api_key": cfg.embedding.api_key,
        "dimension": cfg.embedding.dimension,
    }


def _prepare_paths_data(cfg: AgentConfig, data: dict) -> None:
    """准备路径配置数据。

    Args:
        cfg: AgentConfig实例
        data: 配置数据字典（会被修改）
    """
    data["paths"] = {
        "data_dir": cfg.paths.data_dir,
        "db_path": cfg.paths.db_path,
        "toolkit_dir": cfg.paths.toolkit_dir,
        "kb_dir": cfg.paths.kb_dir,
        "skills_dir": cfg.paths.skills_dir,
    }


def _prepare_session_data(cfg: AgentConfig, data: dict) -> None:
    """准备会话参数数据。

    Args:
        cfg: AgentConfig实例
        data: 配置数据字典（会被修改）
    """
    data["max_history"] = cfg.max_history
    data["max_iterations"] = cfg.max_iterations
    data["enable_thinking"] = cfg.enable_thinking
    data["thinking_strength"] = cfg.thinking_strength
    data["reasoning_effort"] = cfg.reasoning_effort


def _prepare_token_data(cfg: AgentConfig, data: dict) -> None:
    """准备Token优化参数数据。

    Args:
        cfg: AgentConfig实例
        data: 配置数据字典（会被修改）
    """
    data["keep_turns"] = cfg.keep_turns
    data["max_tool_output"] = cfg.max_tool_output
    data["max_assistant_content"] = cfg.max_assistant_content


def _prepare_control_data(cfg: AgentConfig, data: dict) -> None:
    """准备交互控制参数数据。

    Args:
        cfg: AgentConfig实例
        data: 配置数据字典（会被修改）
    """
    data["extra_iterations_on_continue"] = cfg.extra_iterations_on_continue
    data["memory_extraction_threshold"] = cfg.memory_extraction_threshold
    data["memory_dedup_threshold"] = cfg.memory_dedup_threshold
    data["chat_page_size"] = cfg.chat_page_size
    data["history_l2_max"] = cfg.history_l2_max
    data["history_l3_batch"] = cfg.history_l3_batch


def _write_yaml_file(yaml_path: str, data: dict) -> None:
    """写入YAML配置文件。

    Args:
        yaml_path: 文件路径
        data: 要写入的数据
    """
    with open(yaml_path, "w", encoding="utf-8") as f:
        yaml.dump(
            data, f, default_flow_style=False, allow_unicode=True, sort_keys=False
        )


def create_default_config(config_path: str | None = None) -> str:
    """
    创建默认配置文件模板。

    Args:
        config_path: 保存路径，默认 $HOME/.tea_agent/config.yaml

    Returns:
        实际创建的文件路径
    """
    # 步骤1: 解析保存路径
    yaml_path = config_path or str(Path.home() / ".tea_agent" / "config.yaml")

    # 步骤2: 确保配置目录存在
    ensure_config_dir()

    # 步骤3: 生成配置模板
    template = _generate_config_template()

    # 步骤4: 写入模板文件
    _write_template_file(yaml_path, template)

    return yaml_path


def _generate_config_template() -> str:
    """生成配置文件模板内容。

    Returns:
        配置文件模板字符串
    """
    return (
        "# Tea Agent 配置文件\n\n"
        "# 主模型配置（用于核心对话、代码生成等）\n"
        "main_model:\n"
        '  api_key: ""\n'
        '  api_url: ""\n'
        '  model_name: ""\n'
        "  temperature: 0.7      # 温度 0~2，越高越随机发散\n"
        "  max_tokens: 4096      # 最大输出 token 数\n"
        "  top_p: 0.9            # 核采样阈值\n"
        "  options:  # 可选参数，如 {extra_body: {thinking: {type: enabled}}}\n"
        "    key: value\n\n"
        "# 便宜模型配置（用于摘要生成、信息压缩等场景，建议低 temperature）\n"
        "cheap_model:\n"
        '  api_key: ""\n'
        '  api_url: ""\n'
        '  model_name: ""\n'
        "  temperature: 0.3      # 摘要/反思需要确定性，建议 0.2~0.5\n"
        "  max_tokens: 1024      # 摘要通常较短\n"
        "  top_p: 0.9\n"
        "  options: {}\n\n"
        "# ──────────────────── 模式参数覆盖 ────────────────────\n"
        "# 不同人格模式下可覆盖 temperature/top_p，未配置则使用模型默认值。\n"
        "mode_params:\n"
        "  pragmatic:             # 严谨模式 — 代码/排bug，需要精确\n"
        "    temperature: 0.3\n"
        "    top_p: 0.9\n"
        "  creative:              # 创意模式 — 头脑风暴，需要发散\n"
        "    temperature: 0.8\n"
        "    top_p: 0.95\n"
        "  mixed:                 # 混合模式 — 均衡\n"
        "    temperature: 0.6\n"
        "    top_p: 0.9\n\n"
        "# ──────────────────── 路径配置 ────────────────────\n"
        "# 所有路径支持相对路径（相对于本 config.yaml 所在目录）或绝对路径（以 / 开头）。\n"
        "# 支持多 agent 隔离：每个 agent 使用独立的 config.yaml，指向独立的数据库和目录。\n"
        "paths:\n"
        '  data_dir: ""          # 数据根目录，默认 ~/.tea_agent\n'
        '  db_path: ""           # 数据库文件，默认 data_dir/chat_history.db\n'
        '  toolkit_dir: ""       # 自定义工具目录，默认 data_dir/toolkit\n'
        '  kb_dir: ""            # 知识库目录，默认 data_dir/kb\n'
        '  # skills_dir: ""     # <已废弃>\n'
        "# ──────────────────── 向量模型配置 ────────────────────\n"
        "# 用于主题搜索的文本向量生成。api_url 为空时自动使用本地 TF-IDF 回退。\n"
        "embedding_model:\n"
        '  api_url: ""          # Embedding API 地址，如 http://localhost:11434/v1\n'
        '  model_name: ""       # 嵌入模型，如 text-embedding-3-small / bge-m3\n'
        '  api_key: ""          # 为空则复用 main_model.api_key\n'
        "  dimension: 0          # 向量维度，0=自动检测\n\n"
        "# ──────────────────── 会话参数 ────────────────────\n"
        "# 最大历史消息数（保留的对话历史条数）\n"
        "max_history: 10\n\n"
        "# 最大工具调用迭代次数（单次对话中最多允许的工具调用循环数）\n"
        "max_iterations: 50\n\n"
        "# 是否启用 thinking 功能（模型思考过程展示）\n"
        "enable_thinking: true\n\n"
        "# 思考强度 0.0-1.0（0=最弱/最省token，1=最强/最深思考）\n"
        "thinking_strength: 0.7\n\n"
        "# 推理努力程度: auto/low/medium/high，映射到 OpenAI reasoning_effort 参数\n"
        "# auto = 根据 thinking_strength 自动映射\n"
        "reasoning_effort: auto\n\n"
        "# ──────────────────── Token 优化参数 ────────────────────\n"
        "# 保留最近 N 轮完整对话，更早的对话自动摘要（使用 cheap_model）\n"
        "keep_turns: 5\n\n"
        "# 工具输出截断字符数（超过此长度的工具结果会被截断）\n"
        "max_tool_output: 131072  # 128KB\n\n"
        "# 助手回复截断字符数（超过此长度的助手回复会被截断）\n"
        "max_assistant_content: 131072  # 128KB\n\n"
        "# ──────────────────── 交互与控制参数 ────────────────────\n"
        "# 工具调用达到上限后续命时追加的轮数\n"
        "extra_iterations_on_continue: 5\n\n"
        "# 触发自动记忆提取的最少未摘要消息数\n"
        "memory_extraction_threshold: 2\n\n"
        "# 记忆去重相似度阈值，超过此值视为重复并合并(0~1)\n"
        "memory_dedup_threshold: 0.3\n\n"
        "# GUI 单页加载的最大对话轮数（超过则省略更早的对话）\n"
        "chat_page_size: 50\n\n"
        "# 2026-05-20 gen by Tea Agent, L2/L3分层压缩参数\n"
        "# L2 最大保留轮数（用户+助手对，不含工具轮次）\n"
        "history_l2_max: 30\n\n"
        "# L3 摘要批处理：每攒够 N 条L2溢出，触发便宜模型摘要合并\n"
        "history_l3_batch: 10\n"
    )


def _write_template_file(yaml_path: str, template: str) -> None:
    """写入模板文件。

    Args:
        yaml_path: 文件路径
        template: 模板内容
    """
    with open(yaml_path, "w", encoding="utf-8") as f:
        f.write(template)


# 全局单例缓存
_config_cache: AgentConfig | None = None


def get_config(reload: bool = False) -> AgentConfig:
    """
    获取全局配置单例。

    检测 _last_config_path 是否已由 load_config(config_path) 更新，
    若缓存路径与 _last_config_path 不一致则自动重载。
    确保后续所有 get_config() 调用都返回与 load_config() 一致的配置。

    Args:
        reload: 强制重新加载

    Returns:
        AgentConfig 实例
    """
    global _config_cache, _last_config_path
    with _config_lock:
        if _config_cache is None or reload:
            _config_cache = load_config()
        return _config_cache
