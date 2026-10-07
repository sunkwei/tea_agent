"""
配置管理模块 — 加载/保存/运行时修改 Agent 配置。

配置来源：``~/.tea_agent/provider.yaml`` **唯一事实源**
（``roles`` 段 = 主/便宜模型绑定；``settings`` 段 = 运行时参数），
代码内默认值兜底。config.yaml 已删除，不再读写任何 YAML 配置文件。
"""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar

logger = logging.getLogger("tea_agent.config")

AUTO_MAX_TOKENS_WINDOW_RATIO = 0.25

AUTO_MAX_TOKENS_FLOOR = 8192


try:
    import yaml  # noqa: F401

    HAS_YAML: bool = True
except ImportError:
    HAS_YAML = False

__all__ = [
    "ModelConfig",
    "PathsConfig",
    "AgentConfig",
    "REASONING_EFFORT_VALUES",
    "REASONING_EFFORT_RANKS",
    "clamp_reasoning_effort",
    "load_config",
    "save_config",
    "get_config",
    "ensure_config_dir",
    "set_active_config_path",
    "get_active_config_path",
]

# reasoning_effort 合法取值（OpenAI o 系列 / DeepSeek 兼容端点）。
# "auto" 仅为配置占位值：表示"自动推导、不显式下发该参数"，
# 不是合法的 API 值（API 只接受 none/minimal/low/medium/high/xhigh/max）。
REASONING_EFFORT_VALUES: frozenset[str] = frozenset({"auto", "none", "minimal", "low", "medium", "high", "xhigh", "max"})

# reasoning_effort 强度序（数值越大思考越深），用于值域钳制
REASONING_EFFORT_RANKS: dict[str, int] = {
    "none": 0,
    "minimal": 1,
    "low": 2,
    "medium": 3,
    "high": 4,
    "xhigh": 5,
    "max": 6,
}


def clamp_reasoning_effort(value: str, supported: list[str] | None) -> str:
    """把 reasoning_effort 钳制到模型接受的值域内（避免 400）。

    不同模型接受的值域不同：如 qwen3.8 仅接受 xhigh/medium/low，
    而 strength 映射会产出 high。值不在 supported 内时，
    按 REASONING_EFFORT_RANKS 取最接近的支持值（同距时取更强档）。

    Args:
        value: 候选 effort 值（"auto" 等占位值原样返回，由调用方先过滤）
        supported: 模型接受的值域列表；None/空 = 未知值域，不钳制

    Returns:
        钳制后的值（原值在值域内或未提供值域时原样返回）
    """
    if not value or not supported or value in supported:
        return value
    target = REASONING_EFFORT_RANKS.get(value, 3)
    return min(
        supported,
        key=lambda v: (abs(REASONING_EFFORT_RANKS.get(v, 3) - target), -REASONING_EFFORT_RANKS.get(v, 3)),
    )


@dataclass
class ModelConfig:
    """单个 LLM 模型配置"""

    api_key: str = ""
    api_url: str = ""
    model_name: str = ""
    options: dict[str, Any] = field(default_factory=dict)
    temperature: float = 0.7
    max_tokens: int = 131072
    max_context_tokens: int = 0
    top_p: float = 0.9
    # 工具暴露档位（auto=按 max_context_tokens 推导 / full/standard/core/minimal/nano 显式）。
    # 上下文受限模型（如 max_context_tokens<200K）时自动精简工具集，降低每请求固定开销。
    tool_profile: str = "auto"
    # 模型级 token budget（借鉴 Codex model-owned token budget defaults）
    # 支持键: reminder_threshold / reminder_message_template /
    #         guidance_message / fallback_buffer_tokens / auto_compact_fallback_prompt
    token_budget: dict[str, Any] = field(default_factory=dict)
    # 引用式来源（config*.yaml 只存 p_name + m_name 组合时记录；空=传统完整内嵌块）
    provider: str = ""  # p_name（provider.yaml 中的供应商名）
    ref_model: str = ""  # m_name（provider.yaml 中该供应商下的模型 id）

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key and self.api_url and self.model_name)

    @property
    def supports_vision(self) -> bool:
        return self.options.get("supports_vision", False)

    @property
    def is_reference(self) -> bool:
        """是否为 p_name+m_name 引用式（可在 config 层直接写引用，不内嵌密钥）。"""
        return bool(self.provider and self.ref_model)

    def get_token_budget(self, key: str, default: Any = None) -> Any:
        """读取模型级 token budget 配置项。

        Args:
            key: 配置键名（reminder_threshold 等）
            default: 缺省值

        Returns:
            配置值
        """
        return self.token_budget.get(key, default)


