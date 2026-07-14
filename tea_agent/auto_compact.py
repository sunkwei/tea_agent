"""
Auto-Compact — 自动上下文压缩。监控 Token 用量，达到阈值时自动触发摘要折叠。
"""

import json
import logging
import re

logger = logging.getLogger("auto_compact")


def estimate_tokens(text: str) -> int:
    """估算 token 数。中文~1.5t/字, 英文~4t/字。"""
    if not text:
        return 0
    cn = len(re.findall(r"[一-鿿㐀-䶿]", text))
    total = len(text)
    return int(cn / 1.5 + (total - cn) / 4.0) + 4


def estimate_messages_tokens(messages: list) -> int:
    """计算消息列表的总 token 数。"""
    total = 0
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    total += estimate_tokens(part.get("text", ""))
                elif isinstance(part, dict) and part.get("type") == "image_url":
                    total += 85
        elif isinstance(content, str):
            total += estimate_tokens(content)
        if msg.get("tool_calls"):
            total += estimate_tokens(json.dumps(msg["tool_calls"], ensure_ascii=False))
        rc = msg.get("reasoning_content", "")
        if rc:
            total += estimate_tokens(rc)
    return total


def should_compact(messages: list, max_tokens: int, threshold: float = 0.8):
    """判断是否需要压缩。返回 (needs_compact, current_tokens)。"""
    if max_tokens <= 0:
        return False, 0
    current = estimate_messages_tokens(messages)
    if current >= max_tokens * threshold:
        logger.warning(f"Auto-compact: {current}/{max_tokens} tok")
        return True, current
    return False, current


def compact_messages(messages: list, keep_recent: int = 5, summary: str = ""):
    """压缩历史：保留最近的 keep_recent 轮，合并旧消息到摘要。"""
    if not messages:
        return messages, summary
    sys_msgs = [m for m in messages if m.get("role") == "system"]
    others = [m for m in messages if m.get("role") != "system"]
    if len(others) <= keep_recent * 2:
        return messages, summary
    recent = others[-keep_recent * 2 :] if keep_recent > 0 else []
    older = others[: -keep_recent * 2] if keep_recent > 0 else others

    older_text = ""
    for m in older:
        r = m.get("role", "")
        c = m.get("content", "")
        if isinstance(c, str) and c:
            older_text += f"[{r}] {c[:200]}" + "\n"
    if older_text and len(older_text) > 50:
        summary = (
            (summary + "\n---\n" + older_text[:500])[:1000]
            if summary
            else older_text[:500]
        )

    compressed = list(sys_msgs)
    if summary:
        compressed.append({"role": "system", "content": f"[历史摘要] {summary}"})
    compressed.extend(recent)
    logger.info(f"Compacted: {len(messages)} -> {len(compressed)} msgs")
    return compressed, summary


def get_max_context_tokens(config) -> int:
    """从配置中获取最大上下文 token 数。未知模型默认 128K。"""
    try:
        main = config.main_model
        if hasattr(main, "max_context_tokens") and main.max_context_tokens:
            return int(main.max_context_tokens)
        val = main.options.get("max_context_tokens", 0)
        if val:
            return int(val)
        model = (main.model_name or "").lower()
        defaults = {
            "gpt-4": 128000,
            "claude": 200000,
            "deepseek": 65536,
            "gemini": 1048576,
        }
        for k, v in defaults.items():
            if k in model:
                return v
        return 128000
    except Exception:
        return 128000


class AutoCompactStep:
    """可调用压缩步骤 — 用在 pipeline 中作为自动压缩节点。"""

    def __init__(self, threshold: float = 0.8, keep_recent: int = 5):
        self.threshold = threshold
        self.keep_recent = keep_recent
        self._summary = ""

    def __call__(self, context, messages, **kw):
        mt = get_max_context_tokens(context.config)
        needs, cur = should_compact(messages, mt, self.threshold)
        if needs:
            compressed, self._summary = compact_messages(
                messages, self.keep_recent, self._summary
            )
            return {
                "compacted": True,
                "messages": compressed,
                "tokens_before": cur,
                "tokens_after": estimate_messages_tokens(compressed),
            }
        return {"compacted": False}
