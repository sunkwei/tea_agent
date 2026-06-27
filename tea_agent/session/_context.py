"""
@2026-07-07 gen by tea_agent, Session 共享上下文与基类
从 onlinesession.py 提取 SessionContext + SessionComponent
"""
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Callable
from abc import ABC, abstractmethod
from openai import OpenAI


@dataclass
class SessionContext:
    """会话共享上下文 — 所有 Component 通过此对象共享状态。"""
    # ── 核心状态 ──
    messages: List[Dict] = field(default_factory=list)
    model: str = ""
    enable_thinking: bool = True

    # ── 客户端 ──
    client: Optional[OpenAI] = None
    cheap_client: Optional[OpenAI] = None
    cheap_model: str = ""

    # ── 工具相关 ──
    toolkit: Any = None
    tool_log: Optional[Callable[[str], None]] = None
    _rounds_collector: List[Dict] = field(default_factory=list)

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
    _thinking_supported: Optional[bool] = True
    _cheap_thinking_supported: Optional[bool] = None
    _last_usage: Dict[str, int] = field(default_factory=lambda: {
        "total_tokens": 0, "prompt_tokens": 0, "completion_tokens": 0,
        "prompt_cache_hit_tokens": 0, "prompt_cache_miss_tokens": 0,
    })
    _last_cheap_usage: Dict[str, int] = field(default_factory=lambda: {
        "total_tokens": 0, "prompt_tokens": 0, "completion_tokens": 0,
        "prompt_cache_hit_tokens": 0, "prompt_cache_miss_tokens": 0,
    })
    _injected_memories_text: str = ""
    _injected_memories: List[Dict] = field(default_factory=list)
    _injected_os_info_text: str = ""
    _os_info_injected: bool = False
    _history_summary: str = ""
    _semantic_summary: str = ""
    _tool_chain_summary: str = ""
    _level2: List[Dict] = field(default_factory=list)
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
            import logging
            logging.getLogger("session.context").debug(f"保存配置变更失败: {e}")
