"""
会话共享上下文与组件基类

SessionContext: 封装所有共享状态，消除 Mixin 隐式契约
SessionComponent: 所有组件的统一接口
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Callable
from openai import OpenAI


@dataclass
class SessionContext:
    """
    封装会话组件间的所有共享状态。
    
    替代原来 Mixin 通过 self.xxx 隐式共享属性的方式，
    改为显式通过 context 访问，提高可维护性和可测试性。
    """
    # ── 核心状态 ──
    messages: List[Dict] = field(default_factory=list)
    model: str = ""
    enable_thinking: bool = True
    
    # ── 客户端 ──
    client: Optional[OpenAI] = None
    cheap_client: Optional[OpenAI] = None
    cheap_model: str = ""
    
    # ── 工具相关 ──
    toolkit: Any = None  # Toolkit 实例
    tool_log: Optional[Callable[[str], None]] = None
    _rounds_collector: List[Dict] = field(default_factory=list)
    
    # ── 存储与记忆 ──
    storage: Any = None  # Storage 实例
    memory: Any = None   # MemoryManager 实例
    pipeline: Any = None # SessionPipeline 实例
    
    # ── 配置参数 ──
    keep_turns: int = 5
    max_tool_output: int = 128 * 1024
    max_assistant_content: int = 128 * 1024
    memory_extraction_threshold: int = 2
    memory_dedup_threshold: float = 0.3
    supports_vision: bool = False
    supports_reasoning: bool = True
    disable_summary: bool = False
    no_stream_chunk: bool = False  # True=非流式模式，方便单步调试
    
    # ── 运行时状态 ──
    _thinking_supported: Optional[bool] = True
    _cheap_thinking_supported: Optional[bool] = None
    _last_usage: Dict[str, int] = field(default_factory=lambda: {
        "total_tokens": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
    })
    _last_cheap_usage: Dict[str, int] = field(default_factory=lambda: {
        "total_tokens": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
    })
    _injected_memories_text: str = ""
    _injected_memories: List[Dict] = field(default_factory=list)
    _injected_os_info_text: str = ""
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
    """
    所有会话组件的统一接口。
    
    每个组件通过 context 访问共享状态，避免隐式依赖。
    """
    def __init__(self, context: SessionContext):
        """Initialize.
        
        Args:
            context: SessionContext 实例
        """
        self.ctx = context
    
    @abstractmethod
    def initialize(self) -> None:
        """组件初始化，设置内部状态"""
        pass
    
    @property
    @abstractmethod
    def name(self) -> str:
        """组件名称"""
        pass
