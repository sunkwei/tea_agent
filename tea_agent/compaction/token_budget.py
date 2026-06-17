"""
自适应 Token 预算 — 根据任务类型动态分配 token。

用法:
    from tea_agent.compaction import TokenBudgetManager
    
    manager = TokenBudgetManager(max_tokens=128000)
    budget = manager.allocate("code_review")
    # {"system": 2000, "code": 50000, "history": 10000, "tools": 20000}
"""

from typing import Dict, Optional
from dataclasses import dataclass

import logging

logger = logging.getLogger(__name__)


@dataclass
class TokenBudget:
    """Token 预算分配"""
    total: int              # 总预算
    system: int             # 系统提示
    history: int            # 历史对话
    code: int               # 代码上下文
    tools: int              # 工具输出
    response: int           # 生成响应
    
    @property
    def available(self) -> int:
        """可用预算"""
        return self.total - self.system - self.history - self.code - self.tools - self.response
    
    def to_dict(self) -> Dict:
        return {
            "total": self.total,
            "system": self.system,
            "history": self.history,
            "code": self.code,
            "tools": self.tools,
            "response": self.response,
            "available": self.available,
        }


class TokenBudgetManager:
    """Token 预算管理器"""
    
    # 任务类型到预算分配的映射
    TASK_PROFILES = {
        "code_review": {
            "system_ratio": 0.02,     # 系统提示 2%
            "history_ratio": 0.10,    # 历史对话 10%
            "code_ratio": 0.50,       # 代码上下文 50%
            "tools_ratio": 0.20,      # 工具输出 20%
            "response_ratio": 0.18,   # 响应 18%
        },
        "refactor": {
            "system_ratio": 0.02,
            "history_ratio": 0.08,
            "code_ratio": 0.55,
            "tools_ratio": 0.15,
            "response_ratio": 0.20,
        },
        "test": {
            "system_ratio": 0.02,
            "history_ratio": 0.10,
            "code_ratio": 0.40,
            "tools_ratio": 0.25,
            "response_ratio": 0.23,
        },
        "doc": {
            "system_ratio": 0.02,
            "history_ratio": 0.15,
            "code_ratio": 0.45,
            "tools_ratio": 0.10,
            "response_ratio": 0.28,
        },
        "fix": {
            "system_ratio": 0.02,
            "history_ratio": 0.12,
            "code_ratio": 0.50,
            "tools_ratio": 0.18,
            "response_ratio": 0.18,
        },
        "search": {
            "system_ratio": 0.02,
            "history_ratio": 0.08,
            "code_ratio": 0.30,
            "tools_ratio": 0.40,
            "response_ratio": 0.20,
        },
        "chat": {
            "system_ratio": 0.05,
            "history_ratio": 0.60,
            "code_ratio": 0.10,
            "tools_ratio": 0.05,
            "response_ratio": 0.20,
        },
        "quick_question": {
            "system_ratio": 0.05,
            "history_ratio": 0.20,
            "code_ratio": 0.10,
            "tools_ratio": 0.10,
            "response_ratio": 0.55,
        },
        "default": {
            "system_ratio": 0.03,
            "history_ratio": 0.15,
            "code_ratio": 0.40,
            "tools_ratio": 0.20,
            "response_ratio": 0.22,
        },
    }
    
    # 任务关键词到类型的映射
    TASK_KEYWORDS = {
        "code_review": ["review", "审查", "评审", "检查代码"],
        "refactor": ["refactor", "重构", "重写", "重构成"],
        "test": ["test", "测试", "pytest", "unittest"],
        "doc": ["doc", "文档", "readme", "注释"],
        "fix": ["fix", "修复", "bug", "问题", "错误"],
        "search": ["search", "搜索", "查找", "find", "grep"],
        "chat": ["chat", "聊天", "闲聊"],
        "quick_question": ["?", "什么", "怎么", "如何", "why", "what", "how"],
    }
    
    def __init__(self, max_tokens: int = 128000):
        """
        Args:
            max_tokens: 总 token 预算
        """
        self.max_tokens = max_tokens
    
    def allocate(self, task_type: str = "default", context: Optional[Dict] = None) -> TokenBudget:
        """
        分配 token 预算。
        
        Args:
            task_type: 任务类型
            context: 额外上下文
            
        Returns:
            TokenBudget 对象
        """
        # 获取任务配置
        profile = self.TASK_PROFILES.get(task_type, self.TASK_PROFILES["default"])
        
        # 计算各项预算
        total = self.max_tokens
        system = int(total * profile["system_ratio"])
        history = int(total * profile["history_ratio"])
        code = int(total * profile["code_ratio"])
        tools = int(total * profile["tools_ratio"])
        response = int(total * profile["response_ratio"])
        
        # 根据上下文调整
        if context:
            system, history, code, tools, response = self._adjust_by_context(
                system, history, code, tools, response, context
            )
        
        budget = TokenBudget(
            total=total,
            system=system,
            history=history,
            code=code,
            tools=tools,
            response=response,
        )
        
        logger.debug(f"💰 Token 预算分配: {task_type} -> {budget.to_dict()}")
        
        return budget
    
    def detect_task_type(self, text: str) -> str:
        """
        从文本检测任务类型。
        
        Args:
            text: 输入文本
            
        Returns:
            任务类型
        """
        text_lower = text.lower()
        
        for task_type, keywords in self.TASK_KEYWORDS.items():
            if any(kw in text_lower for kw in keywords):
                return task_type
        
        return "default"
    
    def _adjust_by_context(
        self,
        system: int,
        history: int,
        code: int,
        tools: int,
        response: int,
        context: Dict,
    ) -> tuple:
        """根据上下文调整预算"""
        # 如果有代码文件，增加 code 预算
        if context.get("has_code_files"):
            code = int(code * 1.2)
            history = int(history * 0.8)
        
        # 如果有工具调用，增加 tools 预算
        if context.get("has_tool_calls"):
            tools = int(tools * 1.3)
            history = int(history * 0.7)
        
        # 如果是长对话，增加 history 预算
        if context.get("conversation_length", 0) > 10:
            history = int(history * 1.2)
            code = int(code * 0.8)
        
        return system, history, code, tools, response
    
    def calculate_compaction_needed(
        self,
        current_tokens: int,
        task_type: str = "default",
    ) -> Dict:
        """
        计算需要压缩多少。
        
        Args:
            current_tokens: 当前 token 数
            task_type: 任务类型
            
        Returns:
            压缩建议
        """
        budget = self.allocate(task_type)
        
        if current_tokens <= budget.total:
            return {
                "needs_compaction": False,
                "current_tokens": current_tokens,
                "budget": budget.total,
                "headroom": budget.total - current_tokens,
            }
        
        # 需要压缩
        excess = current_tokens - budget.total
        target_history = budget.history - excess
        
        if target_history < budget.system:
            # 即使压缩到最小也无法满足
            target_history = budget.system
        
        return {
            "needs_compaction": True,
            "current_tokens": current_tokens,
            "budget": budget.total,
            "excess": excess,
            "target_history_tokens": target_history,
            "compaction_ratio": excess / current_tokens,
        }
