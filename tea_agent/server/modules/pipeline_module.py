"""
PipelineModule — 热重载 Pipeline 模块。

管理后处理流水线（语义摘要、主题摘要、工具链摘要）。
热重载时重新导入 agent_pipeline 模块。
依赖：agent
"""

from __future__ import annotations

import logging
from typing import Any

from ..module import HotReloadModule, ModuleRegistry, _module_path_for

logger = logging.getLogger("hot_reload.pipeline")


class PipelineModule(HotReloadModule):
    """Pipeline 热重载模块。

    封装 agent_pipeline.py 中的后处理函数。
    热重载时重新导入 agent_pipeline 模块。
    """

    name: str = "pipeline"
    dependencies: list[str] = ["agent"]

    _do_async_summaries: Any = None  # 函数引用
    _auto_summary: Any = None
    _l2_to_l3_summary: Any = None

    @classmethod
    def _load(cls, registry: ModuleRegistry) -> bool:
        """加载 Pipeline 模块。"""
        from tea_agent import agent_pipeline

        cls._do_async_summaries = agent_pipeline.do_async_summaries
        cls._auto_summary = agent_pipeline.auto_summary
        cls._l2_to_l3_summary = agent_pipeline.l2_to_l3_summary

        logger.info("Pipeline loaded")
        return True

    @classmethod
    def _unload(cls) -> None:
        """卸载 Pipeline 模块。"""
        cls._do_async_summaries = None
        cls._auto_summary = None
        cls._l2_to_l3_summary = None

    @classmethod
    def run_async_summaries(cls, agent_proxy: Any, topic_id: str,
                            overflow_items: list | None = None,
                            should_summarize: bool = False) -> None:
        """运行异步摘要（后台线程调用）。"""
        if cls._do_async_summaries:
            cls._do_async_summaries(agent_proxy, topic_id,
                                     overflow_items, should_summarize)

    @classmethod
    def run_auto_summary(cls, agent: Any, topic_id: str) -> tuple:
        """运行自动主题摘要。"""
        if cls._auto_summary:
            return cls._auto_summary(agent, topic_id)
        return None, {}


_module_path_for(PipelineModule)
