"""
API 调用组件

负责 OpenAI API 调用、流式响应处理、thinking 降级、token 统计等功能。
从 SessionAPIMixin 重构而来，使用组合模式替代 Mixin。
"""

from typing import List, Dict, Tuple, Any, Optional, Callable
from .session_context import SessionComponent, SessionContext
from tea_agent.session._params import get_cheap_params

# 向后兼容别名
_get_cheap_params = lambda defaults=None: get_cheap_params("api")

class APIComponent(SessionComponent):
    """
    API 调用组件。
    
    通过 self.ctx 访问共享状态（client, model, enable_thinking, token 统计等）。
    """
    
    @property
    def name(self) -> str:
        """Name."""
        return "api"
    
    def initialize(self) -> None:
        """API 组件无需特殊初始化"""
        pass
    
    def _probe_thinking_support(self, client=None, model=None, is_cheap=False):
        """
        检测模型是否支持 thinking。
        仅检测一次，避免每次 API 调用都重复检测。
        """
        # 根据 is_cheap 选择要检查和更新的状态字段
        if is_cheap:
            if self.ctx._cheap_thinking_supported is not None:
                return  # 已经检测过
        else:
            if self.ctx._thinking_supported is not None:
                return  # 已经检测过

        target_client = client or self.ctx.client
        target_model = model or self.ctx.model

        if not self.ctx.enable_thinking or not target_client:
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
                self.ctx._cheap_thinking_supported = True
            else:
                self.ctx._thinking_supported = True

            if self.ctx.tool_log:
                model_type = "便宜模型" if is_cheap else "主模型"
                self.ctx.tool_log(f"🧠 {model_type}支持 thinking，已启用")
        except Exception as e:
            err_str = str(e).lower()
            if ('thinking' in err_str or 'extra_body' in err_str or
                    'unsupported' in err_str or 'invalid' in err_str):
                # 更新对应的状态
                if is_cheap:
                    self.ctx._cheap_thinking_supported = False
                else:
                    self.ctx._thinking_supported = False

                if self.ctx.tool_log:
                    model_type = "便宜模型" if is_cheap else "主模型"
                    self.ctx.tool_log(f"⚠️ {model_type}不支持 thinking，已禁用")
            else:
                # 其他错误，不影响 thinking 检测，保持 None 状态
                if self.ctx.tool_log:
                    model_type = "便宜模型" if is_cheap else "主模型"
                    self.ctx.tool_log(f"⚠️ {model_type} thinking 检测时出错: {e}")

    def _accumulate_usage(self, usage):
        """
        从 API 响应中累积 token 用量到主模型统计。
        """
        if usage is None:
            return
        u = self.ctx._last_usage
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
            # API 未返回 total_tokens，用本次调用的 prompt+completion 推算
            p = prompt if prompt is not None else 0
            c = completion if completion is not None else 0
            u["total_tokens"] += p + c

    def _accumulate_cheap_usage(self, usage):
        """
        从 API 响应中累积 token 用量到便宜模型统计。
        """
        if usage is None:
            return
        u = self.ctx._last_cheap_usage
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
        """
        if hasattr(response, 'usage') and response.usage:
            if is_cheap:
                self._accumulate_cheap_usage(response.usage)
            else:
                self._accumulate_usage(response.usage)

    def create_chat_stream(self, api_messages: List[Dict], tools: List[Dict], 
                          client=None, model=None, is_cheap=False, 
                          temperature=None, max_tokens=None, top_p=None):
        """
        创建流式聊天请求。
        """
        target_client = client or self.ctx.client
        target_model = model or self.ctx.model

        kwargs = {
            "model": target_model,
            "messages": api_messages,
            "tools": tools,
            "tool_choice": "auto",
            "stream": not self.ctx.no_stream_chunk,
        }
        # 传入推理参数（仅在非 None 时设置）
        for param_name in ("temperature", "max_tokens", "top_p"):
            val = locals().get(param_name)
            if val is not None:
                kwargs[param_name] = val

        # 根据模型能力决定是否传 stream_options
        if self.ctx.supports_reasoning:
            kwargs["stream_options"] = {"include_usage": True}

        # 根据对应的 thinking 状态决定是否启用
        if is_cheap:
            thinking_supported = self.ctx._cheap_thinking_supported
        else:
            thinking_supported = self.ctx._thinking_supported

        if thinking_supported:
            kwargs["extra_body"] = {
                "thinking": {
                    "type": "enabled" if self.ctx.enable_thinking else "disabled"
                }
            }

        if target_model in ("mimo-v2.5-pro", "mimo-v2.5", "mimo-v2.0"):
            kwargs.pop("stream_options")
            kwargs.pop("extra_body")

        stream = target_client.chat.completions.create(**kwargs)
        return stream

    def call_summarize_api(self, cli, mdl, messages, temperature=0.1, max_tokens=500):
        """
        调用 LLM 生成摘要，显式禁用 thinking。
        """
        import logging
        logger = logging.getLogger("session.api")
        
        try:
            logger.debug(f"summarize API request: model={mdl}, msgs={len(messages)}, temperature={temperature}, max_tokens={max_tokens}")
            return cli.chat.completions.create(
                model=mdl,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                extra_body={"thinking": {"type": "disabled"}},
            )
        except Exception as e:
            err_str = str(e).lower()
            if 'thinking' in err_str or 'extra_body' in err_str:
                # 模型不支持 thinking 参数，回退到不带 extra_body 的调用
                logger.debug(f"summarize API: thinking disabled not supported, retrying without extra_body")
                return cli.chat.completions.create(
                    model=mdl,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            logger.warning(f"summarize API call failed: model={mdl}, error={e}")
            raise

    def accumulate_tool_calls_from_delta(self, delta, tool_calls_data: List[Dict]):
        """
        从流式 chunk 的 delta 中累积工具调用数据。
        """
        if not delta.tool_calls:
            return

        for tc in delta.tool_calls:
            idx = tc.index

            # 扩展列表
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
        self.ctx._last_usage = {"total_tokens": 0, "prompt_tokens": 0, "completion_tokens": 0}

    def reset_cheap_usage(self):
        """重置便宜模型 token 用量统计"""
        self.ctx._last_cheap_usage = {"total_tokens": 0, "prompt_tokens": 0, "completion_tokens": 0}

    def get_last_usage(self) -> Dict[str, int]:
        """获取最近一次会话的主模型 token 用量"""
        return dict(self.ctx._last_usage)

    def get_cheap_usage(self) -> Dict[str, int]:
        """获取最近一次会话的便宜模型 token 用量"""
        return dict(self.ctx._last_cheap_usage)

    def get_total_usage(self) -> Dict[str, Dict[str, int]]:
        """获取全部 token 用量统计"""
        return {
            "main": dict(self.ctx._last_usage),
            "cheap": dict(self.ctx._last_cheap_usage),
        }
