"""
任务评估模块 — 自动评估任务执行质量。

用法:
    from tea_agent.evaluation import TaskEvaluator

    evaluator = TaskEvaluator()
    result = evaluator.evaluate(
        task="重构 gui.py 添加类型注解",
        rounds=rounds_data,
        tools_used=["toolkit_file", "toolkit_edit", "toolkit_lsp"],
        token_cost=15000,
        time_seconds=120
    )
"""

from .task_evaluator import EvalResult, TaskEvaluator

__all__ = ["TaskEvaluator", "EvalResult"]