@dataclass
class PathsConfig:
    """路径配置。相对路径相对于 config.yaml 所在目录。

    存储作用域（storage_scope，取值 auto/project/user，默认 auto）：
    - 主题/会话/记忆库（db_path）默认落在「启动目录 .tea_agent_run/chat_history.db」；
    - 启动目录不可写（无权限 / 无磁盘空间）→ 回退**系统临时目录**，并在每轮
      会话结束提示用户手动复制（见 storage_scope.storage_notice）；
    - 启动目录 == 用户主目录 → 用户级 ~/.tea_agent/chat_history.db（主目录即项目）；
    - 显式 storage_scope=user 或 data_dir / 绝对 db_path → 尊重显式配置。
    """

    data_dir: str = ""
    db_path: str = ""
    storage_scope: str = ""  # auto/project/user；空=auto（项目级优先，回退用户级）
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
                self._data_dir_abs = os.path.abspath(os.path.join(config_dir, expanded_data))
        else:
            self._data_dir_abs = default_root

        def _resolve(value: str, default_rel: str) -> str:
            if not value:
                return os.path.join(self._data_dir_abs, default_rel)
            expanded = os.path.expanduser(value)
            if os.path.isabs(expanded):
                return os.path.abspath(expanded)
            return os.path.abspath(os.path.join(self._data_dir_abs, expanded))

        # 用户级 db（保留，作为回退层 / 显式存储根）
        from tea_agent.storage_scope import DEFAULT_DB_NAME

        self._db_path_abs = _resolve(self.db_path, DEFAULT_DB_NAME)
        self._toolkit_dir_abs = _resolve(self.toolkit_dir, "toolkit")
        self._kb_dir_abs = _resolve(self.kb_dir, "kb")
        # active db 路径惰性缓存（由 active_db_path_abs 属性填充）
        self._active_db_path_abs: str | None = None

    @property
    def db_path_abs(self) -> str:
        return self._db_path_abs

    @property
    def user_db_path_abs(self) -> str:
        """用户级 db 绝对路径（~/.tea_agent/... 或显式 data_dir/db_path）。"""
        return self._db_path_abs

    @property
    def active_db_path_abs(self) -> str:
        """会话库实际使用路径（项目级优先，用户级回退）。

        storage_scope：
        - auto（默认）/project：启动目录可写 → <启动目录>/.tea_agent_run/ 下；
        - 不可写 / user / 显式 data_dir 或绝对 db_path → 用户级 db。

        会话库打开点（Agent._init_storage / store.get_storage）使用此属性，
        使主题/会话/记忆默认随项目目录隔离，同时保留用户级 db 作为回退。
        """
        cached = getattr(self, "_active_db_path_abs", None)
        if cached is not None:
            return cached
        # 显式自定义存储根（data_dir 或绝对 db_path）→ 尊重用户配置，不自动项目化
        if self.data_dir or (self.db_path and os.path.isabs(os.path.expanduser(self.db_path))):
            self._active_db_path_abs = self._db_path_abs
        else:
            from tea_agent.storage_scope import resolve_db_path

            self._active_db_path_abs = resolve_db_path(
                user_db_abs=self._db_path_abs,
                db_path_cfg=self.db_path,
                storage_scope_cfg=self.storage_scope,
            )
        return self._active_db_path_abs

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
class AgentConfig:
    """Agent 全局配置"""

    main_model: ModelConfig = field(default_factory=ModelConfig)
    cheap_model: ModelConfig = field(default_factory=ModelConfig)
    paths: PathsConfig = field(default_factory=PathsConfig)
    mode_params: dict[str, dict[str, Any]] = field(default_factory=dict)

    # 任务阶段 → 推荐温度（未显式配置时的智能默认；越低越确定，越高越发散）
    PHASE_DEFAULT_TEMP: ClassVar[dict[str, float]] = {
        "develop": 0.2,  # 代码生成/实现：确定性优先
        "test": 0.2,  # 测试调试：精确可复现
        "review": 0.15,  # 代码审查：事实判断
        "devops": 0.3,  # 部署发布：严谨
        "design": 0.45,  # 架构设计：严谨但需创意
        "docs": 0.5,  # 文档撰写：适中
        "creative": 0.8,  # 创意发散/进化方向：高随机探索
        "mixed": 0.6,  # 自动均衡（默认）
        "pragmatic": 0.2,  # 兼容旧名
    }

    def vision_capable_model(self) -> ModelConfig | None:
        """返回可用于图片输入的已配置模型（主模型优先，其次便宜模型）。

        视觉能力由模型自身声明的 ``supports_vision`` 决定，不再有独立的
        ``vision_model`` 角色槽位。无任何视觉模型时返回 None。
        """
        for m in (self.main_model, self.cheap_model):
            if m is not None and m.is_configured and m.supports_vision:
                return m
        return None

    def get_effective_params(self, model_type: str = "main", mode: str = "mixed") -> dict[str, Any]:
        """获取最终生效的模型推理参数。mode_params 覆盖 model 默认值；
        未显式配置 temperature 时按任务阶段使用智能默认。

        model_type 支持: "main" / "cheap"。
        """
        model_cfg = self.main_model if model_type == "main" else self.cheap_model
        params = {
            "temperature": model_cfg.temperature,
            "max_tokens": model_cfg.max_tokens,
            "top_p": model_cfg.top_p,
        }
        # 1) 用户显式 mode_params 优先
        overrides = self.mode_params.get(mode, {})
        for k in ("temperature", "max_tokens", "top_p"):
            if k in overrides:
                params[k] = overrides[k]
        # 2) 未显式配置 temperature 时，按任务阶段用智能默认
        if "temperature" not in overrides and mode in self.PHASE_DEFAULT_TEMP:
            params["temperature"] = self.PHASE_DEFAULT_TEMP[mode]
        return params

    # 会话参数
    max_history: int = 10  # 最大历史消息数
    max_iterations: int = 200  # 最大工具调用迭代次数
    # 出站 LLM 请求附加 HTTP 头，供自建网关/反代使用（按 host 匹配，避免泄露给其它 provider）
    # 形式: {"*" | "host" | "*.suffix": {Header-Name: value}}；value 支持 ${ENV_VAR}
    api_headers: dict[str, dict[str, str]] = field(default_factory=dict)
    # 是否给 OpenCode Go/Zen 端点自动注入 x-opencode-session（默认开；缺失该头网关会 400）
    opencode_session_header: bool = True
    enable_thinking: bool = True  # 是否启用 thinking 功能
    thinking_strength: float = 0.7  # 思考强度 0.0-1.0（0=最弱/最省token, 1=最强/最深度思考）
    reasoning_effort: str = "auto"  # 推理努力: "auto"=自动推导不发送 / none/minimal/low/medium/high/xhigh/max

    # Token 优化参数
    # 2026-10 L2→L3 批处理：keep_turns 既是 L1 保留轮数，也是 L2 压缩后的
    # **压回水位**（默认 10）。L2 越过 keep_turns 后不立刻摘要，而是攒到
    # keep_turns + batch 再一次性压回 keep_turns（batch 见 history_l3_batch）。
    keep_turns: int = 10  # 保留最近N轮完整对话；L2 压缩后也回到该条数
    max_tool_output: int = 128 * 1024  # 工具输出截断字符数
    max_assistant_content: int = 128 * 1024  # 助手回复截断字符数

    # 交互与控制参数
    memory_extraction_threshold: int = 2  # 触发记忆提取的最低未摘要消息数
    memory_dedup_threshold: float = 0.3  # 记忆去重相似度阈值 (0~1)，bigram Jaccard
    chat_page_size: int = 50  # 单页加载的对话轮数（最多50条）
    # L2 条数**上限约束**（0=不约束，默认）。L2 的压回水位统一取 keep_turns
    # （见 tea_agent/l3_policy.py）；本项只用于额外收紧上限（>0 时取 min），
    # 不再充当"压回目标"——历史模板里的 30 不会再导致一次砍掉过多 L2。
    history_l2_max: int = 0  # 0=自动（上限=keep_turns+batch）
    # L3 摘要批处理：L2 越过 keep_turns 后需再积攒 N 条才触发便宜模型摘要
    # （0=自动 → keep_turns//2，默认 10 → 5）。压缩后 L2 回到 keep_turns 条。
    history_l3_batch: int = 0  # 0=自动（keep_turns//2）
    # 单条 L2 条目 thinking（本轮全部工具步的 reasoning_content 拼接）上限（字符）。
    # 不限幅时单轮 thinking 可达 1.5MB（实测），既撑爆 L2 存储又让 L2→L3 摘要
    # 输入无谓膨胀；截断只影响"回顾用"的 thinking，不影响 API 回传的 L1 RC。
    l2_thinking_max_chars: int = 6000
    # L2 总量上限（字符，user+thinking+assistant 之和）：达到即视同"溢出"，
    # 保留最新 keep=5 条并把其余交给 L3 摘要。此前只看条数（history_l2_max），
    # 条数没到就永不摘要，历史全量堆在 L2 里空转。
    l2_max_chars: int = 120000
    # L1 消息里 reasoning_content 分块限步回传：以 N 步为一块，只保留最近一块
    # 的全文，更早的块整体置为空串字段值（字段保留 → 满足 DeepSeek V4 "必须
    # 回传" 的字段存在性要求；空串是官方合法值，仓库既有兜底路径同样补空串）。
    # 0=关闭（旧行为：全量回传）。分块而非滑窗：只跨块时改写一次，避免每步都
    # 让其后 N 步内容缓存未命中。
    # 背景：单轮 200 步的 RC 可达 37.5 万 token，是上下文被迅速打满的第一主因。
    rc_keep_steps: int = 8

    # API 弹性参数（网络中断 / PC 睡眠恢复等瞬时故障的容错）
    api_request_timeout: float = 120.0  # 单次请求超时（秒）
    api_connect_timeout: float = 30.0  # 连接建立超时（秒）
    api_max_retries: int = 3  # 接口中断最大重试次数（不含首次尝试）
    api_retry_backoff: float = 2.0  # 指数退避基数（秒）：重试等待 = backoff * 2^n
    api_sleep_recovery_wait: float = 5.0  # 连接类错误额外等待（睡眠恢复后网络栈重建）

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
        "memory_extraction_threshold",
        "memory_dedup_threshold",
        "chat_page_size",
        "history_l2_max",
        "history_l3_batch",  # 2026-05-20 gen by Tea Agent, L2/L3分层压缩
        "l2_thinking_max_chars",  # L2 单条 thinking 限幅（上下文填充治理）
        "l2_max_chars",  # L2 总量触发摘要阈值（字符）
        "rc_keep_steps",  # L1 只保留最近 N 步 reasoning_content 全文
    }

    # 打断知识闭环配置（M4/M5）
    interruption: dict = field(
        default_factory=lambda: {
            "enabled": True,  # 总开关
            # corrected/abandoned 判定阈值。0.25 是针对**关键词 Jaccard** 口径
            # 实测标定的：同话题续说 0.31~0.82、换话题恒为 0.0，两组完全可分。
            # 余弦时代的 0.6 照搬过来会让 corrected 分支近乎不可达。
            # 口径与标定依据见 onlinesession.INTERRUPT_SIMILARITY_THRESHOLD。
            "similarity_threshold": 0.25,
            "partial_reply_max": 2000,  # 锚点 partial_reply 截断长度
            "persist_events": True,  # 是否持久化事件表
            "analyze_interval_h": 1.0,  # 后台分析周期（小时）
            "keep_days": 30,  # 事件保留天数（超期清理）
            "skill_min_count": 3,  # M5: 触发行为指导 skill 生成的打断阈值
        }
    )

    def get_interruption(self, key: str, default=None):
        """读取打断知识闭环配置项。"""
        return self.interruption.get(key, default)

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
        "memory_extraction_threshold": int,
        "memory_dedup_threshold": float,
        "chat_page_size": int,
        "history_l2_max": int,
        "history_l3_batch": int,
        "l2_thinking_max_chars": int,
        "l2_max_chars": int,
        "rc_keep_steps": int,
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
        if key == "reasoning_effort":
            # 值域白名单：仅接受 REASONING_EFFORT_VALUES（含 "auto" 占位值）
            value = str(value).strip().lower()
            if value not in REASONING_EFFORT_VALUES:
                return False
        elif expected_type:
            try:
                value = value.lower() in ("true", "1", "yes", "on") if expected_type is bool and isinstance(value, str) else expected_type(value)
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
                    "error": ("" if ok else (f"无效的配置键: {key}" if key not in self._RUNTIME_CONFIG_KEYS else f"值类型错误: {value}")),
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
        return {key: getattr(self, key) for key in self._RUNTIME_CONFIG_KEYS if hasattr(self, key)}

    def to_full_dict(self) -> dict:
        """导出所有配置为字典（含模型/路径等完整配置）"""
        data = {}
        _prepare_model_data(self, data)
        _prepare_paths_data(self, data)
        _prepare_session_data(self, data)
        _prepare_token_data(self, data)
        _prepare_control_data(self, data)
        return data


