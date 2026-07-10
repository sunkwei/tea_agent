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
- 功能委派给各个 Component：API, Tool, Summarizer
- 2026-07 拆分: SessionContext/SessionComponent→_context.py, Prompt→_prompts.py
"""

import json
import logging
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

from openai import OpenAI

from tea_agent.basesession import BaseChatSession, relaxed_json_loads

# 组件导入（替代 Mixin）
from tea_agent.session.context import SessionComponent, SessionContext
from tea_agent.session.history_builder import build_api_messages
from tea_agent.session.os_info_injector import inject_os_info
from tea_agent.session.params import get_cheap_params
from tea_agent.session.prompts import (
    COMPACT_SYSTEM_PROMPT,
    HISTORY_SUMMARIZE_SYSTEM,
    HISTORY_SUMMARIZE_USER,
)
from tea_agent.session.tool_loop_runner import execute_tool_loop
from tea_agent.session_pipeline import SessionPipeline

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



class APIComponent(SessionComponent):
    """API 交互组件 — 负责 LLM API 通信（thinking 检测、流式调用、Token 用量追踪）。"""

    @property
    def name(self) -> str:
        return "api"

    def initialize(self) -> None:
        pass

    def _probe_thinking_support(self, client=None, model=None, is_cheap=False):
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
            target_client.chat.completions.create(
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

    def _accumulate_usage(self, usage, is_cheap=False):
        """累加 token 用量到主模型或便宜模型的计数器。

        Args:
            usage: API 返回的 usage 对象（含 prompt_tokens/completion_tokens 等）
            is_cheap: True=累加到便宜模型计数, False=累加到主模型计数
        """
        if usage is None:
            return
        u = self.ctx._last_cheap_usage if is_cheap else self.ctx._last_usage
        prompt = getattr(usage, 'prompt_tokens', None)
        completion = getattr(usage, 'completion_tokens', None)
        total = getattr(usage, 'total_tokens', None)
        cache_hit = getattr(usage, 'prompt_cache_hit_tokens', None)
        cache_miss = getattr(usage, 'prompt_cache_miss_tokens', None)

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
        if cache_hit is not None:
            u["prompt_cache_hit_tokens"] += cache_hit
        if cache_miss is not None:
            u["prompt_cache_miss_tokens"] += cache_miss

    def _track_api_usage(self, response, is_cheap=False):
        if hasattr(response, 'usage') and response.usage:
            self._accumulate_usage(response.usage, is_cheap=is_cheap)

    def create_chat_stream(self, api_messages: list[dict], tools: list[dict],
                          client=None, model=None, is_cheap=False,
                          temperature=None, max_tokens=None, top_p=None):
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
        thinking_supported = self.ctx._cheap_thinking_supported if is_cheap else self.ctx._thinking_supported

        # 构建 extra_body：合并 thinking + 模型 options（如 Ollama 的 num_ctx）
        extra_body = {}
        if thinking_supported:
            extra_body["thinking"] = {
                "type": "enabled" if self.ctx.enable_thinking else "disabled"
            }

        # 从配置中获取模型 options（如 num_ctx）并合并到 extra_body
        try:
            from tea_agent.config import get_config
            _cfg = get_config()
            model_opts = _cfg.main_model.options if not is_cheap else _cfg.cheap_model.options
            if model_opts:
                extra_body.update(model_opts)
        except Exception:
            pass

        if extra_body:
            kwargs["extra_body"] = extra_body

        if target_model in ("mimo-v2.5-pro", "mimo-v2.5", "mimo-v2.0"):
            kwargs.pop("stream_options")
            kwargs.pop("extra_body")

        stream = target_client.chat.completions.create(**kwargs)
        return stream

    def call_summarize_api(self, cli, mdl, messages, temperature=0.1, max_tokens=500):
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
                logger.debug("summarize API: thinking disabled not supported, retrying without extra_body")
                return cli.chat.completions.create(
                    model=mdl,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            logger.warning(f"summarize API call failed: model={mdl}, error={e}")
            raise

    def accumulate_tool_calls_from_delta(self, delta, tool_calls_data: list[dict]):
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
        self.ctx._last_usage = {"total_tokens": 0, "prompt_tokens": 0, "completion_tokens": 0,
                                "prompt_cache_hit_tokens": 0, "prompt_cache_miss_tokens": 0}

    def reset_cheap_usage(self):
        self.ctx._last_cheap_usage = {"total_tokens": 0, "prompt_tokens": 0, "completion_tokens": 0,
                                      "prompt_cache_hit_tokens": 0, "prompt_cache_miss_tokens": 0}

    def get_last_usage(self) -> dict[str, int]:
        return dict(self.ctx._last_usage)

    def get_cheap_usage(self) -> dict[str, int]:
        return dict(self.ctx._last_cheap_usage)

    def get_total_usage(self) -> dict[str, dict[str, int]]:
        return {
            "main": dict(self.ctx._last_usage),
            "cheap": dict(self.ctx._last_cheap_usage),
        }



logger = logging.getLogger("session.tool")

# ── 模块级纯函数（原 session_tools_builder）──

ESSENTIAL_TOOLS = {"toolkit_memory", "toolkit_kb"}


def filter_tools(tools: list, tool_filter: list = None) -> list:
    """按白名单筛选工具列表（保留 ESSENTIAL_TOOLS）。"""
    if tool_filter:
        allowed = set(tool_filter) | ESSENTIAL_TOOLS
        return [t for t in tools if t["function"]["name"] in allowed]
    return tools


def has_tool(tools: list, name: str) -> bool:
    """检查工具列表中是否存在指定名称的工具。"""
    return any(t.get("function", {}).get("name") == name for t in tools)


class ToolComponent(SessionComponent):
    """工具执行组件 — 负责工具调用执行、结果管理、输出截断与追踪。"""

    @property
    def name(self) -> str:
        return "tool"

    def initialize(self) -> None:
        pass

    def build_tools(self) -> list[dict]:
        tools = []
        if self.ctx.toolkit is None:
            logger.warning("toolkit not set, cannot build tool list")
            return tools

        for _name, meta in self.ctx.toolkit.meta_map.items():
            tools.append(meta)
        return tools

    def execute_tool_call(self, call) -> tuple[str, str, str]:
        import time
        func_name = call.function.name
        call_id = call.id
        start_time = time.time()

        if self.ctx.toolkit is None:
            err = "错误：toolkit 未设置"
            logger.error(err)
            self.add_tool_result(call_id, err)
            self._record_tool_to_trace(func_name, False, err, start_time)
            return call_id, func_name, err

        if func_name not in self.ctx.toolkit.func_map:
            err = f"错误：未知工具 {func_name}"
            logger.warning(f"tool call failed: unknown function '{func_name}'")
            self.add_tool_result(call_id, err)
            self._record_tool_to_trace(func_name, False, err, start_time)
            return call_id, func_name, err

        try:
            args = relaxed_json_loads(call.function.arguments)
        except json.JSONDecodeError:
            err = "错误：参数解析失败"
            logger.warning(f"tool call failed: JSON decode error, func={func_name}, raw_args={call.function.arguments[:300]}")
            self.add_tool_result(call_id, err)
            self._record_tool_to_trace(func_name, False, err, start_time)
            return call_id, func_name, err

        if self.ctx.tool_log:
            self.ctx.tool_log(f"🔧 调用工具: {func_name}({args})")

        success = True
        error_msg = ""
        try:
            result = self.ctx.toolkit.call_tool(func_name, **args)
            if self.ctx.tool_log:
                self.ctx.tool_log(f"✅ 结果: {result}")
        except Exception as e:
            result = f"工具执行错误: {e}"
            logger.warning(f"tool execution failed: {func_name}, error={e}")
            success = False
            error_msg = str(e)
            if self.ctx.tool_log:
                self.ctx.tool_log(f"❌ 错误: {e}")

        result_str = str(result)

        # 截断超长工具输出，防止 413 Request Entity Too Large
        max_output = self.ctx.max_tool_output
        result_bytes = len(result_str.encode("utf-8"))
        if result_bytes > max_output:
            # 首尾各保留一半，按换行对齐
            half = max_output // 2
            raw = result_str.encode("utf-8")

            # 前半部分
            head_end = half
            nl = raw.find(b'\n', head_end)
            if nl != -1 and nl < half + 256:
                head_end = nl
            head_text = raw[:head_end].decode("utf-8", errors="replace")

            # 后半部分
            tail_start = len(raw) - half
            nl = raw.rfind(b'\n', tail_start, len(raw))
            if nl != -1 and nl > tail_start - 256:
                tail_start = nl + 1
            tail_text = raw[tail_start:].decode("utf-8", errors="replace")

            result_str = f"{head_text}\n\n... [工具输出截断: {result_bytes}B → {len(head_text.encode('utf-8')) + len(tail_text.encode('utf-8'))}B] ...\n\n{tail_text}"
            logger.info(f"tool output truncated: {func_name}, {result_bytes}B → {len(result_str.encode('utf-8'))}B")

        self.add_tool_result(call_id, result_str)
        self._record_tool_to_trace(func_name, success, error_msg, start_time)
        return call_id, func_name, result_str

    def _record_tool_to_trace(self, func_name: str, success: bool, error_msg: str, start_time: float):
        import time
        trace = self.ctx._current_trace
        if trace is None:
            return
        reflection_mgr = self.ctx.reflection_manager
        if reflection_mgr is None:
            return
        duration_ms = (time.time() - start_time) * 1000
        reflection_mgr.record_tool_call(trace, func_name, success, error_msg, duration_ms)

    def add_tool_result(self, tool_call_id: str, content: str):
        self.ctx.messages.append({
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": content
        })

    def collect_tool_call_round(self, call_id: str, result_str: str):
        self.ctx._rounds_collector.append({
            "role": "tool",
            "content": result_str,
            "tool_call_id": call_id,
        })

    def collect_assistant_tool_calls_round(self, content: str, tool_calls: list, reasoning_content: str = ""):
        tc_list_for_collector = [{
            "id": tc.id,
            "type": "function",
            "function": {
                "name": tc.function.name,
                "arguments": tc.function.arguments
            }
        } for tc in tool_calls]

        entry = {
            "role": "assistant",
            "content": content if content else "",
            "tool_calls": tc_list_for_collector,
        }
        if reasoning_content:
            entry["reasoning_content"] = reasoning_content
        self.ctx._rounds_collector.append(entry)

    def collect_assistant_text_round(self, content: str, reasoning_content: str = ""):
        entry = {
            "role": "assistant",
            "content": content,
        }
        if reasoning_content:
            entry["reasoning_content"] = reasoning_content
        self.ctx._rounds_collector.append(entry)

    def collect_api_error_round(self, content: str):
        self.ctx._rounds_collector.append({
            "role": "assistant",
            "content": content,
        })

    def collect_max_iterations_round(self, content: str):
        self.ctx._rounds_collector.append({
            "role": "assistant",
            "content": content,
        })

    def collect_interruption_round(self, content: str):
        self.ctx._rounds_collector.append({
            "role": "assistant",
            "content": content,
        })

    def parse_tool_calls_from_stream(self, tool_calls_data: list[dict]) -> list:
        valid_tool_calls = []
        for tc_data in tool_calls_data:
            func_id = tc_data["id"]
            if "name" in tc_data:
                func_name = tc_data["name"]
                func_args = tc_data["arguments"]
            elif "function" in tc_data:
                func_name = tc_data["function"]["name"]
                func_args = tc_data["function"]["arguments"]
            else:
                logger.warning(f"tool call failed: invalid data format, data={tc_data}")
                continue

            valid_tool_calls.append(SimpleNamespace(
                id=func_id,
                function=SimpleNamespace(
                    name=func_name,
                    arguments=func_args,
                )
            ))
        return valid_tool_calls



logger = logging.getLogger("session.summarizer")

class SummarizerComponent(SessionComponent):
    """历史摘要组件 — 负责旧对话压缩、三级历史管理、语义摘要生成。"""

    @property
    def name(self) -> str:
        return "summarizer"

    def initialize(self) -> None:
        pass

    def summarize_old_history(self, api_component, get_summarize_client_fn) -> None:
        # 检查是否禁用摘要
        if self.ctx.disable_summary:
            return

        topic_id = getattr(self.ctx, "current_topic_id", None)
        storage = self.ctx.storage
        if not (topic_id and storage):
            return

        # 1. 获取未摘要的对话
        try:
            unsummarized = storage.get_unsummarized_conversations(topic_id)
        except Exception as e:
            logger.warning(f"Fetch unsaved conversations failed: {e}")
            return

        if len(unsummarized) <= self.ctx.keep_turns:
            return

        # 2. 确定需要摘要的范围
        num_to_summarize = len(unsummarized) - self.ctx.keep_turns
        convs_to_summarize = unsummarized[:num_to_summarize]

        # 3. 提取对话文本
        old_text = self._conversations_to_text(convs_to_summarize)
        if not old_text:
            return

        # 获取旧摘要
        try:
            old_summary = storage.get_topic_summary(topic_id) or ""
        except Exception:
            old_summary = ""

        # 构建 Prompt
        existing = (
            f"已有摘要：{old_summary}\n\n"
            if old_summary
            else ""
        )

        try:
            cli, mdl = get_summarize_client_fn()
            # 判断是否使用便宜模型
            is_cheap = (
                self.ctx.cheap_client is not None
                and cli is self.ctx.cheap_client
            )

            cheap_params = get_cheap_params("summarizer")
            response = api_component.call_summarize_api(
                cli, mdl,
                messages=[
                    {"role": "system", "content": HISTORY_SUMMARIZE_SYSTEM},
                    {
                        "role": "user",
                        "content": HISTORY_SUMMARIZE_USER.format(
                            existing=existing, old_text=old_text
                        ),
                    },
                ],
                temperature=cheap_params["temperature"],
                max_tokens=cheap_params["max_tokens"],
            )

            # 统计 token 用量
            api_component._track_api_usage(response, is_cheap=is_cheap)

            content = response.choices[0].message.content
            if isinstance(content, str):
                new_summary = content.strip()

                # 4. 更新数据库
                last_conv_id = convs_to_summarize[-1]['id']
                storage.update_topic_summary(topic_id, new_summary, last_summarized_id=last_conv_id)
                for conv in convs_to_summarize:
                    storage.mark_as_summarized(conv['id'])

                # 5. 同步内存
                self.ctx._history_summary = new_summary

                # 裁剪 messages，保持与数据库同步
                boundary = self._find_recent_boundary()
                if boundary > 1:
                    self.ctx.messages = [self.ctx.messages[0]] + self.ctx.messages[boundary:]

                if self.ctx.tool_log:
                    self.ctx.tool_log(f"📝 历史摘要更新：{new_summary}")

        except Exception as e:
            logger.warning(f"History summary failed: error={e}")
            if self.ctx.tool_log:
                self.ctx.tool_log(f"⚠️ 摘要生成失败: {e}")

    def _conversations_to_text(self, conversations: list[dict], max_per_msg: int = 500) -> str:
        lines = []
        for conv in conversations:
            # 用户消息
            u_msg = conv.get("user_msg", "")
            lines.append(f"[USER]: {u_msg[:max_per_msg]}")

            # AI 消息（含工具调用链）
            rounds = conv.get("rounds_json_parsed")
            if rounds and conv.get("is_func_calling"):
                for rd in rounds:
                    role = rd.get("role", "")
                    content = rd.get("content", "")
                    if role == "assistant" and rd.get("tool_calls"):
                        tc_names = [tc["function"]["name"] for tc in rd["tool_calls"]]
                        lines.append(f"[ASSISTANT 调用工具]: {', '.join(tc_names)}")
                        if content:
                            lines.append(f"[ASSISTANT]: {content[:max_per_msg]}")
                    elif role == "tool":
                        lines.append(f"[工具结果]: {content[:max_per_msg]}")
                    elif role == "assistant" and content:
                        lines.append(f"[ASSISTANT]: {content[:max_per_msg]}")
            else:
                ai_msg = conv.get("ai_msg", "")
                lines.append(f"[ASSISTANT]: {ai_msg[:max_per_msg]}")

        return "\n".join(lines)

    def _find_recent_boundary(self) -> int:
        user_count = 0

        for i in range(len(self.ctx.messages) - 1, 0, -1):
            msg = self.ctx.messages[i]
            if msg.get("role") == "user":
                user_count += 1
                if user_count >= self.ctx.keep_turns:
                    return i

        # 不足 keep_turns 轮，保留全部
        return 1


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
        max_context_tokens: int = 0,
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
            max_context_tokens: 最大上下文 token 数，0=不限制
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

        cheap_client: OpenAI | None = None
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
            max_context_tokens=max_context_tokens,
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

        # ── HTTP客户端管理 ──
        self._http_clients = []
        if _http_client:
            self._http_clients.append(_http_client)
        if cheap_client and hasattr(cheap_client, '_client') and cheap_client._client:
            self._http_clients.append(cheap_client._client)

        # ── 工具定义 ──
        self.tools: list[dict] = []
        self.tools = self.tools_comp.build_tools()

        # 初始化 Memory 管理器
        self.memory_comp.initialize()

        # ── 反思和提示词管理器 ──
        if self.storage is not None:
            from tea_agent.prompt_manager import SystemPromptManager
            from tea_agent.reflection import ReflectionManager
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
            logger.info(f"System prompt v{self.prompt_manager.current_version} loaded")

            self.context.reflection_manager = self.reflection_manager
        else:
            self.reflection_manager = None
            self.prompt_manager = None
            logger.info("Storage not set, skipping ReflectionManager/PromptManager initialization")

        # ── Pipeline ──
        self.pipeline = SessionPipeline()
        self.context.pipeline = self.pipeline
        self._setup_default_pipeline()

    # ── 属性桥接（仅保留外部代码实际使用的 7 个）──
    # 移除了 14 个冗余属性：model, _last_cheap_usage, _level2, max_tool_output,
    # max_assistant_content, max_context_tokens, keep_turns, extra_iterations_on_continue,
    # memory_extraction_threshold, memory_dedup_threshold, disable_summary, no_stream_chunk,
    # supports_vision, supports_reasoning
    # 这些属性在外部代码中未被使用，直接使用 self.context.xxx 访问

    @property
    def messages(self): return self.context.messages
    @messages.setter
    def messages(self, v): self.context.messages = v

    @property
    def enable_thinking(self): return self.context.enable_thinking
    @enable_thinking.setter
    def enable_thinking(self, v): self.context.enable_thinking = v

    @property
    def tool_log(self): return self.context.tool_log
    @tool_log.setter
    def tool_log(self, v): self.context.tool_log = v

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

    # ──────────────────────────────────────────────
    # 委派方法
    # ──────────────────────────────────────────────

    def _get_summarize_client(self) -> tuple[Any, str]:
        """获取用于摘要/提取任务的客户端和模型名。"""
        if self._cheap_client and self._cheap_model_name:
            return self._cheap_client, self._cheap_model_name
        return self.context.client, self.context.model

    def _get_effective_params(self, model_type: str = "main") -> dict[str, Any]:
        """返回 {temperature, max_tokens, top_p}，失败时返回空 dict。"""
        try:
            from .config import get_config
            return get_config().get_effective_params(model_type, self._current_mode)
        except Exception:
            return {}

    # ──────────────────────────────────────────────
    # 流式处理（委派给 API 组件）
    # ──────────────────────────────────────────────

    def _process_stream_with_reasoning(self, response, callback) -> tuple[str, list[dict], str]:
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

    def _inject_os_info(self, context: dict) -> list:
        """注入操作系统环境信息 — 仅 OS 变化时重新注入。

        跨会话持久化 OS 签名：同一 topic 在同一 OS 上只注入一次，
        切换主机（Windows↔Linux）时自动重新注入。
        """
        from tea_agent.session.os_info_injector import (
            _get_os_signature,
            _load_persisted_os_sig,
            _save_os_sig,
        )
        current_sig = _get_os_signature()

        # 首次检查：从持久化文件加载上次签名
        topic_id = getattr(self, 'current_topic_id', None)
        if not self.context._os_info_injected and topic_id:
            self.context._os_info_injected = _load_persisted_os_sig(topic_id)

        # OS 未变化 → 跳过
        if self.context._os_info_injected == current_sig:
            return self.messages

        # OS 变化或首次注入
        self.context._os_info_injected = current_sig
        if topic_id:
            _save_os_sig(topic_id, current_sig)
        logger.info(f"OS info injected: {current_sig} (topic={topic_id})")
        return inject_os_info(
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

    def _get_topic_system_prompt(self) -> str | None:
        """获取当前主题的自定义系统提示词（若有则优先使用）。"""
        topic_id = getattr(self, 'current_topic_id', None)
        if topic_id and self.storage:
            try:
                return self.storage.get_topic_system_prompt(topic_id)
            except Exception:
                pass
        return None

    def _build_api_messages(self) -> list[dict]:
        """三级历史拼接 — 优先使用主题级 system prompt，否则用进化版本。"""
        topic_sp = self._get_topic_system_prompt()
        sp = topic_sp if topic_sp else self.system_prompt
        return build_api_messages(self.context, sp)

    # ──────────────────────────────────────────────
    # 意图分析与工具循环
    # ──────────────────────────────────────────────

    def _analyze_intent(self, text: str) -> dict:
        """轻量级意图分析。"""
        return analyze_intent(text)

    def _execute_tool_loop(self, context: dict) -> dict:
        """执行工具调用循环 — 委派给 _tool_loop_runner.execute_tool_loop。"""
        return execute_tool_loop(self, context)

    def _build_tools(self, tool_filter: list = None):
        """构建工具定义列表。"""
        # from tea_agent.session_tool_component import filter_tools
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
            logger.exception("operation failed")


    def _notify_reflection_done(self, reflection_id: int):
        self._notify("🔍 元认知反思完成", f"反思 #{reflection_id} 已生成")

    def _notify_prompt_evolved(self, version: int):
        self._notify("📝 提示词进化", f"系统提示词已进化到 v{version}")

    def chat_stream(self, msg: str, callback: Callable[[str], None], topic_id: str = "", on_status: Callable[[str], None] | None = None) -> tuple[str, bool]:
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

    def close(self):
        """关闭会话，释放资源"""
        try:
            # 关闭所有HTTP客户端
            for client in self._http_clients:
                try:
                    if hasattr(client, 'close'):
                        client.close()
                except Exception as e:
                    logger.debug(f"Close HTTP client failed: {e}")
            
            # 关闭OpenAI客户端
            if hasattr(self.context, 'client') and self.context.client:
                try:
                    if hasattr(self.context.client, 'close'):
                        self.context.client.close()
                except Exception as e:
                    logger.debug(f"Close main OpenAI client failed: {e}")
            
            if hasattr(self.context, 'cheap_client') and self.context.cheap_client:
                try:
                    if hasattr(self.context.cheap_client, 'close'):
                        self.context.cheap_client.close()
                except Exception as e:
                    logger.debug(f"Close cheap OpenAI client failed: {e}")
            
            # 关闭存储连接
            if hasattr(self, 'storage') and self.storage:
                try:
                    self.storage.close()
                except Exception as e:
                    logger.debug(f"Close storage connection failed: {e}")
            
            logger.info("OnlineToolSession resources released")
        except Exception as e:
            logger.warning(f"Close OnlineToolSession resources failed: {e}")
    
    def __del__(self):
        """析构函数，确保资源被释放"""
        try:
            self.close()
        except Exception:
            logger.exception("operation failed")

from tea_agent.session_memory_component import MemoryComponent
