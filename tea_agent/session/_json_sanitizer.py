"""
JSON 校验与修复模块

从 onlinesession.py 提取的独立功能：
- sanitize_api_messages: 校验并修复 API 消息中的 tool_calls JSON
- try_fix_truncated_json: 尝试修复被截断的 JSON 字符串
"""

import json
import logging
from typing import List, Dict, Optional

logger = logging.getLogger("session.json_sanitizer")


def try_fix_truncated_json(s: str) -> Optional[str]:
    """尝试修复被截断的 JSON 字符串。
    
    通过分析括号栈和字符串状态，补全缺失的闭合符号。
    
    Args:
        s: 可能被截断的 JSON 字符串
        
    Returns:
        修复后的合法 JSON 字符串，无法修复则返回 None
    """
    if not s or not s.strip():
        return None

    s = s.strip()
    stack = []
    in_str = False
    escape = False
    for ch in s:
        if escape:
            escape = False
            continue
        if ch == '\\':
            escape = True
            continue
        if ch == '"' and not escape:
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch in '{[':
            stack.append(ch)
        elif ch in '}]':
            if stack and ((ch == '}' and stack[-1] == '{') or (ch == ']' and stack[-1] == '[')):
                stack.pop()

    if not stack:
        if in_str:
            s = s + '"'
        try:
            json.loads(s)
            return s
        except json.JSONDecodeError:
            return None

    close_map = {'{': '}', '[': ']'}
    suffix = ''.join(close_map[c] for c in reversed(stack))
    if in_str:
        suffix = '"' + suffix

    fixed = s + suffix
    try:
        json.loads(fixed)
        return fixed
    except json.JSONDecodeError:
        return None


def sanitize_api_messages(messages: List[Dict]) -> List[Dict]:
    """校验并修复 API 消息中的 tool_calls JSON。
    
    扫描所有 assistant 消息的 tool_calls，对非法 JSON 参数尝试修复，
    无法修复的则移除该 tool_call。
    
    Args:
        messages: API 消息列表
        
    Returns:
        修复后的消息列表
    """
    sanitized = []
    removed_count = 0
    for msg in messages:
        if msg.get("role") != "assistant":
            sanitized.append(msg)
            continue

        tool_calls = msg.get("tool_calls")
        if not tool_calls:
            sanitized.append(msg)
            continue

        valid_calls = []
        for tc in tool_calls:
            func = tc.get("function", {})
            raw_args = func.get("arguments", "")

            if isinstance(raw_args, dict):
                valid_calls.append(tc)
                continue

            if not raw_args or not raw_args.strip():
                valid_calls.append(tc)
                continue

            try:
                json.loads(raw_args)
                valid_calls.append(tc)
                continue
            except json.JSONDecodeError:
                pass

            fixed = try_fix_truncated_json(raw_args)
            if fixed is not None:
                tc_copy = dict(tc)
                tc_copy["function"] = dict(func)
                tc_copy["function"]["arguments"] = fixed
                valid_calls.append(tc_copy)
                logger.warning(f"sanitize_api_messages: 修复截断JSON → {fixed[:80]}...")
            else:
                removed_count += 1
                logger.warning(
                    f"sanitize_api_messages: 移除非法tool_call → "
                    f"func={func.get('name','?')}, args前80={raw_args[:80]}"
                )

        if valid_calls:
            msg_copy = dict(msg)
            msg_copy["tool_calls"] = valid_calls
            sanitized.append(msg_copy)
        else:
            sanitized.append({
                "role": "assistant",
                "content": msg.get("content", "") or "[工具调用参数损坏，已移除]"
            })

    if removed_count > 0:
        logger.info(f"sanitize_api_messages: 共移除 {removed_count} 个非法 tool_call")
    return sanitized
