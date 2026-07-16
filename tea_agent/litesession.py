"""轻量级会话 — LiteSession：无状态、无历史、单轮执行。"""

import json
import logging
from collections.abc import Callable

from openai import OpenAI

from tea_agent.basesession import relaxed_json_loads

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
        max_iterations: int = 50,
        supports_reasoning: bool = True,
        allowed_tools: list[str] | None = None,  # 已废弃，保留参数仅为兼容性
        denied_tools: list[str] | None = None,  # 已废弃，保留参数仅为兼容性
    ):
        self.toolkit = toolkit
        self.model = model
        self.system_prompt = system_prompt or self._default_system_prompt()
        self.enable_thinking = enable_thinking
        self.max_iterations = max_iterations
        self.supports_reasoning = supports_reasoning
        self.interrupted = False

        # API 客户端
        self.api = OpenAI(api_key=api_key, base_url=api_url)

        # 构建工具定义（全部工具，无过滤）
        self.tools = self._build_tools()

        logger.info(
            f"LiteSession init | model: {model} | tools: {len(self.tools)} | 自由奔放模式"
        )

    def _default_system_prompt(self) -> str:
        """默认系统提示词。"""
        return """你是可自我扩展的智能Agent。拥有工具库toolkit，可通过toolkit_save(name,meta,pycode)保存新工具、toolkit_reload()重载获得新能力。内置工具：toolkit_exec(执行命令)、toolkit_load_file(读文件)、toolkit_save_file(写文件)。

核心行为：主动分析任务需求，自主创建/优化/组合工具。工具须为纯Python、可执行、有明确输入输出、通用可复用。可自由设计单函数/多函数/工具套件等结构。

上下文感知规则：
1. 如果当前是 tea_agent 项目自身（特征：当前目录或父目录存在 tea_agent/agent.py）
   → 启用全部自进化能力：可创建工具、修改源码、优化提示词
2. 如果是外部项目（非 tea_agent 自身）
   → 禁用自进化行为：不创建新工具、不修改源码框架、不优化提示词
   → 专注于完成用户的外部任务，仅使用通用文件读写/搜索/编辑工具

你不断进化，能力无上限。以最有效优雅的方式完成任务并持续增强自身。"""

    def _build_tools(self) -> list[dict]:
        """构建工具定义列表（全部工具，无过滤）。"""
        tools = []
        if not self.toolkit:
            return tools

        # 使用 meta_map 获取工具定义
        for name, meta in self.toolkit.meta_map.items():
            if not name.startswith("toolkit_"):
                continue
            try:
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
        while state["iterations"] < self.max_iterations:
            # 中断检查
            if self.interrupted:
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
                self._handle_tool_calls(messages, valid_tool_calls, content)

                state["iterations"] += 1
                continue
            else:
                # 无工具调用，对话结束
                state["iterations"] += 1
                break

    def _handle_tool_calls(
        self,
        messages: list[dict],
        valid_tool_calls: list,
        content: str
    ) -> None:
        """处理工具调用。

        Args:
            messages: 消息列表（会被修改）
            valid_tool_calls: 有效的工具调用列表
            content: 助手回复内容
        """
        # 添加 assistant 消息到上下文
        assistant_msg = self._build_assistant_message(content, valid_tool_calls)
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

    def _build_assistant_message(
        self,
        content: str,
        valid_tool_calls: list
    ) -> dict:
        """构建助手消息。

        Args:
            content: 助手回复内容
            valid_tool_calls: 工具调用列表

        Returns:
            助手消息字典
        """
        return {
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

        # thinking 模式
        if self.enable_thinking and self.supports_reasoning:
            kwargs["extra_body"] = {"thinking": {"type": "enabled"}}

        return self.api.chat.completions.create(**kwargs)

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

            # 处理推理内容
            if hasattr(delta, "reasoning_content") and delta.reasoning_content:
                reasoning_content += delta.reasoning_content
                if callback:
                    callback(delta.reasoning_content)

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
                try:
                    # 验证 JSON 参数（使用容错解析）
                    relaxed_json_loads(data["arguments"])
                    valid_calls.append(
                        SimpleToolCall(
                            id=data["id"],
                            function=SimpleFunction(
                                name=data["name"], arguments=data["arguments"]
                            ),
                        )
                    )
                except json.JSONDecodeError:
                    logger.warning(
                        f"工具 {data['name']} 参数 JSON 无效: {data['arguments'][:100]}"
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
            result = self.toolkit.call_tool(func_name, **args)
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
