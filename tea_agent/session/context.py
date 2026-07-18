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
    reasoning_effort: str = "auto"  # "auto"/"low"/"medium"/"high"

    # ── 客户端 ──
    client: OpenAI | None = None
    cheap_client: OpenAI | None = None
    cheap_model: str = ""

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
    no_stream_chunk: bool = False

    # ── 运行时状态 ──
    interface_type: str = ""
    _thinking_supported: bool | None = True
    _cheap_thinking_supported: bool | None = None
    _last_usage: dict[str, int] = field(default_factory=lambda: {
        "total_tokens": 0, "prompt_tokens": 0, "completion_tokens": 0,
        "prompt_cache_hit_tokens": 0, "prompt_cache_miss_tokens": 0,
    })
    _last_cheap_usage: dict[str, int] = field(default_factory=lambda: {
        "total_tokens": 0, "prompt_tokens": 0, "completion_tokens": 0,
        "prompt_cache_hit_tokens": 0, "prompt_cache_miss_tokens": 0,
    })
    _injected_memories_text: str = ""
    _injected_memories: list[dict] = field(default_factory=list)
    _injected_os_info_text: str = ""
    _os_info_injected: bool = False
    _history_summary: str = ""
    _semantic_summary: str = ""
    _tool_chain_summary: str = ""
    _level2: list[dict] = field(default_factory=list)
    _current_trace: Any = None
    reflection_manager: Any = None
    _current_mode: str = "mixed"

    # ── 额外迭代 ──
    extra_iterations_on_continue: int = 5


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
