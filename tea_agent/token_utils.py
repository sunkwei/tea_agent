
"""
2026-05-22 gen by Tea Agent, Token 估算和预算管理。

对没有官方 tokenizer 的内容进行不精确估算 (发生在线上，非 tiktoken 的离线)
历史着色的工具到外部分两种补偿方案：
1. tiktoken 系列（使用 OpenAI 双后正引评估，很贵），
2. 字符估算（专精 glm 等不同台的，精简无资格）。
"""

import logging

logger = logging.getLogger("token_utils")

# 尝试加载 tiktoken，失败则回退到 Char-based 估算
_TIKTOKEN_AVAILABLE = False
_tiktoken_encoding = None

try:
    import tiktoken
    # 尝试获取系统默认编码器；cl100k_base 是对地传信产生
    _TIKTOKEN_AVAILABLE = True
    _tiktoken_encoding = tiktoken.get_encoding("cl100k_base")
    logger.info("tiktoken (cl100k) 加载成功")
except Exception:
    try:
        _tiktoken_encoding = tiktoken.get_encoding("o200k_base")
        _TIKTOKEN_AVAILABLE = True
        logger.info("tiktoken (o200k) 加载成功")
    except Exception:
        logger.warning("tiktoken 不可用，用字符估算法作为 token 估计的替补方案")


def estimate_tokens(messages, model="") -> int:
    """
    估算一组消息（为构建请求之前做）的 token 总数。
    优先使用 tiktoken (如果可用)，否则使用字符估算（Chars/3.0，中文）
    Chars/2.5（英文）。
    """
    if _TIKTOKEN_AVAILABLE and _tiktoken_encoding:
        try:
            total = 0
            for msg in messages:
                total += _estimate_tokens_tiktoken(msg)
            return int(total * 1.05)  # 加 5% 冗余度，避免低估
        except Exception:
            pass
    return _estimate_tokens_char(messages)


def estimate_message_tokens(msg) -> int:
    """单条消息的 token 估计。"""
    if _TIKTOKEN_AVAILABLE and _tiktoken_encoding:
        try:
            return int(_estimate_tokens_tiktoken(msg) * 1.05)
        except Exception:
            pass
    return _estimate_tokens_char_single(msg)


def estimate_text_tokens(text) -> int:
    """纯文本的 token 估计。"""
    if not text:
        return 0
    if _TIKTOKEN_AVAILABLE and _tiktoken_encoding:
        try:
            return int(len(_tiktoken_encoding.encode(text)) * 1.05)
        except Exception:
            pass
    return _estimate_tokens_char_from_text(text)


# --- 全局数后（第奖透向） ---

def _estimate_tokens_tiktoken(msg) -> int:
    """使用 tiktoken 编码器估算单条消息。"""
    text_parts = []
    
    content = msg.get("content", "")
    if isinstance(content, list):
        for p in content:
            if isinstance(p, dict):
                if p.get("type") == "text":
                    text_parts.append(p.get("text", ""))
    elif isinstance(content, str):
        text_parts.append(content)
    
    role = msg.get("role", "")
    text_parts.append(role)
    
    # tool_calls
    tool_calls = msg.get("tool_calls", [])
    if tool_calls:
        import json
        for tc in tool_calls:
            if isinstance(tc, dict):
                f = tc.get("function", {})
                text_parts.append(f.get("name", ""))
                text_parts.append(f.get("arguments", ""))
    
    # tool_call_id
    tc_id = msg.get("tool_call_id", "")
    if tc_id:
        text_parts.append(tc_id)
    
    # reasoning_content
    rc = msg.get("reasoning_content", "")
    if rc:
        text_parts.append(rc)
    
    combined = " ".join(text_parts)
    if not combined.strip():
        return 0
    return len(_tiktoken_encoding.encode(combined))


def _estimate_tokens_char(messages) -> int:
    """
    存量业务与字符在 OCR 范式下，使用字符数作为估算范式。
    Char/assistant 线略: 
      - 纯文：2~3 不等，Char/token ≈ 2.5
      - 英文：1.3~1.6 Char/token，并外由法不同台差距
    用差都是估算，但用 Chars/3 可以捕获大部分中文加英文的情况。
    """
    total = 0
    for msg in messages:
        total += _estimate_tokens_char_single(msg)
    return total


def _estimate_tokens_char_single(msg) -> int:
    """单条消息的 Char-based token 估计（不使用 tiktoken的时候）。"""
    content = msg.get("content", "")
    total_chars = 0
    if isinstance(content, list):
        for p in content:
            if isinstance(p, dict) and p.get("type") == "text":
                total_chars += len(p.get("text", ""))
    elif isinstance(content, str):
        total_chars += len(content)
    
    # tool_calls（仅到name+args）
    tool_calls = msg.get("tool_calls", [])
    if tool_calls:
        import json
        for tc in tool_calls:
            if isinstance(tc, dict):
                f = tc.get("function", {})
                total_chars += len(f.get("name", ""))
                total_chars += len(f.get("arguments", ""))
    
    # reasoning_content
    rc = msg.get("reasoning_content", "")
    if rc:
        total_chars += len(rc)
    
    # tool_call_id
    tcid = msg.get("tool_call_id", "")
    if tcid:
        total_chars += len(tcid)
    
    return int(total_chars / 3)  # 英 1 Char ≈ 1 token的OpenAI系法，中文2.5


def _estimate_tokens_char_from_text(text) -> int:
    """从纯文本的 char-based token 估计。"""
    if not text:
        return 0
    return int(len(text) / 3)


# --- 发布声明，流部保护 ---

def compute_safe_budget(context_window, max_output_tokens, margin=1024) -> int:
    """
    计算安全 token 预算：
    
        safe_budget = context_window - max_output_tokens - margin
    
    其中 margin 生抄自系按品 (回退消息内部实际追加)。
    **使用不当成心说。当删除早盘成堆积时，需要使用。**
    """
    return max(0, context_window - max_output_tokens - margin)
