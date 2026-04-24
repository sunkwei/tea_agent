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
from tea_agent.session_pipeline import SessionPipeline


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

        # DeepSeek 推理模型特殊处理
        self._is_deepseek_reasoning = self._check_deepseek_reasoning_model(model)

        # 工具定义
        self.tools: List[Dict] = []
        self._build_tools()
        
        # 初始化 Pipeline
        self.pipeline = SessionPipeline()
        self._setup_default_pipeline()

    # ──────────────────────────────────────────────
    # 基础方法
    # ──────────────────────────────────────────────

    def _check_deepseek_reasoning_model(self, model: str) -> bool:
        """
        检测是否为 DeepSeek 推理模型。
        
        DeepSeek 推理模型有特殊的多轮对话要求：
        - 当模型输出 reasoning_content 后，下一轮请求中如果之前的 assistant 消息包含 
          reasoning_content 字段，API 会返回 400 错误
        - 当模型进行了工具调用时，必须在后续请求中回传 reasoning_content，否则也会报错
        
        Args:
            model: 模型名称
            
        Returns:
            是否为 DeepSeek 推理模型
        """
        if not model:
            return False
        
        model_lower = model.lower()
        # 检测常见的 DeepSeek 推理模型
        deepseek_reasoning_models = [
            "deepseek-reasoner",
            "deepseek-r",
            "deepseek-r1",
            "deepseek-r2",
            "deepseek-r3",
            "deepseek-r4",
            "deepseek-v4-pro",
            "deepseek-v4-flash",
        ]
        
        # 检查是否包含 deepseek 且包含 r/r1/r2 等推理标识
        is_deepseek = "deepseek" in model_lower
        is_reasoning_model = any(rm in model_lower for rm in deepseek_reasoning_models)
        
        return is_deepseek and (is_reasoning_model or "-r" in model_lower)

    def _handle_deepseek_reasoning_content(self, messages: List[Dict]) -> List[Dict]:
        """
        处理 DeepSeek 推理模型的 reasoning_content 字段。

        DeepSeek 推理模型的特殊规则：
        1. 在多轮对话中，如果之前的 assistant 消息包含 reasoning_content，
           必须在后续请求中完整回传该字段，否则 API 会返回 400 错误。
        2. 无论是否进行了工具调用，reasoning_content 都必须保留。

        Args:
            messages: 原始消息列表

        Returns:
            处理后的消息列表
        """
        # DeepSeek 推理模型要求在后续对话中必须回传 reasoning_content
        # 之前的逻辑在非工具调用轮次删除了它，导致了 400 错误
        return messages

    def _process_stream_with_reasoning(self, response, callback) -> Tuple[str, List[Dict], str]:
        """
        处理流式响应，收集内容、工具调用数据和 reasoning_content。
        
        Args:
            response: 流式响应迭代器
            callback: 流式输出回调函数
            
        Returns:
            Tuple[str, List[Dict], str]: (累积文本内容, 工具调用数据列表, reasoning_content)
        """
        content_parts = []
        tool_calls_data = []
        reasoning_parts = []
        
        for chunk in response:
            # 累积 usage 信息
            if hasattr(chunk, 'usage') and chunk.usage:
                self._accumulate_usage(chunk.usage)
            
            if not hasattr(chunk, 'choices') or not chunk.choices:
                continue
            
            delta = chunk.choices[0].delta
            
            # 处理 reasoning_content
            if hasattr(delta, 'reasoning_content') and delta.reasoning_content:
                reasoning_parts.append(delta.reasoning_content)
            
            # 处理内容
            if delta.content:
                content_parts.append(delta.content)
                callback(delta.content)
            
            # 处理工具调用
            if delta.tool_calls:
                self._accumulate_tool_calls_from_delta(delta, tool_calls_data)
        
        content = "".join(content_parts)
        reasoning_content = "".join(reasoning_parts)
        return content, tool_calls_data, reasoning_content

    def _setup_default_pipeline(self):
        """设置默认的 Pipeline 步骤"""
        # 1. 注入记忆
        self.pipeline.register_step(
            name="inject_memories",
            func=lambda ctx: (self._inject_memories(), {})[1],
            enabled=True,
            description="注入重要记忆到上下文",
            position=10,
        )
        
        # 2. 添加用户消息
        self.pipeline.register_step(
            name="add_user_message",
            func=lambda ctx: (self.add_user_message(ctx.get("user_msg", "")), {})[1],
            enabled=True,
            description="添加用户消息到会话历史",
            position=20,
        )
        
        # 3. 摘要旧历史
        self.pipeline.register_step(
            name="summarize_old_history",
            func=lambda ctx: (self._summarize_old_history(), {})[1],
            enabled=True,
            description="将旧对话历史压缩为摘要",
            position=30,
        )
        
        # 4. 工具调用循环（核心）
        self.pipeline.register_step(
            name="tool_loop",
            func=self._execute_tool_loop,
            enabled=True,
            description="执行工具调用循环",
            position=40,
        )
        
        # 5. 提取记忆
        self.pipeline.register_step(
            name="extract_memory",
            func=lambda ctx: (self._save_conversation_memory(), {})[1],
            enabled=True,
            description="从对话中提取并保存记忆",
            position=50,
        )

    def _execute_tool_loop(self, context: Dict) -> Dict:
        """
        执行工具调用循环。

        Args:
            context: 上下文，包含 msg, callback 等

        Returns:
            结果字典，包含 full_reply, used_tools 等
        """
        msg = context.get("msg", "")
        callback = context.get("callback", lambda x: None)

        full_reply = ""
        used_tools = False
        iterations = 0

        while iterations < self.max_iterations:
            if self.interrupted:
                final_msg = full_reply + "\n[已打断]"
                self.add_assistant_message(final_msg)
                self._collect_interruption_round(final_msg)
                return {
                    "full_reply": final_msg,
                    "used_tools": used_tools,
                    "interrupted": True,
                }

            api_messages = self._build_api_messages()
            # DeepSeek 推理模型特殊处理
            api_messages = self._handle_deepseek_reasoning_content(api_messages)

            try:
                response = self._create_chat_stream(api_messages, self.tools)
            except Exception as e:
                error_msg = f"API调用错误: {e}"
                callback(error_msg)
                self.add_assistant_message(full_reply + error_msg)
                self._collect_api_error_round(full_reply + error_msg)
                return {
                    "full_reply": full_reply + error_msg,
                    "used_tools": used_tools,
                    "error": e,
                }

            # 处理流式响应
            content, tool_calls_data, reasoning_content = self._process_stream_with_reasoning(response, callback)
            full_reply += content

            # 解析工具调用
            valid_tool_calls = self._parse_tool_calls_from_stream(tool_calls_data)

            if valid_tool_calls:
                used_tools = True

                # 收集 assistant tool_calls
                self._collect_assistant_tool_calls_round(content, valid_tool_calls)

                # 存入完整历史（包含 reasoning_content）
                assistant_msg = {
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
                }
                # 如果有 reasoning_content，添加到消息中
                if reasoning_content:
                    assistant_msg["reasoning_content"] = reasoning_content
                
                self.messages.append(assistant_msg)

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
                # 最终文本回答（包含 reasoning_content）
                assistant_msg = {"role": "assistant", "content": content}
                if reasoning_content:
                    assistant_msg["reasoning_content"] = reasoning_content
                self.messages.append(assistant_msg)
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

        return {
            "full_reply": full_reply,
            "used_tools": used_tools,
            "iterations": iterations,
        }

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
        
        使用 Pipeline 执行可配置的步骤。

        Args:
            msg: 用户消息
            callback: 流式输出回调函数

        Returns:
            Tuple[str, bool]: (助手完整回复, 是否使用了工具调用)
        """
        self.reset_interrupt()
        self.reset_session_state()

        # 构建执行上下文
        context = {
            "user_msg": msg,
            "msg": msg,
            "callback": callback,
        }

        # 执行 Pipeline
        result = self.pipeline.execute(context)
        
        # 提取结果
        full_reply = result.get("full_reply", "")
        used_tools = result.get("used_tools", False)
        
        return full_reply, used_tools