_last_config_path = None
# RLock 可重入：get_config 持锁后调用 load_config → resolve_config_path/_update_config_cache
# 会再次取锁，普通 Lock 会导致首次 get_config() 死锁
_config_lock = threading.RLock()

# ── 全局活跃配置路径（Web / ACP / 渠道等各入口共享） ──
_active_config_path: str | None = None


def set_active_config_path(config_path: str) -> None:
    """设置全局活跃配置路径（Web 切换配置时调用）。"""
    global _active_config_path
    with _config_lock:
        _active_config_path = os.path.abspath(config_path)


def get_active_config_path() -> str | None:
    """获取全局活跃配置路径。优先返回此值，None 时回退到 _last_config_path。"""
    with _config_lock:
        return _active_config_path or _last_config_path


def load_config(config_path: str | None = None) -> AgentConfig:
    """加载配置。

    config.yaml 已删除：身份三元组（main/cheap）与运行时参数**全部**来自
    ``~/.tea_agent/provider.yaml``（各自的 ``roles`` / ``settings`` 段），
    代码内默认值兜底。不再读取任何 YAML 配置文件。

    Args:
        config_path: 忽略（保留签名以兼容既有调用方）

    Returns:
        AgentConfig 实例
    """
    global _config_cache

    cfg = AgentConfig()

    # 步骤1: 读取 provider.yaml（唯一事实源）
    store = None
    stored: dict = {}
    try:
        from tea_agent.provider_store import get_provider_store

        store = get_provider_store()
        stored = store.load()
    except Exception as e:  # pragma: no cover - 防御性
        logger.debug("provider.yaml 加载跳过: %s", e)

    # 步骤2: settings 段 → 运行时参数（顶层扁平 + paths 子块）
    data: dict = {}
    settings = stored.get("settings")
    if isinstance(settings, dict):
        data.update(settings)

    # 步骤3: roles 段 → 引用式模型块（provider + model）
    roles = stored.get("roles")
    if isinstance(roles, dict):
        for role_key, block_key in (("main", "main_model"), ("cheap", "cheap_model")):
            r = roles.get(role_key)
            if isinstance(r, dict) and str(r.get("provider") or "").strip():
                data[block_key] = {
                    "provider": r.get("provider"),
                    "model": r.get("model"),
                }

    # 步骤3.5: main_model 缺失 → provider.yaml 第一个提供商的默认模型
    if not _main_block_usable(data):
        ref = _first_provider_ref()
        if ref:
            data["main_model"] = ref
            logger.info(
                "main_model 兜底: 未配置角色绑定，改用 provider.yaml %s/%s",
                ref["provider"],
                ref["model"],
            )

    if data:
        try:
            _parse_model_configs(cfg, data)
            _parse_mode_params(cfg, data)
            _parse_paths_config(cfg, data, "")
            _parse_session_params(cfg, data)
            _parse_token_params(cfg, data)
            _parse_control_params(cfg, data)
        except Exception:
            import traceback

            logger.warning(f"provider.yaml settings 解析部分失败，已回退默认值\n{traceback.format_exc(limit=2)}")

    # paths 解析兜底：无 settings.paths 时按 ~/.tea_agent 补解析
    if not cfg.paths.data_dir_abs:
        cfg.paths.resolve(str(Path.home() / ".tea_agent"))

    # 步骤4: 更新全局缓存
    _update_config_cache(cfg, None)

    return cfg


