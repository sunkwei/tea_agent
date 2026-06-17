"""
智能 Compaction 模块 — 压缩历史对话，保留关键信息。

用法:
    from tea_agent.compaction import Compactor, AdaptiveCompactor, TokenBudgetManager
    
    # 基础压缩
    compactor = Compactor(max_tokens=32000)
    result = compactor.compact(messages)
    
    # 自适应压缩
    adaptive = AdaptiveCompactor(max_tokens=32000)
    result = adaptive.compact_to_budget(messages, budget=16000)
    
    # Token 预算管理
    manager = TokenBudgetManager(max_tokens=128000)
    budget = manager.allocate("code_review")
"""

from .compressor import Compactor, AdaptiveCompactor, CompactionConfig, CompactResult
from .token_budget import TokenBudgetManager, TokenBudget

__all__ = [
    "Compactor", "AdaptiveCompactor", "CompactionConfig", "CompactResult",
    "TokenBudgetManager", "TokenBudget",
]
