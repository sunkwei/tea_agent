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
    - _last_cheap_usage: 便宜模型 Token 用量统计字典
    """

    def __init__(self):
        self.client = None
        # 不覆盖子类已设置的 model 值
        if not hasattr(self, 'model'):
            self.model: str = ""
        self.enable_thinking: bool = True
        # NOTE: 2026-04-29, self-evolved by claude-agent ---
        # thinking 支持状态：分别记录主模型和便宜模型。
        # None = 未探测（首次 _create_chat_stream 时自动探测）
        # True = 支持 thinking
        # False = 不支持 thinking
        # 
        # 主模型：乐观假设支持（主流模型都支持）
        # 便宜模型：默认 None，由 _probe_thinking_support 在实际调用时探测。
        #   摘要调用（_summarize_old_history / generate_topic_summary）
        #   不经过 _create_chat_stream，而是通过 _call_summarize_api
        #   显式禁用 thinking，故便宜模型的 thinking 状态不影响摘要。
        self._thinking_supported: Optional[bool] = True
        self._cheap_thinking_supported: Optional[bool] = None
        self.tool_log: Optional[Callable[[str], None]] = None
        
        # 主模型 token 统计
        self._last_usage: Dict[str, int] = {
            "total_tokens": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
        }
        
        # NOTE: 2026-04-29, self-evolved by claude-agent ---
        # 便宜模型 token 统计，通过 _track_api_usage(response, is_cheap=True) 累积
        self._last_cheap_usage: Dict[str, int] = {
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
        """
        从 API 响应中累积 token 用量到主模型统计。
        
        修复要点：
        1. 条件判断从 truthiness 改为 is not None，防止 prompt_tokens=0 时跳过
        2. 每次调用独立推算 total_tokens：若 API 未返回 total，用 prompt+completion 推算
           （而非等全部累加完才 fallback，避免多轮工具调用场景下漏算）
        
        Args:
            usage: OpenAI API 响应的 usage 对象
        """
        if usage is None:
            return
        u = self._last_usage
        prompt = getattr(usage, 'prompt_tokens', None)
        completion = getattr(usage, 'completion_tokens', None)
        total = getattr(usage, 'total_tokens', None)
        
        if prompt is not None:
            u["prompt_tokens"] += prompt
        if completion is not None:
            u["completion_tokens"] += completion
        if total is not None:
            u["total_tokens"] += total
        else:
            # API 未返回 total_tokens，用本次调用的 prompt+completion 推算并累加
            p = prompt if prompt is not None else 0
            c = completion if completion is not None else 0
            u["total_tokens"] += p + c

    # NOTE: 2026-04-29, self-evolved by claude-agent ---
    # 便宜模型 token 累积，与 _accumulate_usage 逻辑相同，写入 _last_cheap_usage。
    def _accumulate_cheap_usage(self, usage):
        """
        从 API 响应中累积 token 用量到便宜模型统计。
        
        与 _accumulate_usage 逻辑相同，但写入 _last_cheap_usage。
        
        Args:
            usage: OpenAI API 响应的 usage 对象
        """
        if usage is None:
            return
        u = self._last_cheap_usage
        prompt = getattr(usage, 'prompt_tokens', None)
        completion = getattr(usage, 'completion_tokens', None)
        total = getattr(usage, 'total_tokens', None)
        
        if prompt is not None:
            u["prompt_tokens"] += prompt
        if completion is not None:
            u["completion_tokens"] += completion
        if total is not None:
            u["total_tokens"] += total
        else:
            p = prompt if prompt is not None else 0
            c = completion if completion is not None else 0
            u["total_tokens"] += p + c

    def _track_api_usage(self, response, is_cheap=False):
        """
        统一的 token 统计入口：从 API 响应中提取 usage 并路由到正确的计数器。
        
        Args:
            response: OpenAI API 响应对象（流式或非流式）
            is_cheap: 是否为便宜模型调用，决定累积到哪个计数器
        """
        if hasattr(response, 'usage') and response.usage:
            if is_cheap:
                self._accumulate_cheap_usage(response.usage)
            else:
                self._accumulate_usage(response.usage)

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
        
        if not thinking_supported:
            kwargs["extra_body"] = {"thinking": {"type": "disable"}}

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
        """重置主模型 token 用量统计"""
        self._last_usage = {"total_tokens": 0, "prompt_tokens": 0, "completion_tokens": 0}

    # NOTE: 2026-04-29, self-evolved by claude-agent ---
    # 重置便宜模型 token 用量统计
    def reset_cheap_usage(self):
        """重置便宜模型 token 用量统计"""
        self._last_cheap_usage = {"total_tokens": 0, "prompt_tokens": 0, "completion_tokens": 0}

    def get_last_usage(self) -> Dict[str, int]:
        """获取最近一次会话的主模型 token 用量"""
        return dict(self._last_usage)

    def get_cheap_usage(self) -> Dict[str, int]:
        """获取最近一次会话的便宜模型 token 用量"""
        return dict(self._last_cheap_usage)

    def get_total_usage(self) -> Dict[str, Dict[str, int]]:
        """
        获取全部 token 用量统计。
        
        Returns:
            {"main": {...}, "cheap": {...}}
        """
        return {
            "main": dict(self._last_usage),
            "cheap": dict(self._last_cheap_usage),
        }
