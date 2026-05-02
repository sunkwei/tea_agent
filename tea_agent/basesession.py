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

    # NOTE: 2026-05-03 06:37:41, self-evolved by tea_agent --- basesession.py: 添加 _repair_incomplete_tool_chains 修复中断导致的残缺工具调用链
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

    # NOTE: 2026-05-02, self-evolved by tea_agent ---
    # 修复中断会话后 400 错误：assistant tool_calls 之后必须有对应的 tool 消息
    @staticmethod
    def _repair_incomplete_tool_chains(rounds: List[Dict]) -> List[Dict]:
        """
        修复中断导致的不完整工具调用链。

        规则：
          - 每个带有 tool_calls 的 assistant 消息，其后必须有对应的 tool 消息
            回应每一个 tool_call_id，否则该 assistant 及其后续消息被截断。
          - 孤立的 tool 消息（无对应 assistant tool_calls）也被移除。

        Args:
            rounds: 原始 rounds 列表（可能包含不完整链）

        Returns:
            修复后的 rounds 列表
        """
        if not rounds:
            return rounds

        result: List[Dict] = []
        # 追踪尚未匹配的 tool_call_id -> 在 result 中的起始索引
        pending: Dict[str, int] = {}
        last_safe_len = 0  # 最后安全点：所有 pending 已清零时的 result 长度

        for i, rd in enumerate(rounds):
            role = rd.get("role", "")

            if role == "assistant" and rd.get("tool_calls"):
                # 先检查当前是否有未清空的 pending（前一个 assistant 的 tool_calls 未完成）
                # 这种情况：上一个 assistant 的 tool_calls 还没全匹配，又来了新 assistant
                # → 放弃当前批次（上一个 assistant 之后的都是垃圾），回滚到上一个安全点
                if pending:
                    result = result[:last_safe_len]
                    pending.clear()

                # 记录新的 tool_call_ids
                tc_list = rd["tool_calls"]
                if isinstance(tc_list, list):
                    tc_ids = [tc.get("id", "") for tc in tc_list if tc.get("id")]
                else:
                    tc_ids = []

                if not tc_ids:
                    # 有 tool_calls 字段但没有有效 id，视为纯 assistant 消息
                    result.append(dict(rd))
                    last_safe_len = len(result)
                    continue

                # 添加 assistant 消息
                start_idx = len(result)
                result.append(dict(rd))
                for tid in tc_ids:
                    pending[tid] = start_idx

            elif role == "tool":
                tid = rd.get("tool_call_id", "")
                if tid and tid in pending:
                    # 匹配到一个 tool_call_id
                    result.append(dict(rd))
                    del pending[tid]
                    if not pending:
                        # 所有 tool_call_id 都已匹配 → 安全点
                        last_safe_len = len(result)
                else:
                    # 孤立的 tool 消息：跳过
                    logger.debug(f"_repair: 跳过孤立 tool 消息 tool_call_id={tid}")
                    continue

            elif role == "assistant":
                # 纯 assistant 消息（无 tool_calls）
                if pending:
                    # 前一批 tool_calls 还没清空就来了新的 assistant 消息
                    # → 回滚到上一个安全点，丢弃未完成的工具调用链
                    result = result[:last_safe_len]
                    pending.clear()
                result.append(dict(rd))
                last_safe_len = len(result)

            else:
                # user/system 等其他角色：直接保留
                result.append(dict(rd))

        # 末尾检查：如果还有未清空的 pending，回滚到最后一个安全点
        if pending:
            result = result[:last_safe_len]
            logger.warning(
                f"_repair: 截断不完整工具调用链，移除 {len(pending)} 个未匹配的 tool_call_id: "
                f"{list(pending.keys())}"
            )

        # 最终清理：结果中不应再有 reasoning_content（非 assistant 消息）
        BaseChatSession._strip_reasoning_content(result)

        return result

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
# NOTE: 2026-05-03 06:37:54, self-evolved by tea_agent --- load_history 中加载 rounds_json_parsed 时调用 _repair_incomplete_tool_chains 修复中断链
            else:
                # 最近N轮：加载完整工具调用链
                rounds = conv.get("rounds_json_parsed")
                if rounds and conv.get("is_func_calling"):
                    # 修复中断导致的不完整工具调用链
                    repaired = BaseChatSession._repair_incomplete_tool_chains(rounds)
                    if len(repaired) != len(rounds):
                        logger.warning(
                            f"load_history: 修复不完整工具调用链 ({len(rounds)}→{len(repaired)} 条)"
                        )
                    for rd in repaired:
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
