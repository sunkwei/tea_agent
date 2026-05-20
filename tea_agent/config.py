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
# NOTE: 2026-05-17 08:46:29, self-evolved by tea_agent --- ModelConfig 添加 temperature/max_tokens/top_p 参数字段
    options: Dict[str, Any] = field(default_factory=dict)
    # @2026-05-17 gen by tea_agent, 模型推理参数（支持按模型+模式差异化配置）
    temperature: float = 0.7       # 温度 0~2，越高越随机
    max_tokens: int = 4096         # 最大输出 token 数
    top_p: float = 0.9             # 核采样阈值

    @property
    def is_configured(self) -> bool:
        """检查配置是否完整"""
        return bool(self.api_key and self.api_url and self.model_name)


# NOTE: 2026-04-30 16:17:53, self-evolved by tea_agent --- AgentConfig增加运行时get/set/apply/reload方法，支持自我配置调优
# NOTE: 2026-05-04 17:52:03, self-evolved by tea_agent --- 新增 PathsConfig dataclass + 路径解析逻辑，所有路径相对 config.yaml 所在目录解析
@dataclass
class PathsConfig:
    """路径配置。所有相对路径均相对于 config.yaml 所在目录解析。
    
    以 / 或 ~ 开头的路径视为绝对路径（~ 展开为用户目录）。
    未配置时回退到 ~/.tea_agent/<默认值>。
    """
    data_dir: str = ""        # 数据根目录，其他路径默认基于此
    db_path: str = ""         # 数据库文件路径（相对或绝对）
    toolkit_dir: str = ""     # 自定义工具目录
    kb_dir: str = ""          # 知识库目录
    skills_dir: str = ""      # 用户自定义 skills 目录

    # 运行时解析后的绝对路径（由 load_config 填充）
    _data_dir_abs: str = ""
    _db_path_abs: str = ""
    _toolkit_dir_abs: str = ""
    _kb_dir_abs: str = ""
    _skills_dir_abs: str = ""

# NOTE: 2026-05-09 19:44:19, self-evolved by tea_agent --- PathsConfig.resolve: 子路径相对 data_dir_abs 解析，data_dir 相对 config_dir 解析
    def resolve(self, config_dir: str) -> None:
        """根据 config.yaml 所在目录解析所有路径为绝对路径。
        
        子路径（db/toolkit/kb/skills）的相对路径相对于 data_dir_abs 解析。
        
        Args:
            config_dir: config.yaml 所在目录的绝对路径
        """
        import os
        default_root = str(Path.home() / ".tea_agent")

        # 先解析 data_dir（相对路径相对于 config_dir）
        if self.data_dir:
            expanded_data = os.path.expanduser(self.data_dir)
            if os.path.isabs(expanded_data):
                self._data_dir_abs = os.path.abspath(expanded_data)
            else:
                self._data_dir_abs = os.path.abspath(os.path.join(config_dir, expanded_data))
        else:
            self._data_dir_abs = default_root

        # 子路径解析：相对路径相对于 data_dir_abs
        def _resolve(value: str, default_rel: str) -> str:
            if not value:
                return os.path.join(self._data_dir_abs, default_rel)
            expanded = os.path.expanduser(value)
            if os.path.isabs(expanded):
                return os.path.abspath(expanded)
            return os.path.abspath(os.path.join(self._data_dir_abs, expanded))

        self._db_path_abs = _resolve(self.db_path, "chat_history.db") if self.db_path else os.path.join(self._data_dir_abs, "chat_history.db")
        self._toolkit_dir_abs = _resolve(self.toolkit_dir, "toolkit") if self.toolkit_dir else os.path.join(self._data_dir_abs, "toolkit")
        self._kb_dir_abs = _resolve(self.kb_dir, "kb") if self.kb_dir else os.path.join(self._data_dir_abs, "kb")
        self._skills_dir_abs = _resolve(self.skills_dir, "skills") if self.skills_dir else os.path.join(self._data_dir_abs, "skills")

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
    def skills_dir_abs(self) -> str:
        return self._skills_dir_abs

    @property
    def data_dir_abs(self) -> str:
        return self._data_dir_abs


