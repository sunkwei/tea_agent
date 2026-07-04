# version: 1.0.0
"""
会话组件公共参数工具

提取自 session_api_component, session_summarizer_component, session_memory_component
的重复代码，统一管理 cheap 模型参数获取。
"""

import logging
from typing import Dict, Any

logger = logging.getLogger("session.params")

# 各组件的默认参数
_DEFAULTS = {
    "api": {"temperature": 0.3, "max_tokens": 1000},
    "summarizer": {"temperature": 0.1, "max_tokens": 500},
    "memory": {"temperature": 0.3, "max_tokens": 1000},
}


def get_cheap_params(section: str = "api") -> Dict[str, Any]:
    """获取 cheap 模型参数，按使用场景区分。
    
    Args:
        section: 使用场景，可选 "api", "summarizer", "memory"
        
    Returns:
        包含 temperature, max_tokens 的 dict
    """
    defaults = _DEFAULTS.get(section, _DEFAULTS["api"])
    try:
        from ..config import get_config
        eff = get_config().get_effective_params("cheap", "mixed")
        return {
            "temperature": eff.get("temperature", defaults["temperature"]),
            "max_tokens": eff.get("max_tokens", defaults["max_tokens"]),
        }
    except Exception as e:
        logger.debug(f"获取 cheap 模型参数失败，使用默认值: {e}")
        return defaults.copy()
