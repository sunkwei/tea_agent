"""
API 调用组件

负责 OpenAI API 调用、流式响应处理、thinking 降级、token 统计等功能。
从 SessionAPIMixin 重构而来，使用组合模式替代 Mixin。
"""

from typing import List, Dict, Tuple, Any, Optional, Callable
from .session_context import SessionComponent, SessionContext

def _get_cheap_params(defaults=None):
    """
    返回 cheap 模型 {temperature, max_tokens}，失败时使用传入的 defaults 或保守值。

    Args:
        defaults: Description.
    """
    d = defaults or {"temperature": 0.3, "max_tokens": 1000}
    try:
        from .config import get_config
        eff = get_config().get_effective_params("cheap", "mixed")
        return {
            "temperature": eff.get("temperature", d["temperature"]),
            "max_tokens": eff.get("max_tokens", d["max_tokens"]),
        }
    except Exception:
        return d

class APIComponent(SessionComponent):
    """
    API 调用组件。
    
    通过 self.ctx 访问共享状态（client, model, enable_thinking, token 统计等）。
    """
    
    @property
    def name(self) -> str:
        """
        Name

        Returns:
            str: Description.
        """
        return "api"
    
    def initialize(self) -> None:
        """
        API 组件无需特殊初始化

        Returns:
            None: Description.
        """
        pass
    
    def _probe_thinking_support(self, client=None, model=None, is_cheap=False):
        """
        检测模型是否支持 thinking。

        Args:
            client: Description.
            model: Description.
            is_cheap: Description.
        """
        if is_cheap:
            if self.ctx._cheap_thinking_supported is not None:
                return
        else:
            if self.ctx._thinking_supported is not None:
                return

        target_client = client or self.ctx.client
        target_model = model or self.ctx.model

        if not self.ctx.enable_thinking or not target_client:
            return

        try:
            test_response = target_client.chat.completions.create(
                model=target_model,
                messages=[{"role": "user", "content": "Hi"}],
                stream=False,
                extra_body={"thinking": {"type": "enabled"}},
                max_tokens=10,
            )

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
                if is_cheap:
                    self.ctx._cheap_thinking_supported = False
                else:
                    self.ctx._thinking_supported = False

                if self.ctx.tool_log:
                    model_type = "便宜模型" if is_cheap else "主模型"
                    self.ctx.tool_log(f"⚠️ {model_type}不支持 thinking，已禁用")
            else:
                if self.ctx.tool_log:
                    model_type = "便宜模型" if is_cheap else "主模型"
                    self.ctx.tool_log(f"⚠️ {model_type} thinking 检测时出错: {e}")

    def _accumulate_usage(self, usage):
        """
        从 API 响应中累积 token 用量到主模型统计。

        Args:
            usage: Description.
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
            p = prompt if prompt is not None else 0
            c = completion if completion is not None else 0
            u["total_tokens"] += p + c

    def _accumulate_cheap_usage(self, usage):
        """
        从 API 响应中累积 token 用量到便宜模型统计。

        Args:
            usage: Description.
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

        Args:
            response: Description.
            is_cheap: Description.
        """
        if hasattr(response, 'usage') and response.usage:
            if is_cheap:
                self._accumulate_cheap_usage(response.usage)
            else:
                self._accumulate_usage(response.usage)

    def create_chat_stream(self, api_messages: List[Dict], tools: List[Dict], 
                          client=None, model=None, is_cheap=False, 
                          temperature=None, max_tokens=None, top_p=None,
                          reasoning_effort=None, json_mode=False):
        """
        创建流式聊天请求。

        Args:
            reasoning_effort: DeepSeek thinking 推理力度 (high/max)，
                              None 时取 self.ctx.reasoning_effort。
            json_mode: 是否启用 JSON 输出模式。
        """
        target_client = client or self.ctx.client
        target_model = model or self.ctx.model

        kwargs = {
            "model": target_model,
            "messages": api_messages,
            "tools": tools,
            "tool_choice": "auto",
            "stream": True,
        }

        if self.ctx.supports_reasoning:
            kwargs["stream_options"] = {"include_usage": True}

        if is_cheap:
            thinking_supported = self.ctx._cheap_thinking_supported
        else:
            thinking_supported = self.ctx._thinking_supported

        thinking_active = thinking_supported and self.ctx.enable_thinking

        if thinking_supported:
            kwargs["extra_body"] = {
                "thinking": {
                    "type": "enabled" if self.ctx.enable_thinking else "disabled"
                }
            }

        if thinking_active:
            eff = reasoning_effort if reasoning_effort is not None else self.ctx.reasoning_effort
            if eff:
                kwargs["reasoning_effort"] = eff

        if thinking_active:
            if max_tokens is not None:
                kwargs["max_tokens"] = max_tokens
        else:
            for param_name in ("temperature", "max_tokens", "top_p"):
                val = locals().get(param_name)
                if val is not None:
                    kwargs[param_name] = val

        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        return target_client.chat.completions.create(**kwargs)
    def call_summarize_api(self, cli, mdl, messages, temperature=0.1, max_tokens=500):
        """
        调用 LLM 生成摘要，显式禁用 thinking。

        Args:
            cli: Description.
            mdl: Description.
            messages: Description.
            temperature: Description.
            max_tokens: Description.
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

        Args:
            delta: Description.
            tool_calls_data (List[Dict]): Description.
        """
        if not delta.tool_calls:
            return

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
        self.ctx._last_usage = {"total_tokens": 0, "prompt_tokens": 0, "completion_tokens": 0}

    def reset_cheap_usage(self):
        """重置便宜模型 token 用量统计"""
        self.ctx._last_cheap_usage = {"total_tokens": 0, "prompt_tokens": 0, "completion_tokens": 0}

    def get_last_usage(self) -> Dict[str, int]:
        """
        获取最近一次会话的主模型 token 用量

        Returns:
            Dict[str, int]: Description.
        """
        return dict(self.ctx._last_usage)

    def get_cheap_usage(self) -> Dict[str, int]:
        """
        获取最近一次会话的便宜模型 token 用量

        Returns:
            Dict[str, int]: Description.
        """
        return dict(self.ctx._last_cheap_usage)

    def get_total_usage(self) -> Dict[str, Dict[str, int]]:
        """
        获取全部 token 用量统计

        Returns:
            Dict[str, Dict[str, int]]: Description.
        """
        return {
            "main": dict(self.ctx._last_usage),
            "cheap": dict(self.ctx._last_cheap_usage),
        }
