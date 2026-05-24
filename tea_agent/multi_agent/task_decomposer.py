"""
# @2026-05-27 gen by Tea Agent, 任务分解器

TaskDecomposer: 将用户任务分解为可并行执行的子任务。
支持两种分解模式：
1. LLM驱动：使用LLM智能分解复杂任务
2. 规则驱动：基于预定义规则快速分解（回退方案）

子任务结构 SubTask 包含：
- 任务描述
- 所需Agent角色
- 依赖关系
- 优先级
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any

logger = logging.getLogger("multi_agent.task_decomposer")


@dataclass
class SubTask:
    """
    子任务定义。
    """
    id: str = ""
    description: str = ""
    agent_role: str = "general"
    agent_type: str = ""
    dependencies: List[str] = field(default_factory=list)
    priority: int = 0
    expected_output: str = ""
    context: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """
        转为字典

        Returns:
            Dict[str, Any]: Description.
        """
        return {
            "id": self.id,
            "description": self.description,
            "agent_role": self.agent_role,
            "agent_type": self.agent_type,
            "dependencies": self.dependencies,
            "priority": self.priority,
            "expected_output": self.expected_output,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SubTask":
        """
        从字典创建

        Args:
            data (Dict[str, Any]): Description.

        Returns:
            'SubTask': Description.
        """
        return cls(
            id=data.get("id", ""),
            description=data.get("description", ""),
            agent_role=data.get("agent_role", "general"),
            agent_type=data.get("agent_type", ""),
            dependencies=data.get("dependencies", []),
            priority=data.get("priority", 0),
            expected_output=data.get("expected_output", ""),
        )


class TaskDecomposer:
    """
    任务分解器。
    
    将用户任务分析并分解为一组可独立/有序执行的子任务。
    
    用法:
        decomposer = TaskDecomposer(agent_types=["coder", "reviewer", "tester"])
        subtasks = decomposer.decompose("实现一个用户登录功能")
    """
    
    DECOMPOSE_PROMPT = (
        "你是一个任务分解专家。请将以下用户任务分解为多个可并行或有序执行的子任务。\n\n"
        "可用的Agent角色类型: {agent_types}\n\n"
        "要求:\n"
        "1. 每个子任务应该明确、独立、可验证\n"
        "2. 标注子任务之间的依赖关系\n"
        "3. 为每个子任务分配合适的Agent角色\n"
        "4. 优先级0=最高，数字越大优先级越低\n"
        "5. 输出格式为JSON数组:\n"
        '[\n'
        '  {{\n'
        '    "id": "task_1",\n'
        '    "description": "详细的任务描述",\n'
        '    "agent_type": "对应的Agent类型",\n'
        '    "agent_role": "角色描述",\n'
        '    "dependencies": [],\n'
        '    "priority": 0,\n'
        '    "expected_output": "期望的输出结果"\n'
        '  }},\n'
        '  ...\n'
        ']\n\n'
        "请只输出JSON数组，不要包含其他文本。\n\n"
        "用户任务:\n{task}"
    )
    
    def __init__(
        self,
        agent_types: Optional[List[str]] = None,
        llm_client: Any = None,
        llm_model: str = "",
        lite_agent: Any = None,
    ):
        """
        初始化任务分解器。

        Args:
            agent_types: 可用的Agent类型列表
            llm_client: LLM客户端（用于智能分解），None则使用规则分解
            llm_model: LLM模型名
            lite_agent: LiteAgent 实例（推荐）。提供后优先使用 LiteAgent 进行分解，
                        无需额外配置 LLM 客户端。
        """
        self.agent_types = agent_types or ["general"]
        self._llm_client = llm_client
        self._llm_model = llm_model
        self._lite_agent = lite_agent
    
    def decompose(self, task: str) -> List[SubTask]:
        """
        分解任务为子任务列表。

        优先级: LiteAgent > LLM客户端 > 规则分解。
        失败时自动回退到下一级。

        Args:
            task: 用户任务描述

        Returns:
            子任务列表
        """
        # 1) 优先使用 LiteAgent
        if self._lite_agent:
            try:
                return self._decompose_with_lite_agent(task)
            except Exception as e:
                logger.warning(f"LiteAgent分解失败，尝试回退: {e}")

        # 2) 旧版 LLM 客户端
        if self._llm_client:
            try:
                return self._decompose_with_llm(task)
            except Exception as e:
                logger.warning(f"LLM分解失败，回退到规则分解: {e}")

        # 3) 规则分解
        return self._decompose_with_rules(task)
    
    def _decompose_with_llm(self, task: str) -> List[SubTask]:
        """
        使用LLM智能分解任务。

        Args:
            task: 任务描述

        Returns:
            子任务列表
        """
        prompt = self.DECOMPOSE_PROMPT.format(
            agent_types=", ".join(self.agent_types),
            task=task,
        )
        
        response = self._llm_client.chat.completions.create(
            model=self._llm_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=2048,
        )
        
        content = response.choices[0].message.content
        
        subtasks_data = self._extract_json_array(content)
        subtasks = [SubTask.from_dict(item) for item in subtasks_data]
        
        if not subtasks:
            logger.warning("LLM分解返回空结果，回退到规则分解")
            return self._decompose_with_rules(task)
        
        logger.info(f"LLM分解完成: {len(subtasks)} 个子任务")
        return subtasks

    def _decompose_with_lite_agent(self, task: str) -> List[SubTask]:
        """
        使用 LiteAgent 智能分解任务（推荐方式）。

        LiteAgent 无需额外的 LLM 客户端配置，
        直接使用已配置好的 LiteAgent 实例进行分解。

        Args:
            task: 任务描述

        Returns:
            子任务列表
        """
        prompt = self.DECOMPOSE_PROMPT.format(
            agent_types=", ".join(self.agent_types),
            task=task,
        )

        # LiteAgent.run() 直接返回文本结果
        content = self._lite_agent.run(prompt)

        subtasks_data = self._extract_json_array(content)
        subtasks = [SubTask.from_dict(item) for item in subtasks_data]

        if not subtasks:
            logger.warning("LiteAgent分解返回空结果，回退到规则分解")
            return self._decompose_with_rules(task)

        logger.info(f"LiteAgent分解完成: {len(subtasks)} 个子任务")
        return subtasks
    
    def _decompose_with_rules(self, task: str) -> List[SubTask]:
        """
        基于规则的简单任务分解。

        识别关键词，生成预定义模式的子任务。

        Args:
            task: 任务描述

        Returns:
            子任务列表
        """
        task_lower = task.lower()
        subtasks = []
        counter = [0]
        
        def _next_id(prefix: str = "task") -> str:
            """
            Next id.

            Args:
                prefix (str): Description.

            Returns:
                str: Description.
            """
            counter[0] += 1
            return f"{prefix}_{counter[0]}"
        
        if any(kw in task_lower for kw in ['代码', 'code', '实现', '编写', '写', '开发', '函数', '类', '模块']):
            subtasks.append(SubTask(
                id=_next_id(),
                description=f"分析需求并设计方案: {task}",
                agent_type="general",
                agent_role="系统架构师",
                priority=0,
                expected_output="设计方案和实现步骤",
            ))
            subtasks.append(SubTask(
                id=_next_id(),
                description=f"编写代码实现: {task}",
                agent_type="coder",
                agent_role="代码实现专家",
                dependencies=[subtasks[-1].id],
                priority=1,
                expected_output="可运行的代码",
            ))
            if any(kw in task_lower for kw in ['测试', 'test', '验证', '检查', '审查']):
                subtasks.append(SubTask(
                    id=_next_id(),
                    description=f"代码审查与测试: {task}",
                    agent_type="reviewer",
                    agent_role="代码审查专家",
                    dependencies=[subtasks[-1].id],
                    priority=2,
                    expected_output="审查报告和测试结果",
                ))
        
        elif any(kw in task_lower for kw in ['文件', 'file', '数据', 'data', '处理', '分析', '日志', '配置']):
            subtasks.append(SubTask(
                id=_next_id(),
                description=f"数据收集与检查: {task}",
                agent_type="general",
                agent_role="数据分析师",
                priority=0,
                expected_output="收集到的数据和初步分析",
            ))
            subtasks.append(SubTask(
                id=_next_id(),
                description=f"处理与生成结果: {task}",
                agent_type="general",
                agent_role="数据处理专家",
                dependencies=[subtasks[-1].id],
                priority=1,
                expected_output="处理后的结果和报告",
            ))
        
        elif any(kw in task_lower for kw in ['搜索', 'search', '查找', 'find', '查询', 'query']):
            subtasks.append(SubTask(
                id=_next_id(),
                description=f"搜索与信息收集: {task}",
                agent_type="general",
                agent_role="信息检索专家",
                priority=0,
                expected_output="搜索结果和相关信息",
            ))
        
        if not subtasks:
            subtasks.append(SubTask(
                id=_next_id(),
                description=task,
                agent_type="general",
                agent_role="通用助手",
                priority=0,
                expected_output="任务完成结果",
            ))
        
        logger.info(f"规则分解完成: {len(subtasks)} 个子任务")
        return subtasks
    
    def _extract_json_array(self, text: str) -> List[Dict]:
        """
        从文本中提取JSON数组。

        Args:
            text: 可能包含JSON的文本

        Returns:
            解析后的字典列表
        """
        start = text.find('[')
        end = text.rfind(']')
        
        if start != -1 and end != -1 and end > start:
            json_str = text[start:end + 1]
            try:
                return json.loads(json_str)
            except json.JSONDecodeError:
                pass
        
        match = re.search(r'```(?:json)?\s*(\[.*?\])\s*```', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass
        
        logger.warning(f"无法从LLM输出中提取JSON数组: {text[:200]}...")
        return []
    
    def get_execution_order(self, subtasks: List[SubTask]) -> List[List[SubTask]]:
        """
        根据依赖关系计算执行顺序（拓扑排序）。

        Args:
            subtasks: 子任务列表

        Returns:
            按执行顺序分组的子任务列表，每批可并行执行
        """
        in_degree = {t.id: len(t.dependencies) for t in subtasks}
        dependents = {t.id: [] for t in subtasks}
        
        for t in subtasks:
            for dep_id in t.dependencies:
                if dep_id in dependents:
                    dependents[dep_id].append(t.id)
        
        batches = []
        remaining = set(t.id for t in subtasks)
        
        while remaining:
            ready = [t for t in subtasks if t.id in remaining and in_degree[t.id] == 0]
            
            if not ready:
                logger.warning("检测到循环依赖，强制排序")
                ready = [t for t in subtasks if t.id in remaining]
            
            batches.append(ready)
            
            for t in ready:
                remaining.discard(t.id)
                for dep_id in dependents.get(t.id, []):
                    in_degree[dep_id] = max(0, in_degree[dep_id] - 1)
            
            if not remaining:
                break
        
        return batches
