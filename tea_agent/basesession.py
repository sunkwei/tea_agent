"""
会话模块 - 基类
提供统一的聊天会话接口抽象基类
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Callable, Tuple


class BaseChatSession(ABC):
    """
    聊天会话抽象基类
    定义公共接口和共享功能
    """

    def __init__(
        self,
        model: str,
        max_history: int = 10,
        system_prompt: str = "你是一个智能助手，可以调用工具函数来帮助用户解决问题。"
    ):
        """
        初始化基类

        Args:
            model: 模型名称
            max_history: 最大历史消息数
            system_prompt: 系统提示词
        """
        self.model = model
        self.max_history = max_history
        self.system_prompt = system_prompt

        # 消息列表
        self.messages: List[Dict] = []
        self.messages.append({"role": "system", "content": self.system_prompt})

        # 打断标志
        self.interrupted = False

    @abstractmethod
    def chat_stream(self, msg: str, callback: Callable[[str], None]) -> Tuple[str, bool]:
        """
        流式对话（抽象方法，子类必须实现）

        Args:
            msg: 用户消息
            callback: 流式输出回调函数

        Returns:
            Tuple[str, bool]: (助手完整回复, 是否使用了工具调用)
        """
        pass

    def add_user_message(self, msg: str):
        """添加用户消息"""
        self.messages.append({"role": "user", "content": msg})

    def add_assistant_message(self, msg: str):
        """添加助手消息"""
        self.messages.append({"role": "assistant", "content": msg})

    def add_tool_result(self, tool_call_id: str, content: str):
        """添加工具执行结果"""
        self.messages.append({
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": content
        })

    def get_recent_messages(self) -> List[Dict]:
        """获取最近的消息（排除系统消息）"""
        return [m for m in self.messages if m["role"] != "system"]

    def load_history(self, conversations: List[Dict]):
        """
        从数据库加载历史记录，含中间工具调用链。

        如果对话有 rounds_json_parsed，则从中重建完整的工具调用链
        （assistant tool_calls → tool results → assistant final answer），
        确保 LLM 后续对话能获得正确的工具调用上下文。

        Args:
            conversations: 对话记录列表，每条含 user_msg, ai_msg,
                           is_func_calling, rounds_json_parsed 等字段
        """
        self.messages = [{"role": "system", "content": self.system_prompt}]

        for conv in conversations:
            self.messages.append({"role": "user", "content": conv["user_msg"]})

            rounds = conv.get("rounds_json_parsed")
            if rounds and conv.get("is_func_calling"):
                for rd in rounds:
                    self.messages.append(rd)
            else:
                self.messages.append({"role": "assistant", "content": conv["ai_msg"]})

    def interrupt(self):
        """打断当前生成"""
        self.interrupted = True

    def reset_interrupt(self):
        """重置打断标志"""
        self.interrupted = False

    def _trim_messages(self):
        """裁剪消息，保持最近N条"""
        if len(self.messages) <= self.max_history * 2 + 1:
            return

        system_msg = self.messages[0]
        recent = self.messages[-(self.max_history * 2):]
        self.messages = [system_msg] + recent
