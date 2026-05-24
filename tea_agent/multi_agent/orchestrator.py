"""
# @2026-05-27 gen by Tea Agent, 多Agent编排器

MultiAgentOrchestrator: 主编排器，负责：
1. 接收用户任务，分析并分解为子任务
2. 将子任务分发给合适的子Agent
3. 管理子Agent的并行执行
4. 收集结果并合并为最终输出

这是多Agent系统的核心协调组件。
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Dict, List, Optional, Any, Callable

from tea_agent.multi_agent.sub_agent import SubAgentWrapper, SubAgentConfig
from tea_agent.multi_agent.agent_pool import AgentPool
from tea_agent.multi_agent.task_decomposer import TaskDecomposer, SubTask
from tea_agent.multi_agent.result_aggregator import ResultAggregator

logger = logging.getLogger("multi_agent.orchestrator")


class MultiAgentOrchestrator:
    """
    多Agent编排器。
    
    作为主Agent协调多个子Agent完成复杂任务。
    
    典型用法:
        orchestrator = MultiAgentOrchestrator(
            parent_toolkit=my_toolkit,
            parent_storage=my_storage,
            parent_config=my_config,
            max_workers=4,
        )
        
        # 注册Agent类型
        orchestrator.register_agent_type("coder", role="代码编写专家")
        orchestrator.register_agent_type("reviewer", role="代码审查专家")
        
        # 执行任务（自动分解、分发、合并）
        result = orchestrator.execute(
            task="实现一个REST API用户注册功能，并进行代码审查",
            stream_callback=print,
        )
    
    支持三种执行模式：
    1. auto: 自动分解 → 并行执行 → 合并结果
    2. manual: 手动指定子任务和Agent映射
    3. single: 只用一个子Agent（退化模式）
    """
    
    ORCHESTRATOR_PROMPT = (
        "你是一个任务编排主Agent。你的职责是:\n"
        "1. 分析用户任务的复杂度\n"
        "2. 如果任务简单，直接完成\n"
        "3. 如果任务复杂，分解为子任务并委派给子Agent\n"
        "4. 子Agent完成后，整合所有结果\n\n"
        "可用的子Agent类型: {agent_types}\n\n"
        "委托工具: 使用 toolkit_delegate 将子任务委派给子Agent\n"
        "格式: toolkit_delegate(agent_name=\"...\", task=\"...\")\n\n"
        "注意: 多个独立的子任务应该同时委派以实现并行。"
    )
    
    def __init__(
        self,
        parent_toolkit: Any = None,
        parent_storage: Any = None,
        parent_config: Any = None,
        max_workers: int = 4,
        llm_client: Any = None,
        llm_model: str = "",
    ):
        """
        初始化编排器。

        Args:
            parent_toolkit: 主Agent的Toolkit实例
            parent_storage: 主Agent的Storage实例
            parent_config: 主Agent的AgentConfig实例
            max_workers: 最大并行工作线程数
            llm_client: LLM客户端（用于智能分解/合并）
            llm_model: LLM模型名
        """
        self.pool = AgentPool(
            parent_toolkit=parent_toolkit,
            parent_storage=parent_storage,
            parent_config=parent_config,
            max_workers=max_workers,
        )
        
        self.decomposer = TaskDecomposer(
            agent_types=[],
            llm_client=llm_client,
            llm_model=llm_model,
        )
        
        self.aggregator = ResultAggregator(
            llm_client=llm_client,
            llm_model=llm_model,
        )
        
        self._parent_toolkit = parent_toolkit
        self._parent_storage = parent_storage
        self._parent_config = parent_config
        self._max_workers = max_workers
        self._llm_client = llm_client
        self._llm_model = llm_model
        
        self._execution_history: List[Dict] = []
        self._lock = threading.Lock()
        
        self._register_default_types()
    
    def _register_default_types(self):
        """注册默认的子Agent类型"""
        defaults = [
            ("general", "通用助手", None),
            ("coder", "代码编写专家，擅长分析代码、编写实现、修复bug", 
             ["toolkit_file", "toolkit_exec", "toolkit_edit", "toolkit_file_replace",
              "toolkit_explr", "toolkit_search", "toolkit_read_pyproject",
              "toolkit_lsp", "toolkit_diff", "toolkit_run_tests"]),
            ("reviewer", "代码审查专家，检查代码质量、安全漏洞、性能问题",
             ["toolkit_file", "toolkit_exec", "toolkit_explr", "toolkit_search",
              "toolkit_lsp", "toolkit_diff", "toolkit_run_tests"]),
            ("analyst", "数据分析专家，收集、处理、分析数据和文件",
             ["toolkit_file", "toolkit_exec", "toolkit_explr", "toolkit_search",
              "toolkit_kb", "toolkit_memory"]),
            ("researcher", "信息检索专家，搜索文档、知识库、代码库",
             ["toolkit_file", "toolkit_explr", "toolkit_search", "toolkit_kb",
              "toolkit_memory", "toolkit_query_chat_history"]),
        ]
        
        for type_name, role, whitelist in defaults:
            self.register_agent_type(type_name, role=role, tool_whitelist=whitelist)
    
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
        注册子Agent类型模板。与 AgentPool.register_agent_type 相同。

        Args:
            type_name: 类型名称
            role: 角色描述
            system_prompt_extra: 额外提示词
            tool_whitelist: 工具白名单
            tool_blacklist: 工具黑名单
            max_iterations: 最大迭代次数
            max_history: 最大历史轮数
            **extra_config: 其他配置
        """
        self.pool.register_agent_type(
            type_name=type_name,
            role=role,
            system_prompt_extra=system_prompt_extra,
            tool_whitelist=tool_whitelist,
            tool_blacklist=tool_blacklist,
            max_iterations=max_iterations,
            max_history=max_history,
            **extra_config,
        )
        self.decomposer.agent_types.append(type_name)
    
    def execute(
        self,
        task: str,
        mode: str = "auto",
        subtasks: Optional[List[SubTask]] = None,
        agent_mapping: Optional[Dict[str, str]] = None,
        stream_callback: Optional[Callable[[str], None]] = None,
    ) -> str:
        """
        执行任务（主入口）。

        Args:
            task: 用户任务描述
            mode: 执行模式
                - "auto": 自动分解任务、创建Agent、执行、合并
                - "manual": 使用提供的 subtasks 和 agent_mapping
                - "single": 只用一个通用Agent执行（退化模式）
            subtasks: 手动指定的子任务列表（mode=manual时使用）
            agent_mapping: 手动指定的 {task_id: agent_name} 映射
            stream_callback: 可选的回调函数，接收进度信息

        Returns:
            合并后的最终结果
        """
        exec_start = time.time()
        execution_record = {
            "task": task,
            "mode": mode,
            "start_time": exec_start,
            "subtasks": [],
            "results": {},
            "final_result": "",
        }
        
        try:
            if stream_callback:
                stream_callback(f"[编排器] 开始处理任务 (mode={mode})...\n")
            
            if mode == "manual" and subtasks:
                task_list = subtasks
            elif mode == "single":
                task_list = [SubTask(
                    id="single_task",
                    description=task,
                    agent_type="general",
                    agent_role="通用助手",
                    priority=0,
                )]
            else:
                if stream_callback:
                    stream_callback("[编排器] 正在分解任务...\n")
                task_list = self.decomposer.decompose(task)
            
            execution_record["subtasks"] = [t.to_dict() for t in task_list]
            
            if stream_callback:
                stream_callback(f"[编排器] 分解为 {len(task_list)} 个子任务\n")
                for t in task_list:
                    stream_callback(f"  - {t.id}: [{t.agent_type}] {t.description[:60]}...\n")
            
            agent_tasks = self._assign_agents(task_list, agent_mapping, stream_callback)
            
            if not agent_tasks:
                return "[编排器] 没有可执行的子任务"
            
            execution_order = self.decomposer.get_execution_order(task_list)
            
            all_results: Dict[str, str] = {}
            
            for batch_idx, batch in enumerate(execution_order):
                if stream_callback:
                    stream_callback(f"\n[编排器] 执行第 {batch_idx+1}/{len(execution_order)} 批 ({len(batch)} 个子任务)...\n")
                
                batch_items = []
                for t in batch:
                    agent_name = agent_tasks.get(t.id)
                    if agent_name:
                        batch_items.append((agent_name, t.description))
                
                if not batch_items:
                    continue
                
                batch_results = self.pool.run_parallel(batch_items)
                all_results.update(batch_results)
                
                execution_record["results"].update(batch_results)
                
                if stream_callback:
                    for agent_name, result in batch_results.items():
                        short_result = result[:100] + "..." if len(result) > 100 else result
                        stream_callback(f"  [{agent_name}] ✅ {short_result}\n")
            
            if stream_callback:
                stream_callback("\n[编排器] 正在合并结果...\n")
            
            final_result = self.aggregator.aggregate(
                subtasks=task_list,
                results=all_results,
                original_task=task,
            )
            
            execution_record["final_result"] = final_result
            execution_record["elapsed"] = time.time() - exec_start
            
            with self._lock:
                self._execution_history.append(execution_record)
            
            if stream_callback:
                stream_callback(f"\n[编排器] 完成 (耗时 {execution_record['elapsed']:.1f}s)\n")
            
            return final_result
            
        except Exception as e:
            logger.error(f"编排器执行失败: {e}")
            error_msg = f"[编排器错误] {e}"
            execution_record["error"] = error_msg
            execution_record["elapsed"] = time.time() - exec_start
            
            with self._lock:
                self._execution_history.append(execution_record)
            
            return error_msg
    
    def _assign_agents(
        self,
        task_list: List[SubTask],
        agent_mapping: Optional[Dict[str, str]],
        stream_callback: Optional[Callable[[str], None]],
    ) -> Dict[str, str]:
        """
        为子任务分配Agent实例。

        策略:
        1. 如果提供了 agent_mapping，直接使用
        2. 否则按 task.agent_type 查找或动态创建
        3. 如果 agent_type 未注册，使用 "general" 类型

        Args:
            task_list: 子任务列表
            agent_mapping: 预定义的映射
            stream_callback: 回调

        Returns:
            {task_id: agent_name} 映射
        """
        if agent_mapping:
            for task_id, agent_name in agent_mapping.items():
                if self.pool.get_agent(agent_name) is None:
                    task_def = next((t for t in task_list if t.id == task_id), None)
                    agent_type = task_def.agent_type if task_def else "general"
                    self.pool.create_agent(agent_name, type_name=agent_type)
            return agent_mapping
        
        assignments: Dict[str, str] = {}
        
        for t in task_list:
            agent_name = f"agent_{t.id}"
            
            agent_type = t.agent_type if t.agent_type in self.pool._agent_types else "general"
            
            agent = self.pool.get_agent(agent_name)
            if agent is None:
                agent = self.pool.create_agent(
                    agent_name,
                    type_name=agent_type,
                    role=t.agent_role if t.agent_role else None,
                )
            
            assignments[t.id] = agent_name
        
        return assignments
    
    def execute_single(self, task: str, agent_type: str = "general") -> str:
        """
        使用单个Agent执行任务（退化模式）。

        Args:
            task: 任务描述
            agent_type: Agent类型

        Returns:
            执行结果
        """
        return self.execute(task, mode="single")
    
    def execute_manual(
        self,
        task: str,
        subtasks: List[SubTask],
        agent_mapping: Dict[str, str],
    ) -> str:
        """
        手动指定子任务和Agent映射。

        Args:
            task: 任务描述
            subtasks: 子任务列表
            agent_mapping: {task_id: agent_name}

        Returns:
            合并结果
        """
        return self.execute(
            task,
            mode="manual",
            subtasks=subtasks,
            agent_mapping=agent_mapping,
        )
    
    def get_execution_history(self) -> List[Dict]:
        """
        获取执行历史

        Returns:
            List[Dict]: Description.
        """
        with self._lock:
            return list(self._execution_history)
    
    def clear_history(self):
        """清除执行历史"""
        with self._lock:
            self._execution_history.clear()
    
    def shutdown(self):
        """关闭编排器和所有子Agent"""
        self.pool.shutdown_all()
        logger.info("MultiAgentOrchestrator 已关闭")
    
    def get_status(self) -> Dict[str, Any]:
        """
        获取编排器状态

        Returns:
            Dict[str, Any]: Description.
        """
        return {
            "active_agents": self.pool.active_agents,
            "agent_types": list(self.pool._agent_types.keys()),
            "max_workers": self._max_workers,
            "execution_count": len(self._execution_history),
            "last_execution": self._execution_history[-1] if self._execution_history else None,
        }