def resolve_config_path(config_path: str | None = None) -> str | None:
    """解析配置文件路径（兼容保留；config.yaml 已删除）。

    config.yaml 不再存在：本函数恒返回 None，身份三元组与运行时参数
    一律由 provider.yaml 提供。保留符号供 agent/server 等历史调用点使用。
    """
    return None


def _update_config_cache(cfg: AgentConfig, yaml_path: str | None) -> None:
    """更新全局配置缓存。

    Args:
        cfg: AgentConfig实例
        yaml_path: 配置文件路径（config.yaml 已删除，恒为 None）
    """
    global _config_cache, _active_config_path

    with _config_lock:
        _config_cache = cfg
        if yaml_path:
            src = os.path.abspath(yaml_path)
            _active_config_path = src
            _last_config_path = src
            # 记录配置来源，供 get_config 检测路径切换并自动重载
            cfg._config_source = src


def _main_block_usable(data: dict) -> bool:
    """config 数据的 main_model 块是否含用户配置（有则尊重，不被 provider.yaml 兜底覆盖）。

    可用 = 引用式 provider+model 齐，或传统内嵌任一身份字段非空。
    块缺失 / 非 dict / 身份字段全空串 → False（视为未配置，交给 provider.yaml 补位）。

    Args:
        data: 配置文件解析出的字典（可为空）

    Returns:
        True=块提供了配置，False=未配置
    """
    mb = data.get("main_model")
    if not isinstance(mb, dict):
        return False
    if str(mb.get("provider") or "").strip() and str(mb.get("model") or "").strip():
        return True
    return any(str(mb.get(k) or "").strip() for k in ("api_url", "api_key", "model_name"))


