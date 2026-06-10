"""
在线工具调用会话 - Token 优化版 (重构版：组合模式)
支持 OpenAI 兼容 API 的 Function Calling 功能

Token 优化策略:
1. 压缩系统提示词 (~200 tokens, 原 ~1000+)
2. 历史摘要：超过5轮的对话自动摘要，只传摘要+最近N轮
3. 工具输出截断：超长结果截断至 max_tool_output 字符
4. 助手回复截断：超长回复截断至 max_assistant_content 字符
5. 长期记忆注入：相关记忆在每次对话中自动注入（上限5条）

重构说明:
- 从 Mixin 多重继承改为组合模式
- 所有共享状态通过 SessionContext 管理
- 功能委派给各个 Component：API, Tool, Memory, Summarizer
- 2026-05 P2重构: 提取 JsonSanitizer/HistoryBuilder/OsInfoInjector/ToolLoopRunner
"""

from openai import OpenAI
from typing import List, Dict, Callable, Tuple, Any, Optional
import logging

from tea_agent.basesession import BaseChatSession
from tea_agent.session_prompts import COMPACT_SYSTEM_PROMPT
from tea_agent.session_pipeline import SessionPipeline

# 组件导入（替代 Mixin）
from tea_agent.session_context import SessionContext
from tea_agent.session_api_component import APIComponent
from tea_agent.session_tool_component import ToolComponent
from tea_agent.session_memory_component import MemoryComponent
from tea_agent.session_summarizer_component import SummarizerComponent

# 提取的独立模块
from tea_agent.session._history_builder import build_api_messages
from tea_agent.session._os_info_injector import inject_os_info as _inject_os_info_impl
from tea_agent.session._tool_loop_runner import execute_tool_loop

logger = logging.getLogger("session")


# ── 模块级纯函数 ──

def analyze_intent(text: str) -> dict:
    """轻量级意图分析 — 返回 {type, skip_tool_loop, required_tools}。"""
    return {"type": "general", "skip_tool_loop": False, "required_tools": None}


_VALID_MODES = {"pragmatic", "creative", "mixed"}


def detect_mode(call_tool_fn, user_text: str) -> dict:
    """根据用户输入自动检测并返回建议的模式。"""
    try:
        result = call_tool_fn(action="auto", text=user_text)
        if isinstance(result, dict):
            return result
        return {"switched": False, "mode": None}
    except Exception as e:
        logging.getLogger("session").debug(f"模式检测失败: {e}")
        return {"switched": False, "mode": None, "error": str(e)}


def extract_mode(result: dict):
    """从 detect_mode 结果中提取模式值，验证合法性。"""
    mode = result.get("to_mode") or result.get("mode") or result.get("detected")
    if mode in _VALID_MODES:
        return mode
    return None