# NOTE: 2026-05-06 19:15:20, self-evolved by tea_agent --- 添加 EmbeddingConfig 配置类，支持向量模型设置
@dataclass
class EmbeddingConfig:
    """文本向量模型配置。用于消息语义搜索。
    
    支持两种模式：
    1. API 模式：通过 api_url/embeddings 端点获取向量
    2. 本地 TF-IDF 回退：当 api_url 为空时自动使用
    
    api_key 为空时复用 main_model 的 api_key。
    """
    api_url: str = ""       # Embedding API 地址，如 http://localhost:11434/v1
    model_name: str = ""    # 嵌入模型名称，如 text-embedding-3-small
    api_key: str = ""       # API Key，为空则使用 main_model.api_key
    dimension: int = 0      # 向量维度，0=自动检测

    @property
    def is_configured(self) -> bool:
        """至少配置了 api_url 和 model_name 才视为有效"""
@dataclass
class AgentConfig:
    """Agent 全局配置"""
# NOTE: 2026-05-04 17:52:12, self-evolved by tea_agent --- AgentConfig 增加 paths 字段，load_config 中解析 paths 配置块并调用 resolve
# NOTE: 2026-05-06 19:15:39, self-evolved by tea_agent --- AgentConfig 增加 embedding 字段
    main_model: ModelConfig = field(default_factory=ModelConfig)
    cheap_model: ModelConfig = field(default_factory=ModelConfig)
    embedding: EmbeddingConfig = field(default_factory=EmbeddingConfig)