def _first_provider_ref() -> dict | None:
    """provider.yaml 第一个提供商（文档序）的第一个模型 → {provider, model} 引用块。

    「第一个提供商」按 YAML 文档序（= 写入序）：首次引导先配置的那家即默认主模型，
    与「provider 中第一个提供商的第一个模型」字面语义一致。
    模型取 default_model（引导写入时 = 所选模型），缺省时取 models 键序第一个。

    Returns:
        引用式块 dict；provider.yaml 为空/无模型/基础设施异常 → None
    """
    try:
        from tea_agent.provider_store import get_provider_store

        providers = get_provider_store().load().get("providers") or {}
        if not providers:
            return None
        first = next(iter(providers))  # dict 插入序 = YAML 文档序
        p = providers[first] or {}
        model = str(p.get("default_model") or "").strip()
        if not model:
            model = next(iter(p.get("models") or {}), "")
        if not model:
            return None
        return {"provider": first, "model": model}
    except Exception as e:
        logger.debug("provider.yaml 首模型兜底跳过: %s", e)
        return None


def _resolve_ref_model(provider: str, model: str) -> dict | None:
    """从 provider.yaml 解析 p_name + m_name 组合（延迟 import 避免循环依赖）。

    Args:
        provider: 供应商名（p_name）
        model: 模型 id（m_name）

    Returns:
        扁平元数据 {api_url, api_key, model, max_context_tokens,
                    max_output_tokens, options, reasoning_effort}；失败返回 None
    """
    try:
        from tea_agent.provider_store import get_provider_store

        return get_provider_store().resolve(provider, model)
    except Exception as e:
        logger.debug("provider ref resolve skipped (%s/%s): %s", provider, model, e)
        return None


def auto_max_tokens_cap(max_context_tokens: int) -> int:
    """自动填充 max_tokens 时的限幅上限（=窗口的 25%，下限 8192）。

    Args:
        max_context_tokens: 模型窗口（≤0 表示未知 → 返回下限）

    Returns:
        max_tokens 自动填充上限
    """
    try:
        ctx = int(max_context_tokens or 0)
    except (TypeError, ValueError):
        ctx = 0
    if ctx <= 0:
        return AUTO_MAX_TOKENS_FLOOR
    return max(AUTO_MAX_TOKENS_FLOOR, int(ctx * AUTO_MAX_TOKENS_WINDOW_RATIO))


