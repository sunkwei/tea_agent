# version: 1.0.0
"""
Agent 后处理流水线模块

从 agent.py 提取的后处理逻辑：
- L2→L3 语义摘要
- 自动主题摘要
- 工具链摘要
"""

import threading
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger("agent.pipeline")


def do_async_summaries(agent, topic_id: str, overflow_items: list = None,
                       should_summarize: bool = False):
    """后台线程：执行标题摘要 + 条件 L2→L3 摘要 + 工具链摘要。
    
    Args:
        agent: Agent 实例
        topic_id: 主题 ID
        overflow_items: L2 溢出条目
        should_summarize: 是否触发 L2→L3 摘要
    """
    try:
        auto_summary(agent, topic_id)
        if should_summarize and overflow_items:
            l2_to_l3_summary(agent, topic_id, overflow_items)
    except Exception as e:
        logger.warning(f"异步摘要失败: {e}")


def l2_to_l3_summary(agent, topic_id: str, overflow_items: list):
    """将溢出的 L2 条目 + 现有 L3 摘要合并，生成新的 L3 语义摘要。
    
    Args:
        agent: Agent 实例
        topic_id: 主题 ID
        overflow_items: L2 溢出条目
    """
    try:
        cli, mdl = agent._sess._get_summarize_client()
        existing_l3 = agent._db.get_semantic_summary(topic_id) or ""
        extra_params = agent._sess._get_effective_params("cheap")
        new_summary = agent._db.generate_l2_to_l3_summary(
            topic_id, overflow_items, existing_l3, cli, mdl,
            extra_params=extra_params,
        )
        if new_summary and hasattr(agent._sess, 'context'):
            agent._sess.context._semantic_summary = new_summary
        logger.info(f"L2→L3 摘要完成: topic={topic_id}")
    except Exception as e:
        logger.warning(f"L2→L3 摘要失败: {e}")


def auto_summary(agent, topic_id: str):
    """自动生成主题摘要。
    
    Args:
        agent: Agent 实例
        topic_id: 主题 ID
    """
    tp = agent._db.get_topic(topic_id)
    if tp and (tp.get("title") or "").startswith("※"):
        return
    recent = agent._db.get_recent_conversations(topic_id, limit=3)
    if not recent:
        return
    try:
        cli, mdl = agent._sess._get_summarize_client()
        from tea_agent._gui._topic_summary import _generate_topic_summary
        summary = _generate_topic_summary(client=cli, model=mdl, conversations=recent)
        if summary:
            agent._db.update_topic_title(topic_id, summary)
            logger.info(f"📝 主题摘要更新: {summary}")
    except Exception as e:
        logger.warning(f"自动摘要失败: {e}")