# NOTE: 2026-05-17 08:46:46, self-evolved by tea_agent --- AgentConfig 添加 mode_params 模式参数覆盖 + get_effective_params 方法
    paths: PathsConfig = field(default_factory=PathsConfig)
    # @2026-05-17 gen by tea_agent, 按模式覆盖模型参数
    # 格式: {"pragmatic": {"temperature": 0.3}, "creative": {"temperature": 0.8}, "mixed": {"temperature": 0.6}}
    mode_params: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    
    def get_effective_params(self, model_type: str = "main", mode: str = "mixed") -> Dict[str, Any]:
        """
        获取最终生效的模型推理参数。优先级：mode_params > model 默认值。

        Args:
            model_type: "main" 或 "cheap"
            mode: "pragmatic" / "creative" / "mixed"

        Returns:
            包含 temperature, max_tokens, top_p 的 dict
        """
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
    # 2026-05-20 gen by Tea Agent, L2/L3分层压缩参数
    history_l2_max: int = 30    # L2最多保留轮数（含user+assistant，不含工具轮）
    history_l3_batch: int = 10  # L3摘要批处理大小（攒够N条触发便宜模型摘要）
    # 2026-04-30 gen by deepseek-v4-pro, 运行时配置读写方法（支持自我调优）

    # 可运行时修改的配置键白名单
    _RUNTIME_CONFIG_KEYS = {
        "max_history", "max_iterations", "enable_thinking",
        "keep_turns", "max_tool_output", "max_assistant_content",
        "extra_iterations_on_continue", "memory_extraction_threshold",
        "memory_dedup_threshold", "chat_page_size",
        "history_l2_max", "history_l3_batch",  # 2026-05-20 gen by Tea Agent, L2/L3分层压缩
    }

    # 类型映射
    _CONFIG_TYPES = {
        "max_history": int, "max_iterations": int, "enable_thinking": bool,
        "keep_turns": int, "max_tool_output": int, "max_assistant_content": int,
        "extra_iterations_on_continue": int, "memory_extraction_threshold": int,
        "memory_dedup_threshold": float, "chat_page_size": int,
        "history_l2_max": int, "history_l3_batch": int,
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
# NOTE: 2026-05-17 08:46:57, self-evolved by tea_agent --- load_config 解析模型参数 + mode_params 配置块
                    target.api_key = m_data.get("api_key", "")
                    target.api_url = m_data.get("api_url", "")
                    target.model_name = m_data.get("model_name", "")
                    target.options = m_data.get("options", {})
                    # @2026-05-17 gen by tea_agent, 解析模型推理参数
                    target.temperature = float(m_data.get("temperature", target.temperature))
                    target.max_tokens = int(m_data.get("max_tokens", target.max_tokens))
                    target.top_p = float(m_data.get("top_p", target.top_p))

# NOTE: 2026-05-04 17:52:35, self-evolved by tea_agent --- load_config 中解析 paths 配置块 + 调用 resolve 解析路径
# NOTE: 2026-05-06 19:15:56, self-evolved by tea_agent --- load_config 解析 embedding 配置块
            # 加载 Embedding 配置
            emb_data = data.get("embedding_model", {})
            if isinstance(emb_data, dict):
                cfg.embedding.api_url = str(emb_data.get("api_url", cfg.embedding.api_url))
                cfg.embedding.model_name = str(emb_data.get("model_name", cfg.embedding.model_name))
                cfg.embedding.api_key = str(emb_data.get("api_key", cfg.embedding.api_key))
                cfg.embedding.dimension = int(emb_data.get("dimension", cfg.embedding.dimension))

# NOTE: 2026-05-17 08:47:08, self-evolved by tea_agent --- load_config 解析 mode_params 配置块
            # @2026-05-17 gen by tea_agent, 加载模式参数覆盖
            mp_data = data.get("mode_params", {})
            if isinstance(mp_data, dict):
                for mode_name in ("pragmatic", "creative", "mixed"):
                    mode_cfg = mp_data.get(mode_name, {})
                    if isinstance(mode_cfg, dict):
                        cfg.mode_params[mode_name] = {
                            k: v for k, v in mode_cfg.items()
                            if k in ("temperature", "max_tokens", "top_p")
                        }

            # 加载路径配置
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
            # 2026-05-20 gen by Tea Agent, L2/L3分层压缩
            cfg.history_l2_max = int(data.get("history_l2_max", cfg.history_l2_max))
            cfg.history_l3_batch = int(data.get("history_l3_batch", cfg.history_l3_batch))            
        except Exception:
            pass  # 加载失败时使用默认空配置

    return cfg


# NOTE: 2026-05-04 17:57:48, self-evolved by tea_agent --- ensure_config_dir 使用 config.paths 路径
def ensure_config_dir() -> Path:
    """确保数据目录存在（从 config 读取，回退 ~/.tea_agent），返回路径"""
    try:
        cfg = get_config()
        cfg_dir = Path(cfg.paths.data_dir_abs)
    except Exception:
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
# NOTE: 2026-05-17 08:47:22, self-evolved by tea_agent --- save_config 保存模型推理参数和 mode_params
            m_data = {
                "api_key": target.api_key,
                "api_url": target.api_url,
                "model_name": target.model_name,
            }
            # @2026-05-17 gen by tea_agent, 保存模型推理参数
            if target.temperature != 0.7:
                m_data["temperature"] = target.temperature
            if target.max_tokens != 4096:
                m_data["max_tokens"] = target.max_tokens
            if target.top_p != 0.9:
                m_data["top_p"] = target.top_p
            if target.options:
                m_data["options"] = target.options
            data[m_type] = m_data
    
# NOTE: 2026-05-04 17:52:50, self-evolved by tea_agent --- save_config 中保存 paths 配置
# NOTE: 2026-05-06 19:16:13, self-evolved by tea_agent --- save_config 保存 embedding 配置块
    # 保存 Embedding 配置
    data["embedding_model"] = {
        "api_url": cfg.embedding.api_url,
        "model_name": cfg.embedding.model_name,
        "api_key": cfg.embedding.api_key,
        "dimension": cfg.embedding.dimension,
    }

# NOTE: 2026-05-17 08:47:32, self-evolved by tea_agent --- save_config 写入 mode_params 配置块
    # @2026-05-17 gen by tea_agent, 保存模式参数覆盖
    if cfg.mode_params:
        data["mode_params"] = cfg.mode_params

    # 保存路径配置（保存原始配置值，非解析后的绝对路径）
    data["paths"] = {
        "data_dir": cfg.paths.data_dir,
        "db_path": cfg.paths.db_path,
        "toolkit_dir": cfg.paths.toolkit_dir,
        "kb_dir": cfg.paths.kb_dir,
        "skills_dir": cfg.paths.skills_dir,
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
    # 2026-05-20 gen by Tea Agent, L2/L3分层压缩
    data["history_l2_max"] = cfg.history_l2_max
    data["history_l3_batch"] = cfg.history_l3_batch    
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
# NOTE: 2026-05-17 08:48:03, self-evolved by tea_agent --- create_default_config 模板增加模型参数和 mode_params 配置
        "# 主模型配置（用于核心对话、代码生成等）\n"
        "main_model:\n"
        "  api_key: \"\"\n"
        "  api_url: \"\"\n"
        "  model_name: \"\"\n"
        "  temperature: 0.7      # 温度 0~2，越高越随机发散\n"
        "  max_tokens: 4096      # 最大输出 token 数\n"
        "  top_p: 0.9            # 核采样阈值\n"
        "  options:  # 可选参数，如 {extra_body: {thinking: {type: enabled}}}\n"
        "    key: value\n\n"
        "# 便宜模型配置（用于摘要生成、信息压缩等场景，建议低 temperature）\n"
        "cheap_model:\n"
        "  api_key: \"\"\n"
        "  api_url: \"\"\n"
        "  model_name: \"\"\n"
        "  temperature: 0.3      # 摘要/反思需要确定性，建议 0.2~0.5\n"
        "  max_tokens: 1024      # 摘要通常较短\n"
        "  top_p: 0.9\n"
        "  options: {}\n\n"
        "# ==================== 模式参数覆盖 ====================\n"
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
# NOTE: 2026-05-04 17:53:08, self-evolved by tea_agent --- create_default_config 模板增加 paths 配置块
        "# ==================== 路径配置 ====================\n"
        "# 所有路径支持相对路径（相对于本 config.yaml 所在目录）或绝对路径（以 / 开头）。\n"
        "# 支持多 agent 隔离：每个 agent 使用独立的 config.yaml，指向独立的数据库和目录。\n"
        "paths:\n"
        "  data_dir: \"\"          # 数据根目录，默认 ~/.tea_agent\n"
        "  db_path: \"\"           # 数据库文件，默认 data_dir/chat_history.db\n"
        "  toolkit_dir: \"\"       # 自定义工具目录，默认 data_dir/toolkit\n"
        "  kb_dir: \"\"            # 知识库目录，默认 data_dir/kb\n"
        "  skills_dir: \"\"        # 用户 skills 目录，默认 data_dir/skills\n\n"
# NOTE: 2026-05-06 19:16:28, self-evolved by tea_agent --- create_default_config 模板增加 embedding_model 配置块
        "# ==================== 向量模型配置 ====================\n"
        "# 用于主题搜索的文本向量生成。api_url 为空时自动使用本地 TF-IDF 回退。\n"
        "embedding_model:\n"
        "  api_url: \"\"          # Embedding API 地址，如 http://localhost:11434/v1\n"
        "  model_name: \"\"       # 嵌入模型，如 text-embedding-3-small / bge-m3\n"
        "  api_key: \"\"          # 为空则复用 main_model.api_key\n"
        "  dimension: 0          # 向量维度，0=自动检测\n\n"
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
# NOTE: 2026-05-06 08:47:24, self-evolved by tea_agent --- M1: 修复模板 memory_dedup_threshold 默认值与代码一致 (0.5→0.3)
        "# 记忆去重相似度阈值，超过此值视为重复并合并(0~1)\n"
        "memory_dedup_threshold: 0.3\n\n"
# NOTE: 2026-04-30 09:47:45, self-evolved by tea_agent --- create_default_config模板同步更新chat_page_size默认值30→50
        "# GUI 单页加载的最大对话轮数（超过则省略更早的对话）\n"
        "# GUI 单页加载的最大对话轮数（超过则省略更早的对话）\n"
        "chat_page_size: 50\n\n"
        "# 2026-05-20 gen by Tea Agent, L2/L3分层压缩参数\n"
        "# L2 最大保留轮数（用户+助手对，不含工具轮次）\n"
        "history_l2_max: 30\n\n"
        "# L3 摘要批处理：每攒够 N 条L2溢出，触发便宜模型摘要合并\n"
        "history_l3_batch: 10\n"    )

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
