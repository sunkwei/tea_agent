"""{name} —— 从 onlinesession.py 拆分（2026-09-06，保持 API 兼容）。"""

import logging

from tea_agent.config import REASONING_EFFORT_VALUES, clamp_reasoning_effort
from tea_agent.session.context import SessionComponent
from tea_agent.session.history_builder import (
    messages_contain_images,
)

logger = logging.getLogger("session")

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
            return {
                "supports_thinking": True,
                "supports_reasoning_effort": False,
                "family": "openai_o",
                "supported_efforts": ["none", "low", "medium", "high"],
                "confidence": 0.95,
            }
        if any(kw in name for kw in ("gpt-4o", "gpt-4.1", "gpt-4-turbo")):
            # 注意 qwen3 不归此组：qwen 系列有原生思考且接受 xhigh，
            # 曾被误分到此组（supports_reasoning_effort=False），
            # 导致 qwen 的 effort 值域/推荐值全部失效。
            return {
                "supports_thinking": True,
                "supports_reasoning_effort": False,
                "family": "openai_gpt4",
                "confidence": 0.85,
            }

        # ── DeepSeek 系列 ──
        if "deepseek-v4" in name:
            return {
                "supports_thinking": True,
                "supports_reasoning_effort": True,
                "family": "deepseek_v4",
                "supported_efforts": ["none", "minimal", "low", "medium", "high", "xhigh", "max"],
                "confidence": 0.8,
            }

        # ── Anthropic Claude ──
        if "claude" in name:
            return {
                "supports_thinking": True,
                "supports_reasoning_effort": False,
                "family": "anthropic",
                "confidence": 0.9,
            }

        # ── Gemini ──
        if "gemini" in name:
            return {
                "supports_thinking": True,
                "supports_reasoning_effort": False,
                "family": "gemini",
                "confidence": 0.8,
            }

        # ── MiniMax ──
        if any(kw in name for kw in ("minimax", "m2.5", "mimo")):
            return {
                "supports_thinking": True,
                "supports_reasoning_effort": False,
                "family": "minimax",
                "confidence": 0.7,
            }

        # ── Qwen ──
        # 值域按 qwen3.8 实际报错确认：仅 xhigh（默认）/ medium / low。
        # 注：o 系列之外的 qwen 端点若放宽值域，更新此列表即可。
        if "qwen" in name:
            return {
                "supports_thinking": True,
                "supports_reasoning_effort": True,
                "family": "qwen",
                "supported_efforts": ["low", "medium", "xhigh"],
                "confidence": 0.8,
            }

        # ── Llama ──
        if "llama" in name:
            return {
                "supports_thinking": True,
                "supports_reasoning_effort": False,
                "family": "llama",
                "confidence": 0.5,
            }

        # ── GLM / 智谱 ──
        if "glm" in name or "zhipu" in name:
            return {
                "supports_thinking": True,
                "supports_reasoning_effort": False,
                "family": "glm",
                "confidence": 0.6,
            }

        # ── 未知模型 ──
        return {
            "supports_thinking": True,
            "supports_reasoning_effort": False,
            "family": "unknown",
            "confidence": 0.3,
        }

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
            return {
                "supports_thinking": cached,
                "supports_reasoning_effort": self.ctx.reasoning_effort != "xhigh",
                "recommended_strength": self.ctx.thinking_strength,
                "recommended_effort": self.ctx.reasoning_effort,
                "method": "cached",
            }

        target_client = self.ctx.cheap_client if is_cheap else self.ctx.client
        target_model = self.ctx.cheap_model if is_cheap else self.ctx.model

        if not self.ctx.enable_thinking or not target_client:
            return {
                "supports_thinking": False,
                "supports_reasoning_effort": False,
                "recommended_strength": 0.0,
                "recommended_effort": "medium",
                "method": "disabled",
            }

        # ── Phase 1: 模型名匹配（零成本） ──
        match = self._match_model_family(target_model)
        if match["confidence"] >= 0.7:
            # 高置信度匹配，直接使用
            supports_re = match["supports_reasoning_effort"]
            strength = 0.7
            effort = "medium"

            if supports_re:
                effort = "medium"
                strength = 0.7
            elif match["family"] == "deepseek_v4":
                effort = "xhigh"
                strength = 0.6  # V4 flash 轻量模型，中等思考
            elif match["family"] == "openai_gpt4":
                effort = "xhigh"
                strength = 0.5  # GPT-4o 的 thinking 支持有限
            elif match["family"] == "minimax":
                effort = "xhigh"
                strength = 0.6  # MiniMax 的 thinking 支持中等
            elif match["family"] == "qwen":
                effort = "xhigh"
                strength = 0.8

            # 更新缓存
            setattr(self.ctx, cache_attr, match["supports_thinking"])
            _tl = getattr(self.ctx, "tool_log", None)
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
                "method": f"model_match({match['family']})",
            }

        # ── Phase 2: API 探测（低置信度匹配或未知模型） ──
        _tl = getattr(self.ctx, "tool_log", None)
        if _tl:
            _tl(f"🔍 低置信度模型匹配 ({match['confidence']:.0%})，启动 API 探测...")

        result = {
            "supports_thinking": True,
            "supports_reasoning_effort": False,
            "recommended_strength": 0.5,
            "recommended_effort": "high",
            "method": "default",
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
                    extra_body={
                        "thinking": {"type": "enabled"},
                        "reasoning_effort": "medium",
                    },
                    max_tokens=5,
                )
                result["supports_reasoning_effort"] = False
                result["recommended_strength"] = 0.7
                result["recommended_effort"] = "medium"
            except Exception:
                result["supports_reasoning_effort"] = False
                result["recommended_strength"] = 0.7
                result["recommended_effort"] = "high"

        except Exception as e:
            err_str = str(e).lower()
            if (
                "thinking" in err_str
                or "extra_body" in err_str
                or "unsupported" in err_str
                or "invalid" in err_str
            ):
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
        disable_thinking: bool = False,
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
                # 视觉模型必须使用自己的推理参数（max_tokens/temperature/top_p），
                # 不能继承主模型的配置。vision 未配置时 get_effective_params 回退主模型。
                try:
                    from tea_agent.config import get_config

                    vp = get_config().get_effective_params(
                        "vision", getattr(self.ctx, "_current_mode", "mixed")
                    )
                    if vp:
                        temperature = vp.get("temperature", temperature)
                        max_tokens = vp.get("max_tokens", max_tokens)
                        top_p = vp.get("top_p", top_p)
                except Exception:
                    pass

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

        # reasoning_effort 是独立参数（OpenAI o-series 使用），不受 thinking probe 影响。
        # 仅当取值合法且非 "auto"（"auto"=自动推导，不显式下发）时才发送；
        # 否则回退到 thinking_strength 自动映射。
        reasoning_effort = self.ctx.reasoning_effort
        if (
            reasoning_effort
            and reasoning_effort in REASONING_EFFORT_VALUES
            and reasoning_effort != "auto"
        ):
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
                # 将 strength 映射为推理努力程度（通用映射；API 不接受 "auto"）
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

        # ── reasoning_effort 终末校验 ──
        # options 合并可能注入非法值（如 "auto"），API 只接受
        # none/minimal/low/medium/high/xhigh/max；"auto" 语义=自动推导，
        # 直接移除该参数，避免 400。
        _eff = extra_body.get("reasoning_effort")
        if _eff is not None and (_eff not in REASONING_EFFORT_VALUES or _eff == "auto"):
            extra_body.pop("reasoning_effort", None)

        # ── reasoning_effort 值域钳制（按模型家族）──
        # 各模型接受的值域不同（如 qwen3.8 仅 xhigh/medium/low，
        # 而 strength 映射会产出 high）。不在值域内时钳制到最接近的支持值，
        # 避免 400。显式配置值与 strength 映射结果在此统一兜底。
        _eff = extra_body.get("reasoning_effort")
        if _eff:
            _match = self._match_model_family(target_model)
            _supported = _match.get("supported_efforts")
            if _supported and _eff not in _supported:
                _clamped = clamp_reasoning_effort(_eff, _supported)
                logger.info(f"🔧 reasoning_effort 钳制: {_eff} → {_clamped} (模型: {target_model})")
                extra_body["reasoning_effort"] = _clamped

        # ⚠️ 思考模式下不发送 temperature/top_p（DeepSeek V4 文档明确不支持；
        # 官方端点会忽略，但第三方代理可能直接 400）。凡启用 thinking 或
        # 显式传 reasoning_effort 即视为思考模式，从 kwargs 移除这两个参数。
        if "thinking" in extra_body or "reasoning_effort" in extra_body:
            kwargs.pop("temperature", None)
            kwargs.pop("top_p", None)

        if extra_body:
            kwargs["extra_body"] = extra_body

        if target_model in ("mimo-v2.5-pro", "mimo-v2.5", "mimo-v2.0"):
            kwargs.pop("stream_options", None)
            kwargs.pop("extra_body", None)

        # ── 400 自愈降级（disable_thinking）──
        # 本回合先前请求已触发 DeepSeek 400 "reasoning_content must be passed back"
        # （tool_loop_runner 检测后置位 ctx._rc400_recovery）。此时历史 assistant 消息
        # 的 RC 值已无法由客户端还原/校验，继续开启 thinking 会反复 400；强制关闭
        # thinking 后 DeepSeek 不再要求 RC 回传，对话可继续。下一用户回合
        # reset_session_state() 清除该标志，thinking 自动恢复。
        if (
            (disable_thinking or getattr(self.ctx, "_rc400_recovery", False))
            and target_model not in ("mimo-v2.5-pro", "mimo-v2.5", "mimo-v2.0")
        ):
            extra_body = {"thinking": {"type": "disabled"}}
            kwargs["extra_body"] = extra_body
            kwargs.pop("stream_options", None)
            logger.warning(
                f"⚠️ RC 400 自愈：本回合剩余请求强制关闭 thinking (model={target_model})"
            )

        # ── 防御性 RC 字段补全（DeepSeek thinking 模式硬性要求）──
        # 凡 thinking **启用**（extra_body.thinking.type=enabled 或携带
        # reasoning_effort）且请求携带 tools，**每个** assistant 消息都必须携带
        # reasoning_content 字段（值可为空串）——字段缺失即触发 400
        # "The reasoning_content in the thinking mode must be passed back to
        # the API"。此处兜底任何绕过 build_api_messages 的旁路（如
        # supports_reasoning=False 但 thinking 探测开启的不一致配置），
        # 保证发送前结构完整。api_messages 是副本，原地补全不影响会话历史。
        _thinking_enabled = (
            extra_body.get("thinking", {}).get("type") == "enabled"
            or "reasoning_effort" in extra_body
        )
        if tools and _thinking_enabled:
            _filled = 0
            for _m in api_messages:
                if _m.get("role") == "assistant" and "reasoning_content" not in _m:
                    _m["reasoning_content"] = ""
                    _filled += 1
            if _filled:
                logger.debug(f"create_chat_stream: 为 {_filled} 条 assistant 消息补全空 reasoning_content")

        # API 弹性：网络中断/睡眠恢复时自动重试（仅重试可恢复错误，指数退避）
        from tea_agent.api_retry import call_with_retry
        from tea_agent.config import get_config as _get_cfg

        try:
            _api_cfg = _get_cfg()
            _mr = int(getattr(_api_cfg, "api_max_retries", 3))
            _bf = float(getattr(_api_cfg, "api_retry_backoff", 2.0))
            _sw = float(getattr(_api_cfg, "api_sleep_recovery_wait", 5.0))
        except Exception:
            _mr, _bf, _sw = 3, 2.0, 5.0

        stream = call_with_retry(
            target_client.chat.completions.create,
            max_retries=_mr,
            backoff=_bf,
            sleep_recovery_wait=_sw,
            on_retry=lambda a, e, w: logger.warning(
                f"⚠️ 接口中断，第 {a} 次重试中（{type(e).__name__}），等待 {w:.0f}s…"
            ),
            **kwargs,
        )
        return stream

    def call_summarize_api(self, cli, mdl, messages, temperature=0.1, max_tokens=500):
        import logging

        logger = logging.getLogger("session.api")

        # 摘要调用同样支持网络重试（睡眠恢复场景）
        from tea_agent.api_retry import call_with_retry
        from tea_agent.config import get_config as _get_cfg

        try:
            _cfg = _get_cfg()
            _mr = int(getattr(_cfg, "api_max_retries", 3))
            _bf = float(getattr(_cfg, "api_retry_backoff", 2.0))
            _sw = float(getattr(_cfg, "api_sleep_recovery_wait", 5.0))
        except Exception:
            _mr, _bf, _sw = 3, 2.0, 5.0

        try:
            logger.debug(
                f"summarize API request: model={mdl}, msgs={len(messages)}, temperature={temperature}, max_tokens={max_tokens}"
            )
            return call_with_retry(
                cli.chat.completions.create,
                max_retries=_mr,
                backoff=_bf,
                sleep_recovery_wait=_sw,
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
                return call_with_retry(
                    cli.chat.completions.create,
                    max_retries=_mr,
                    backoff=_bf,
                    sleep_recovery_wait=_sw,
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
