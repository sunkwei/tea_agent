"""
# @2026-05-27 gen by Tea Agent, Agent池管理

AgentPool: 管理多个子Agent实例的生命周期，支持：
- 创建/销毁子Agent
- 根据角色类型获取合适的Agent
- 批量并行执行任务
- 资源限制（最大并发数）
"""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed, Future
from typing import Dict, List, Optional, Callable, Any

from tea_agent.multi_agent.sub_agent import SubAgentWrapper, SubAgentConfig

logger = logging.getLogger("multi_agent.agent_pool")


class AgentPool:
    """
    子Agent池，管理多个子Agent实例。
    
    支持预创建Agent和动态创建Agent两种模式。
    提供批量并行执行任务的便捷接口。
    
    用法:
        pool = AgentPool(
            parent_toolkit=my_toolkit,
            parent_storage=my_storage,
            parent_config=my_config,
            max_workers=4,
        )
        
        # 预注册Agent类型
        pool.register_agent_type("coder", role="代码专家", tool_whitelist=["toolkit_file", "toolkit_exec"])
        
        # 创建实例
        agent = pool.create_agent("coder_1", "coder", extra_system_prompt="你是Python专家")
        
        # 批量执行
        results = pool.run_parallel([
            ("agent_a", "审查文件A"),
            ("agent_b", "审查文件B"),
            ("agent_c", "审查文件C"),
        ])
    """
    
    def __init__(
        self,
        parent_toolkit: Any = None,
        parent_storage: Any = None,
        parent_config: Any = None,
        max_workers: int = 4,
    ):
        """
        初始化Agent池。

        Args:
            parent_toolkit: 主Agent的Toolkit实例
            parent_storage: 主Agent的Storage实例
            parent_config: 主Agent的AgentConfig实例
            max_workers: 最大并行工作线程数
        """
        self._parent_toolkit = parent_toolkit
        self._parent_storage = parent_storage
        self._parent_config = parent_config
        self._max_workers = max_workers
        
        self._agent_types: Dict[str, SubAgentConfig] = {}
        
        self._agents: Dict[str, SubAgentWrapper] = {}
        
        self._lock = threading.Lock()
        
        self._executor: Optional[ThreadPoolExecutor] = None
    
    def register_agent_type(
        self,
        type_name: str,
        role: str = "",
        system_prompt_extra: str = "",
        tool_whitelist: Optional[List[str]] = None,
        tool_blacklist: Optional[List[str]] = None,
        max_iterations: Optional[int] = None,
        max_history: int = 5,
        **extra_config,
    ):
        """
        注册一个Agent类型模板，后续可通过 create_agent 基于模板创建实例。

        Args:
            type_name: 类型名称（唯一标识）
            role: 角色描述
            system_prompt_extra: 额外系统提示词
            tool_whitelist: 工具白名单
            tool_blacklist: 工具黑名单
            max_iterations: 最大迭代次数
            max_history: 最大历史轮数
            **extra_config: 其他 SubAgentConfig 字段
        """
        if type_name in self._agent_types:
            logger.warning(f"Agent类型 '{type_name}' 已存在，将被覆盖")
        
        config = SubAgentConfig(
            name="",
            role=role,
            system_prompt_extra=system_prompt_extra,
            tool_whitelist=tool_whitelist,
            tool_blacklist=tool_blacklist,
            max_iterations=max_iterations,
            max_history=max_history,
            **extra_config,
        )
        
        self._agent_types[type_name] = config
        logger.info(f"注册Agent类型: '{type_name}' (role={role})")
    
    def create_agent(
        self,
        agent_name: str,
        type_name: Optional[str] = None,
        config: Optional[SubAgentConfig] = None,
        **overrides,
    ) -> SubAgentWrapper:
        """
        创建一个子Agent实例。

        Args:
            agent_name: Agent实例名称（唯一标识）
            type_name: 基于已注册的类型模板创建（可选）
            config: 直接提供 SubAgentConfig（可选）
            **overrides: 覆盖模板中的字段

        Returns:
            SubAgentWrapper 实例
        """
        with self._lock:
            if agent_name in self._agents:
                logger.warning(f"Agent '{agent_name}' 已存在，返回现有实例")
                return self._agents[agent_name]
            
            if config:
                agent_config = config
            elif type_name and type_name in self._agent_types:
                template = self._agent_types[type_name]
                agent_config = SubAgentConfig(
                    name=agent_name,
                    role=template.role,
                    system_prompt_extra=template.system_prompt_extra,
                    tool_whitelist=template.tool_whitelist,
                    tool_blacklist=template.tool_blacklist,
                    max_iterations=template.max_iterations,
                    max_history=template.max_history,
                    shared_tools=template.shared_tools,
                )
            else:
                agent_config = SubAgentConfig(name=agent_name)
            
            for key, value in overrides.items():
                if hasattr(agent_config, key):
                    setattr(agent_config, key, value)
            
            agent = SubAgentWrapper(
                config=agent_config,
                parent_toolkit=self._parent_toolkit,
                parent_storage=self._parent_storage,
                parent_config=self._parent_config,
            )
            
            agent.initialize()
            self._agents[agent_name] = agent
            logger.info(f"创建Agent实例: '{agent_name}'")
            return agent
    
    def get_agent(self, agent_name: str) -> Optional[SubAgentWrapper]:
        """
        获取已创建的Agent实例。

        Args:
            agent_name: Agent名称

        Returns:
            SubAgentWrapper 或 None
        """
        return self._agents.get(agent_name)
    
    def remove_agent(self, agent_name: str):
        """
        移除并关闭一个Agent实例。

        Args:
            agent_name: Agent名称
        """
        with self._lock:
            agent = self._agents.pop(agent_name, None)
            if agent:
                agent.shutdown()
                logger.info(f"移除Agent: '{agent_name}'")
    
    def run_parallel(
        self,
        tasks: List[tuple],
        timeout_per_task: Optional[float] = None,
    ) -> Dict[str, str]:
        """
        并行执行多个子任务。

        Args:
            tasks: 任务列表，每项为 (agent_name, task_description) 或
                   (agent_name, task_description, callback)
            timeout_per_task: 每个任务的超时秒数，None=不限制

        Returns:
            {agent_name: result_text} 字典
        """
        if not tasks:
            return {}
        
        if self._executor is None:
            self._executor = ThreadPoolExecutor(max_workers=self._max_workers)
        
        futures: Dict[Future, str] = {}
        
        for task_item in tasks:
            if len(task_item) == 2:
                agent_name, task_desc = task_item
                callback = None
            elif len(task_item) >= 3:
                agent_name, task_desc, callback = task_item[:3]
            else:
                continue
            
            agent = self._agents.get(agent_name)
            if agent is None:
                logger.error(f"Agent '{agent_name}' 不存在，跳过任务: {task_desc}")
                continue
            
            agent.reset()
            future = self._executor.submit(agent.run, task_desc, callback)
            futures[future] = agent_name
        
        results: Dict[str, str] = {}
        try:
            for future in as_completed(futures, timeout=timeout_per_task):
                agent_name = futures[future]
                try:
                    result = future.result(timeout=timeout_per_task)
                    results[agent_name] = result
                except Exception as e:
                    results[agent_name] = f"[执行异常: {e}]"
                    logger.error(f"Agent '{agent_name}' 执行异常: {e}")
        except TimeoutError:
            for future, agent_name in futures.items():
                if agent_name not in results:
                    results[agent_name] = f"[超时取消]"
                    future.cancel()
        
        return results
    
    def run_batch(
        self,
        agent_names: List[str],
        task: str,
        timeout_per_task: Optional[float] = None,
    ) -> Dict[str, str]:
        """
        多个Agent执行同一个任务（用于对比或冗余）。

        Args:
            agent_names: Agent名称列表
            task: 任务描述
            timeout_per_task: 超时秒数

        Returns:
            {agent_name: result} 字典
        """
        tasks = [(name, task) for name in agent_names]
        return self.run_parallel(tasks, timeout_per_task)
    
    @property
    def active_agents(self) -> List[str]:
        """
        获取活跃Agent名称列表

        Returns:
            List[str]: Description.
        """
        with self._lock:
            return list(self._agents.keys())
    
    def shutdown_all(self):
        """关闭所有Agent和线程池"""
        with self._lock:
            for name, agent in list(self._agents.items()):
                try:
                    agent.shutdown()
                except Exception as e:
                    logger.error(f"关闭Agent '{name}' 失败: {e}")
            self._agents.clear()
        
        if self._executor:
            self._executor.shutdown(wait=False)
            self._executor = None
        
        logger.info("AgentPool 已完全关闭")
