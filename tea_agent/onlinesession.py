"""在线工具调用会话 — Token 优化版（组合模式，支持 OpenAI Function Calling）。"""

import json
import logging
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

from openai import OpenAI

from tea_agent.agent_evolution import EvolutionTrigger
from tea_agent.basesession import BaseChatSession, relaxed_json_loads

# 组件导入（替代 Mixin）
from tea_agent.session.context import SessionComponent, SessionContext
from tea_agent.session.history_builder import (
    build_api_messages,
    messages_contain_images,
)
from tea_agent.session.params import get_cheap_params
from tea_agent.session.prompts import (
    COMPACT_SYSTEM_PROMPT,
    HISTORY_SUMMARIZE_SYSTEM,
    HISTORY_SUMMARIZE_USER,
)
from tea_agent.prompt_manager import (
    INTERRUPT_ABANDONED_TMPL,
    INTERRUPT_CORRECTED_TMPL,
)
from tea_agent.session.tool_loop_runner import execute_tool_loop
from tea_agent.session_pipeline import SessionPipeline

logger = logging.getLogger("session")


# 模块级函数


def analyze_intent(text: str) -> dict:
    """轻量级意图分析。"""
    return {"type": "general", "skip_tool_loop": False, "required_tools": None}


# ── 打断知识闭环：信号分类（M2）──
INTERRUPT_SIMILARITY_THRESHOLD = 0.6  # corrected/abandoned 判定阈值（默认，可由配置覆盖）


