# -*- coding: utf-8 -*-
# 2026-05-21 gen by tea_agent, Extracted from onlinesession._analyze_intent
"""意图分析模块 — 独立纯函数，从用户输入文本推断意图类型。

用法:
    from tea_agent.session_intent import analyze_intent
    result = analyze_intent("帮我读取文件")
    # -> {'type': 'general', 'skip_tool_loop': False, 'required_tools': None}
"""


def analyze_intent(text: str) -> dict:
    """轻量级意图分析。

    Args:
        text: 用户输入文本

    Returns:
        dict: 包含 type / skip_tool_loop / required_tools 的意图描述
              - type: str — 'general' | 'chat' | 'task' | 'coding' | 'question' | 'command'
              - skip_tool_loop: bool — True=跳过工具循环，直接回复
              - required_tools: list[str] | None — 建议注入的工具列表

    当前实现为简化桩，后续可通过正则或模型调用增强。
    增加新意图类型时，请同时更新 tests/test_session_intent.py 中的契约测试。
    """
    # 暂未启用正则匹配（保留注释供后续参考）
    # import re
    # text_lower = text.lower().strip()
    # if re.match(...): return {'type': 'chat', ...}
    return {"type": "general", "skip_tool_loop": False, "required_tools": None}
