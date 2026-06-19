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


def _empty_usage():
    return {"total_tokens": 0, "prompt_tokens": 0, "completion_tokens": 0}


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
        _sum, _usage = auto_summary(agent, topic_id)
        if _usage and _usage.get("total_tokens", 0) > 0:
            agent._db.accumulate_pending_cheap_tokens(topic_id, _usage)
        if should_summarize and overflow_items:
            _sum2, _usage2 = l2_to_l3_summary(agent, topic_id, overflow_items)
            if _usage2 and _usage2.get("total_tokens", 0) > 0:
                agent._db.accumulate_pending_cheap_tokens(topic_id, _usage2)
    except Exception as e:
        logger.warning(f"异步摘要失败: {e}")


def l2_to_l3_summary(agent, topic_id: str, overflow_items: list) -> tuple:
    """将溢出的 L2 条目 + 现有 L3 摘要合并，生成新的 L3 语义摘要。
    
    Args:
        agent: Agent 实例
        topic_id: 主题 ID
        overflow_items: L2 溢出条目
        
    Returns:
        (new_summary: str, usage: dict)
    """
    try:
        cli, mdl = agent._sess._get_summarize_client()
        existing_l3 = agent._db.get_semantic_summary(topic_id) or ""
        extra_params = agent._sess._get_effective_params("cheap")
        new_summary, usage = agent._db.generate_l2_to_l3_summary(
            topic_id, overflow_items, existing_l3, cli, mdl,
            extra_params=extra_params,
        )
        if new_summary and hasattr(agent._sess, 'context'):
            agent._sess.context._semantic_summary = new_summary
        logger.info(f"L2→L3 摘要完成: topic={topic_id}")
        return new_summary, usage
    except Exception as e:
        logger.warning(f"L2→L3 摘要失败: {e}")
        return "", _empty_usage()


def auto_summary(agent, topic_id: str) -> tuple:
    """自动生成主题摘要。
    
    Args:
        agent: Agent 实例
        topic_id: 主题 ID
        
    Returns:
        (summary: Optional[str], usage: dict)
    """
    tp = agent._db.get_topic(topic_id)
    if tp and (tp.get("title") or "").startswith("※"):
        return None, _empty_usage()
    recent = agent._db.get_recent_conversations(topic_id, limit=3)
    if not recent:
        return None, _empty_usage()
    try:
        cli, mdl = agent._sess._get_summarize_client()
        from tea_agent._gui._topic_summary import _generate_topic_summary
        summary, usage = _generate_topic_summary(client=cli, model=mdl, conversations=recent)
        if summary:
            agent._db.update_topic_title(topic_id, summary)
            logger.info(f"📝 主题摘要更新: {summary}")
        return summary, usage
    except Exception as e:
        logger.warning(f"自动摘要失败: {e}")
        return None, _empty_usage()
