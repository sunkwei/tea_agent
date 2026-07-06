# version: 1.0.0
"""
Agent 后处理流水步楽型

从 agent.py 提取的后处理逻辑：
- L2→L3 语义摔要
- 自动主题摔要
- 工具链摔要
"""

import logging

logger = logging.getLogger("agent.pipeline")


def _empty_usage():
    return {"total_tokens": 0, "prompt_tokens": 0, "completion_tokens": 0}


def _merge_usage(acc: dict, new_usage: dict):
    """合聶 usage 到 acc。"""
    for k in ("total_tokens", "prompt_tokens", "completion_tokens"):
        acc[k] = acc.get(k, 0) + new_usage.get(k, 0)


def do_async_summaries(agent, topic_id: str, overflow_items: list = None,
                       should_summarize: bool = False):
    """后台线程：执行标题摘要 + 条件 L2→L3 摘要 + 工具链摘要."""
    pending = {}
    try:
        _sum, usage = auto_summary(agent, topic_id)
        if usage and usage.get("total_tokens", 0) > 0:
            _merge_usage(pending, usage)
        if should_summarize and overflow_items:
            _sum2, usage2 = l2_to_l3_summary(agent, topic_id, overflow_items)
            if usage2 and usage2.get("total_tokens", 0) > 0:
                _merge_usage(pending, usage2)
    except Exception as e:
        logger.warning(f"异步摘要失败: {e}")
    finally:
        if pending.get("total_tokens", 0) > 0:
            agent._pending_cheap_tokens = pending


def l2_to_l3_summary(agent, topic_id: str, overflow_items: list) -> tuple:
    """将昶出 LR 条目、 玻线 L3 摘要 合回，刟绐新的 L3 语义摘要。

    Args:
        agent: Agent 实例
        topic_id: 主题 ID
        overflow_items: L2 昶出 条目

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
        logger.info(f"L2→L3 摘要 完成: topic={topic_id}")
        return new_summary, usage
    except Exception as e:
        logger.warning(f"L2→L3 摘要失败: {e}")
        return "", _empty_usage()


# 尝试导入 GUI 主题摘要（精简版可能没有 _gui 模块）
try:
    from tea_agent._gui._topic_summary import _generate_topic_summary
    _HAVE_GUI_TOPIC_SUMMARY = True
except ImportError:
    _HAVE_GUI_TOPIC_SUMMARY = False
    logger.debug("tea_agent._gui._topic_summary 不可用，自动主题摘要将被跳过")


def auto_summary(agent, topic_id: str) -> tuple:
    """自动生成主题摘要.

    Args:
        agent: Agent 实例
        topic_id: 主题 ID

    Returns:
        (summary: Optional[str], usage: dict)
    """
    if not _HAVE_GUI_TOPIC_SUMMARY:
        return None, _empty_usage()
    tp = agent._db.get_topic(topic_id)
    if tp and (tp.get("title") or "").startswith("‛"):
        return None, _empty_usage()
    recent = agent._db.get_recent_conversations(topic_id, limit=3)
    if not recent:
        return None, _empty_usage()
    try:
        cli, mdl = agent._sess._get_summarize_client()
        summary, usage = _generate_topic_summary(client=cli, model=mdl, conversations=recent)
        if summary:
            agent._db.update_topic_title(topic_id, summary)
            logger.info(f"📝 主题摘要更新: {summary}")
        return summary, usage
    except Exception as e:
        logger.warning(f"自动摘要失败: {e}")
        return None, _empty_usage()
