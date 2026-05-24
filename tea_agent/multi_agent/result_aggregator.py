"""
# @2026-05-27 gen by Tea Agent, 结果合并器

ResultAggregator: 收集和合并多个子Agent的执行结果。
支持：
- 按任务依赖关系合并
- LLM驱动的智能合并（综合分析各子Agent输出）
- 简单拼接合并（回退方案）
- 结果摘要生成
"""

from __future__ import annotations

import json
import logging
from typing import Dict, List, Optional, Any, Callable

from tea_agent.multi_agent.task_decomposer import SubTask

logger = logging.getLogger("multi_agent.result_aggregator")


class ResultAggregator:
    """
    结果合并器。
    
    收集所有子Agent的执行结果，进行整合和总结。
    
    用法:
        aggregator = ResultAggregator()
        final_result = aggregator.aggregate(
            subtasks=subtasks,
            results={"task_1": "结果1", "task_2": "结果2"},
            original_task="原始任务描述",
        )
    """
    
    AGGREGATE_PROMPT = (
        "你是一个结果整合专家。请根据以下子任务结果，生成一份综合报告。\n\n"
        "原始任务: {original_task}\n\n"
        "子任务及结果:\n"
        "{subtask_results}\n\n"
        "要求:\n"
        "1. 整合所有子任务的结果\n"
        "2. 指出关键发现和结论\n"
        "3. 如果有不一致的地方，明确指出\n"
        "4. 生成结构化的最终报告\n"
        "5. 如果子任务失败，说明失败原因和影响\n\n"
        "请直接输出整合后的结果。"
    )
    
    SUMMARY_PROMPT = (
        "请对以下结果进行一句话摘要（不超过100字）:\n"
        "{content}"
    )
    
    def __init__(
        self,
        llm_client: Any = None,
        llm_model: str = "",
    ):
        """
        初始化结果合并器。

        Args:
            llm_client: LLM客户端（用于智能合并）
            llm_model: LLM模型名
        """
        self._llm_client = llm_client
        self._llm_model = llm_model
    
    def aggregate(
        self,
        subtasks: List[SubTask],
        results: Dict[str, str],
        original_task: str = "",
    ) -> str:
        """
        合并所有子任务结果。

        Args:
            subtasks: 子任务列表
            results: {task_id: result_text} 字典
            original_task: 原始用户任务

        Returns:
            合并后的综合结果
        """
        if not results:
            return "[无子任务结果]"
        
        if len(results) == 1:
            return list(results.values())[0]
        
        if self._llm_client:
            try:
                return self._aggregate_with_llm(subtasks, results, original_task)
            except Exception as e:
                logger.warning(f"LLM合并失败，回退到简单合并: {e}")
        
        return self._aggregate_simple(subtasks, results, original_task)
    
    def _aggregate_with_llm(
        self,
        subtasks: List[SubTask],
        results: Dict[str, str],
        original_task: str,
    ) -> str:
        """
        使用LLM智能合并结果。

        Args:
            subtasks: 子任务列表
            results: 结果字典
            original_task: 原始任务

        Returns:
            合并结果
        """
        parts = []
        for t in subtasks:
            result_text = results.get(t.id, "[未完成]")
            status = "✅" if t.id in results else "❌"
            parts.append(
                f"### {status} 子任务 {t.id}: {t.agent_role}\n"
                f"描述: {t.description}\n"
                f"结果:\n{result_text}\n"
            )
        
        subtask_results_text = "\n---\n".join(parts)
        
        prompt = self.AGGREGATE_PROMPT.format(
            original_task=original_task,
            subtask_results=subtask_results_text,
        )
        
        response = self._llm_client.chat.completions.create(
            model=self._llm_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=4096,
        )
        
        return response.choices[0].message.content
    
    def _aggregate_simple(
        self,
        subtasks: List[SubTask],
        results: Dict[str, str],
        original_task: str,
    ) -> str:
        """
        简单拼接合并（无LLM时使用）。

        Args:
            subtasks: 子任务列表
            results: 结果字典
            original_task: 原始任务

        Returns:
            合并结果
        """
        parts = [f"# 任务执行报告\n\n> 原始任务: {original_task}\n"]
        
        task_map = {t.id: t for t in subtasks}
        
        ordered_tasks = self._order_by_deps(subtasks)
        
        for t in ordered_tasks:
            result = results.get(t.id, "[未完成]")
            status = "✅" if t.id in results else "⚠️"
            parts.append(f"## {status} {t.id}: {t.agent_role}")
            parts.append(f"**任务**: {t.description}")
            parts.append(f"**结果**:\n{result}\n")
        
        completed = len([r for r in results.values() if not r.startswith("[")])
        total = len(subtasks)
        parts.append(f"---\n**执行统计**: {completed}/{total} 个子任务成功完成")
        
        return "\n".join(parts)
    
    def _order_by_deps(self, subtasks: List[SubTask]) -> List[SubTask]:
        """
        按依赖关系排序子任务。

        Args:
            subtasks: 子任务列表

        Returns:
            排序后的子任务列表
        """
        from tea_agent.multi_agent.task_decomposer import TaskDecomposer
        decomposer = TaskDecomposer()
        batches = decomposer.get_execution_order(subtasks)
        
        ordered = []
        for batch in batches:
            ordered.extend(batch)
        
        return ordered
    
    def summarize_result(self, result: str, max_chars: int = 200) -> str:
        """
        对结果进行简短摘要。

        Args:
            result: 完整结果文本
            max_chars: 摘要最大字符数

        Returns:
            摘要文本
        """
        if len(result) <= max_chars:
            return result
        
        if self._llm_client:
            try:
                prompt = self.SUMMARY_PROMPT.format(content=result[:4000])
                response = self._llm_client.chat.completions.create(
                    model=self._llm_model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.2,
                    max_tokens=200,
                )
                summary = response.choices[0].message.content
                return summary[:max_chars]
            except Exception:
                pass
        
        return result[:max_chars - 3] + "..."
    
    def merge_code_results(self, results: Dict[str, str]) -> Dict[str, Any]:
        """
        专门用于合并代码相关的子任务结果。
        
        识别结果中的代码块并合并。
        
        Args:
            results: {agent_name: result_text}

        Returns:
            {"merged_code": "...", "files": {...}, "summary": "..."}
        """
        import re
        
        merged = {
            "merged_code": "",
            "files": {},
            "summary": "",
            "errors": [],
        }
        
        code_blocks = []
        summaries = []
        
        for agent_name, result in results.items():
            blocks = re.findall(r'```(?:\w+)?\n(.*?)```', result, re.DOTALL)
            for i, block in enumerate(blocks):
                code_blocks.append(f"# --- 来自 {agent_name} (block {i+1}) ---\n{block}\n")
            
            text_only = re.sub(r'```.*?```', '', result, flags=re.DOTALL)
            text_only = text_only.strip()
            if text_only:
                summaries.append(f"[{agent_name}]: {text_only[:200]}")
            
            if "错误" in result or "error" in result.lower() or "失败" in result:
                merged["errors"].append(f"{agent_name}: 检测到错误")
        
        merged["merged_code"] = "\n".join(code_blocks)
        merged["summary"] = "\n".join(summaries)
        
        return merged
