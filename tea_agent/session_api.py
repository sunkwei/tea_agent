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
        # 不覆盖子类已设置的 model 值
        if not hasattr(self, 'model'):
            self.model: str = ""
        self.enable_thinking: bool = True
        # thinking 支持状态：分别记录主模型和便宜模型
        self._thinking_supported: Optional[bool] = None  # 主模型
        self._cheap_thinking_supported: Optional[bool] = None  # 便宜模型
        self.tool_log: Optional[Callable[[str], None]] = None
        self._last_usage: Dict[str, int] = {
            "total_tokens": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
        }

    def _probe_thinking_support(self, client=None, model=None, is_cheap=False):
        """
        检测模型是否支持 thinking。
        仅检测一次，避免每次 API 调用都重复检测。
        
        Args:
            client: OpenAI 客户端实例（默认为主客户端）
            model: 模型名称（默认为主模型）
            is_cheap: 是否为便宜模型
        """
        # 根据 is_cheap 选择要检查和更新的状态字段
        if is_cheap:
            if self._cheap_thinking_supported is not None:
                return  # 已经检测过
        else:
            if self._thinking_supported is not None:
                return  # 已经检测过
        
        target_client = client or self.client
        target_model = model or self.model
        
        if not self.enable_thinking or not target_client:
            return
        
        try:
            # 发送一个极简请求来检测 thinking 支持
            test_response = target_client.chat.completions.create(
                model=target_model,
                messages=[{"role": "user", "content": "Hi"}],
                stream=False,
                extra_body={"thinking": {"type": "enabled"}},
                max_tokens=10,
            )
            
            # 更新对应的状态
            if is_cheap:
                self._cheap_thinking_supported = True
            else:
                self._thinking_supported = True
                
            if self.tool_log:
                model_type = "便宜模型" if is_cheap else "主模型"
                self.tool_log(f"🧠 {model_type}支持 thinking，已启用")
        except Exception as e:
            err_str = str(e).lower()
            if ('thinking' in err_str or 'extra_body' in err_str or
                    'unsupported' in err_str or 'invalid' in err_str):
                # 更新对应的状态
                if is_cheap:
                    self._cheap_thinking_supported = False
                else:
                    self._thinking_supported = False
                    
                if self.tool_log:
                    model_type = "便宜模型" if is_cheap else "主模型"
                    self.tool_log(f"⚠️ {model_type}不支持 thinking，已禁用")
            else:
                # 其他错误，不影响 thinking 检测，保持 None 状态
                if self.tool_log:
                    model_type = "便宜模型" if is_cheap else "主模型"
                    self.tool_log(f"⚠️ {model_type} thinking 检测时出错: {e}")

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

    def _create_chat_stream(self, api_messages: List[Dict], tools: List[Dict], client=None, model=None, is_cheap=False):
        """
        创建流式聊天请求。

        Args:
            api_messages: 紧凑消息列表
            tools: 工具定义列表
            client: OpenAI 客户端实例（默认为主客户端）
            model: 模型名称（默认为主模型）
            is_cheap: 是否为便宜模型（用于选择对应的 thinking 状态）

        Returns:
            流式响应迭代器
        """
        target_client = client or self.client
        target_model = model or self.model
        
        kwargs = {
            "model": target_model,
            "messages": api_messages,
            "tools": tools,
            "tool_choice": "auto",
            "stream": True,
            "stream_options": {"include_usage": True},
        }

        # 根据对应的 thinking 状态决定是否启用
        if is_cheap:
            thinking_supported = self._cheap_thinking_supported
        else:
            thinking_supported = self._thinking_supported
            
        if self.enable_thinking and thinking_supported:
            kwargs["extra_body"] = {"thinking": {"type": "enabled"}}

        return target_client.chat.completions.create(**kwargs)

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
