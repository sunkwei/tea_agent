"""
在线工具调用会话 - Token 优化版
支持 OpenAI 兼容 API 的 Function Calling 功能

Token 优化策略:
1. 压缩系统提示词 (~200 tokens, 原 ~1000+)
2. 历史摘要：超过5轮的对话自动摘要，只传摘要+最近N轮
3. 工具输出截断：超长结果截断至 max_tool_output 字符
4. 助手回复截断：超长回复截断至 max_assistant_content 字符
5. 长期记忆注入：相关记忆在每次对话中自动注入（上限5条）
"""

from openai import OpenAI
from typing import List, Dict, Callable, Tuple, Any, Optional
import logging

from tea_agent.basesession import BaseChatSession
from tea_agent.session_summarizer import SessionSummarizerMixin
from tea_agent.session_tool import SessionToolMixin
from tea_agent.session_api import SessionAPIMixin
from tea_agent.session_prompts import COMPACT_SYSTEM_PROMPT
from tea_agent.session_pipeline import SessionPipeline
from tea_agent.session_memory import SessionMemoryMixin

logger = logging.getLogger("session")

class OnlineToolSession(
    BaseChatSession,
    SessionSummarizerMixin,
    SessionToolMixin,
    SessionAPIMixin,
    SessionMemoryMixin,
):
    """
    在线工具调用会话 - Token 优化版
    支持 OpenAI 兼容 API 的 Function Calling 功能

    Token 优化策略:
    - 历史摘要：超过 keep_turns 轮的对话自动摘要，只传摘要 + 最近 N 轮
    - 紧凑消息：工具输出和助手回复超长时截断
    - 精简系统提示词（~200 tokens，原 ~1000+）
    - 长期记忆：从 DB 按优先级+相关性选择最多 5 条注入

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
        storage=None,
        cheap_api_key: str = "",
        cheap_api_url: str = "",
        cheap_model: str = "",
        keep_turns: int = 5,
        max_tool_output: int = 128 * 1024,
        max_assistant_content: int = 128 * 1024,
        extra_iterations_on_continue: int = 5,
        memory_extraction_threshold: int = 2,
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
            storage: Storage 实例，用于持久化存储
            cheap_api_key: 便宜模型 API密钥（用于摘要等低成本任务）
            cheap_api_url: 便宜模型 API地址
            cheap_model: 便宜模型名称
            keep_turns: 保留最近N轮完整对话，更早的对话自动摘要
            max_tool_output: 工具输出截断字符数
            max_assistant_content: 助手回复截断字符数
            extra_iterations_on_continue: 续命时追加的工具调用轮数
            memory_extraction_threshold: 触发记忆提取的最低未摘要消息数
        """
        sp = system_prompt or self._COMPACT_SYSTEM_PROMPT
        BaseChatSession.__init__(self, model, max_history, sp)
        SessionSummarizerMixin.__init__(self)
        SessionToolMixin.__init__(self)
        SessionAPIMixin.__init__(self)
        SessionMemoryMixin.__init__(self)

        logger.info(f"OnlineToolSession init ok: main model: {model}, cheap model: {cheap_model}")

        self.toolkit = toolkit
        self.client = OpenAI(api_key=api_key, base_url=api_url)
        self.max_iterations = max_iterations
        self.enable_thinking = enable_thinking
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
        self.extra_iterations_on_continue = extra_iterations_on_continue
        self.memory_extraction_threshold = memory_extraction_threshold

        # @2026-04-29 gen by deepseek-v4-pro, max_iterations交互式续跑
        import threading
        self._extra_iterations = 0
        self._continue_after_max = False
        self._max_iter_wait = threading.Event()


        # 工具定义
        self.tools: List[Dict] = []
        self._build_tools()
        
        # 初始化 Memory 管理器（在 storage 设置之后）
        self._setup_memory()
        
        # 初始化 Pipeline
        self.pipeline = SessionPipeline()
        self._setup_default_pipeline()

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
        # 1. 记忆注入（在用户消息添加后、摘要前）
        self.pipeline.register_step(
            name="inject_memories",
            func=self._pipeline_inject_memories,
            enabled=True,
            description="从长期记忆中注入相关记忆",
            position=15,
        )
        
        # 2. 添加用户消息
        self.pipeline.register_step(
            name="add_user_message",
            func=lambda ctx: (self.add_user_message(ctx.get("user_msg", "")), self.messages)[1],
            enabled=True,
            description="添加用户消息到会话历史",
            position=20,
        )
        
        # 3. 摘要旧历史
        self.pipeline.register_step(
            name="summarize_old_history",
            func=lambda ctx: (self._summarize_old_history(), self.messages)[1],
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

    # NOTE: 2026-04-29, self-evolved by claude-agent ---
    # _build_api_messages 在系统提示词之后注入长期记忆。
    # 记忆注入位置：system prompt → [记忆] → summary → recent messages
    # 这样模型在处理当前请求时能优先看到相关记忆。
        # @2026-04-29 gen by deepseek-v4-pro, on_status回调+记忆注入至_build_api_messages
    def _build_api_messages(self) -> List[Dict]:
        """
        构建发送给 API 的消息列表。

        压缩策略:
            1. 系统提示词 (始终第一条)
            2. 长期记忆 (如有，紧接系统提示词)
            3. 历史摘要 (如有，替代旧消息)
            4. 最新 n 轮完整对话
        """
        result: List[Dict] = []

        # 1. 系统提示词 (始终第一)
        result.append(self.messages[0])

        # 2. 长期记忆注入（紧接系统提示词）
        if self._injected_memories_text:
            result.append({
                "role": "user",
                "content": self._injected_memories_text
            })

        # 3. 历史摘要
        if self._history_summary:
            result.append({
                "role": "user",
                "content": f"这是我们之前对话的摘要：\n{self._history_summary}"
            })
            result.append({
                "role": "assistant",
                "content": "好的，我已经了解了之前的对话背景。请问有什么我可以帮您的？"
            })

        # 4. 最新 N 轮完整对话
        boundary = self._find_recent_boundary()
        for i in range(boundary, len(self.messages)):
            msg = self.messages[i]
            msg_copy = dict(msg)
            ## XXX: 貌似 deepseek 需要这个字段，否则会报错 400
            if msg_copy["role"] == "assistant" and "reasoning_content" not in msg_copy:
                msg_copy["reasoning_content"] = ""
            result.append(msg_copy)

        return result

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
        on_status = context.get("on_status", None)

        full_reply = ""
        used_tools = False
        iterations = 0

        while iterations < self.max_iterations + self._extra_iterations:
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

                if on_status:
                    on_status(f"⏳ 生成中... 调用工具第{iterations+1}轮 (ESC 打断)")

                # NOTE: 2026-04-28, self-evolved by claude-agent ---
                # 收集 assistant tool_calls 时传递 reasoning_content，
                # 确保持久化到 rounds_json 时不会丢失。
                self._collect_assistant_tool_calls_round(content, valid_tool_calls, reasoning_content)

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

                # 达到最大迭代次数 - 交互式续跑
                if iterations >= self.max_iterations + self._extra_iterations:
                    if on_status:
                        # 通知 GUI 弹框询问，轮询等待支持 ESC 打断
                        on_status(f"!MAX_ITER:已执行{iterations}轮，上限{self.max_iterations + self._extra_iterations}，是否继续？")
                        while not self._max_iter_wait.wait(timeout=0.5):
                            if self.interrupted:
                                final_msg = full_reply + "\n[已打断]"
                                self.add_assistant_message(final_msg)
                                self._collect_interruption_round(final_msg)
                                return {
                                    "full_reply": final_msg,
                                    "used_tools": used_tools,
                                    "interrupted": True,
                                }
                        if not self._continue_after_max:
                            # 用户选择终止
                            warning = f"\n\n[用户选择终止，已执行 {iterations} 轮工具调用]"
                            callback(warning)
                            full_reply += warning
                            self.add_assistant_message(full_reply)
                            self._collect_max_iterations_round(full_reply)
                            break
                        # 用户选择继续：追加5轮
                        self._extra_iterations += self.extra_iterations_on_continue
                        self._continue_after_max = False
                        self._max_iter_wait.clear()
                        on_status("⏳ 已续命5轮，继续生成... (ESC 打断)")
                        continue
                    else:
                        # 无 GUI，直接终止
                        warning = f"\n\n[警告：已达到最大迭代次数 {self.max_iterations}，对话终止]"
                        callback(warning)
                        full_reply += warning
                        self.add_assistant_message(full_reply)
                        self._collect_max_iterations_round(full_reply)
                        break


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
                self._collect_assistant_text_round(content, reasoning_content)
                break
            else:
                break

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
        """
        重置会话状态。
        """
        self.reset_usage()
        self.reset_cheap_usage()
        self._rounds_collector = []
        self._extra_iterations = 0
        self._max_iter_wait.clear()
        
        # NOTE: 2026-04-28, self-evolved by claude-agent ---
        # 清除上一轮 API 会话遗留的 reasoning_content，
        # 避免跨 chat_stream 传递失效的 reasoning_content。
        self._strip_reasoning_content(self.messages)

    def chat_stream(self, msg: str, callback: Callable[[str], None], topic_id: int = -1, on_status: Optional[Callable[[str], None]] = None) -> Tuple[str, bool]:
        """
        流式对话，支持工具调用。
        
        使用 Pipeline 执行可配置的步骤。

        Args:
            msg: 用户消息
            callback: 流式输出回调函数
            topic_id: 当前会话的主题 ID

        Returns:
            Tuple[str, bool]: (助手完整回复, 是否使用了工具调用)
        """

        logger.debug(f"chat_stream: user message: {msg}")

        self.current_topic_id = topic_id
        self.reset_interrupt()
        self.reset_session_state()

        # 构建执行上下文
        context = {
            "user_msg": msg,
            "msg": msg,
            "callback": callback,
            "on_status": on_status,
        }

        # 执行 Pipeline
        result = self.pipeline.execute(context)
        
        # 提取结果
        full_reply = result.get("full_reply", "")
        used_tools = result.get("used_tools", False)
        
        # 自动提取记忆（真正异步，不阻塞）
        # 仅在有效 topic_id 且非打断时触发
        if topic_id > 0 and not result.get("interrupted", False):
            import threading
            def _auto_extract():
                try:
                    count = self.trigger_memory_extraction(topic_id)
                    if count > 0 and on_status:
                        # on_status 回调内部使用 root.after，线程安全
                        on_status(f"🧠 自动提取了 {count} 条新记忆")
                except Exception:
                    pass  # 提取失败不影响主流程
            threading.Thread(target=_auto_extract, daemon=True).start()
        
        return full_reply, used_tools