def _parse_model_configs(cfg: AgentConfig, data: dict) -> None:
    """解析模型配置。

    支持两种形态（每角色可独立混用）：
      1) 传统内嵌：main_model: {api_key, api_url, model_name, options, ...}
      2) 引用式（推荐）：main_model: {provider: <p_name>, model: <m_name>[, 覆盖字段]}
         密钥/端点/能力从 ~/.tea_agent/provider.yaml 解析，config 不内嵌密钥。

    Args:
        cfg: AgentConfig实例
        data: 配置数据字典
    """
    for m_type in ["main_model", "cheap_model"]:
        m_data = data.get(m_type, {})
        if not isinstance(m_data, dict):
            continue

        target = cfg.main_model if m_type == "main_model" else cfg.cheap_model

        # 引用式：provider/p_name + model/m_name/model_name
        p_name = str(m_data.get("provider") or m_data.get("p_name") or "").strip()
        m_name = str(m_data.get("model") or m_data.get("m_name") or "").strip()
        is_ref = bool(p_name and m_name)
        target.provider = p_name if is_ref else ""
        target.ref_model = m_name if is_ref else ""

        if is_ref:
            resolved = _resolve_ref_model(p_name, m_name)
            if resolved:
                target.api_key = str(resolved.get("api_key") or "")
                target.api_url = str(resolved.get("api_url") or "")
                target.model_name = str(resolved.get("model") or m_name)
                target.options = dict(resolved.get("options") or {})
                if resolved.get("max_context_tokens"):
                    target.max_context_tokens = int(resolved["max_context_tokens"])
                if resolved.get("max_output_tokens"):
                    # 自动填充按窗口比例限幅（显式 max_tokens 在下方覆盖，仍优先）
                    _ctx_for_cap = int(resolved.get("max_context_tokens") or target.max_context_tokens or 0)
                    _auto_cap = auto_max_tokens_cap(_ctx_for_cap)
                    target.max_tokens = min(int(resolved["max_output_tokens"]), _auto_cap)
                eff = resolved.get("reasoning_effort") or "auto"
                if isinstance(eff, str) and eff and eff != "auto":
                    target.options.setdefault("reasoning_effort", eff)
            else:
                # provider.yaml 缺失/未收录：退化为仅内嵌（允许 config 自带 url/key 兜底）
                target.api_key = str(m_data.get("api_key") or "")
                target.api_url = str(m_data.get("api_url") or "")
                target.model_name = m_name
                target.options = dict(m_data["options"]) if isinstance(m_data.get("options"), dict) else {}
        else:
            target.api_key = str(m_data.get("api_key") or "")
            target.api_url = str(m_data.get("api_url") or "")
            target.model_name = str(m_data.get("model_name") or "")
            target.options = dict(m_data["options"]) if isinstance(m_data.get("options"), dict) else {}

        target.temperature = float(m_data.get("temperature", target.temperature))
        target.max_tokens = int(m_data.get("max_tokens", target.max_tokens))
        target.top_p = float(m_data.get("top_p", target.top_p))
        target.max_context_tokens = int(m_data.get("max_context_tokens", target.max_context_tokens))
        # 工具暴露档位（auto=按窗口推导；显式档位优先）
        tp_val = m_data.get("tool_profile")
        if isinstance(tp_val, str) and tp_val.strip():
            target.tool_profile = tp_val.strip().lower()
        # 引用式下允许内联 options 覆盖（合并而非整体替换，避免丢 resolve 能力标记）
        if is_ref and isinstance(m_data.get("options"), dict):
            target.options.update({k: v for k, v in m_data["options"].items() if v is not None})
        # 引用式下内联 api_key/api_url/model_name 显式覆盖（少用；供 provider 未收录时兜底）
        if is_ref:
            if m_data.get("api_key"):
                target.api_key = str(m_data["api_key"])
            if m_data.get("api_url"):
                target.api_url = str(m_data["api_url"])
            if m_data.get("model_name"):
                target.model_name = str(m_data["model_name"])
        # 模型级 token budget 配置（Codex 风格：不同模型不同预算策略）
        tb = m_data.get("token_budget")
        if isinstance(tb, dict):
            target.token_budget = {
                k: v
                for k, v in tb.items()
                if k
                in (
                    "reminder_threshold",
                    "reminder_message_template",
                    "guidance_message",
                    "fallback_buffer_tokens",
                    "auto_compact_fallback_prompt",
                )
            }


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
            cfg.mode_params[mode_name] = {k: v for k, v in mode_cfg.items() if k in ("temperature", "max_tokens", "top_p")}


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
        cfg.paths.storage_scope = str(paths_data.get("storage_scope", cfg.paths.storage_scope)).strip().lower()
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

    # 出站附加请求头：{host 模式: {头名: 值}}；非法条目在注入时被丢弃（见 api_headers）
    _raw_headers = data.get("api_headers")
    if isinstance(_raw_headers, dict):
        cfg.api_headers = {str(pattern): dict(headers) for pattern, headers in _raw_headers.items() if isinstance(headers, dict)}
    elif _raw_headers is not None:
        logger.warning("config: api_headers 需要是 {host: {header: value}} 映射，已忽略")

    # opencode_session_header 开关（字符串 "false"/"0"/"no" 也视为关闭）
    _oc = data.get("opencode_session_header", cfg.opencode_session_header)
    if isinstance(_oc, str):
        cfg.opencode_session_header = _oc.strip().lower() in ("true", "1", "yes", "on")
    else:
        cfg.opencode_session_header = bool(_oc)
    val = data.get("enable_thinking", cfg.enable_thinking)
    if isinstance(val, str):
        cfg.enable_thinking = val.lower() in ("true", "1", "yes")
    else:
        cfg.enable_thinking = bool(val)
    cfg.thinking_strength = float(data.get("thinking_strength", cfg.thinking_strength))
    # reasoning_effort 值域校验：非法值回退 "auto"（自动推导，不显式下发）
    _effort = str(data.get("reasoning_effort", cfg.reasoning_effort)).strip().lower()
    cfg.reasoning_effort = _effort if _effort in REASONING_EFFORT_VALUES else "auto"


