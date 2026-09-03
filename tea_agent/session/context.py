"""
@2026-07-07 gen by tea_agent, Session 共享上下文与基类
从 onlinesession.py 提取 SessionContext + SessionComponent
"""
import logging
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from openai import OpenAI


@dataclass
class SessionContext:
    """会话共享上下文 — 所有 Component 通过此对象共享状态。"""
    # ── 核心状态 ──
    messages: list[dict] = field(default_factory=list)
    model: str = ""
    enable_thinking: bool = True
    thinking_strength: float = 0.7  # 思考强度 0.0-1.0
    reasoning_effort: str = "auto"  # "auto"=自动推导不发送 / none/minimal/low/medium/high/xhigh/max

    # ── 客户端 ──
    client: OpenAI | None = None
    cheap_client: OpenAI | None = None
    cheap_model: str = ""
    # 视觉模型客户端（会话输入含图片时自动切换；无图片时回退主模型）
    vision_client: OpenAI | None = None
    vision_model: str = ""

    # ── 工具相关 ──
    toolkit: Any = None
    tool_log: Callable[[str], None] | None = None
    _rounds_collector: list[dict] = field(default_factory=list)

    # ── 存储与记忆 ──
    storage: Any = None
    memory: Any = None
    pipeline: Any = None

    # ── 配置参数 ──
    keep_turns: int = 5
    max_tool_output: int = 128 * 1024
    max_assistant_content: int = 128 * 1024
    max_context_tokens: int = 0
    memory_extraction_threshold: int = 2
    memory_dedup_threshold: float = 0.3
    supports_vision: bool = False
    supports_reasoning: bool = True
    disable_summary: bool = False
    disable_l3: bool = False          # 仅禁用 Level 3（摘要）
    disable_l2: bool = False          # 仅禁用 Level 2（相关历史）
    no_stream_chunk: bool = False

    # ── 运行时状态 ──
    interface_type: str = ""
    _thinking_supported: bool | None = True
    _cheap_thinking_supported: bool | None = None
    _last_usage: dict[str, int] = field(default_factory=lambda: {
        "total_tokens": 0, "prompt_tokens": 0, "completion_tokens": 0,
        "prompt_cache_hit_tokens": 0, "prompt_cache_miss_tokens": 0,
    })
    # S3: 最近一次主模型请求的真实 prompt_tokens（单次值，非累计），
    # 用于校正 token_budget 启发式估算偏差（实际/估算 平滑校正）。
    _last_request_prompt_tokens: int = 0
    # S5: token 预算已用尽标志，pipeline 的 summarize 步骤检测后强制压缩。
    _token_exhausted: bool = False
    # A8: 输出感知预算（上下文溢出防线）——
    # _output_cap: 求解器（history_builder.solve_token_budget）解析出的输出 token 上限，
    #   build_api_messages 每次构建时刷新；工具循环把请求的 max_tokens 钳制到该值，
    #   保证 输入 + 输出 + 安全余量 ≤ max_context_tokens。
    _output_cap: int = 0
    # _emergency_input_budget: 400 溢出自愈后的一次性紧急输入预算（错误中揭示的
    #   真实输入规模驱动），build_api_messages 消费后即清零，触发最深本地裁剪。
    _emergency_input_budget: int = 0
    # RC 400 自愈标志：本回合曾触发 DeepSeek "reasoning_content must be passed back"
    # 400，剩余请求强制关闭 thinking（reset_session_state 清除）。
    _rc400_recovery: bool = False
    _last_cheap_usage: dict[str, int] = field(default_factory=lambda: {
        "total_tokens": 0, "prompt_tokens": 0, "completion_tokens": 0,
        "prompt_cache_hit_tokens": 0, "prompt_cache_miss_tokens": 0,
    })
    _injected_memories_text: str = ""
    _injected_memories: list[dict] = field(default_factory=list)
    _last_l0_hash: int = 0            # L0 注入内容 hash，用于去重
    _injected_os_info_text: str = ""
    _os_info_injected: bool = False
    _history_summary: str = ""
    _semantic_summary: str = ""
    _tool_chain_summary: str = ""
    _level2: list[dict] = field(default_factory=list)
    # L2 相关性过滤的"入库定型"结果（缓存友好，对齐 DSH 派生确定性）：
    # _level2_selected 在 add_user_message 时置 dirty，构建 API 消息时一次性
    # 计算并固化；工具循环内多轮请求复用同一版本，不随 current_msg 重算，
    # 避免 L2 条目 full↔summary↔消失 翻转破坏其后 L1 历史的前缀缓存。
    _level2_selected: list | None = None
    _level2_dirty: bool = True
    # 水位线裁剪的"单调 clamp"（缓存友好）：当前轮已到达的最大 ratio，
    # 用于防止校准 scale 振荡导致 tier 反复翻转破坏前缀缓存；add_user_message 时清零。
    _loop_max_ratio: float = 0.0
    # 水位线裁剪的"首建即定型"标志（缓存友好）：一旦本轮的首次构建完成裁剪并
    # 写回定型，后续同一工具循环的请求不再重复裁剪（前缀已定型），
    # 仅追加新工具结果 → 全命中前缀缓存。add_user_message 时清零。
    _loop_trim_done: bool = False
    _current_trace: Any = None
    reflection_manager: Any = None
    _current_mode: str = "mixed"

    # ── 额外迭代 ──
    extra_iterations_on_continue: int = 5

    # ── 消息队列（Steering/Follow-up） ──
    message_queue: Any = None          # MessageQueue 实例（延迟初始化）
    queue_mode: str = "one-at-a-time"  # one-at-a-time / all

    # ── 并行执行 ──
    enable_parallel: bool = True       # 是否启用并行工具执行
    max_parallel_workers: int = 4      # 最大并行线程数

    # ── 自进化 ──
    evolution_trigger: Any = None


class SessionComponent(ABC):
    """会话组件基类 — 所有功能组件继承此类。"""

    def __init__(self, context: SessionContext):
        """绑定 SessionContext 引用。"""
        self.ctx = context

    @abstractmethod
    def initialize(self) -> None:
        """子类实现：初始化组件资源。"""
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        """子类实现：返回组件唯一标识名。"""
        pass

    def save_agent_config(self, config: Any) -> None:
        """保存 Agent 配置变更到 storage。"""
        if not self.ctx.storage:
            return
        try:
            if hasattr(config, '__dict__'):
                cfg_dict = {
                    'max_iterations': getattr(config, 'max_iterations', None),
                    'keep_turns': getattr(config, 'keep_turns', None),
                    'max_tool_output': getattr(config, 'max_tool_output', None),
                    'enable_thinking': getattr(config, 'enable_thinking', None),
                }
            elif isinstance(config, dict):
                cfg_dict = config
            else:
                return
            cfg_dict = {k: v for k, v in cfg_dict.items() if v is not None}
            if cfg_dict:
                self.ctx.storage.add_config_change(
                    key="agent_config_update",
                    new_value=str(cfg_dict),
                    reason="会话中配置变更",
                )
        except Exception as e:
            logging.getLogger("session.context").debug(f"保存配置变更失败: {e}")