class OnlineToolSession(BaseChatSession):
    """
    在线工具调用会话 - Token 优化版
    支持 OpenAI 兼容 API 的 Function Calling 功能

    重构说明：
    - 使用组合模式替代 Mixin 多重继承
    - 共享状态通过 self.context (SessionContext) 管理
    - 功能委派给 self.api, self.tools, self.memory, self.summarizer 组件
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
        memory_dedup_threshold: float = 0.3,
        supports_vision: bool = False,
        supports_reasoning: bool = True,
        disable_summary: bool = False,
        no_stream_chunk: bool = False,
    ):
        """初始化会话

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
            cheap_api_key: 便宜模型 API密钥
            cheap_api_url: 便宜模型 API地址
            cheap_model: 便宜模型名称
            keep_turns: 保留最近N轮完整对话
            max_tool_output: 工具输出截断字符数
            max_assistant_content: 助手回复截断字符数
            extra_iterations_on_continue: 续命时追加的工具调用轮数
            memory_extraction_threshold: 触发记忆提取的最低未摘要消息数
            memory_dedup_threshold: 记忆去重相似度阈值 (0~1)
            supports_vision: 是否支持视觉输入
            supports_reasoning: 是否支持 reasoning
            disable_summary: 禁用历史压缩和摘要
        """
        sp = system_prompt or self._COMPACT_SYSTEM_PROMPT

        # ── 1. 创建共享上下文 ──
        import httpx
        _http_client = httpx.Client(proxy=None)
        main_client = OpenAI(api_key=api_key, base_url=api_url, http_client=_http_client)

        cheap_client: Optional[OpenAI] = None
        if cheap_api_key and cheap_api_url and cheap_model:
            cheap_client = OpenAI(api_key=cheap_api_key, base_url=cheap_api_url, http_client=httpx.Client(proxy=None))

        self.context = SessionContext(
            messages=[],
            model=model,
            enable_thinking=enable_thinking,
            client=main_client,
            cheap_client=cheap_client,
            cheap_model=cheap_model,
            toolkit=toolkit,
            storage=storage,
            keep_turns=keep_turns,
            max_tool_output=max_tool_output,
            max_assistant_content=max_assistant_content,
            memory_extraction_threshold=memory_extraction_threshold,
            memory_dedup_threshold=memory_dedup_threshold,
            supports_vision=supports_vision,
            supports_reasoning=supports_reasoning,
            disable_summary=disable_summary,
            no_stream_chunk=no_stream_chunk,
            extra_iterations_on_continue=extra_iterations_on_continue,
        )

        # ── 2. 调用基类初始化 ──
        BaseChatSession.__init__(self, model, max_history, sp)

        logger.info(f"OnlineToolSession init ok: main model: {model}, cheap model: {cheap_model}")

        # ── 3. 创建并初始化组件 ──
        self.api = APIComponent(self.context)
        self.tools_comp = ToolComponent(self.context)
        self.memory_comp = MemoryComponent(self.context)
        self.summarizer_comp = SummarizerComponent(self.context)

        for comp in [self.api, self.tools_comp, self.memory_comp, self.summarizer_comp]:
            comp.initialize()

        # ── 兼容属性 ──
        self.max_iterations = max_iterations
        self.storage = storage
        self._cheap_client = cheap_client
        self._cheap_model_name = cheap_model
        self._current_mode = "mixed"
        self._supports_vision = supports_vision
        self._supports_reasoning = supports_reasoning
        self._disable_summary = disable_summary

        # ── 续跑控制 ──
        import threading
        self._extra_iterations = 0
        self._continue_after_max = False
        self._max_iter_wait = threading.Event()

        # ── 工具定义 ──
        self.tools: List[Dict] = []
        self.tools = self.tools_comp.build_tools()

        # 初始化 Memory 管理器
        self.memory_comp.initialize()

        # ── 反思和提示词管理器 ──
        if self.storage is not None:
            from tea_agent.reflection import ReflectionManager
            from tea_agent.prompt_manager import SystemPromptManager
            self.reflection_manager = ReflectionManager(
                storage=self.storage,
                cheap_client=cheap_client,
                cheap_model=cheap_model,
            )
            self.prompt_manager = SystemPromptManager(
                storage=self.storage,
                cheap_client=cheap_client,
                cheap_model=cheap_model,
            )
            dynamic_prompt = self.prompt_manager.initialize()
            if not system_prompt:
                self.system_prompt = dynamic_prompt
            logger.info(f"系统提示词 v{self.prompt_manager.current_version} 已加载")

            self.context.reflection_manager = self.reflection_manager
        else:
            self.reflection_manager = None
            self.prompt_manager = None
            logger.info("Storage 未设置，跳过 ReflectionManager/PromptManager 初始化")

        # ── Pipeline ──
        self.pipeline = SessionPipeline()
        self.context.pipeline = self.pipeline
        self._setup_default_pipeline()

    # ── 属性桥接（context 代理，保持 BaseChatSession 兼容）──

    @property
    def messages(self): return self.context.messages
    @messages.setter
    def messages(self, v): self.context.messages = v

    @property
    def model(self): return self.context.model
    @model.setter
    def model(self, v): self.context.model = v

    @property
    def enable_thinking(self): return self.context.enable_thinking
    @enable_thinking.setter
    def enable_thinking(self, v): self.context.enable_thinking = v

    @property
    def _rounds_collector(self): return self.context._rounds_collector
    @_rounds_collector.setter
    def _rounds_collector(self, v): self.context._rounds_collector = v

    @property
    def _last_usage(self): return self.context._last_usage
    @_last_usage.setter
    def _last_usage(self, v): self.context._last_usage = v

    @property
    def _last_cheap_usage(self): return self.context._last_cheap_usage
    @_last_cheap_usage.setter
    def _last_cheap_usage(self, v): self.context._last_cheap_usage = v

    @property
    def _history_summary(self): return self.context._history_summary
    @_history_summary.setter
    def _history_summary(self, v): self.context._history_summary = v

    @property
    def _semantic_summary(self): return self.context._semantic_summary
    @_semantic_summary.setter
    def _semantic_summary(self, v): self.context._semantic_summary = v

    @property
    def _tool_chain_summary(self): return self.context._tool_chain_summary
    @_tool_chain_summary.setter
    def _tool_chain_summary(self, v): self.context._tool_chain_summary = v

    @property
    def _level2(self): return self.context._level2
    @_level2.setter
    def _level2(self, v): self.context._level2 = v

    @property
    def max_tool_output(self): return self.context.max_tool_output
    @max_tool_output.setter
    def max_tool_output(self, v): self.context.max_tool_output = v

    @property
    def max_assistant_content(self): return self.context.max_assistant_content
    @max_assistant_content.setter
    def max_assistant_content(self, v): self.context.max_assistant_content = v

    @property
    def keep_turns(self): return self.context.keep_turns
    @keep_turns.setter
    def keep_turns(self, v): self.context.keep_turns = v

    @property
    def extra_iterations_on_continue(self): return self.context.extra_iterations_on_continue
    @extra_iterations_on_continue.setter
    def extra_iterations_on_continue(self, v): self.context.extra_iterations_on_continue = v

    @property
    def memory_extraction_threshold(self): return self.context.memory_extraction_threshold
    @memory_extraction_threshold.setter
    def memory_extraction_threshold(self, v): self.context.memory_extraction_threshold = v

    @property
    def memory_dedup_threshold(self): return self.context.memory_dedup_threshold
    @memory_dedup_threshold.setter
    def memory_dedup_threshold(self, v): self.context.memory_dedup_threshold = v

    @property
    def disable_summary(self): return self.context.disable_summary
    @disable_summary.setter
    def disable_summary(self, v): self.context.disable_summary = v

    @property
    def no_stream_chunk(self): return self.context.no_stream_chunk
    @no_stream_chunk.setter
    def no_stream_chunk(self, v): self.context.no_stream_chunk = v

    @property
    def supports_vision(self): return self.context.supports_vision
    @supports_vision.setter
    def supports_vision(self, v): self.context.supports_vision = v

    @property
    def supports_reasoning(self): return self.context.supports_reasoning
    @supports_reasoning.setter
    def supports_reasoning(self, v): self.context.supports_reasoning = v

    # ──────────────────────────────────────────────
    # 委派方法
    # ──────────────────────────────────────────────

    def _get_summarize_client(self) -> Tuple[Any, str]:
        """获取用于摘要/提取任务的客户端和模型名。"""
        if self._cheap_client and self._cheap_model_name:
            return self._cheap_client, self._cheap_model_name
        return self.context.client, self.context.model

    def _get_effective_params(self, model_type: str = "main") -> Dict[str, Any]:
        """返回 {temperature, max_tokens, top_p}，失败时返回空 dict。"""
        try:
            from .config import get_config
            return get_config().get_effective_params(model_type, self._current_mode)
        except Exception:
            return {}

    # ──────────────────────────────────────────────
    # 流式处理（委派给 API 组件）
    # ──────────────────────────────────────────────

    def _process_stream_with_reasoning(self, response, callback) -> Tuple[str, List[Dict], str]:
        """处理流式/非流式响应，收集内容、工具调用数据和 reasoning_content。"""
        content_parts = []
        tool_calls_data = []
        reasoning_parts = []

        # 非流式模式
        if self.context.no_stream_chunk:
            if hasattr(response, 'usage') and response.usage:
                self.api._accumulate_usage(response.usage)
            if response.choices:
                msg = response.choices[0].message
                if hasattr(msg, 'reasoning_content') and msg.reasoning_content:
                    reasoning_parts.append(msg.reasoning_content)
                    callback(f"[THINK]{msg.reasoning_content}")
                if msg.content:
                    content_parts.append(msg.content)
                    callback(msg.content)
                if msg.tool_calls:
                    for tc in msg.tool_calls:
                        tool_calls_data.append({
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        })
            content = "".join(content_parts)
            reasoning_content = "".join(reasoning_parts)
            return content, tool_calls_data, reasoning_content

        # 流式模式
        for chunk in response:
            if hasattr(chunk, 'usage') and chunk.usage:
                self.api._accumulate_usage(chunk.usage)

            if not hasattr(chunk, 'choices') or not chunk.choices:
                continue

            delta = chunk.choices[0].delta

            if hasattr(delta, 'reasoning_content') and delta.reasoning_content:
                reasoning_parts.append(delta.reasoning_content)
                callback(f"[THINK]{delta.reasoning_content}")

            if delta.content:
                content_parts.append(delta.content)
                callback(delta.content)

            if delta.tool_calls:
                self.api.accumulate_tool_calls_from_delta(delta, tool_calls_data)

        content = "".join(content_parts)
        reasoning_content = "".join(reasoning_parts)
        return content, tool_calls_data, reasoning_content

    # ──────────────────────────────────────────────
    # Pipeline 设置
    # ──────────────────────────────────────────────

    def _inject_os_info(self, context: Dict) -> List:
        """注入操作系统环境信息 — 仅 OS 变化时重新注入。
        
        跨会话持久化 OS 签名：同一 topic 在同一 OS 上只注入一次，
        切换主机（Windows↔Linux）时自动重新注入。
        """
        from tea_agent.session._os_info_injector import (
            _get_os_signature, _load_persisted_os_sig, _save_os_sig,
            _inject_os_info_impl,
        )
        current_sig = _get_os_signature()

        # 首次检查：从持久化文件加载上次签名
        topic_id = getattr(self.context, 'current_topic_id', None)
        if not self.context._os_info_injected and topic_id:
            self.context._os_info_injected = _load_persisted_os_sig(topic_id)

        # OS 未变化 → 跳过
        if self.context._os_info_injected == current_sig:
            return self.messages

        # OS 变化或首次注入
        self.context._os_info_injected = current_sig
        if topic_id:
            _save_os_sig(topic_id, current_sig)
        logger.info(f"OS 信息注入: {current_sig} (topic={topic_id})")
        return _inject_os_info_impl(
            self.messages,
            toolkit_root_dir=self.toolkit.root_dir,
            supports_reasoning=self.context.supports_reasoning,
        )

    def _setup_default_pipeline(self):
        """设置默认的 Pipeline 步骤"""
        self.pipeline.register_step(
            name="inject_os_info", func=self._inject_os_info,
            enabled=True, description="注入操作系统环境信息轮次", position=17,
        )
        self.pipeline.register_step(
            name="inject_memories", func=self.memory_comp.inject_memories,
            enabled=True, description="从长期记忆中注入相关记忆", position=15,
        )
        self.pipeline.register_step(
            name="add_user_message",
            func=lambda ctx: (self.add_user_message(ctx.get("user_msg", "")), self.context.messages)[1],
            enabled=True, description="添加用户消息到会话历史", position=20,
        )
        self.pipeline.register_step(
            name="summarize_old_history",
            func=lambda ctx: (self.summarizer_comp.summarize_old_history(self.api, self._get_summarize_client), self.context.messages)[1],
            enabled=True, description="将旧对话历史压缩为摘要", position=30,
        )
        self.pipeline.register_step(
            name="tool_loop", func=self._execute_tool_loop,
            enabled=True, description="执行工具调用循环", position=40,
        )

    # ──────────────────────────────────────────────
    # 构建 API 消息（委派给 _history_builder）
    # ──────────────────────────────────────────────

    def _build_api_messages(self) -> List[Dict]:
        """三级历史拼接 — 委派给 _history_builder.build_api_messages。"""
        return build_api_messages(self.context, self.system_prompt)

    # ──────────────────────────────────────────────
    # 意图分析与工具循环
    # ──────────────────────────────────────────────

    def _analyze_intent(self, text: str) -> dict:
        """轻量级意图分析。"""
        return analyze_intent(text)

    def _execute_tool_loop(self, context: Dict) -> Dict:
        """执行工具调用循环 — 委派给 _tool_loop_runner.execute_tool_loop。"""
        return execute_tool_loop(self, context)

    def _build_tools(self, tool_filter: list = None):
        """构建工具定义列表。"""
        from tea_agent.session_tool_component import filter_tools
        all_tools = self.tools_comp.build_tools()
        self.tools = filter_tools(all_tools, tool_filter)
        if tool_filter:
            logger.info(f"[Pipe Dynamic] Tool Injection: enabled {len(self.tools)} tools based on intent")

    def update_tools(self):
        """重新加载并刷新工具定义"""
        self.context.toolkit.reload()
        self._build_tools()

    def _auto_detect_mode(self, user_text: str):
        """根据用户输入自动检测并切换 Agent 模式。"""
        result = detect_mode(
            call_tool_fn=lambda action, text: self.context.toolkit.call_tool(
                'toolkit_mode', action=action, text=text
            ),
            user_text=user_text,
        )
        if result.get('switched'):
            logger.info(
                f"🤖 自动切换模式: {result.get('from_mode')} → {result.get('to_mode')} "
                f"(原因: {result.get('reason', 'N/A')})"
            )
        new_mode = extract_mode(result)
        if new_mode:
            self._current_mode = new_mode

    def reset_session_state(self):
        """重置会话状态。"""
        self.api.reset_usage()
        self.api.reset_cheap_usage()
        self._rounds_collector = []
        self._extra_iterations = 0
        self._max_iter_wait.clear()
        self._strip_reasoning_content(self.context.messages)

    def _notify(self, title: str, message: str) -> None:
        """跨平台桌面通知（通过 toolkit_notify）。"""
        try:
            self.context.toolkit.call_tool(
                "toolkit_notify", title=title, message=message, duration=5000
            )
        except Exception:
            pass

    def _notify_reflection_done(self, reflection_id: int):
        self._notify("🔍 元认知反思完成", f"反思 #{reflection_id} 已生成")

    def _notify_prompt_evolved(self, version: int):
        self._notify("📝 提示词进化", f"系统提示词已进化到 v{version}")

    def chat_stream(self, msg: str, callback: Callable[[str], None], topic_id: str = "", on_status: Optional[Callable[[str], None]] = None) -> Tuple[str, bool]:
        """流式对话，支持工具调用。使用 Pipeline 执行可配置的步骤。"""
        _msg_text = msg if isinstance(msg, str) else msg.get("text", "")
        _msg_images = None if isinstance(msg, str) else msg.get("images", [])

        if _msg_images and not self.context.supports_vision:
            error_msg = f"⚠️ 当前模型 {self.context.model} 不支持图片输入，请更换支持视觉的模型或移除图片后重试。"
            logger.warning(error_msg)
            callback(error_msg)
            return error_msg, False

        logger.debug(f"chat_stream start: msg_len={len(str(msg))}, topic_id={topic_id}, model={self.context.model}, enable_thinking={self.context.enable_thinking}")
        logger.debug(f"chat_stream user message: {_msg_text[:200]}..." if len(_msg_text) > 200 else f"chat_stream user message: {_msg_text}")

        self.current_topic_id = topic_id
        self.reset_interrupt()
        self.reset_session_state()

        self._auto_detect_mode(_msg_text)

        intent = self._analyze_intent(_msg_text)

        if intent.get('required_tools'):
            self._build_tools(tool_filter=intent['required_tools'])
        else:
            self._build_tools()

        context = {
            "user_msg": msg,
            "msg": _msg_text,
            "callback": callback,
            "on_status": on_status,
        }

        if intent.get('skip_tool_loop'):
            context['skip_tool_loop'] = True

        # 开始反思追踪
        if self.reflection_manager is not None:
            trace = self.reflection_manager.start_trace(topic_id, _msg_text)
            self.context._current_trace = trace
        else:
            self.context._current_trace = None

        # 执行 Pipeline
        result = self.pipeline.execute(context)

        full_reply = result.get("full_reply", "")
        used_tools = result.get("used_tools", False)
        iterations = result.get("iterations", 0)

        # 完成追踪
        if self.reflection_manager is not None and self.context._current_trace is not None:
            self.reflection_manager.finish_trace(
                self.context._current_trace,
                total_iterations=iterations,
                used_tools=used_tools,
                interrupted=result.get("interrupted", False),
                error=str(result.get("error", "")) if result.get("error") else None,
            )
        return full_reply, used_tools