def _parse_token_params(cfg: AgentConfig, data: dict) -> None:
    """解析Token优化参数。

    Args:
        cfg: AgentConfig实例
        data: 配置数据字典
    """
    cfg.keep_turns = int(data.get("keep_turns", cfg.keep_turns))
    cfg.max_tool_output = int(data.get("max_tool_output", cfg.max_tool_output))
    cfg.max_assistant_content = int(data.get("max_assistant_content", cfg.max_assistant_content))
    cfg.rc_keep_steps = int(data.get("rc_keep_steps", cfg.rc_keep_steps))


def _parse_control_params(cfg: AgentConfig, data: dict) -> None:
    """解析交互控制参数。

    Args:
        cfg: AgentConfig实例
        data: 配置数据字典
    """
    # 打断知识闭环配置节（M4）：合并 yaml 覆盖默认值
    if isinstance(data.get("interruption"), dict):
        cfg.interruption = {**cfg.interruption, **data["interruption"]}
    cfg.memory_extraction_threshold = int(data.get("memory_extraction_threshold", cfg.memory_extraction_threshold))
    cfg.memory_dedup_threshold = float(data.get("memory_dedup_threshold", cfg.memory_dedup_threshold))
    cfg.chat_page_size = int(data.get("chat_page_size", cfg.chat_page_size))
    cfg.history_l2_max = int(data.get("history_l2_max", cfg.history_l2_max))
    cfg.history_l3_batch = int(data.get("history_l3_batch", cfg.history_l3_batch))
    cfg.l2_thinking_max_chars = int(data.get("l2_thinking_max_chars", cfg.l2_thinking_max_chars))
    cfg.l2_max_chars = int(data.get("l2_max_chars", cfg.l2_max_chars))

    # API 弹性参数（网络中断/睡眠恢复容错）
    cfg.api_request_timeout = float(data.get("api_request_timeout", cfg.api_request_timeout))
    cfg.api_connect_timeout = float(data.get("api_connect_timeout", cfg.api_connect_timeout))
    cfg.api_max_retries = int(data.get("api_max_retries", cfg.api_max_retries))
    cfg.api_retry_backoff = float(data.get("api_retry_backoff", cfg.api_retry_backoff))
    cfg.api_sleep_recovery_wait = float(data.get("api_sleep_recovery_wait", cfg.api_sleep_recovery_wait))


def _resolve_save_path(config_path: str | None) -> str:
    """解析配置文件保存路径。

    Args:
        config_path: 指定的保存路径

    Returns:
        实际保存路径
    """
    global _last_config_path

    return config_path or _last_config_path or str(Path.home() / ".tea_agent" / "config.yaml")


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
    """保存配置 → 写入 provider.yaml（roles + settings 段）。

    config.yaml 已删除：不再产生任何 YAML 配置文件。角色绑定（main/cheap）
    与运行时参数分别在 provider.yaml 的 ``roles`` / ``settings`` 段。

    Args:
        cfg: AgentConfig 实例
        config_path: 忽略（保留签名以兼容既有调用方）

    Returns:
        写入的目标文件路径（provider.yaml）；失败返回空串
    """
    try:
        from tea_agent.provider_store import get_provider_store

        store = get_provider_store()
        for role_key, m in (("main", cfg.main_model), ("cheap", cfg.cheap_model)):
            if m is None:
                continue
            provider, ref = m.provider, m.ref_model
            # 内嵌式配置（如 Web /api/model 热切换）无显式绑定 → 按 api_url 反查补齐；
            # 另：model_name 才是"当前实际模型"，ref_model 陈旧时以它为准
            # （switch_model 只改 model_name，不清旧 ref_model）
            if not provider and m.api_url:
                provider = store.provider_name_for_url(m.api_url)
            if m.model_name and ref != m.model_name:
                ref = m.model_name
            if provider and ref:
                m.provider, m.ref_model = provider, ref
                store.set_role(role_key, provider, ref, api_url=m.api_url)
        store.update_settings(_prepare_settings_data(cfg))
        with _config_lock:
            _config_cache = cfg
            cfg._config_source = str(store.file_path)
        return str(store.file_path)
    except Exception as e:
        logger.warning("保存运行时配置到 provider.yaml 失败: %s", e)
        return ""


def _prepare_settings_data(cfg: AgentConfig) -> dict:
    """导出运行时参数（原 config.yaml 顶层标量 + paths + interruption）。

    Args:
        cfg: AgentConfig 实例

    Returns:
        可直接并入 provider.yaml ``settings`` 段的字典（不含 providers/roles）
    """
    data: dict = {}
    _prepare_session_data(cfg, data)
    _prepare_token_data(cfg, data)
    _prepare_control_data(cfg, data)
    _prepare_paths_data(cfg, data)
    return data


