# -*- coding: utf-8 -*-
# 2026-05-21 gen by tea_agent, Extracted from onlinesession._auto_detect_mode
"""模式检测模块 — 根据用户输入自动检测 Agent 人格模式。

用法:
    from tea_agent.session_mode import detect_mode
    result = detect_mode(lambda action, text: toolkit.call_tool('toolkit_mode', action=action, text=text), text)
    # -> {'switched': False, 'mode': 'pragmatic', ...}
"""

import logging
from typing import Callable, Optional

logger = logging.getLogger("session_mode")

VALID_MODES = {"pragmatic", "creative", "mixed"}
"""合法模式值集合。"""


def detect_mode(call_tool_fn: Callable, user_text: str) -> dict:
    """根据用户输入自动检测并返回建议的模式。

    Args:
        call_tool_fn: 调用 toolkit_mode 的函数，签名 (action, text) -> dict
        user_text: 用户输入文本

    Returns:
        dict: 包含检测结果
            - switched: bool — 是否切换了模式
            - from_mode: str | None — 原模式
            - to_mode: str | None — 目标模式
            - mode: str | None — 当前模式
            - reason: str | None — 切换原因
    """
    try:
        result = call_tool_fn(action="auto", text=user_text)
        if isinstance(result, dict):
            return result
        return {"switched": False, "mode": None}
    except Exception as e:
        logger.debug(f"模式检测失败: {e}")
        return {"switched": False, "mode": None, "error": str(e)}


def extract_mode(result: dict) -> Optional[str]:
    """从 detect_mode 结果中提取模式值，验证合法性。"""
    mode = result.get("to_mode") or result.get("mode") or result.get("detected")
    if mode in VALID_MODES:
        return mode
    return None