def classify_interruption(
    event: dict, user_msg: str, embedding_engine=None,
    threshold: float = INTERRUPT_SIMILARITY_THRESHOLD,
) -> tuple[str, float | None]:
    """打断信号三分类：corrected / abandoned / silent。

    打断是隐式负面反馈。用户下一条消息决定信号类型：
    - silent：无下一条消息（用户沉默/关窗）→ 方向被放弃
    - corrected：新消息与被打断内容语义相似（≥ 阈值）→ 方向修正
    - abandoned：新消息语义漂移（< 阈值）→ 方向弃用（换话题）

    Args:
        event: 打断事件锚点（至少含 partial_reply）
        user_msg: 用户下一条消息（可为空）
        embedding_engine: EmbeddingEngine 实例；None 时降级为 corrected（宁缺毋滥）
        threshold: 相似度阈值（M4 起可由配置覆盖）

    Returns:
        (classification, similarity)：similarity 为 None 表示未计算（降级/静默）
    """
    if not user_msg or not user_msg.strip():
        return "silent", None
    partial_reply = (event or {}).get("partial_reply") or ""
    if not partial_reply or embedding_engine is None:
        # 降级：有下一条消息但无法计算相似度 → 保守视为 corrected
        return "corrected", None
    try:
        emb_u = embedding_engine.embed(user_msg[:500])
        emb_p = embedding_engine.embed(partial_reply[:500])
        sim = embedding_engine.cosine_similarity(emb_u, emb_p)
        if sim >= threshold:
            return "corrected", round(sim, 4)
        return "abandoned", round(sim, 4)
    except Exception:
        logger.exception("classify_interruption embedding failed")
        return "corrected", None


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
    """LLM API 通信组件。"""

    @property
    def name(self) -> str:
        return "api"

    def initialize(self) -> None:
        pass

    @staticmethod
    def _match_model_family(model_name: str) -> dict:
        """通过模型名称推测模型家族和能力。

        使用模型名模式匹配，不依赖外部 API 调用。

        Args:
            model_name: 模型名称，如 "gpt-4o", "deepseek-chat", "claude-sonnet"

        Returns:
            dict: {supports_thinking, supports_reasoning_effort, family, confidence}
        """
        name = model_name.lower()

        # ── OpenAI o-series / reasoning_effort 原生支持 ──
        if any(kw in name for kw in ("o1", "o3", "o4", "o-mini", "o3-mini")):
            return {"supports_thinking": True, "supports_reasoning_effort": True,
                    "family": "openai_o", "confidence": 0.95}
        if any(kw in name for kw in ("gpt-4o", "gpt-4.1", "gpt-4-turbo")):
            return {"supports_thinking": True, "supports_reasoning_effort": False,
                    "family": "openai_gpt4", "confidence": 0.85}

        # ── DeepSeek 系列 ──
        if "deepseek-reasoner" in name or "deepseek-r1" in name:
            return {"supports_thinking": True, "supports_reasoning_effort": False,
                    "family": "deepseek_reasoner", "confidence": 0.9}
        if "deepseek-v4" in name:
            return {"supports_thinking": True, "supports_reasoning_effort": False,
                    "family": "deepseek_v4", "confidence": 0.8}
        if "deepseek" in name:
            return {"supports_thinking": True, "supports_reasoning_effort": False,
                    "family": "deepseek", "confidence": 0.7}

        # ── Anthropic Claude ──
        if "claude" in name:
            return {"supports_thinking": True, "supports_reasoning_effort": False,
                    "family": "anthropic", "confidence": 0.9}

        # ── Gemini ──
        if "gemini" in name:
            return {"supports_thinking": True, "supports_reasoning_effort": False,
                    "family": "gemini", "confidence": 0.8}

        # ── MiniMax ──
        if any(kw in name for kw in ("minimax", "m2.5", "mimo")):
            return {"supports_thinking": True, "supports_reasoning_effort": False,
                    "family": "minimax", "confidence": 0.7}

        # ── Qwen ──
        if "qwen" in name:
            return {"supports_thinking": True, "supports_reasoning_effort": False,
                    "family": "qwen", "confidence": 0.6}

        # ── Llama ──
        if "llama" in name:
            return {"supports_thinking": True, "supports_reasoning_effort": False,
                    "family": "llama", "confidence": 0.5}

        # ── GLM / 智谱 ──
        if "glm" in name or "zhipu" in name:
            return {"supports_thinking": True, "supports_reasoning_effort": False,
                    "family": "glm", "confidence": 0.6}

        # ── 未知模型 ──
        return {"supports_thinking": True, "supports_reasoning_effort": False,
                "family": "unknown", "confidence": 0.3}

    def _auto_detect_thinking_config(self, is_cheap=False, force=False) -> dict:
        """自动检测模型的最佳 thinking 配置（模型名匹配 + API 探测）。

        策略（从快到慢）：
        1. 模型名匹配：通过名称模式推测能力（无需 API 调用）
        2. API探测：如果名称匹配不可靠，发送 probe 请求确认
        3. 保存结果：探测到的配置自动保存到 config.yaml

        Args:
            is_cheap: True=检测便宜模型，False=检测主模型
            force: True=强制重新探测（即使已缓存）

        Returns:
            dict: {
                "supports_thinking": bool,
                "supports_reasoning_effort": bool,
                "recommended_strength": float,
                "recommended_effort": str,
                "method": str (检测方法: "model_match" / "api_probe" / "default")
            }
        """
        # 检查缓存
        cache_attr = "_cheap_thinking_supported" if is_cheap else "_thinking_supported"
        cached = getattr(self.ctx, cache_attr, None)
        if cached is not None and not force:
            return {"supports_thinking": cached,
                    "supports_reasoning_effort": self.ctx.reasoning_effort != "auto",
                    "recommended_strength": self.ctx.thinking_strength,
                    "recommended_effort": self.ctx.reasoning_effort,
                    "method": "cached"}

        target_client = self.ctx.cheap_client if is_cheap else self.ctx.client
        target_model = self.ctx.cheap_model if is_cheap else self.ctx.model

        if not self.ctx.enable_thinking or not target_client:
            return {"supports_thinking": False, "supports_reasoning_effort": False,
                    "recommended_strength": 0.0, "recommended_effort": "auto",
                    "method": "disabled"}

        # ── Phase 1: 模型名匹配（零成本） ──
        match = self._match_model_family(target_model)
        if match["confidence"] >= 0.7:
            # 高置信度匹配，直接使用
            supports_re = match["supports_reasoning_effort"]
            strength = 0.7
            effort = "auto"

            if supports_re:
                effort = "medium"
                strength = 0.7
            elif match["family"] == "deepseek_reasoner":
                effort = "auto"
                strength = 0.8
            elif match["family"] == "deepseek_v4":
                effort = "auto"
                strength = 0.6  # V4 flash 轻量模型，中等思考
            elif match["family"] == "deepseek":
                effort = "auto"
                strength = 0.7
            elif match["family"] == "openai_gpt4":
                effort = "auto"
                strength = 0.5  # GPT-4o 的 thinking 支持有限
            elif match["family"] == "minimax":
                effort = "auto"
                strength = 0.6  # MiniMax 的 thinking 支持中等

            # 更新缓存
            setattr(self.ctx, cache_attr, match["supports_thinking"])
            _tl = getattr(self.ctx, 'tool_log', None)
            if _tl:
                _tl(
                    f"🧠 自动检测: [{target_model}] "
                    f"家族={match['family']}, 置信度={match['confidence']:.0%}, "
                    f"thinking={'✓' if match['supports_thinking'] else '✗'}"
                )

            return {
                "supports_thinking": match["supports_thinking"],
                "supports_reasoning_effort": supports_re,
                "recommended_strength": strength,
                "recommended_effort": effort,
                "method": f"model_match({match['family']})"
            }

        # ── Phase 2: API 探测（低置信度匹配或未知模型） ──
        _tl = getattr(self.ctx, 'tool_log', None)
        if _tl:
            _tl(f"🔍 低置信度模型匹配 ({match['confidence']:.0%})，启动 API 探测...")

        result = {
            "supports_thinking": True,
            "supports_reasoning_effort": False,
            "recommended_strength": 0.5,
            "recommended_effort": "auto",
            "method": "default"
        }

        # Probe 1: 测试 thinking.type = enabled
        try:
            target_client.chat.completions.create(
                model=target_model,
                messages=[{"role": "user", "content": "Hi"}],
                stream=False,
                extra_body={"thinking": {"type": "enabled"}},
                max_tokens=5,
            )
            result["supports_thinking"] = True
            result["method"] = "api_probe"

            # Probe 2: 测试 reasoning_effort 支持（仅当 thinking 支持时）
            try:
                target_client.chat.completions.create(
                    model=target_model,
                    messages=[{"role": "user", "content": "Hi"}],
                    stream=False,
                    extra_body={"thinking": {"type": "enabled"}, "reasoning_effort": "medium"},
                    max_tokens=5,
                )
                result["supports_reasoning_effort"] = True
                result["recommended_strength"] = 0.7
                result["recommended_effort"] = "medium"
            except Exception:
                result["supports_reasoning_effort"] = False
                result["recommended_strength"] = 0.7
                result["recommended_effort"] = "auto"

        except Exception as e:
            err_str = str(e).lower()
            if "thinking" in err_str or "extra_body" in err_str or "unsupported" in err_str or "invalid" in err_str:
                result["supports_thinking"] = False
                result["recommended_strength"] = 0.0
                if _tl:
                    _tl("⚠️ 模型不支持 thinking，已禁用")
            else:
                # 其他错误（如网络），保留默认值
                if _tl:
                    _tl(f"⚠️ thinking 探测出错（保留默认）: {e}")

        # 更新缓存
        setattr(self.ctx, cache_attr, result["supports_thinking"])
        return result

    def _accumulate_usage(self, usage, is_cheap=False):
        """累加 token 用量到主模型或便宜模型的计数器。

        Args:
            usage: API 返回的 usage 对象（含 prompt_tokens/completion_tokens 等）
            is_cheap: True=累加到便宜模型计数, False=累加到主模型计数
        """
        if usage is None:
            return
        u = self.ctx._last_cheap_usage if is_cheap else self.ctx._last_usage
        prompt = getattr(usage, "prompt_tokens", None)
        completion = getattr(usage, "completion_tokens", None)
        total = getattr(usage, "total_tokens", None)
        cache_hit = getattr(usage, "prompt_cache_hit_tokens", None)
        cache_miss = getattr(usage, "prompt_cache_miss_tokens", None)

        # S3: 记录最近一次主模型请求的真实 prompt_tokens（单次值，非累计），
        # 供 token_budget 片段校正启发式估算偏差。
        if prompt is not None and not is_cheap:
            self.ctx._last_request_prompt_tokens = int(prompt)

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
        if hasattr(response, "usage") and response.usage:
            self._accumulate_usage(response.usage, is_cheap=is_cheap)

    def create_chat_stream(
        self,
        api_messages: list[dict],
        tools: list[dict],
        client=None,
        model=None,
        is_cheap=False,
        temperature=None,
        max_tokens=None,
        top_p=None,
        request_timeout: float | None = None,
    ):
        target_client = client or self.ctx.client
        target_model = model or self.ctx.model

        # 请求级视觉自动切换：请求消息含图片（当前轮或历史轮）→ 使用视觉模型。
        # 兜底 chat_stream 的回合级切换，覆盖「上一轮发图、本轮纯文本追问」等场景，
        # 避免主模型（无视觉能力）收到 image_url 内容导致 API 报错或图片被忽略。
        if client is None and model is None and not is_cheap:
            vision_client = getattr(self.ctx, "vision_client", None)
            vision_model = getattr(self.ctx, "vision_model", "") or ""
            if vision_client and vision_model and messages_contain_images(api_messages):
                target_client = vision_client
                target_model = vision_model
                logger.info(f"👁️ 请求级视觉切换: {vision_model}")

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

        # 请求超时保护：防止 API hang 导致线程卡死
        if request_timeout is not None:
            kwargs["timeout"] = request_timeout

        # 根据模型能力决定是否传 stream_options
        if self.ctx.supports_reasoning:
            kwargs["stream_options"] = {"include_usage": True}

        # 根据对应的 thinking 状态决定是否启用
        thinking_supported = (
            self.ctx._cheap_thinking_supported
            if is_cheap
            else self.ctx._thinking_supported
        )

        # ── 构建 extra_body：思维配置 + 模型 options ──
        extra_body = {}

        # reasoning_effort 是独立参数（OpenAI o-series 使用），不受 thinking probe 影响
        reasoning_effort = self.ctx.reasoning_effort
        if reasoning_effort and reasoning_effort != "auto":
            # 用户明确指定 effort 级别
            extra_body["reasoning_effort"] = reasoning_effort
            # 如果 thinking 也支持，同时启用 thinking（兼容模式）
            if thinking_supported and self.ctx.enable_thinking:
                extra_body["thinking"] = {"type": "enabled"}
        elif self.ctx.enable_thinking:
            # 根据 thinking_strength 自动映射 reasoning_effort
            strength = max(0.0, min(1.0, self.ctx.thinking_strength))
            if strength > 0 and thinking_supported:
                extra_body["thinking"] = {"type": "enabled"}
                # 将 strength 映射为推理努力程度（通用映射）
                if strength < 0.3:
                    extra_body["reasoning_effort"] = "low"
                elif strength < 0.7:
                    extra_body["reasoning_effort"] = "medium"
                else:
                    extra_body["reasoning_effort"] = "high"
            elif strength > 0:
                # thinking 不支持但 strength>0：尝试只传 reasoning_effort
                if strength < 0.3:
                    extra_body["reasoning_effort"] = "low"
                elif strength < 0.7:
                    extra_body["reasoning_effort"] = "medium"
                else:
                    extra_body["reasoning_effort"] = "high"
            else:
                if thinking_supported:
                    extra_body["thinking"] = {"type": "disabled"}
        elif thinking_supported:
            # enable_thinking=False 时显式禁用
            extra_body["thinking"] = {"type": "disabled"}

        # 从配置中获取模型 options（如 num_ctx）并合并到 extra_body
        # 模型 options 优先级最高，可覆盖上述自动生成的参数
        try:
            from tea_agent.config import get_config

            _cfg = get_config()
            model_opts = (
                _cfg.main_model.options if not is_cheap else _cfg.cheap_model.options
            )
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
            logger.debug(
                f"summarize API request: model={mdl}, msgs={len(messages)}, temperature={temperature}, max_tokens={max_tokens}"
            )
            return cli.chat.completions.create(
                model=mdl,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                extra_body={"thinking": {"type": "disabled"}},
            )
        except Exception as e:
            err_str = str(e).lower()
            if "thinking" in err_str or "extra_body" in err_str:
                # 模型不支持 thinking 参数，回退到不带 extra_body 的调用
                logger.debug(
                    "summarize API: thinking disabled not supported, retrying without extra_body"
                )
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
                tool_calls_data.append({"id": "", "name": "", "arguments": ""})

            if tc.id:
                tool_calls_data[idx]["id"] = tc.id
            if tc.function:
                if tc.function.name:
                    tool_calls_data[idx]["name"] = tc.function.name
                if tc.function.arguments:
                    tool_calls_data[idx]["arguments"] += tc.function.arguments

    def reset_usage(self):
        self.ctx._last_usage = {
            "total_tokens": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "prompt_cache_hit_tokens": 0,
            "prompt_cache_miss_tokens": 0,
        }

    def reset_cheap_usage(self):
        self.ctx._last_cheap_usage = {
            "total_tokens": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "prompt_cache_hit_tokens": 0,
            "prompt_cache_miss_tokens": 0,
        }

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

