"""
从 gui.py L477-572 提取：LLM 生成不超过20字的主题摘要标题
"""

import re
import json as _json_gs
import logging
from typing import Optional, List, Dict

logger = logging.getLogger(__name__)

# 从 session_prompts 导入共享 prompt 模板
from tea_agent.session_prompts import TOPIC_SUMMARY_SYSTEM, TOPIC_SUMMARY_USER_TEMPLATE


def _empty_usage():
    return {"total_tokens": 0, "prompt_tokens": 0, "completion_tokens": 0}


def _extract_usage(response):
    """从 OpenAI response 提取 usage 信息。"""
    try:
        u = response.usage
        return {
            "total_tokens": getattr(u, 'total_tokens', 0) or 0,
            "prompt_tokens": getattr(u, 'prompt_tokens', 0) or 0,
            "completion_tokens": getattr(u, 'completion_tokens', 0) or 0,
        }
    except Exception:
        return _empty_usage()


def _generate_topic_summary(client, model: str, conversations: List[Dict]) -> tuple:
    """
    根据最近1～2条用户消息通过 LLM 生成不超过20字的摘要。

    Args:
        client: OpenAI 客户端实例
        model: 模型名称
        conversations: 最近的对话列表（按时间正序），包含 user_msg 和 ai_msg

    Returns:
        (summary: Optional[str], usage: dict) 
        — summary 为 None 表示生成失败，usage 为 {'total_tokens': N, 'prompt_tokens': N, 'completion_tokens': N}
    """
    if not conversations:
        return None, _empty_usage()

    # 只取最近 1~2 条用户消息（避免长对话内容发散）
    user_msgs = []
    for conv in conversations[-2:]:
        um = conv.get("user_msg", "").strip()
        if um:
            if um.startswith('{'):
                try:
                    parsed = _json_gs.loads(um)
                    if isinstance(parsed, dict):
                        um = parsed.get("text", um)
                except Exception:
                    logger.exception("operation failed")

            if len(um) > 200:
                um = um[:200] + "..."
            user_msgs.append(f"用户：{um}")

    if not user_msgs:
        return None, _empty_usage()

    user_content = TOPIC_SUMMARY_USER_TEMPLATE.format(
        user_msgs="\n".join(user_msgs)
    )

    try:
        logger.debug(f"generate_topic_summary request: model={model}, conversations={len(conversations)}, user_msgs={len(user_msgs)}")
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": TOPIC_SUMMARY_SYSTEM},
                {"role": "user", "content": user_content},
            ],
            temperature=0.3,
            max_tokens=50,
        )

        # 安全检查返回值
        if not response.choices or len(response.choices) == 0:
            return None, _empty_usage()

        content = response.choices[0].message.content
        # DeepSeek 等推理模型可能把回复放到 reasoning_content 中，content 为空
        if not content:
            content = getattr(response.choices[0].message, 'reasoning_content', None)
        if not content or not isinstance(content, str):
            logger.warning(f"_generate_topic_summary: API 返回空 content, model={model}")
            return None, _empty_usage()

        raw = content.strip()
        # 调试日志：记录 LLM 原始返回
        logger.info(f"_generate_topic_summary 原始返回: model={model}, raw_len={len(raw)}, raw={repr(raw[:80])}")
        # 去掉各种引号包裹（中英文全角半角）
        raw = re.sub(r'^[\'"\u201c\u201d\u2018\u2019\u300c\u300d\uff02\uff07]+', '', raw)
        raw = re.sub(r'[\'"\u201c\u201d\u2018\u2019\u300c\u300d\uff02\uff07]+$', '', raw)
        raw = raw.strip()

        if not raw:
            logger.warning(f"_generate_topic_summary: 清洗后 raw 为空, content={repr(content[:80])}")
            return None, _empty_usage()

        # NOTE: 2026-06-22 硬过滤：禁止输出废词标题
        forbidden = ['我们', '用户', '您', '对话', '消息', '根据', '以下', '上文',
                     '主题', '这个', '输入', '生成']
        for word in forbidden:
            if word in raw:
                logger.warning(f"_generate_topic_summary: 标题含禁词'{word}'被拒: {repr(raw)}")
                return None, _empty_usage()

        # NOTE: 2026-05-01 08:17:32, min_length调整为4
        # 拒绝过短的摘要（<4个字符）
        if len(raw) < 4:
            logger.warning(f"_generate_topic_summary: 摘要过短被拒, len={len(raw)}, raw={repr(raw)}")
            return None, _empty_usage()

        if len(raw) > 20:
            raw = raw[:20]

        return (raw, _extract_usage(response)) if raw else (None, _extract_usage(response))
    except Exception as e:
        logger.warning(f"_generate_topic_summary 失败: {type(e).__name__}: {e}, model={model}")
        return None, _empty_usage()
