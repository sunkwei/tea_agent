"""
# @2026-05-27 gen by Tea Agent, 子Agent包装器

SubAgentWrapper: 封装一个独立的 OnlineToolSession 实例，提供简化的任务接口。
每个子Agent可拥有独立的配置、工具集，支持并行执行。

设计要点：
- 每个子Agent是一个独立的 OnlineToolSession
- 配置可继承自主Agent或完全独立
- 工具可通过白名单/黑名单控制访问
- 支持同步和异步两种运行模式
- 支持流式回调
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Callable, Any
from pathlib import Path

logger = logging.getLogger("multi_agent.sub_agent")


@dataclass
class SubAgentConfig:
    """
    子Agent独立配置。
    
    未设置的字段将继承自主Agent配置。
    """
    name: str = ""
    role: str = ""
    
    api_key: Optional[str] = None
    api_url: Optional[str] = None
    model_name: Optional[str] = None
    cheap_api_key: Optional[str] = None
    cheap_api_url: Optional[str] = None
    cheap_model: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    
    tool_whitelist: Optional[List[str]] = None
    tool_blacklist: Optional[List[str]] = None
    shared_tools: bool = True
    
    max_iterations: Optional[int] = None
    system_prompt_extra: str = ""
    max_history: int = 5
    
    data_dir: Optional[str] = None
    db_path: Optional[str] = None


class SubAgentWrapper:
    """
    子Agent包装器。
    
    封装一个独立的 OnlineToolSession，提供简化的 run(task) 接口。
    
    用法:
        config = SubAgentConfig(name="code_reviewer", role="代码审查专家")
        agent = SubAgentWrapper(config, parent_toolkit, parent_storage, parent_config)
        result = agent.run("审查 ./src/main.py 的代码质量")
    """
    
    DEFAULT_SYSTEM_PROMPT = (
        "你是一个子Agent，负责完成主Agent分配的特定子任务。\n"
        "角色: {role}\n\n"
        "工作原则:\n"
        "1. 专注于被分配的子任务，不要偏离范围\n"
        "2. 使用工具高效完成任务\n"
        "3. 完成后返回明确的结果，包含关键发现和结论\n"
        "4. 如果遇到无法解决的问题，清晰报告给主Agent\n"
        "{extra_prompt}"
    )
    
    def __init__(
        self,
        config: SubAgentConfig,
        parent_toolkit: Any = None,
        parent_storage: Any = None,
        parent_config: Any = None,
    ):
        """
        初始化子Agent包装器。

        Args:
            config: 子Agent配置
            parent_toolkit: 主Agent的Toolkit实例（用于工具共享）
            parent_storage: 主Agent的Storage实例
            parent_config: 主Agent的AgentConfig实例
        """
        self.config = config
        self._parent_toolkit = parent_toolkit
        self._parent_storage = parent_storage
        self._parent_config = parent_config
        
        self._session: Optional[Any] = None
        self._lock = threading.Lock()
        self._result: Optional[str] = None
        self._error: Optional[str] = None
        self._running = False
        self._done = threading.Event()
        
        self._effective_params: Dict[str, Any] = {}
        self._initialized = False
    
    def _resolve_effective_params(self) -> Dict[str, Any]:
        """
        解析实际参数：config 中设置的优先，否则继承父Agent。

        Returns:
            参数字典
        """
        pc = self._parent_config
        
        def _value(attr: str, default=None):
            """
            优先子Agent配置，回退到父Agent配置

            Args:
                attr (str): Description.
                default: Description.
            """
            val = getattr(self.config, attr, None)
            if val is not None:
                return val
            if pc is not None:
                return getattr(pc, attr, default)
            return default
        
        params = {
            "api_key": self.config.api_key or (pc.main_model.api_key if pc else ""),
            "api_url": self.config.api_url or (pc.main_model.api_url if pc else ""),
            "model": self.config.model_name or (pc.main_model.model_name if pc else ""),
            "cheap_api_key": self.config.cheap_api_key or (pc.cheap_model.api_key if pc else ""),
            "cheap_api_url": self.config.cheap_api_url or (pc.cheap_model.api_url if pc else ""),
            "cheap_model": self.config.cheap_model or (pc.cheap_model.model_name if pc else ""),
            "max_iterations": self.config.max_iterations or (pc.max_iterations if pc else 25),
            "keep_turns": self.config.max_history,
            "max_tool_output": pc.max_tool_output if pc else 128 * 1024,
            "max_assistant_content": pc.max_assistant_content if pc else 128 * 1024,
            "temperature": self.config.temperature or (pc.main_model.temperature if pc else 0.7),
            "max_tokens": self.config.max_tokens or (pc.main_model.max_tokens if pc else 4096),
            "supports_vision": pc.main_model.supports_vision if pc and hasattr(pc.main_model, 'supports_vision') else False,
            "supports_reasoning": True,
            "reasoning_effort": pc.main_model.reasoning_effort if pc and hasattr(pc.main_model, 'reasoning_effort') else "max",
            "disable_summary": True,
            "memory_extraction_threshold": 10,
            "memory_dedup_threshold": 0.3,
        }
        
        self._effective_params = params
        return params
    
    def initialize(self) -> bool:
        """
        初始化子Agent的 OnlineToolSession。

        Returns:
            是否成功
        """
        if self._initialized:
            return True
        
        try:
            from tea_agent.onlinesession import OnlineToolSession
            
            params = self._resolve_effective_params()
            
            system_prompt = self.DEFAULT_SYSTEM_PROMPT.format(
                role=self.config.role or self.config.name or "通用助手",
                extra_prompt=self.config.system_prompt_extra or "",
            )
            
            if self.config.shared_tools and self._parent_toolkit:
                toolkit = self._parent_toolkit
            else:
                toolkit = self._parent_toolkit
            
            tools = self._build_tool_list(toolkit)
            
            with self._lock:
                self._session = OnlineToolSession(
                    toolkit=toolkit,
                    api_key=params["api_key"],
                    api_url=params["api_url"],
                    model=params["model"],
                    max_history=params["keep_turns"],
                    system_prompt=system_prompt,
                    max_iterations=params["max_iterations"],
                    enable_thinking=True,
                    storage=self._parent_storage,
                    cheap_api_key=params["cheap_api_key"],
                    cheap_api_url=params["cheap_api_url"],
                    cheap_model=params["cheap_model"],
                    keep_turns=params["keep_turns"],
                    max_tool_output=params["max_tool_output"],
                    max_assistant_content=params["max_assistant_content"],
                    extra_iterations_on_continue=5,
                    memory_extraction_threshold=params["memory_extraction_threshold"],
                    memory_dedup_threshold=params["memory_dedup_threshold"],
                    supports_vision=params["supports_vision"],
                    supports_reasoning=params["supports_reasoning"],
                    reasoning_effort=params["reasoning_effort"],
                    disable_summary=params["disable_summary"],
                )
                
                if tools:
                    self._session.tools = tools
                
                self._initialized = True
                logger.info(f"子Agent '{self.config.name}' 初始化成功 (model={params['model']})")
                return True
                
        except Exception as e:
            logger.error(f"子Agent '{self.config.name}' 初始化失败: {e}")
            self._error = str(e)
            return False
    
    def _build_tool_list(self, toolkit: Any) -> List[Dict]:
        """
        根据白名单/黑名单构建子Agent可用的工具列表。

        Args:
            toolkit: Toolkit实例

        Returns:
            工具元数据列表
        """
        all_metas = getattr(toolkit, 'meta_map', {})
        
        default_blacklist = {
            'toolkit_save', 'toolkit_self_evolve', 'toolkit_release',
            'toolkit_pkg', 'toolkit_mode', 'toolkit_prompt_evolve',
            'toolkit_config', 'toolkit_toggle_reasoning',
            'toolkit_set_topic_title',
            'toolkit_git_push_all_remotes',
        }
        
        blacklist = set(default_blacklist)
        if self.config.tool_blacklist:
            blacklist.update(self.config.tool_blacklist)
        
        tools = []
        for name, meta in all_metas.items():
            if self.config.tool_whitelist and name not in self.config.tool_whitelist:
                continue
            if name in blacklist:
                continue
            tools.append(meta)
        
        return tools
    
    def run(self, task: str, callback: Optional[Callable[[str], None]] = None) -> str:
        """
        同步执行子任务，阻塞直到完成。

        Args:
            task: 任务描述（会作为用户消息发送）
            callback: 可选的流式回调函数

        Returns:
            子Agent的最终回复文本
        """
        if not self._initialized and not self.initialize():
            return f"[子Agent '{self.config.name}' 初始化失败: {self._error}]"
        
        self._running = True
        self._done.clear()
        self._result = None
        self._error = None
        
        try:
            with self._lock:
                session = self._session
                if session is None:
                    return f"[子Agent '{self.config.name}' 未初始化]"
                
                session.interrupted = False
                session.reset_interrupt()
                
                ai_msg, used_tools = session.chat_stream(task, callback or (lambda x: None))
                
                self._result = ai_msg
                return ai_msg
                
        except Exception as e:
            logger.error(f"子Agent '{self.config.name}' 执行失败: {e}")
            self._error = str(e)
            return f"[子Agent '{self.config.name}' 执行错误: {e}]"
        finally:
            self._running = False
            self._done.set()
    
    def run_async(self, task: str, callback: Optional[Callable[[str], None]] = None) -> threading.Thread:
        """
        异步执行子任务，立即返回线程对象。

        Args:
            task: 任务描述
            callback: 可选的流式回调函数

        Returns:
            执行线程
        """
        thread = threading.Thread(
            target=self.run,
            args=(task, callback),
            daemon=True,
            name=f"subagent-{self.config.name}",
        )
        thread.start()
        return thread
    
    def wait(self, timeout: Optional[float] = None) -> bool:
        """
        等待子Agent完成。

        Args:
            timeout: 超时秒数，None=无限等待

        Returns:
            是否在超时前完成
        """
        return self._done.wait(timeout=timeout)
    
    @property
    def is_running(self) -> bool:
        """
        是否正在运行

        Returns:
            bool: Description.
        """
        return self._running
    
    @property
    def is_done(self) -> bool:
        """
        是否已完成

        Returns:
            bool: Description.
        """
        return self._done.is_set()
    
    @property
    def result(self) -> Optional[str]:
        """
        获取执行结果（完成前为None）

        Returns:
            Optional[str]: Description.
        """
        return self._result
    
    @property
    def error(self) -> Optional[str]:
        """
        获取错误信息

        Returns:
            Optional[str]: Description.
        """
        return self._error
    
    def reset(self):
        """重置子Agent状态，准备下一次任务"""
        self._result = None
        self._error = None
        self._done.clear()
        self._running = False
        if self._session:
            self._session.interrupted = False
            self._session.reset_interrupt()
    
    def shutdown(self):
        """关闭子Agent会话"""
        self._running = False
        self._done.set()
        self._session = None
        self._initialized = False
        logger.info(f"子Agent '{self.config.name}' 已关闭")