# ESSENTIAL_TOOLS 已废弃，保留仅为兼容性


def filter_tools(tools: list, tool_filter: list = None) -> list:
    """工具过滤已禁用，返回全部工具。自由奔放！"""
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
            logger.warning(
                f"tool call failed: JSON decode error, func={func_name}, raw_args={call.function.arguments[:300]}"
            )
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
            nl = raw.find(b"\n", head_end)
            if nl != -1 and nl < half + 256:
                head_end = nl
            head_text = raw[:head_end].decode("utf-8", errors="replace")

            # 后半部分：向后找第一个换行，tail 保留约 half 字节
            tail_start = len(raw) - half
            nl = raw.find(b"\n", tail_start)
            if nl != -1 and nl < tail_start + 256:
                tail_start = nl + 1
            else:
                nl = raw.rfind(b"\n", 0, tail_start)
                if nl != -1 and nl > tail_start - 256:
                    tail_start = nl + 1
            tail_text = raw[tail_start:].decode("utf-8", errors="replace")

            result_str = f"{head_text}\n\n... [工具输出截断: {result_bytes}B → {len(head_text.encode('utf-8')) + len(tail_text.encode('utf-8'))}B] ...\n\n{tail_text}"
            logger.info(
                f"tool output truncated: {func_name}, {result_bytes}B → {len(result_str.encode('utf-8'))}B"
            )

        self.add_tool_result(call_id, result_str)
        self._record_tool_to_trace(func_name, success, error_msg, start_time)
        # 进化触发器：采集工具调用信号
        evolution_trigger = getattr(self.ctx, 'evolution_trigger', None)
        if evolution_trigger:
            evolution_trigger.on_tool_result(func_name, result, time.time() - start_time)
        return call_id, func_name, result_str

    def _record_tool_to_trace(
        self, func_name: str, success: bool, error_msg: str, start_time: float
    ):
        import time

        trace = self.ctx._current_trace
        if trace is None:
            return
        reflection_mgr = self.ctx.reflection_manager
        if reflection_mgr is None:
            return
        duration_ms = (time.time() - start_time) * 1000
        reflection_mgr.record_tool_call(
            trace, func_name, success, error_msg, duration_ms
        )

    def add_tool_result(self, tool_call_id: str, content: str):
        # S2/缓存友好：入库即压缩到与裁剪阈值一致的定长，消息从出生起定型。
        # 否则实时消息以原始大小（最高 max_tool_output=128KB）入库，滑出
        # 3 轮窗口后被 _solidify_history 替换为占位符 → "完整→占位符"两阶段
        # 翻转会破坏其后全部历史消息的前缀缓存命中。
        try:
            from tea_agent.session.history_builder import get_tool_prune_threshold
            from tea_agent.basesession import BaseChatSession

            max_chars = get_tool_prune_threshold(self.ctx)
            content = BaseChatSession._compress_tool_content(content, max_chars=max_chars)
        except Exception:
            logger.debug("tool content compression failed, keeping raw", exc_info=True)
        self.ctx.messages.append(
            {"role": "tool", "tool_call_id": tool_call_id, "content": content}
        )

    def collect_tool_call_round(self, call_id: str, result_str: str):
        self.ctx._rounds_collector.append(
            {
                "role": "tool",
                "content": result_str,
                "tool_call_id": call_id,
            }
        )

    def collect_assistant_tool_calls_round(
        self, content: str, tool_calls: list, reasoning_content: str = ""
    ):
        tc_list_for_collector = [
            {
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.function.name,
                    "arguments": tc.function.arguments,
                },
            }
            for tc in tool_calls
        ]

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
        self.ctx._rounds_collector.append(
            {
                "role": "assistant",
                "content": content,
            }
        )

    def collect_max_iterations_round(self, content: str):
        self.ctx._rounds_collector.append(
            {
                "role": "assistant",
                "content": content,
            }
        )

    def collect_interruption_round(self, content: str):
        self.ctx._rounds_collector.append(
            {
                "role": "assistant",
                "content": content,
            }
        )

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

            valid_tool_calls.append(
                SimpleNamespace(
                    id=func_id,
                    function=SimpleNamespace(
                        name=func_name,
                        arguments=func_args,
                    ),
                )
            )
        return valid_tool_calls


logger = logging.getLogger("session.summarizer")


