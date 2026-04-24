"""
在线工具调用会话 - Token 优化版
支持 OpenAI 兼容 API 的 Function Calling 功能

Token 优化策略:
1. 压缩系统提示词 (~200 tokens, 原 ~1000+)
2. 历史摘要：超过3轮的对话自动摘要，只传摘要+最近N轮
3. 工具输出截断：超长结果截断至 max_tool_output 字符
4. 记忆注入精简：8条记忆，独立于消息列表（不侵入 self.messages）
5. 记忆提取限窗：仅从最近6轮提取
"""

from openai import OpenAI
from typing import List, Dict, Callable, Tuple, Any, Optional

from tea_agent.basesession import BaseChatSession
from tea_agent.session_memory import SessionMemoryMixin
from tea_agent.session_summarizer import SessionSummarizerMixin
from tea_agent.session_tool import SessionToolMixin
from tea_agent.session_api import SessionAPIMixin
from tea_agent.session_prompts import COMPACT_SYSTEM_PROMPT


class OnlineToolSession(
    BaseChatSession,
    SessionMemoryMixin,
    SessionSummarizerMixin,
    SessionToolMixin,
    SessionAPIMixin,
):
    """
    在线工具调用会话 - Token 优化版
    支持 OpenAI 兼容 API 的 Function Calling 功能

    Token 优化策略:
    - 历史摘要：超过 keep_turns 轮的对话自动摘要，只传摘要 + 最近 N 轮
    - 紧凑消息：工具输出和助手回复超长时截断
    - 精简系统提示词（~200 tokens，原 ~1000+）
    - 记忆注入独立于消息列表，不侵入 self.messages
    - 记忆提取限窗，仅从最近 N 轮提取

    中间轮次存储策略:
    - chat_stream 期间收集所有中间 request/response 到 _rounds_collector
    - 流结束后由调用方通过 storage.update_msg_rounds() 一次性写入 conversations 表
    - rounds_json 列存储 OpenAI API 消息格式的完整工具调用链
    """

    # 压缩后的系统提示词
    _COMPACT_SYSTEM_PROMPT = COMPACT_SYSTEM_PROMPT

    def __init__(
        self,
        toolkit,
        api_key: str,
        api_url: str,
        model: str = "glm-5",
        max_history: int = 10,
        system_prompt: str = "",
        max_iterations: int = 50,
        enable_thinking: bool = True,
        memory=None,
        storage=None,
        cheap_api_key: str = "",
        cheap_api_url: str = "",
        cheap_model: str = "",
        keep_turns: int = 3,
        max_tool_output: int = 128 * 1024,
        max_assistant_content: int = 128 * 1024,
        memory_inject_limit: int = 8,
        memory_extract_rounds: int = 6,
    ):
        """
        初始化会话

        Args:
            toolkit: Toolkit 工具库实例
            api_key: API密钥
            api_url: API地址
            model: 模型名称
            max_history: 最大历史消息数
            system_prompt: 系统提示词（为空则使用压缩版）
            max_iterations: 最大工具调用迭代次数
            enable_thinking: 是否启用 thinking 功能
            memory: Memory 实例，用于长期记忆
            storage: Storage 实例，用于持久化存储
            cheap_api_key: 便宜模型 API密钥（用于摘要等低成本任务）
            cheap_api_url: 便宜模型 API地址
            cheap_model: 便宜模型名称
            keep_turns: 保留最近N轮完整对话，更早的对话自动摘要
            max_tool_output: 工具输出截断字符数
            max_assistant_content: 助手回复截断字符数
            memory_inject_limit: 记忆注入条数上限
            memory_extract_rounds: 记忆提取窗口轮数
        """
        sp = system_prompt or self._COMPACT_SYSTEM_PROMPT
        BaseChatSession.__init__(self, model, max_history, sp)
        SessionMemoryMixin.__init__(self)
        SessionSummarizerMixin.__init__(self)
        SessionToolMixin.__init__(self)
        SessionAPIMixin.__init__(self)

        self.toolkit = toolkit
        self.client = OpenAI(api_key=api_key, base_url=api_url)
        self.max_iterations = max_iterations
        self.enable_thinking = enable_thinking
        self.memory = memory
        self.storage = storage

        # 便宜模型客户端
        self._cheap_client: Optional[OpenAI] = None
        self._cheap_model_name: str = ""
        if cheap_api_key and cheap_api_url and cheap_model:
            self._cheap_client = OpenAI(api_key=cheap_api_key, base_url=cheap_api_url)
            self._cheap_model_name = cheap_model

        # Token 优化参数
        self.keep_turns = keep_turns
        self.max_tool_output = max_tool_output
        self.max_assistant_content = max_assistant_content
        self.memory_inject_limit = memory_inject_limit
        self.memory_extract_rounds = memory_extract_rounds

        # 工具定义
        self.tools: List[Dict] = []
        self._build_tools()

    # ──────────────────────────────────────────────
    # 基础方法
    # ──────────────────────────────────────────────

    def _build_tools(self):
        """构建工具定义列表"""
        self.tools = super()._build_tools()

    def update_tools(self):
        """重新加载并刷新工具定义"""
        self.toolkit.reload()
        self._build_tools()

    def _get_summarize_client(self) -> Tuple[Any, str]:
        """获取用于摘要/提取任务的客户端和模型名。"""
        if self._cheap_client and self._cheap_model_name:
            return self._cheap_client, self._cheap_model_name
        return self.client, self.model

    def reset_session_state(self):
        """重置会话状态（用于新会话开始前）"""
        self.reset_memory_state()
        self.reset_summary_state()
        self.reset_usage()
        self._rounds_collector = []
        
        # 在会话初始化时检测一次主模型的 thinking 支持
        self._probe_thinking_support()
        
        # 检测便宜模型的 thinking 支持
        if self._cheap_client and self._cheap_model_name:
            self._probe_thinking_support(
                client=self._cheap_client,
                model=self._cheap_model_name,
                is_cheap=True
            )

    # ──────────────────────────────────────────────
    # 核心对话流程
    # ──────────────────────────────────────────────

    def chat_stream(self, msg: str, callback: Callable[[str], None]) -> Tuple[str, bool]:
        """
        流式对话，支持工具调用。

        Args:
            msg: 用户消息
            callback: 流式输出回调函数

        Returns:
            Tuple[str, bool]: (助手完整回复, 是否使用了工具调用)
        """
        self.reset_interrupt()
        self.reset_session_state()

        # 1. 注入记忆
        self._inject_memories()

        # 2. 添加用户消息
        self.add_user_message(msg)

        # 3. 摘要旧历史
        self._summarize_old_history()

        full_reply = ""
        used_tools = False
        iterations = 0

        while iterations < self.max_iterations:
            if self.interrupted:
                final_msg = full_reply + "\n[已打断]"
                self.add_assistant_message(final_msg)
                self._collect_interruption_round(final_msg)
                return final_msg, used_tools

            api_messages = self._build_api_messages()

            try:
                response = self._create_chat_stream(api_messages, self.tools)
            except Exception as e:
                error_msg = f"API调用错误: {e}"
                callback(error_msg)
                self.add_assistant_message(full_reply + error_msg)
                self._collect_api_error_round(full_reply + error_msg)
                return full_reply + error_msg, used_tools

            # 处理流式响应
            content, tool_calls_data = self.process_stream_response(response, callback)
            full_reply += content

            # 解析工具调用
            valid_tool_calls = self._parse_tool_calls_from_stream(tool_calls_data)

            if valid_tool_calls:
                used_tools = True

                # 收集 assistant tool_calls
                self._collect_assistant_tool_calls_round(content, valid_tool_calls)

                # 存入完整历史
                self.messages.append({
                    "role": "assistant",
                    "content": content if content else None,
                    "tool_calls": [{
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments
                        }
                    } for tc in valid_tool_calls]
                })

                # 执行工具调用
                has_reload = any(
                    tc.function.name == "toolkit_reload"
                    for tc in valid_tool_calls
                )

                for call in valid_tool_calls:
                    call_id, func_name, result_str = self._execute_tool_call(call)
                    self._collect_tool_call_round(call_id, result_str)

                # 如果调用了 reload，刷新本地工具定义
                if has_reload:
                    self._build_tools()

                iterations += 1

                # 流式反馈
                if content:
                    callback("\n\n[正在执行工具，处理中...]\n\n")

                continue

            elif content:
                # 最终文本回答
                self.add_assistant_message(content)
                self._collect_assistant_text_round(content)
                break
            else:
                break

        # 达到最大迭代次数
        if iterations >= self.max_iterations:
            warning = f"\n\n[警告：已达到最大迭代次数 {self.max_iterations}，对话强制终止]"
            callback(warning)
            full_reply += warning
            self.add_assistant_message(full_reply)
            self._collect_max_iterations_round(full_reply)

        # 自动提取并保存记忆
        self._save_conversation_memory()

        return full_reply, used_tools
