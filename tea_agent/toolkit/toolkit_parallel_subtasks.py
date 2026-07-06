## llm generated tool func, created Mon Jun  1 09:01:10 2026
# version: 1.0.0

"""
分治并发执行器

将复杂问题分解为子任务，简单任务用 lite agent 并发执行。
"""

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger("toolkit.parallel_subtasks")


def _execute_single_subtask(task: dict, timeout: int = 60, enable_thinking: bool = True) -> dict:
    """执行单个子任务（在独立线程中运行）。"""
    from tea_agent.agent import Agent

    task_id = task.get("id", "unknown")
    description = task.get("description", "")
    config_fname = task.get("config_fname")
    system_prompt = task.get("system_prompt")

    start_time = time.time()

    try:
        # 创建 lite agent（开启 thinking 以支持深度推理）
        agent = Agent(
            mode="lite",
            config_fname=config_fname,
            use_tools=True,
            enable_thinking=enable_thinking,
            use_cheap_model=True,
        )

        # 设置自定义系统提示词
        if system_prompt:
            agent._sess.system_prompt = system_prompt

        # 执行任务
        result = agent.chat(description)

        elapsed = time.time() - start_time

        return {
            "task_id": task_id,
            "status": "success" if not result.get("error") else "error",
            "result": result.get("assistant", ""),
            "thinking": result.get("thinking", ""),
            "tool_calls": result.get("tool_calls", 0),
            "error": result.get("error"),
            "elapsed": round(elapsed, 2),
            "model": agent._sess.model,
        }

    except Exception as e:
        elapsed = time.time() - start_time
        return {
            "task_id": task_id,
            "status": "error",
            "result": "",
            "thinking": "",
            "tool_calls": 0,
            "error": str(e),
            "elapsed": round(elapsed, 2),
            "model": "unknown",
        }


def toolkit_parallel_subtasks(
    subtasks: list[dict],
    max_workers: int = 5,
    timeout: int = 60,
    enable_thinking: bool = True,
) -> dict:
    """
    分治并发执行器。

    将子任务按难度分类：
    - easy: 使用 lite agent 并发执行
    - medium: 使用 lite agent 并发执行（可配置）
    - hard: 标记为需要主 agent 执行（本工具不执行）

    Args:
        subtasks: 子任务列表，每项包含 id, description, difficulty
        max_workers: 最大并发数
        timeout: 单个任务超时秒数
        enable_thinking: 是否启用推理（thinking）功能，默认 True。复杂分析任务建议开启，简单查询可关闭以提速

    Returns:
        {
            "summary": "执行摘要",
            "results": [...],  # 已完成的任务结果
            "pending_hard": [...],  # 需要主 agent 执行的困难任务
            "errors": [...],  # 失败的任务
            "stats": {"total", "easy", "medium", "hard", "success", "failed", "elapsed"}
        }
    """
    start_time = time.time()

    # 分类任务
    easy_tasks = []
    medium_tasks = []
    hard_tasks = []

    for task in subtasks:
        difficulty = task.get("difficulty", "medium")
        if difficulty == "easy":
            easy_tasks.append(task)
        elif difficulty == "medium":
            medium_tasks.append(task)
        else:
            hard_tasks.append(task)

    # 合并 easy + medium 任务用于并发执行
    parallel_tasks = easy_tasks + medium_tasks

    logger.info(
        f"任务分解: easy={len(easy_tasks)}, medium={len(medium_tasks)}, "
        f"hard={len(hard_tasks)}, 并发执行={len(parallel_tasks)}"
    )

    results = []
    errors = []

    # 并发执行 easy + medium 任务
    if parallel_tasks:
        with ThreadPoolExecutor(max_workers=min(max_workers, len(parallel_tasks))) as executor:
            future_to_task = {
                executor.submit(_execute_single_subtask, task, timeout, enable_thinking): task
                for task in parallel_tasks
            }

            for future in as_completed(future_to_task):
                task = future_to_task[future]
                try:
                    result = future.result(timeout=timeout + 5)
                    if result["status"] == "success":
                        results.append(result)
                    else:
                        errors.append(result)
                except Exception as e:
                    errors.append({
                        "task_id": task.get("id", "unknown"),
                        "status": "error",
                        "error": str(e),
                    })

    total_elapsed = time.time() - start_time

    # 构建返回结果
    success_count = len(results)
    failed_count = len(errors)

    summary_parts = [
        "分治并发执行完成",
        f"总任务: {len(subtasks)}",
        f"并发执行: {len(parallel_tasks)} (easy: {len(easy_tasks)}, medium: {len(medium_tasks)})",
        f"成功: {success_count}, 失败: {failed_count}",
        f"待主Agent执行: {len(hard_tasks)}",
        f"总耗时: {total_elapsed:.2f}s",
    ]

    return {
        "summary": " | ".join(summary_parts),
        "results": results,
        "pending_hard": hard_tasks,
        "errors": errors,
        "stats": {
            "total": len(subtasks),
            "easy": len(easy_tasks),
            "medium": len(medium_tasks),
            "hard": len(hard_tasks),
            "success": success_count,
            "failed": failed_count,
            "elapsed": round(total_elapsed, 2),
        }
    }


def meta_toolkit_parallel_subtasks() -> dict:
    return {"type": "function", "function": {"name": "toolkit_parallel_subtasks", "description": "分治并发执行器：将复杂问题分解为子任务，简单任务用 lite agent 并发执行，复杂任务由主 agent 执行，最后整合结果。\n\n适用场景：\n- 多文件代码分析\n- 批量数据处理\n- 多源信息收集\n- 并行调研任务\n\n返回：{summary, results[], errors[], stats}", "parameters": {"type": "object", "properties": {"subtasks": {"type": "array", "description": "子任务列表", "items": {"type": "object", "properties": {"id": {"type": "string", "description": "任务ID，如 'task_1'"}, "description": {"type": "string", "description": "任务描述"}, "difficulty": {"type": "string", "enum": ["easy", "medium", "hard"], "description": "难度评估：easy=lite并发, medium=可选, hard=主agent"}, "config_fname": {"type": "string", "description": "lite agent 配置文件名（可选）"}, "system_prompt": {"type": "string", "description": "lite agent 系统提示词（可选）"}}, "required": ["id", "description", "difficulty"]}, "minItems": 1}, "max_workers": {"type": "integer", "description": "最大并发数，默认 5", "default": 5}, "timeout": {"type": "integer", "description": "单个任务超时秒数，默认 60", "default": 60}, "enable_thinking": {"type": "boolean", "description": "是否启用推理（thinking）功能，默认 True。复杂分析任务建议开启，简单查询可关闭以提速", "default": True}}, "required": ["subtasks"]}}}
