"""轻量级会话 — LiteSession：无状态、无历史、单轮执行。"""

import json
import logging
from collections.abc import Callable

from openai import OpenAI

from tea_agent.basesession import extract_reasoning, relaxed_json_loads
from tea_agent.config import REASONING_EFFORT_VALUES, clamp_reasoning_effort
from tea_agent.tool_hooks import tool_hooks

logger = logging.getLogger("session.lite")


class LiteSession:
    """轻量级会话 — 无状态、无历史、单轮执行。"""

    def __init__(
        self,
        toolkit,
        api_key: str,
        api_url: str,
        model: str,
        system_prompt: str = "",
        enable_thinking: bool = True,
        thinking_strength: float = 0.7,
        reasoning_effort: str = "auto",  # "auto"=自动推导不发送 / none/minimal/low/medium/high/xhigh/max
        max_iterations: int = 50,
        supports_reasoning: bool = True,
        allowed_tools: list[str] | None = None,  # 已废弃，保留参数仅为兼容性
        denied_tools: list[str] | None = None,  # 已废弃，保留参数仅为兼容性
    ):
        self.toolkit = toolkit
        self.model = model
        self.system_prompt = system_prompt or self._default_system_prompt()
        self.enable_thinking = enable_thinking
        self.thinking_strength = thinking_strength
        self.reasoning_effort = reasoning_effort
        self.max_iterations = max_iterations
        self.supports_reasoning = supports_reasoning
        self.interrupted = False

        # API 客户端
        # API 弹性：从配置读取超时与重试次数（网络中断/睡眠恢复容错）
        try:
            from tea_agent.config import get_config as _get_cfg
            _cfg = _get_cfg()
            _req_to = float(getattr(_cfg, "api_request_timeout", 120.0))
            _conn_to = float(getattr(_cfg, "api_connect_timeout", 30.0))
            _max_retries = int(getattr(_cfg, "api_max_retries", 3))
        except Exception:
            _req_to, _conn_to, _max_retries = 120.0, 30.0, 3

        self.api = OpenAI(
            api_key=api_key, base_url=api_url,
            timeout=_req_to,
            max_retries=_max_retries,
        )

        # 构建工具定义（全部工具，无过滤）
        self.tools = self._build_tools()

        logger.info(
            f"LiteSession init | model: {model} | tools: {len(self.tools)} | 自由奔放模式"
        )

    def _default_system_prompt(self) -> str:
        """默认系统提示词（单一来源：prompt_manager.DEFAULT_SYSTEM_PROMPT）。"""
        from tea_agent.prompt_manager import DEFAULT_SYSTEM_PROMPT

        return DEFAULT_SYSTEM_PROMPT

    def _build_tools(self) -> list[dict]:
        """构建工具定义列表（全部工具，无过滤）。"""
        tools = []
        if not self.toolkit:
            return tools

        # 仅暴露 LLM 可见工具（排除 harness_schema/export_last_pdf），名称排序保证顺序稳定
        from tea_agent.tlk import llm_tool_names

        for name in llm_tool_names(self.toolkit.meta_map.keys()):
            try:
                meta = self.toolkit.meta_map.get(name)
                if not (meta and "function" in meta):
                    continue
            except Exception as e:
                logger.warning(f"Tool {name} meta load failed: {e}")
                continue

            tools.append(meta)

        return tools

    def chat(
        self, user_input: str, callback: Callable[[str], None] | None = None
    ) -> dict:
        """单轮对话。返回 {user, thinking, assistant, tool_calls, error}。

        Args:
            user_input: 用户输入文本
            callback: 回调函数，用于实时输出内容

        Returns:
            包含对话结果的字典
        """
        self.interrupted = False

        # 初始化对话状态
        state = self._init_chat_state(user_input)

        # 构建初始消息
        messages = self._build_initial_messages(user_input)

        try:
            # 执行对话循环
            self._execute_chat_loop(messages, state, callback)

            # 返回结果
            return self._build_chat_result(user_input, state)

        except Exception as e:
            logger.error(f"LiteSession.chat 失败: {e}")
            return self._build_chat_result(user_input, state, error=str(e))

    def _init_chat_state(self, user_input: str) -> dict:
        """初始化对话状态。

        Args:
            user_input: 用户输入

        Returns:
            对话状态字典
        """
        return {
            "full_reply": "",
            "thinking_content": "",
            "tool_calls_count": 0,
            "iterations": 0,
        }

    def _build_initial_messages(self, user_input: str) -> list[dict]:
        """构建初始消息列表。

        Args:
            user_input: 用户输入

        Returns:
            消息列表
        """
        return [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_input},
        ]

    def _execute_chat_loop(
        self,
        messages: list[dict],
        state: dict,
        callback: Callable[[str], None] | None
    ) -> None:
        """执行对话循环。

        Args:
            messages: 消息列表（会被修改）
            state: 对话状态（会被修改）
            callback: 回调函数
        """
        while True:
            # 中断检查
            if self.interrupted:
                break

            # 已达工具轮上限：再执行一次模型回合（最终总结文本）后结束，
            # 避免回复停在上一个工具结果
            if state["iterations"] >= self.max_iterations:
                response = self._call_api(messages)
                content, tool_calls_data, reasoning = self._process_response(
                    response, callback
                )
                state["full_reply"] += content
                if reasoning:
                    state["thinking_content"] += reasoning
                break

            # 调用 API
            response = self._call_api(messages)

            # 处理响应
            content, tool_calls_data, reasoning = self._process_response(
                response, callback
            )

            # 累积回复
            state["full_reply"] += content
            if reasoning:
                state["thinking_content"] += reasoning

            # 解析工具调用
            valid_tool_calls = self._parse_tool_calls(tool_calls_data)

            if valid_tool_calls:
                state["tool_calls_count"] += len(valid_tool_calls)

                # 处理工具调用
                self._handle_tool_calls(messages, valid_tool_calls, content, reasoning)

                state["iterations"] += 1
                continue
            else:
                # 无工具调用，对话结束
                break

    def _handle_tool_calls(
        self,
        messages: list[dict],
        valid_tool_calls: list,
        content: str,
        reasoning_content: str = ""
    ) -> None:
        """处理工具调用。

        Args:
            messages: 消息列表（会被修改）
            valid_tool_calls: 有效的工具调用列表
            content: 助手回复内容
            reasoning_content: 本轮的思维链内容（可能为空字符串，仍需保留字段，
                见 _build_assistant_message 注释——DeepSeek V4 思考模式要求回传）
        """
        # 添加 assistant 消息到上下文
        assistant_msg = self._build_assistant_message(
            content, valid_tool_calls, reasoning_content
        )
        messages.append(assistant_msg)

        # 执行工具调用
        for call in valid_tool_calls:
            if self.interrupted:
                break

            call_id, func_name, result_str = self._execute_tool(call)
            messages.append({
                "role": "tool",
                "tool_call_id": call_id,
                "content": result_str,
            })

        # 立即排空本会话注入的 additionalContexts 并作为 user 消息消费，
        # 避免泄漏到全局 tool_hooks 单例、污染下一个会话的工具循环
        extra_ctxs = tool_hooks.drain_contexts()
        for ctx in extra_ctxs:
            ctx_text = ctx.get("text") if isinstance(ctx, dict) else None
            if not ctx_text:
                ctx_text = ctx.get("content") if isinstance(ctx, dict) else None
            ctx_text = ctx_text or str(ctx)
            messages.append({"role": "user", "content": f"[附加上下文]\n{ctx_text}"})

    def _build_assistant_message(
        self,
        content: str,
        valid_tool_calls: list,
        reasoning_content: str = ""
    ) -> dict:
        """构建助手消息。

        Args:
            content: 助手回复内容
            valid_tool_calls: 工具调用列表
            reasoning_content: 本轮的思维链内容

        Returns:
            助手消息字典
        """
        msg = {
            "role": "assistant",
            "content": content if content else None,
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in valid_tool_calls
            ],
        }
        if self.supports_reasoning:
            # DeepSeek V4 思考模式：带 tools 的请求必须回传 reasoning_content 字段，
            # **含空字符串**——V4 部分 tool_call 轮次返回 reasoning_content=""，
            # 因值为空而丢弃该字段会在下一轮请求触发 400 "must be passed back"。
            msg["reasoning_content"] = reasoning_content
        return msg

    def _build_chat_result(
        self,
        user_input: str,
        state: dict,
        error: str | None = None
    ) -> dict:
        """构建对话结果。

        Args:
            user_input: 用户输入
            state: 对话状态
            error: 错误信息

        Returns:
            对话结果字典
        """
        return {
            "user": user_input,
            "thinking": state["thinking_content"],
            "assistant": state["full_reply"],
            "tool_calls": state["tool_calls_count"],
            "error": error,
        }

    def _call_api(self, messages: list[dict]):
        """调用 API。"""
        kwargs = {
            "model": self.model,
            "messages": messages,
            "stream": True,
        }

        # 如果有工具，添加工具定义
        if self.tools:
            kwargs["tools"] = self.tools

        # thinking 模式（支持思考强度配置）
        if self.enable_thinking and self.supports_reasoning:
            extra_body = {"thinking": {"type": "enabled"}}

            # 映射 reasoning_effort（"auto"=自动推导不发送；非法值回退自动映射）
            reasoning_effort = self.reasoning_effort
            if (
                reasoning_effort
                and reasoning_effort in REASONING_EFFORT_VALUES
                and reasoning_effort != "auto"
            ):
                extra_body["reasoning_effort"] = reasoning_effort
            else:
                strength = max(0.0, min(1.0, self.thinking_strength))
                if strength >= 0.3:
                    extra_body["reasoning_effort"] = "medium" if strength < 0.7 else "high"
                elif strength > 0:
                    extra_body["reasoning_effort"] = "low"
                else:
                    extra_body["thinking"]["type"] = "disabled"

            # 值域钳制：各模型接受的 reasoning_effort 值域不同
            # （如 qwen3.8 仅 xhigh/medium/low，strength 映射会产出 high），
            # 不在值域内时钳制到最接近的支持值，避免 400。
            _eff = extra_body.get("reasoning_effort")
            if _eff:
                from tea_agent.onlinesession import APIComponent  # 延迟导入防循环

                _match = APIComponent._match_model_family(self.model)
                _supported = _match.get("supported_efforts")
                if _supported and _eff not in _supported:
                    extra_body["reasoning_effort"] = clamp_reasoning_effort(_eff, _supported)

            kwargs["extra_body"] = extra_body

        # API 弹性：请求建立阶段失败（网络中断/睡眠恢复）自动重试
        from tea_agent.api_retry import call_with_retry
        try:
            from tea_agent.config import get_config as _get_cfg
            _cfg = _get_cfg()
            _mr = int(getattr(_cfg, "api_max_retries", 3))
            _bf = float(getattr(_cfg, "api_retry_backoff", 2.0))
            _sw = float(getattr(_cfg, "api_sleep_recovery_wait", 5.0))
        except Exception:
            _mr, _bf, _sw = 3, 2.0, 5.0

        return call_with_retry(
            self.api.chat.completions.create,
            max_retries=_mr, backoff=_bf, sleep_recovery_wait=_sw,
            **kwargs,
        )

    def _process_response(self, response, callback: Callable | None) -> tuple:
        """处理流式响应。"""
        content = ""
        reasoning_content = ""
        tool_calls_data = {}

        for chunk in response:
            if self.interrupted:
                break

            if not chunk.choices:
                continue

            delta = chunk.choices[0].delta

            # 处理推理内容（兼容端点为 `reasoning_content`，
            # vLLM 思考模式（Qwen3.8 等）为 `reasoning`）
            _rc = extract_reasoning(delta)
            if _rc:
                reasoning_content += _rc
                if callback:
                    callback(_rc)

            # 处理普通内容
            if delta.content:
                content += delta.content
                if callback:
                    callback(delta.content)

            # 处理工具调用
            if delta.tool_calls:
                for tc in delta.tool_calls:
                    idx = tc.index
                    if idx not in tool_calls_data:
                        tool_calls_data[idx] = {
                            "id": tc.id or "",
                            "name": "",
                            "arguments": "",
                        }
                    if tc.id:
                        tool_calls_data[idx]["id"] = tc.id
                    if tc.function:
                        if tc.function.name:
                            tool_calls_data[idx]["name"] = tc.function.name
                        if tc.function.arguments:
                            tool_calls_data[idx]["arguments"] += tc.function.arguments

        return content, tool_calls_data, reasoning_content

    def _parse_tool_calls(self, tool_calls_data: dict) -> list:
        """解析工具调用数据。"""
        from dataclasses import dataclass

        from tea_agent.session.json_sanitizer import normalize_tool_args

        @dataclass
        class SimpleFunction:
            name: str
            arguments: str

        @dataclass
        class SimpleToolCall:
            id: str
            type: str = "function"
            function: SimpleFunction = None

        valid_calls = []
        for idx in sorted(tool_calls_data.keys()):
            data = tool_calls_data[idx]
            if data["id"] and data["name"]:
                # 源头规范化：截断/非法 arguments 修复为完整 JSON 后再入库，
                # 避免截断参数进入历史 → 每轮 build_api_messages 重复修复刷屏。
                # 无法修复时返回 None，丢弃该 tool_call。
                args = normalize_tool_args(data["name"], data["arguments"])
                if args is None:
                    logger.warning(
                        f"工具 {data['name']} 参数 JSON 无效: {data['arguments'][:100]}"
                    )
                    continue
                valid_calls.append(
                    SimpleToolCall(
                        id=data["id"],
                        function=SimpleFunction(
                            name=data["name"], arguments=args
                        ),
                    )
                )

        return valid_calls

    def _execute_tool(self, call) -> tuple:
        """执行工具调用。"""
        func_name = call.function.name
        args_str = call.function.arguments
        call_id = call.id

        try:
            args = relaxed_json_loads(args_str) if args_str else {}
        except json.JSONDecodeError:
            args = {}

        # 执行工具
        try:
            # ── pre-execute 瀑布（默认放行） ──
            allow, deny_reason = tool_hooks.run_pre(func_name, args)
            if not allow:
                result_str = f"⛔ 工具被拒绝执行: {deny_reason}"
                logger.warning(f"tool blocked by pre-hook: {func_name}, reason={deny_reason}")
            else:
                result = self.toolkit.call_tool(func_name, **args)
                # ── post-execute 瀑布（结果改写 + additionalContexts） ──
                final_result, extra_contexts = tool_hooks.run_post(func_name, args, result)
                if extra_contexts:
                    for ctx in extra_contexts:
                        tool_hooks.inject_context(ctx)
                result = final_result
                result_str = (
                    json.dumps(result, ensure_ascii=False)
                    if isinstance(result, dict)
                    else str(result)
                )
        except Exception as e:
            result_str = f"工具执行错误: {e}"
            logger.warning(f"工具 {func_name} 执行失败: {e}")

        return call_id, func_name, result_str

    def interrupt(self):
        """中断当前对话。"""
        self.interrupted = True

    def close(self):
        """关闭会话，释放 HTTP 客户端资源。"""
        try:
            if hasattr(self, "api") and self.api and hasattr(self.api, "close"):
                self.api.close()
            logger.info("LiteSession 资源已释放")
        except Exception as e:
            logger.warning(f"关闭 LiteSession 资源失败: {e}")