def _prepare_model_data(cfg: AgentConfig, data: dict) -> None:
    """准备模型配置数据。

    引用式模型（provider+model）保存为 p_name+m_name 组合，密钥/端点不内嵌；
    传统完整块保持原样写回（向后兼容）。用户对引用式模型的本地覆盖
    （temperature/top_p/max_tokens/max_context/options 与 provider.yaml 默认不同者）
    会以覆盖字段保留；api_key 若被修改则同步回写 provider.yaml。

    Args:
        cfg: AgentConfig实例
        data: 配置数据字典（会被修改）
    """
    for m_type in ["main_model", "cheap_model"]:
        target = cfg.main_model if m_type == "main_model" else cfg.cheap_model
        if target.is_reference:
            m_data = _prepare_ref_model_data(target)
            if m_data is not None:
                data[m_type] = m_data
            continue
        if target.is_configured:
            m_data = {
                "api_key": target.api_key,
                "api_url": target.api_url,
                "model_name": target.model_name,
            }
            if target.temperature != 0.7:
                m_data["temperature"] = target.temperature
            if target.max_tokens != 131072:  # 与 dataclass 默认一致，避免模板 4096 被写漏
                m_data["max_tokens"] = target.max_tokens
            if target.top_p != 0.9:
                m_data["top_p"] = target.top_p
            if target.options:
                m_data["options"] = target.options
            if target.max_context_tokens:
                m_data["max_context_tokens"] = target.max_context_tokens
            if target.tool_profile and target.tool_profile != "auto":
                m_data["tool_profile"] = target.tool_profile
            if target.token_budget:
                m_data["token_budget"] = target.token_budget
            data[m_type] = m_data


def _prepare_ref_model_data(target: ModelConfig) -> dict | None:
    """把引用式 ModelConfig 序列化为 {provider, model, ...覆盖}。

    规则：
      - 基础键 provider/model 恒写；
      - temperature/top_p 与 dataclass 默认不同才写；
      - max_tokens/max_context_tokens/options 与 provider.yaml 解析默认不同才写（覆盖）；
      - api_key 若与 provider.yaml 默认不同 → 同步回写 provider.yaml（config 永不内嵌密钥）；
      - provider.yaml 无法解析该组合时（provider 被删/未收录）→ 返回 None，由调用方走完整块。

    Args:
        target: 引用式 ModelConfig

    Returns:
        dict | None
    """
    resolved = _resolve_ref_model(target.provider, target.ref_model)
    if resolved is None:
        # provider 已从 provider.yaml 移除 → 退化完整块保留既有密钥（不丢配置）
        if target.is_configured:
            return None
        return {"provider": target.provider, "model": target.ref_model}

    m_data: dict[str, Any] = {
        "provider": target.provider,
        "model": target.ref_model,
    }
    if target.temperature != 0.7:
        m_data["temperature"] = target.temperature
    if target.top_p != 0.9:
        m_data["top_p"] = target.top_p
    # 与 provider.yaml 解析默认对比，仅保留差异覆盖
    if target.max_tokens != int(resolved.get("max_output_tokens") or 131072):
        m_data["max_tokens"] = target.max_tokens
    if target.max_context_tokens and int(resolved.get("max_context_tokens") or 0) != target.max_context_tokens:
        m_data["max_context_tokens"] = target.max_context_tokens
    # tool_profile 为使用侧配置（非 provider 能力）：显式设置才写入覆盖
    if target.tool_profile and target.tool_profile != "auto":
        m_data["tool_profile"] = target.tool_profile
    res_opts = resolved.get("options") or {}
    diff_opts = {k: v for k, v in (target.options or {}).items() if res_opts.get(k) != v}
    if diff_opts:
        m_data["options"] = diff_opts
    if target.token_budget:
        m_data["token_budget"] = target.token_budget
    # api_key 差异 → 同步 provider.yaml（引用式下密钥归属 provider 条目）
    if target.api_key and target.api_key != (resolved.get("api_key") or ""):
        try:
            from tea_agent.provider_store import get_provider_store

            get_provider_store().upsert_provider(target.provider, {"api_key": target.api_key})
        except Exception as e:
            logger.warning("api_key sync to provider.yaml failed: %s", e)
    return m_data


def _prepare_paths_data(cfg: AgentConfig, data: dict) -> None:
    """准备路径配置数据。

    Args:
        cfg: AgentConfig实例
        data: 配置数据字典（会被修改）
    """
    data["paths"] = {
        "data_dir": cfg.paths.data_dir,
        "db_path": cfg.paths.db_path,
        "storage_scope": cfg.paths.storage_scope,
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
    data["rc_keep_steps"] = cfg.rc_keep_steps


def _prepare_control_data(cfg: AgentConfig, data: dict) -> None:
    """准备交互控制参数数据。

    Args:
        cfg: AgentConfig实例
        data: 配置数据字典（会被修改）
    """
    data["memory_extraction_threshold"] = cfg.memory_extraction_threshold
    data["memory_dedup_threshold"] = cfg.memory_dedup_threshold
    data["chat_page_size"] = cfg.chat_page_size
    data["history_l2_max"] = cfg.history_l2_max
    data["history_l3_batch"] = cfg.history_l3_batch
    data["l2_thinking_max_chars"] = cfg.l2_thinking_max_chars
    data["l2_max_chars"] = cfg.l2_max_chars
    data["interruption"] = cfg.interruption


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
    global _config_cache, _last_config_path, _active_config_path
    with _config_lock:
        current = _last_config_path or _active_config_path
        cached_src = getattr(_config_cache, "_config_source", None) if _config_cache else None
        path_changed = bool(current and cached_src and os.path.abspath(current) != os.path.abspath(cached_src))
        if _config_cache is None or reload or path_changed:
            _config_cache = load_config()
        return _config_cache
