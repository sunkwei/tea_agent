"""
会话 API 调用模块
负责 OpenAI API 调用、流式响应处理、thinking 降级等功能
"""

from typing import List, Dict, Tuple, Any, Optional, Callable


class SessionAPIMixin:
    """
    API 调用 mixin 类。
    期望使用者提供以下属性：
    - client: OpenAI 客户端
    - model: 模型名称
    - enable_thinking: 是否启用 thinking
    - _thinking_supported: thinking 支持状态（None=未知, True=支持, False=不支持）
    - tool_log: 可选日志回调
    - _last_usage: Token 用量统计字典
    """

    def __init__(self):
        self.client = None
        self.model: str = ""
        self.enable_thinking: bool = True
        self._thinking_supported: Optional[bool] = None
        self.tool_log: Optional[Callable[[str], None]] = None
        self._last_usage: Dict[str, int] = {
            "total_tokens": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
        }

    def _accumulate_usage(self, usage):
        """从 API 响应中累积 token 用量"""
        if usage is None:
            return
        u = self._last_usage
        prompt = getattr(usage, 'prompt_tokens', None)
        completion = getattr(usage, 'completion_tokens', None)
        total = getattr(usage, 'total_tokens', None)
        if prompt:
            u["prompt_tokens"] += prompt
        if completion:
            u["completion_tokens"] += completion
        if total:
            u["total_tokens"] += total
        if u["total_tokens"] == 0 and u["prompt_tokens"] and u["completion_tokens"]:
            u["total_tokens"] = u["prompt_tokens"] + u["completion_tokens"]

    def _create_chat_stream(self, api_messages: List[Dict], tools: List[Dict]):
        """
        创建流式聊天请求，支持 thinking 自动检测和降级。

        Args:
            api_messages: 紧凑消息列表
            tools: 工具定义列表

        Returns:
            流式响应迭代器
        """
        kwargs = {
            "model": self.model,
            "messages": api_messages,
            "tools": tools,
            "tool_choice": "auto",
            "stream": True,
            "stream_options": {"include_usage": True},
        }

        should_try_thinking = (
            self.enable_thinking
            and self._thinking_supported is not False
        )
        if should_try_thinking:
            kwargs["extra_body"] = {"thinking": {"type": "enabled"}}

        try:
            response = self.client.chat.completions.create(**kwargs)
            # 调用成功，确认支持 thinking
            if should_try_thinking and self._thinking_supported is None:
                self._thinking_supported = True
                if self.tool_log:
                    self.tool_log("🧠 模型支持 thinking，已启用")
            return response
        except Exception as think_err:
            # 判断是否为 thinking 不支持的错误
            if should_try_thinking and self._thinking_supported is None:
                err_str = str(think_err).lower()
                if ('thinking' in err_str or 'extra_body' in err_str or
                        'unsupported' in err_str or 'invalid' in err_str):
                    # 降级：不带 thinking 重试
                    self._thinking_supported = False
                    if self.tool_log:
                        self.tool_log("⚠️ 模型不支持 thinking，已自动降级")
                    kwargs.pop("extra_body", None)
                    return self.client.chat.completions.create(**kwargs)
                else:
                    # 非 thinking 相关错误，向上抛出
                    raise
            else:
                raise

    def process_stream_response(self, response, callback: Callable[[str], None]) -> Tuple[str, List[Dict]]:
        """
        处理流式响应，收集内容和工具调用数据。

        Args:
            response: 流式响应迭代器
            callback: 流式输出回调函数

        Returns:
            Tuple[str, List[Dict]]: (累积文本内容, 工具调用数据列表)
        """
        content_parts = []
        tool_calls_data = []

        for chunk in response:
            # 累积 usage 信息
            if hasattr(chunk, 'usage') and chunk.usage:
                self._accumulate_usage(chunk.usage)

            if not hasattr(chunk, 'choices') or not chunk.choices:
                continue

            delta = chunk.choices[0].delta

            # 处理内容
            if delta.content:
                content_parts.append(delta.content)
                callback(delta.content)

            # 处理工具调用
            if delta.tool_calls:
                self._accumulate_tool_calls_from_delta(delta, tool_calls_data)  # type: ignore[attr-defined]

        content = "".join(content_parts)
        return content, tool_calls_data

    def _accumulate_tool_calls_from_delta(self, delta, tool_calls_data: List[Dict]):
        """从流式 chunk 的 delta 中累积工具调用数据（供 process_stream_response 调用）。"""
        for tc in delta.tool_calls:
            idx = tc.index
            while len(tool_calls_data) <= idx:
                tool_calls_data.append({
                    "id": "",
                    "name": "",
                    "arguments": ""
                })

            if tc.id:
                tool_calls_data[idx]["id"] = tc.id
            if tc.function:
                if tc.function.name:
                    tool_calls_data[idx]["name"] = tc.function.name
                if tc.function.arguments:
                    tool_calls_data[idx]["arguments"] += tc.function.arguments

    def reset_usage(self):
        """重置 token 用量统计"""
        self._last_usage = {"total_tokens": 0, "prompt_tokens": 0, "completion_tokens": 0}

    def get_last_usage(self) -> Dict[str, int]:
        """获取最近一次 chat_stream 的 token 用量"""
        return dict(self._last_usage)
