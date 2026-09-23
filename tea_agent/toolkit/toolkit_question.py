# version: 1.0.0

"""
问题工具 - 执行过程中向用户提问

交互路径（按优先级）：
1. Web 模式：通过 tlk.toolkit._question_web_handler 回调（由 server.py 设置）
2. 静默模式（Server/Headless）：无交互时自动返回 default 值

关键设计：通过 tlk.toolkit 共享单例传递 handler，规避 exec() 变量隔离问题。

注：GUI（tkinter 弹窗）与 CLI（终端 input）两条路径已随 GUI/CLI 接口废弃移除 ——
交互面收敛为 Web；非 Web 环境一律返回默认值，绝不阻塞在 stdin 上。
"""

import logging
import os

logger = logging.getLogger("toolkit.question")


def _get_web_handler():
    """从 tlk.toolkit 单例获取 Web handler（绕过 exec 隔离）。

    当 server.py 的 chat_stream_sse 设置 handler 后，
    exec 加载的函数也能通过 tlk.toolkit 访问到同一 handler。
    """
    try:
        from tea_agent import tlk
        if tlk.toolkit is not None:
            return getattr(tlk.toolkit, '_question_web_handler', None)
    except Exception:
        pass
    return None


def _is_headless_context() -> bool:
    """检测是否在无用户交互环境下运行（Server 后台 / TEA_HEADLESS）。

    此时不应弹出 GUI/CLI 提问，应直接返回 default。
    """
    # 显式环境变量
    if os.environ.get('TEA_HEADLESS', '').lower() in ('1', 'true', 'yes'):
        return True

    # Server 模式：tlk.toolkit 被标记为 server 实例
    try:
        from tea_agent import tlk
        if tlk.toolkit is not None and getattr(tlk.toolkit, '_is_server', False):
            return True
    except Exception:
        pass

    return False


def toolkit_question(
    title: str,
    question: str,
    options: list[str] = None,
    default: str = "",
    timeout: int = 0
) -> str:
    """
    执行过程中向用户提问。

    Args:
        title: 问题标题
        question: 问题描述
        options: 选项列表，为空时允许自由输入
        default: 默认选项或默认输入
        timeout: 超时秒数，0=不超时

    Returns:
        用户选择的答案字符串
    """
    # ── 优先级 1: Web 模式（通过 tlk.toolkit 共享单例） ──
    handler = _get_web_handler()
    if handler is not None:
        try:
            return handler(title, question, options, default, timeout)
        except Exception as e:
            logger.warning(f"Web question handler failed, fallback: {e}")

    # ── 优先级 2: 无交互通道 → 返回默认值（绝不阻塞 main thread 等 stdin） ──
    logger.info(
        "No interactive channel (headless=%s): auto-return default=%r for question: %s",
        _is_headless_context(), default, title,
    )
    return default or ""


# 工具元信息
TOOL_META = {
    "type": "function",
    "function": {
        "name": "toolkit_question",
        "description": "执行过程中向用户提问。支持选项列表和自定义输入。",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "问题标题"},
                "question": {"type": "string", "description": "问题描述"},
                "options": {"type": "array", "items": {"type": "string"}, "description": "选项列表"},
                "default": {"type": "string", "description": "默认选项"},
                "timeout": {"type": "integer", "description": "超时秒数"}
            },
            "required": ["title", "question"]
        }
    }
}


def meta_toolkit_question() -> dict:
    return {"type": "function", "function": {"name": "toolkit_question", "description": "执行过程中向用户提问。支持选项列表和自定义输入。 使用场景： - 收集用户偏好或需求 - 澄清模糊的指令 - 获取实现方案的决策 - 提供方向选择的选项 返回：用户选择的答案字符串", "parameters": {"type": "object", "properties": {"title": {"type": "string", "description": "问题标题，如 '选择编程语言'"}, "question": {"type": "string", "description": "问题描述，如 '您希望使用哪种编程语言？'"}, "options": {"type": "array", "items": {"type": "string"}, "description": "选项列表，如 。为空时允许自由输入"}, "default": {"type": "string", "description": "默认选项或默认输入"}, "timeout": {"type": "integer", "description": "超时秒数，0=不超时，默认 0"}}, "required": ["title", "question"]}}}
