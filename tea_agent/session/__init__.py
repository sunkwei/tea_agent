"""
Session subpackage - LLM context building pipeline

All modules can be directly imported and used by AI Agents.

模块清单（供 AI 导航）：
- context           — SessionContext 数据类 + SessionComponent 抽象基类
- prompts           — 系统提示词常量与模板（HISTORY_SUMMARIZE_*, TOPIC_SUMMARY_*, ...）
- history_builder   — L1/L2/L3 历史消息拼接（build_api_messages, estimate_tokens）
- json_sanitizer    — JSON 校验与修复（sanitize_api_messages, try_fix_truncated_json）
- os_info_injector  — 操作系统信息注入到会话提示词（inject_os_info）
- params            — 便宜模型参数提取（get_cheap_params）
- tool_loop_runner  — 工具调用循环执行器（execute_tool_loop, LoopDetector）

所有符号从子模块 re-export，AI 可以直接 `from tea_agent.session import SessionContext` 使用，
无需知道底层文件名。
"""

from .context import SessionContext, SessionComponent
from .prompts import (
    HISTORY_SUMMARIZE_SYSTEM, HISTORY_SUMMARIZE_USER,
    TOPIC_SUMMARY_SYSTEM, TOPIC_SUMMARY_USER_TEMPLATE,
    COMPACT_SYSTEM_PROMPT,
)
from .history_builder import build_api_messages, estimate_tokens, to_multimodal
from .json_sanitizer import sanitize_api_messages, try_fix_truncated_json
from .os_info_injector import inject_os_info
from .params import get_cheap_params
from .tool_loop_runner import execute_tool_loop, LoopDetector

__all__ = [
    "SessionContext", "SessionComponent",
    "HISTORY_SUMMARIZE_SYSTEM", "HISTORY_SUMMARIZE_USER",
    "TOPIC_SUMMARY_SYSTEM", "TOPIC_SUMMARY_USER_TEMPLATE",
    "COMPACT_SYSTEM_PROMPT",
    "build_api_messages", "estimate_tokens", "to_multimodal",
    "sanitize_api_messages", "try_fix_truncated_json",
    "inject_os_info",
    "get_cheap_params",
    "execute_tool_loop", "LoopDetector",
]