class SummarizerComponent(SessionComponent):
    """历史摘要组件 — 负责旧对话压缩、三级历史管理、语义摘要生成。"""

    @property
    def name(self) -> str:
        return "summarizer"

    def initialize(self) -> None:
        pass

    def summarize_old_history(
        self, api_component, get_summarize_client_fn, force: bool = False
    ) -> None:
        """将旧对话历史压缩为摘要。

        Args:
            api_component: API 组件
            get_summarize_client_fn: 获取摘要客户端的回调
            force: S5 强制压缩标志 — token 预算已用尽时忽略 keep_turns
                轮次阈值，无条件执行摘要（即使未摘要对话较少也压缩）。
        """
        # 检查是否禁用摘要（disable_l3 或向后兼容的 disable_summary）
        if self.ctx.disable_summary or getattr(self.ctx, 'disable_l3', False):
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

        if len(unsummarized) <= self.ctx.keep_turns and not force:
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
        existing = f"已有摘要：{old_summary}\n\n" if old_summary else ""

        try:
            cli, mdl = get_summarize_client_fn()
            # 判断是否使用便宜模型
            is_cheap = (
                self.ctx.cheap_client is not None and cli is self.ctx.cheap_client
            )

            cheap_params = get_cheap_params("summarizer")
            response = api_component.call_summarize_api(
                cli,
                mdl,
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
                last_conv_id = convs_to_summarize[-1]["id"]
                storage.update_topic_summary(
                    topic_id, new_summary, last_summarized_id=last_conv_id
                )
                for conv in convs_to_summarize:
                    storage.mark_as_summarized(conv["id"])

                # 5. 同步内存
                self.ctx._history_summary = new_summary

                # 裁剪 messages，保持与数据库同步
                boundary = self._find_recent_boundary()
                if boundary > 1:
                    self.ctx.messages = [self.ctx.messages[0]] + self.ctx.messages[
                        boundary:
                    ]

                if self.ctx.tool_log:
                    self.ctx.tool_log(f"📝 历史摘要更新：{new_summary}")

        except Exception as e:
            logger.warning(f"History summary failed: error={e}")
            if self.ctx.tool_log:
                self.ctx.tool_log(f"⚠️ 摘要生成失败: {e}")

    def _conversations_to_text(
        self, conversations: list[dict], max_per_msg: int = 500
    ) -> str:
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

    # ── 打断知识闭环（M2/M4）──
    # 注入模板统一在 prompt_manager.py 管理（支持 prompt 进化）
    _INTERRUPT_ABANDONED_TMPL = INTERRUPT_ABANDONED_TMPL
    _INTERRUPT_CORRECTED_TMPL = INTERRUPT_CORRECTED_TMPL

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
        thinking_strength: float = 0.7,
        reasoning_effort: str = "auto",
        storage=None,
        cheap_api_key: str = "",
        cheap_api_url: str = "",
        cheap_model: str = "",
        vision_api_key: str = "",
        vision_api_url: str = "",
        vision_model: str = "",
        keep_turns: int = 5,
        max_tool_output: int = 128 * 1024,
        max_assistant_content: int = 128 * 1024,
        max_context_tokens: int = 0,
        extra_iterations_on_continue: int = 5,
        memory_extraction_threshold: int = 2,
        memory_dedup_threshold: float = 0.6,
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
            thinking_strength: 思考强度 0.0-1.0（0=最弱/最省token, 1=最强/最深思考）
            reasoning_effort: 推理努力程度 "auto"/"low"/"medium"/"high"
            storage: Storage 实例，用于持久化存储
            cheap_api_key: 便宜模型 API密钥
            cheap_api_url: 便宜模型 API地址
            cheap_model: 便宜模型名称
            vision_api_key: 视觉模型 API密钥（会话输入含图片时自动切换到此模型）
            vision_api_url: 视觉模型 API地址
            vision_model: 视觉模型名称
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
            no_stream_chunk: 是否禁用流式输出
        """
        # 步骤1: 准备系统提示词
        sp = system_prompt or self._COMPACT_SYSTEM_PROMPT

        # 步骤2: 创建HTTP客户端和API客户端
        _http_client, main_client, cheap_client, vision_client = self._create_api_clients(
            api_key, api_url, cheap_api_key, cheap_api_url, cheap_model,
            vision_api_key, vision_api_url, vision_model,
        )

        # 步骤3: 创建共享上下文
        self.context = self._create_session_context(
            toolkit=toolkit,
            model=model,
            enable_thinking=enable_thinking,
            thinking_strength=thinking_strength,
            reasoning_effort=reasoning_effort,
            main_client=main_client,
            cheap_client=cheap_client,
            cheap_model=cheap_model,
            vision_client=vision_client,
            vision_model=vision_model,
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

        # 步骤4: 调用基类初始化
        BaseChatSession.__init__(self, model, max_history, sp)

        logger.info(
            f"OnlineToolSession init ok: main model: {model}, cheap model: {cheap_model}"
            + (f", vision model: {vision_model}" if vision_model else "")
        )

        # 步骤5: 创建并初始化组件
        self._initialize_components()

        # 步骤6: 设置兼容属性
        self._setup_compatible_attributes(
            max_iterations=max_iterations,
            storage=storage,
            cheap_client=cheap_client,
            cheap_model=cheap_model,
            vision_client=vision_client,
            vision_model=vision_model,
            supports_vision=supports_vision,
            supports_reasoning=supports_reasoning,
            disable_summary=disable_summary,
        )

        # 步骤7: 初始化续跑控制
        self._init_continue_control()

        # 步骤8: 管理HTTP客户端
        self._manage_http_clients(_http_client, cheap_client, vision_client)

        # 步骤9: 构建工具定义
        self._build_tools()

        # 步骤10: 初始化反思和提示词管理器 + 进化触发器
        self._init_reflection_and_prompt_manager(
            storage=storage,
            cheap_client=cheap_client,
            cheap_model=cheap_model,
            system_prompt=system_prompt,
        )

        # 步骤11: 初始化进化触发器（上下文共享）
        trigger = EvolutionTrigger()
        self.context.evolution_trigger = trigger
        self.evolution_trigger = trigger  # 便利引用

        # 步骤11: 初始化Pipeline
        self._init_pipeline()

        # 步骤12: 自动探测并保存 thinking 配置（异步执行，不阻塞初始化）
        self._auto_detect_and_save_thinking_config()

    def _auto_detect_and_save_thinking_config(self):
        """自动探测模型的 thinking 能力，并将优化值保存到 config.yaml。

        检测策略：
        1. 模型名匹配（零成本，高置信度）
        2. API 探测（无需时跳过，避免延迟）
        3. 若 config 中值为默认值，自动将探测结果持久化到配置文件

        调用时机：会话初始化末尾，不阻塞对话启动。
        """
        try:
            # 仅当 config 中的值为默认值时，才进行探测并保存
            from tea_agent.config import get_active_config_path, get_config, save_config

            cfg = get_config()
            # 检查是否为用户显式设置的（非默认值则跳过自动保存）
            is_default_strength = abs(cfg.thinking_strength - 0.7) < 0.01
            is_default_effort = cfg.reasoning_effort == "auto"
            should_auto_save = is_default_strength and is_default_effort

            # 执行探测（同时更新主模型和便宜模型的 thinking 缓存）
            main_detected = self.api._auto_detect_thinking_config(is_cheap=False)

            if self._cheap_client and self._cheap_model_name:
                self.api._auto_detect_thinking_config(is_cheap=True)
            # cheap 模型的探测结果仅用于更新缓存，不保存到配置

            if should_auto_save and main_detected.get("method") != "disabled":
                # 更新配置对象
                cfg.thinking_strength = main_detected["recommended_strength"]
                if main_detected["recommended_effort"] != "auto":
                    cfg.reasoning_effort = main_detected["recommended_effort"]

                # 同时更新 ctx
                self.context.thinking_strength = cfg.thinking_strength
                self.context.reasoning_effort = cfg.reasoning_effort

                # 保存到配置文件
                config_path = get_active_config_path()
                if config_path:
                    save_config(cfg, config_path)
                    logger.info(
                        f"📝 thinking 配置自动保存: "
                        f"strength={cfg.thinking_strength}, "
                        f"effort={cfg.reasoning_effort!r} "
                        f"(检测方法: {main_detected['method']})"
                    )
                    _tl = getattr(self.context, 'tool_log', None)
                    if _tl:
                        _tl(
                            f"💾 thinking 配置已自动优化并保存: "
                            f"强度={cfg.thinking_strength}, "
                            f"努力={cfg.reasoning_effort} "
                            f"(依据: {main_detected['method']})"
                        )
        except Exception as e:
            logger.debug(f"Thinking 自动探测跳过（非阻塞）: {e}")

    def _create_api_clients(
        self,
        api_key: str,
        api_url: str,
        cheap_api_key: str,
        cheap_api_url: str,
        cheap_model: str,
        vision_api_key: str = "",
        vision_api_url: str = "",
        vision_model: str = "",
    ) -> tuple:
        """创建API客户端。

        Args:
            api_key: 主API密钥
            api_url: 主API地址
            cheap_api_key: 便宜模型API密钥
            cheap_api_url: 便宜模型API地址
            cheap_model: 便宜模型名称
            vision_api_key: 视觉模型API密钥（可选，会话含图片时自动切换）
            vision_api_url: 视觉模型API地址
            vision_model: 视觉模型名称

        Returns:
            (http_client, main_client, cheap_client, vision_client) 元组
        """
        import httpx

        _http_client = httpx.Client(proxy=None, timeout=httpx.Timeout(120.0, connect=30.0))
        main_client = OpenAI(
            api_key=api_key, base_url=api_url, http_client=_http_client
        )

        cheap_client: OpenAI | None = None
        if cheap_api_key and cheap_api_url and cheap_model:
            cheap_client = OpenAI(
                api_key=cheap_api_key,
                base_url=cheap_api_url,
                http_client=httpx.Client(proxy=None, timeout=httpx.Timeout(120.0, connect=30.0)),
            )

        vision_client: OpenAI | None = None
        if vision_api_key and vision_api_url and vision_model:
            vision_client = OpenAI(
                api_key=vision_api_key,
                base_url=vision_api_url,
                http_client=httpx.Client(proxy=None, timeout=httpx.Timeout(120.0, connect=30.0)),
            )

        return _http_client, main_client, cheap_client, vision_client

    def _create_session_context(
        self,
        toolkit,
        model: str,
        enable_thinking: bool,
        thinking_strength: float,
        reasoning_effort: str,
        main_client: OpenAI,
        cheap_client: OpenAI | None,
        cheap_model: str,
        vision_client: OpenAI | None,
        vision_model: str,
        storage,
        keep_turns: int,
        max_tool_output: int,
        max_assistant_content: int,
        max_context_tokens: int,
        memory_extraction_threshold: int,
        memory_dedup_threshold: float,
        supports_vision: bool,
        supports_reasoning: bool,
        disable_summary: bool,
        no_stream_chunk: bool,
        extra_iterations_on_continue: int,
    ) -> SessionContext:
        """创建会话上下文。

        Args:
            toolkit: 工具库实例
            model: 模型名称
            enable_thinking: 是否启用思考
            thinking_strength: 思考强度 0.0-1.0
            reasoning_effort: 推理努力程度
            main_client: 主API客户端
            cheap_client: 便宜模型客户端
            cheap_model: 便宜模型名称
            vision_client: 视觉模型客户端（可选）
            vision_model: 视觉模型名称
            storage: 存储实例
            keep_turns: 保留轮数
            max_tool_output: 工具输出最大长度
            max_assistant_content: 助手内容最大长度
            max_context_tokens: 最大上下文token数
            memory_extraction_threshold: 记忆提取阈值
            memory_dedup_threshold: 记忆去重阈值
            supports_vision: 是否支持视觉
            supports_reasoning: 是否支持推理
            disable_summary: 是否禁用摘要
            no_stream_chunk: 是否禁用流式输出
            extra_iterations_on_continue: 续命轮数

        Returns:
            SessionContext实例
        """
        return SessionContext(
            messages=[],
            model=model,
            enable_thinking=enable_thinking,
            thinking_strength=thinking_strength,
            reasoning_effort=reasoning_effort,
            client=main_client,
            cheap_client=cheap_client,
            cheap_model=cheap_model,
            vision_client=vision_client,
            vision_model=vision_model,
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

    def _initialize_components(self) -> None:
        """初始化会话组件。"""
        self.api = APIComponent(self.context)
        self.tools_comp = ToolComponent(self.context)
        self.memory_comp = MemoryComponent(self.context)
        self.summarizer_comp = SummarizerComponent(self.context)

        for comp in [self.api, self.tools_comp, self.memory_comp, self.summarizer_comp]:
            comp.initialize()

    def _setup_compatible_attributes(
        self,
        max_iterations: int,
        storage,
        cheap_client: OpenAI | None,
        cheap_model: str,
        vision_client: OpenAI | None,
        vision_model: str,
        supports_vision: bool,
        supports_reasoning: bool,
        disable_summary: bool,
    ) -> None:
        """设置兼容属性。

        Args:
            max_iterations: 最大迭代次数
            storage: 存储实例
            cheap_client: 便宜模型客户端
            cheap_model: 便宜模型名称
            vision_client: 视觉模型客户端（可选）
            vision_model: 视觉模型名称
            supports_vision: 是否支持视觉
            supports_reasoning: 是否支持推理
            disable_summary: 是否禁用摘要
        """
        self.max_iterations = max_iterations
        self.storage = storage
        self._cheap_client = cheap_client
        self._cheap_model_name = cheap_model
        self._vision_client = vision_client
        self._vision_model_name = vision_model
        self._current_mode = "mixed"
        self._supports_vision = supports_vision
        self._supports_reasoning = supports_reasoning
        self._disable_summary = disable_summary

    def _init_continue_control(self) -> None:
        """初始化续跑控制。"""
        import threading

        self._extra_iterations = 0
        self._continue_after_max = False
        self._max_iter_wait = threading.Event()

    def _manage_http_clients(
        self,
        _http_client,
        cheap_client: OpenAI | None,
        vision_client: OpenAI | None = None,
    ) -> None:
        """管理HTTP客户端。

        Args:
            _http_client: 主HTTP客户端
            cheap_client: 便宜模型客户端
            vision_client: 视觉模型客户端
        """
        self._http_clients = []
        if _http_client:
            self._http_clients.append(_http_client)
        if cheap_client and hasattr(cheap_client, "_client") and cheap_client._client:
            self._http_clients.append(cheap_client._client)
        if vision_client and hasattr(vision_client, "_client") and vision_client._client:
            self._http_clients.append(vision_client._client)

    def _build_tools(self) -> None:
        """构建工具定义。"""
        self.tools: list[dict] = []
        self.tools = self.tools_comp.build_tools()

        # 初始化 Memory 管理器
        self.memory_comp.initialize()

    def _init_reflection_and_prompt_manager(
        self,
        storage,
        cheap_client: OpenAI | None,
        cheap_model: str,
        system_prompt: str,
    ) -> None:
        """初始化反思和提示词管理器。

        Args:
            storage: 存储实例
            cheap_client: 便宜模型客户端
            cheap_model: 便宜模型名称
            system_prompt: 系统提示词
        """
        if storage is not None:
            from tea_agent.prompt_manager import SystemPromptManager
            from tea_agent.reflection import ReflectionManager

            self.reflection_manager = ReflectionManager(
                storage=storage,
                cheap_client=cheap_client,
                cheap_model=cheap_model,
            )
            self.prompt_manager = SystemPromptManager(
                storage=storage,
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
            logger.info(
                "Storage not set, skipping ReflectionManager/PromptManager initialization"
            )

    def _init_pipeline(self) -> None:
        """初始化Pipeline。"""
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
    def messages(self):
        return self.context.messages

    @messages.setter
    def messages(self, v):
        self.context.messages = v

    @property
    def enable_thinking(self):
        return self.context.enable_thinking

    @enable_thinking.setter
    def enable_thinking(self, v):
        self.context.enable_thinking = v

    @property
    def thinking_strength(self):
        return self.context.thinking_strength

    @thinking_strength.setter
    def thinking_strength(self, v):
        self.context.thinking_strength = v

    @property
    def reasoning_effort(self):
        return self.context.reasoning_effort

    @reasoning_effort.setter
    def reasoning_effort(self, v):
        self.context.reasoning_effort = v

    @property
    def tool_log(self):
        return self.context.tool_log

    @tool_log.setter
    def tool_log(self, v):
        self.context.tool_log = v

    @property
    def _rounds_collector(self):
        return self.context._rounds_collector

    @_rounds_collector.setter
    def _rounds_collector(self, v):
        self.context._rounds_collector = v

    @property
    def _last_usage(self):
        return self.context._last_usage

    @_last_usage.setter
    def _last_usage(self, v):
        self.context._last_usage = v

    @property
    def _last_cheap_usage(self):
        return self.context._last_cheap_usage

    @_last_cheap_usage.setter
    def _last_cheap_usage(self, v):
        self.context._last_cheap_usage = v

    @property
    def _history_summary(self):
        return self.context._history_summary

    @_history_summary.setter
    def _history_summary(self, v):
        self.context._history_summary = v

    @property
    def _semantic_summary(self):
        return self.context._semantic_summary

    @_semantic_summary.setter
    def _semantic_summary(self, v):
        self.context._semantic_summary = v

    @property
    def _tool_chain_summary(self):
        return self.context._tool_chain_summary

    @_tool_chain_summary.setter
    def _tool_chain_summary(self, v):
        self.context._tool_chain_summary = v

    @property
    def _level2(self):
        return self.context._level2

    @_level2.setter
    def _level2(self, v):
        self.context._level2 = v

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

    def _process_stream_with_reasoning(
        self, response, callback
    ) -> tuple[str, list[dict], str]:
        """处理流式/非流式响应，收集内容、工具调用数据和 reasoning_content。"""
        content_parts = []
        tool_calls_data = []
        reasoning_parts = []

        # 非流式模式
        if self.context.no_stream_chunk:
            if hasattr(response, "usage") and response.usage:
                self.api._accumulate_usage(response.usage)
            if response.choices:
                msg = response.choices[0].message
                if hasattr(msg, "reasoning_content") and msg.reasoning_content:
                    reasoning_parts.append(msg.reasoning_content)
                    callback(f"[THINK]{msg.reasoning_content}")
                if msg.content:
                    content_parts.append(msg.content)
                    callback(msg.content)
                if msg.tool_calls:
                    for tc in msg.tool_calls:
                        tool_calls_data.append(
                            {
                                "id": tc.id,
                                "type": "function",
                                "function": {
                                    "name": tc.function.name,
                                    "arguments": tc.function.arguments,
                                },
                            }
                        )
            content = "".join(content_parts)
            reasoning_content = "".join(reasoning_parts)
            return content, tool_calls_data, reasoning_content

        # 流式模式
        for chunk in response:
            if hasattr(chunk, "usage") and chunk.usage:
                self.api._accumulate_usage(chunk.usage)

            if not hasattr(chunk, "choices") or not chunk.choices:
                continue

            delta = chunk.choices[0].delta

            if hasattr(delta, "reasoning_content") and delta.reasoning_content:
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

    def _inject_os_info(self, pipeline_ctx: dict) -> dict:
        """检测 OS 变化并设置上下文属性（不再注入虚假消息轮次）。

        [重构 2026-07] 从「虚假消息注入」改为「属性注入」：
        - 不再调用 inject_os_info() 添加 user+assistant 假对话
        - 改为设置 SessionContext._injected_os_info_text
        - 由 _build_l0_enriched_system() 在 Level 0 合并到 system prompt 尾部

        跨会话持久化 OS 签名：同一 topic 在同一 OS 上只注入一次，
        切换主机（Windows↔Linux）时自动重新注入。
        """
        from tea_agent.session.os_info_injector import (
            _get_os_signature,
            _load_persisted_os_sig,
            _save_os_sig,
            generate_os_info_text,
        )

        current_sig = _get_os_signature()

        # 首次检查：从持久化文件加载上次签名
        topic_id = getattr(self, "current_topic_id", None)
        if not self.context._os_info_injected and topic_id:
            self.context._os_info_injected = _load_persisted_os_sig(topic_id)

        # OS 未变化且已有文本 → 跳过
        if self.context._os_info_injected == current_sig and self.context._injected_os_info_text:
            return pipeline_ctx

        # OS 变化或首次 → 生成 OS 信息文本并写入上下文属性
        self.context._injected_os_info_text = generate_os_info_text(
            toolkit_root_dir=self.context.toolkit.tool_dir if self.context.toolkit else "",
            interface_type=getattr(self.context, 'interface_type', None),
        )
        self.context._os_info_injected = current_sig
        if topic_id:
            _save_os_sig(topic_id, current_sig)
        logger.info(f"OS info set on context: {current_sig} (topic={topic_id})")

        return pipeline_ctx

    def _setup_default_pipeline(self):
        """设置默认的 Pipeline 步骤"""
        self.pipeline.register_step(
            name="inject_os_info",
            func=self._inject_os_info,
            enabled=True,
            description="注入操作系统环境信息轮次",
            position=10,
        )
        self.pipeline.register_step(
            name="inject_memories",
            func=self.memory_comp.inject_memories,
            enabled=True,
            description="从长期记忆中注入相关记忆",
            position=20,
        )
        self.pipeline.register_step(
            name="add_user_message",
            func=lambda ctx: (
                self.add_user_message(ctx.get("user_msg", "")),
                self.context.messages,
            )[1],
            enabled=True,
            description="添加用户消息到会话历史",
            position=30,
            critical=True,
        )
        self.pipeline.register_step(
            name="summarize_old_history",
            func=self._summarize_old_history,
            enabled=True,
            description="将旧对话历史压缩为摘要",
            position=40,
        )
        self.pipeline.register_step(
            name="tool_loop",
            func=self._execute_tool_loop,
            enabled=True,
            description="执行工具调用循环",
            position=50,
            critical=True,
        )

    # ──────────────────────────────────────────────
    # Pipeline 步骤辅助方法
    # ──────────────────────────────────────────────

    def _summarize_old_history(self, context: dict) -> dict:
        """Pipeline 步骤：将旧对话历史压缩为摘要，返回更新后的 context。

        S5: token_budget 片段检测到上下文已用尽时（_frag_token_budget 置
        context._token_exhausted=True），此处强制压缩（即便未达到 keep_turns
        轮次阈值也执行），形成「报警 → 自动压缩」闭环。
        """
        force = bool(getattr(self.context, "_token_exhausted", False))
        if force:
            # 消费标志，避免后续轮次重复触发
            self.context._token_exhausted = False
            if self.context.tool_log:
                self.context.tool_log("⚠️ 上下文已用尽，强制压缩历史…")
            self.summarizer_comp.summarize_old_history(
                self.api, self._get_summarize_client, force=True
            )
        else:
            self.summarizer_comp.summarize_old_history(self.api, self._get_summarize_client)
        return context  # summarize_old_history 副作用修改 context，此处显式返回

    # ──────────────────────────────────────────────
    # 构建 API 消息（委派给 _history_builder）
    # ──────────────────────────────────────────────

    def _get_topic_system_prompt(self) -> str | None:
        """获取当前主题的自定义系统提示词（若有则优先使用）。"""
        topic_id = getattr(self, "current_topic_id", None)
        if topic_id and self.storage:
            try:
                return self.storage.get_topic_system_prompt(topic_id)
            except Exception:
                pass
        return None

    def _build_api_messages(self) -> list[dict]:
        """三级历史拼接 — 主题 SP 叠加到进化 SP 之上（不再二选一覆盖）。"""
        topic_sp = self._get_topic_system_prompt()
        if topic_sp:
            # 主题 SP + 进化 SP 叠加：主题特有指令在前，进化优化在后
            sp = topic_sp + "\n\n" + self.system_prompt
            logger.info("使用主题 SP + 进化 SP 合并版")
        else:
            sp = self.system_prompt
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
            logger.info(
                f"[Pipe Dynamic] Tool Injection: enabled {len(self.tools)} tools based on intent"
            )

    def update_tools(self):
        """重新加载并刷新工具定义"""
        self.context.toolkit.reload()
        self._build_tools()

    def _auto_detect_mode(self, user_text: str):
        """根据用户输入自动检测并切换 Agent 模式。"""
        result = detect_mode(
            call_tool_fn=lambda action, text: self.context.toolkit.call_tool(
                "toolkit_mode", action=action, text=text
            ),
            user_text=user_text,
        )
        if result.get("switched"):
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

    def _restore_interruption_anchor(self, topic_id: str | None = None) -> dict | None:
        """M2-fix(Web): 内存锚点丢失时从事件表恢复最新 pending 事件为锚点。

        Web server 每次 /api/chat 都新建 session（create_session），
        内存锚点 _last_interruption 在新 session 中丢失。事件表已持久化
        pending 事件，这里将其恢复为锚点，保证换话题/纠正信号在 Web
        场景下同样生效。

        Args:
            topic_id: 当前主题；无则无法定位（返回 None）

        Returns:
            恢复的锚点 dict（含 DB id 标记 restored）；无 pending 事件返回 None
        """
        if not topic_id:
            return None
        storage = getattr(self, "storage", None)
        if storage is None:
            return None
        try:
            rows = storage.query_interruptions(topic_id=topic_id, status="pending", limit=1)
            if not rows:
                return None
            row = rows[0]
            ev = {
                "id": row.get("id"),
                "tool_name": row.get("tool_name") or "",
                "iteration": row.get("iteration") or 0,
                "partial_reply": row.get("partial_reply") or "",
                "topic_id": topic_id,
                "restored": True,
            }
            self._last_interruption = ev
            logger.info(
                f"[InterruptionKnowledge] 从 DB 恢复打断锚点 event_id={ev['id']} tool={ev['tool_name']}"
            )
            return ev
        except Exception:
            logger.exception("restore interruption anchor failed")
            return None

    def _inject_interruption_knowledge(self, user_msg: str, topic_id: str | None = None) -> bool:
        """M2/M4: 上轮被打断 → 三分类（corrected/abandoned/silent）注入提示。

        打断是隐式负面反馈：上轮方向被否定。用户下一条消息决定信号类型：
        - corrected：语义相似 → 注入「按最新指令重新规划」
        - abandoned：语义漂移 → 注入「不要回到被打断方向」
        - silent：无消息 → 不注入（M3 后台沉淀）
        注入为 system 消息（紧跟初始 system 之后），注入后清除锚点保证幂等。
        分类结果回写 interruption_events 表（若有 storage）。

        M4：读取 interruption.* 配置（enabled / similarity_threshold / partial_reply_max）。

        Args:
            user_msg: 本轮用户输入文本

        Returns:
            bool: 是否成功注入
        """
        ev = getattr(self, "_last_interruption", None)
        if not ev:
            # M2-fix(Web): 新 session 内存锚点丢失 → 从事件表恢复 pending 事件
            ev = self._restore_interruption_anchor(topic_id)
        if not ev:
            return False
        # M4: 总开关
        try:
            from tea_agent.config import get_config

            icfg = get_config().interruption
        except Exception:
            icfg = {}
        if not icfg.get("enabled", True):
            self._last_interruption = None
            return False
        try:
            # 1) 语义分类（embedding 不可用时降级 corrected）
            engine = None
            try:
                from tea_agent.embedding_util import get_embedding_engine

                engine = get_embedding_engine()
            except Exception:
                engine = None
            threshold = float(icfg.get("similarity_threshold", INTERRUPT_SIMILARITY_THRESHOLD))
            classification, similarity = classify_interruption(
                ev, user_msg or "", embedding_engine=engine, threshold=threshold
            )

            # 2) silent：不注入，仅回写事件（若有 id）
            if classification == "silent":
                self._persist_classification(ev, classification, similarity, user_msg)
                self._last_interruption = None
                return False

            # 3) 按分类选择模板（prompt_manager 统一管理）
            if classification == "abandoned":
                inject_text = self._INTERRUPT_ABANDONED_TMPL
            else:
                tool = ev.get("tool_name") or "未知工具"
                iteration = ev.get("iteration", 0)
                followup_max = min(int(icfg.get("partial_reply_max", 2000)), 300)
                followup = (user_msg or "").strip()[:followup_max]
                inject_text = self._INTERRUPT_CORRECTED_TMPL.format(
                    tool_name=tool, iteration=iteration, followup=followup
                )

            # 4) 紧跟初始 system 消息之后插入（位置1），历史之前
            self.context.messages.insert(1, {"role": "system", "content": inject_text})

            # 5) 回写事件表 + 清除锚点（幂等）
            self._persist_classification(ev, classification, similarity, user_msg)
            self._last_interruption = None
            logger.info(
                f"[InterruptionKnowledge] 注入 {classification} 提示 "
                f"(sim={similarity}, tool={ev.get('tool_name')}, "
                f"iter={ev.get('iteration')}, followup={(user_msg or '')[:40]}...)"
            )
            return True
        except Exception:
            logger.exception("inject_interruption_knowledge failed")
            return False

    def _persist_classification(
        self, ev: dict, classification: str, similarity: float | None, user_msg: str
    ) -> None:
        """M2: 打断事件分类结果回写事件表（失败仅记日志）。"""
        event_id = ev.get("id")
        if not event_id:
            return
        storage = getattr(self, "storage", None)
        if storage is None:
            return
        try:
            import time as _time

            storage.update_interruption_classification(
                event_id,
                classification,
                similarity,
                (user_msg or "").strip()[:500],
                _time.strftime("%Y-%m-%d %H:%M:%S"),
            )
        except Exception:
            logger.exception("persist interruption classification failed")

    def _notify(self, title: str, message: str) -> None:
        """跨平台桌面通知（通过 toolkit_notify）。"""
        try:
            self.context.toolkit.call_tool(
                "toolkit_notify", title=title, message=message, duration=5000
            )
        except Exception:
            logger.exception('op_failed')

    def _notify_reflection_done(self, reflection_id: int):
        self._notify("🔍 元认知反思完成", f"反思 #{reflection_id} 已生成")

    def _notify_prompt_evolved(self, version: int):
        self._notify("📝 提示词进化", f"系统提示词已进化到 v{version}")

    def chat_stream(
        self,
        msg: str,
        callback: Callable[[str], None],
        topic_id: str = "",
        on_status: Callable[[str], None] | None = None,
    ) -> tuple[str, bool]:
        """流式对话，支持工具调用。使用 Pipeline 执行可配置的步骤。"""
        _msg_text = msg if isinstance(msg, str) else msg.get("text", "")
        _msg_images = None if isinstance(msg, str) else msg.get("images", [])

        # 视觉模型自动切换：会话输入含图片 → 使用 vision_model；无图片 → 使用主模型。
        # 切换在回合开始时生效（含工具循环内多次请求），回合结束 finally 恢复主模型。
        _switched_to_vision = False
        _prev_client, _prev_model = None, None
        if _msg_images:
            if getattr(self, "_vision_client", None) is not None and getattr(
                self, "_vision_model_name", ""
            ):
                _prev_client, _prev_model = self.context.client, self.context.model
                self.context.client = self._vision_client
                self.context.model = self._vision_model_name
                _switched_to_vision = True
                logger.info(
                    f"👁️ 检测到图片输入，本回合切换视觉模型: {self._vision_model_name}"
                )
            elif not self.context.supports_vision:
                error_msg = f"⚠️ 当前模型 {self.context.model} 不支持图片输入，请更换支持视觉的模型或移除图片后重试。"
                logger.warning(error_msg)
                callback(error_msg)
                return error_msg, False

        logger.debug(
            f"chat_stream start: msg_len={len(str(msg))}, topic_id={topic_id}, model={self.context.model}, enable_thinking={self.context.enable_thinking}"
        )
        logger.debug(
            f"chat_stream user message: {_msg_text[:200]}..."
            if len(_msg_text) > 200
            else f"chat_stream user message: {_msg_text}"
        )

        self.current_topic_id = topic_id
        self.reset_interrupt()
        self.reset_session_state()

        # M1: 打断知识注入 — 上轮被打断且本轮有新指令 → corrected 提示
        self._inject_interruption_knowledge(_msg_text, topic_id=topic_id)

        self._auto_detect_mode(_msg_text)

        intent = self._analyze_intent(_msg_text)

        if intent.get("required_tools"):
            self._build_tools(tool_filter=intent["required_tools"])
        else:
            self._build_tools()

        context = {
            "user_msg": msg,
            "msg": _msg_text,
            "callback": callback,
            "on_status": on_status,
        }

        if intent.get("skip_tool_loop"):
            context["skip_tool_loop"] = True

        # 开始反思追踪
        if self.reflection_manager is not None:
            trace = self.reflection_manager.start_trace(topic_id, _msg_text)
            self.context._current_trace = trace
        else:
            self.context._current_trace = None

        try:
            # 执行 Pipeline
            result = self.pipeline.execute(context)
        finally:
            # 回合结束恢复主模型（视觉模型仅在本回合生效）
            if _switched_to_vision and _prev_client is not None:
                self.context.client = _prev_client
                self.context.model = _prev_model
                logger.info(
                    f"👁️ 图片回合结束，恢复主模型: {_prev_model}"
                )

        full_reply = result.get("full_reply", "")
        used_tools = result.get("used_tools", False)
        iterations = result.get("iterations", 0)

        # 完成追踪
        if (
            self.reflection_manager is not None
            and self.context._current_trace is not None
        ):
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
            # 关闭所有HTTP客户端（注意: OpenAI wrapper 内部也持有 httpx.Client，
            # 已在 _http_clients 中关闭，避免重复关闭）
            _closed_clients = set()
            for client in self._http_clients:
                try:
                    if hasattr(client, "close"):
                        client.close()
                        _closed_clients.add(id(client))
                except Exception as e:
                    logger.debug(f"Close HTTP client failed: {e}")
            self._http_clients.clear()

            # 关闭OpenAI客户端（跳过已被 _http_clients 关闭的）
            if hasattr(self.context, "client") and self.context.client:
                try:
                    _internal = getattr(self.context.client, '_client', None)
                    if (_internal is None or id(_internal) not in _closed_clients) and hasattr(self.context.client, "close"):
                        self.context.client.close()
                except Exception as e:
                    logger.debug(f"Close main OpenAI client failed: {e}")

            if hasattr(self.context, "cheap_client") and self.context.cheap_client:
                try:
                    _internal = getattr(self.context.cheap_client, '_client', None)
                    if (_internal is None or id(_internal) not in _closed_clients) and hasattr(self.context.cheap_client, "close"):
                        self.context.cheap_client.close()
                except Exception as e:
                    logger.debug(f"Close cheap OpenAI client failed: {e}")

            if (
                hasattr(self.context, "vision_client")
                and self.context.vision_client
            ):
                try:
                    _internal = getattr(self.context.vision_client, '_client', None)
                    if (_internal is None or id(_internal) not in _closed_clients) and hasattr(self.context.vision_client, "close"):
                        self.context.vision_client.close()
                except Exception as e:
                    logger.debug(f"Close vision OpenAI client failed: {e}")

            # 关闭存储连接
            if hasattr(self, "storage") and self.storage:
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
            logger.exception('op_failed')


# 延迟导入（避免循环依赖）：MemoryComponent 在 _initialize_components 中使用
from tea_agent.session_memory_component import MemoryComponent  # noqa: E402
