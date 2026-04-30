"""
会话模块 - 基类
提供统一的聊天会话接口抽象基类
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Callable, Tuple
import logging

logger = logging.getLogger("basesession")

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
        self._history_summary = ""

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

    # NOTE: 2026-04-28, self-evolved by claude-agent ---
    # 从加载的历史消息中清除 reasoning_content。
    # reasoning_content 是 DeepSeek thinking 模式下的会话内状态，
    # 只在一个 API 会话内有效。从数据库加载的历史消息中的
    # reasoning_content 属于之前的 API 会话，传回新会话将导致
    # DeepSeek API 返回 400 错误：
    # "The reasoning_content in the thinking mode must be passed back to the API."
    @staticmethod
    def _strip_reasoning_content(messages: List[Dict]) -> None:
        """
        原地清除消息列表中的 reasoning_content 字段。
        
        注意：对于包含 tool_calls 的 assistant 消息，必须保留 reasoning_content，
        否则 DeepSeek API 会返回 400 错误。
        """
        for msg in messages:
            # 如果是助手消息且包含工具调用，则保留 reasoning_content
            # if msg.get("role") == "assistant" and msg.get("tool_calls"):
            if msg.get("role") == "assistant":
                continue
            msg.pop("reasoning_content", None)

# NOTE: 2026-04-30 10:02:24, self-evolved by tea_agent --- load_history支持recent_turns参数，旧轮次仅user+ai，最近N轮含完整工具链
    def load_history(self, conversations: List[Dict], summary: str = "", recent_turns: int = 10):
        """
        从数据库加载历史记录。

        - 最近 recent_turns 轮：加载完整消息（user + 中间工具调用链 + 最终 ai）
        - 超过 recent_turns 的旧轮次：仅保留 user + 最终 ai_msg

        Args:
            conversations: 对话记录列表（按时间正序），每条含 user_msg, ai_msg, rounds_json_parsed
            summary: 历史对话摘要（如有）
            recent_turns: 保留完整消息的最近轮数，默认10
        """
        self.messages = [{"role": "system", "content": self.system_prompt}]
        self._history_summary = summary

        total = len(conversations)
        old_count = max(0, total - recent_turns)

        logger.info(f"加载历史 {total}条 (完整:{min(total, recent_turns)} 简洁:{old_count}), 摘要：{summary}")

        for i, conv in enumerate(conversations):
            is_old = i < old_count
            self.messages.append({"role": "user", "content": conv["user_msg"]})

            if is_old:
                # 旧轮次：仅保留最终 ai_msg，丢弃中间工具调用链
                self.messages.append({"role": "assistant", "content": conv["ai_msg"]})
            else:
                # 最近N轮：加载完整工具调用链
                rounds = conv.get("rounds_json_parsed")
                if rounds and conv.get("is_func_calling"):
                    for rd in rounds:
                        self.messages.append(dict(rd))
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
