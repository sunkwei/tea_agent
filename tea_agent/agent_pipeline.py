"""
Agent 后处理流水线模块 — 语义摘要、主题摘要、工具链摘要。
所有函数在后台线程执行，不阻塞主对话流程。
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("agent.pipeline")


def _empty_usage() -> dict[str, int]:
    return {"total_tokens": 0, "prompt_tokens": 0, "completion_tokens": 0}


def _merge_usage(acc: dict[str, int], new_usage: dict[str, int]) -> None:
    for k in ("total_tokens", "prompt_tokens", "completion_tokens"):
        acc[k] = acc.get(k, 0) + new_usage.get(k, 0)


def do_async_summaries(
    agent: Any,
    topic_id: str,
    overflow_items: list[dict] | None = None,
    should_summarize: bool = False,
) -> None:
    """后台线程入口：执行标题摘要 + 条件 L2→L3 摘要。"""
    pending: dict[str, int] = {}
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


def l2_to_l3_summary(
    agent: Any,
    topic_id: str,
    overflow_items: list[dict],
) -> tuple[str | None, dict[str, int]]:
    """将溢出 LR 条目通过 L3 摘要合并，生成新的 L3 语义摘要。

    步骤：
    1. 获取 cheap model 客户端
    2. 读取已有的 L3 语义摘要
    3. 调用 storage.generate_l2_to_l3_summary 将新溢出条目与旧摘要合并
    4. 更新 session context 中的语义摘要

    Args:
        agent: Agent 实例
        topic_id: 主题 ID
        overflow_items: L2 溢出条目列表

    Returns:
        (new_summary, usage):
            - new_summary: 更新后的语义摘要文本，失败时返回 ""
            - usage: token 消耗统计
    """
    try:
        cli, mdl = agent._sess._get_summarize_client()
        existing_l3 = agent._db.get_semantic_summary(topic_id) or ""
        extra_params = agent._sess._get_effective_params("cheap")
        new_summary, usage = agent._db.generate_l2_to_l3_summary(
            topic_id,
            overflow_items,
            existing_l3,
            cli,
            mdl,
            extra_params=extra_params,
        )
        if new_summary and hasattr(agent._sess, "context"):
            agent._sess.context._semantic_summary = new_summary
        logger.info(f"L2→L3 摘要完成: topic={topic_id}")
        return new_summary, usage
    except Exception as e:
        logger.warning(f"L2→L3 摘要失败: {e}")
        return "", _empty_usage()


# ── 尝试导入 GUI 主题摘要（精简版可能没有 _gui 模块）──
try:
    from tea_agent._gui._topic_summary import _generate_topic_summary  # noqa: F811

    _HAVE_GUI_TOPIC_SUMMARY = True
except ImportError:
    _HAVE_GUI_TOPIC_SUMMARY = False
    logger.debug("tea_agent._gui._topic_summary 不可用，自动主题摘要将被跳过")


def auto_summary(
    agent: Any,
    topic_id: str,
) -> tuple[str | None, dict[str, int]]:
    """自动生成主题摘要（基于最近 3 条对话生成主题标题）。

    条件：
    - 需要 GUI 模块可用（_HAVE_GUI_TOPIC_SUMMARY）
    - 跳过已有自定义标题的主题（不以特殊前缀开头）
    - 需要至少 1 条最近对话

    Args:
        agent: Agent 实例
        topic_id: 主题 ID

    Returns:
        (summary, usage):
            - summary: 生成的标题摘要字符串，无条件或失败时返回 None
            - usage: token 消耗统计
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
        summary, usage = _generate_topic_summary(
            client=cli, model=mdl, conversations=recent
        )
        if summary:
            agent._db.update_topic_title(topic_id, summary)
            logger.info(f"📝 主题摘要更新: {summary}")
        return summary, usage
    except Exception as e:
        logger.warning(f"自动摘要失败: {e}")
        return None, _empty_usage()
