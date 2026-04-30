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

# NOTE: 2026-04-30 08:53:33, self-evolved by tea_agent --- 更新load_history docstring，去除过时的中间工具调用链描述
    def load_history(self, conversations: List[Dict], summary: str = ""):
        """
        从数据库加载历史记录（仅保留 user + 最终 ai_msg，丢弃中间工具调用链）。

        Args:
            conversations: 对话记录列表，每条含 user_msg, ai_msg 等字段
            summary: 历史对话摘要（如有）
        """
        self.messages = [{"role": "system", "content": self.system_prompt}]

        # # 如果有持久化摘要，作为 user + assistant 对注入，而非合并到 system prompt
        # if summary:
        #     self.messages.append({
        #         "role": "user",
        #         "content": f"这是我们之前对话的摘要：\n{summary}"
        #     })
        #     self.messages.append({
        #         "role": "assistant",
        #         "content": "好的，我已经了解了之前的对话背景。请问有什么我可以帮您的？"
        #     })

        ## 在 _build_api_messages() 时，合并到 messages 中
        self._history_summary = summary

        logger.info(f"加载历史 {len(conversations)}条, 摘要：{summary}")
# NOTE: 2026-04-30 08:53:14, self-evolved by tea_agent --- 历史加载只保留最终ai_msg，丢弃中间工具调用链，减少token浪费和LLM干扰
        for conv in conversations:
            self.messages.append({"role": "user", "content": conv["user_msg"]})

            logger.info(
                f"==> user '{conv['user_msg']}'\n"
                f"--> ai '{conv['ai_msg']}'\n"
            )
            # 历史中只保留最终 ai_msg，丢弃中间工具调用链。
            # 中间轮次（assistant tool_call + tool result）对后续对话无价值，
            # 保留只会浪费 token 并干扰 LLM 判断。
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
