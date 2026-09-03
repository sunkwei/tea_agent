"""LLM Provider 目录 — 仿 DeepSeek Harness 的「供应商 → 模型」两级模型库

每个 Provider（供应商）包含：
  - api_url:         OpenAI 兼容端点
  - default_model:   默认模型 id（必须存在于 models 内）
  - supports_*:      供应商级能力兜底（某模型未单独声明时继承）
  - models:          模型条目列表。每条可写成两种形态：
       1) 简写字符串：{"models": ["deepseek-chat"]}              ← 仅 id，无元数据
       2) 富条目对象：{"models": [{"id": "...", "context_window": ...}]}  ← 推荐
     富条目字段：
       - id:                  模型 id（必填）
       - context_window:      最大上下文窗口（tokens）
       - max_output_tokens:   最大单次输出（tokens）→ 对应 config 的 max_tokens
       - supports_vision:     视觉能力（缺省继承供应商级）
       - supports_thinking:   思考/推理能力（缺省继承供应商级）
       - description:         一句话说明（UI 展示用）

目录数据为「预置参考值」：上下文窗口/输出上限/能力标记随厂商发布而演进，
切换后仍可在 config.yaml 或「配置」弹窗内细调，不会写死运行时行为。
"""

from __future__ import annotations

from typing import Any


# ── 模型条目小工具 ──────────────────────────────────────────


def _m(
    model_id: str,
    context_window: int = 0,
    max_output_tokens: int = 0,
    supports_vision: bool | None = None,
    supports_thinking: bool | None = None,
    description: str = "",
) -> dict[str, Any]:
    """构造富模型条目；0 / None / 空 的字段自动省略。

    返回字段与 config.ModelConfig / options 一一对应，避免切换时映射错位。
    """
    entry: dict[str, Any] = {"id": model_id}
    if context_window:
        entry["context_window"] = context_window
    if max_output_tokens:
        entry["max_output_tokens"] = max_output_tokens
    if supports_vision is not None:
        entry["supports_vision"] = supports_vision
    if supports_thinking is not None:
        entry["supports_thinking"] = supports_thinking
    if description:
        entry["description"] = description
    return entry


def _normalize_model_entry(entry: str | dict[str, Any]) -> dict[str, Any] | None:
    """字符串简写 → {"id": str}；dict 保证含 id；非法条目返回 None（跳过）。"""
    if isinstance(entry, str):
        return {"id": entry}
    if isinstance(entry, dict) and entry.get("id"):
        return dict(entry)
    return None


def model_entries(provider: dict[str, Any]) -> list[dict[str, Any]]:
    """规范化某供应商的模型条目列表（每条至少含 id）。

    Args:
        provider: 供应商 dict（含 models 字段；缺省时回退 default_model）

    Returns:
        富条目列表；无 models 且无 default_model 时返回 []；非法条目自动跳过
    """
    raw = provider.get("models") or []
    if not raw and provider.get("default_model"):
        raw = [provider["default_model"]]
    out = []
    for e in raw:
        norm = _normalize_model_entry(e)
        if norm is not None:
            out.append(norm)
    return out


def model_ids(provider: dict[str, Any]) -> list[str]:
    """某供应商的模型 id 列表（保持声明顺序，去重）。"""
    seen: set[str] = set()
    ids: list[str] = []
    for e in model_entries(provider):
        mid = e["id"]
        if mid not in seen:
            seen.add(mid)
            ids.append(mid)
    return ids


def get_model(provider: dict[str, Any], model_id: str) -> dict[str, Any] | None:
    """在某供应商目录内查找模型条目（含继承后的有效能力）。

    Args:
        provider: 供应商 dict
        model_id: 目标模型 id

    Returns:
        富条目（含 id 与解析后能力）；未找到返回 None
    """
    if not model_id:
        return None
    target = next((e for e in model_entries(provider) if e["id"] == model_id), None)
    if target is None:
        return None
    merged = dict(target)
    # 模型级未声明 → 继承供应商级
    if merged.get("supports_vision") is None:
        merged["supports_vision"] = bool(provider.get("supports_vision", False))
    if merged.get("supports_thinking") is None:
        merged["supports_thinking"] = bool(provider.get("supports_thinking", False))
    return merged


# ── Provider 定义 ──

PROVIDERS: dict[str, dict[str, Any]] = {}

PROVIDERS = {
    # ═══════════════ OpenAI ═══════════════
    "OpenAI": {
        "api_url": "https://api.openai.com/v1",
        "default_model": "gpt-4o",
        "supports_vision": True,
        "supports_thinking": True,
        "description": "OpenAI GPT / o 系列",
        "models": [
            _m("gpt-4o", 128000, 16384, True, False, "均衡旗舰，支持视觉"),
            _m("gpt-4o-mini", 128000, 16384, True, False, "轻量便宜，支持视觉"),
            _m("gpt-4-turbo", 128000, 4096, True, False, "旧代大窗口"),
            _m("gpt-4.1", 1047576, 32768, True, False, "超长上下文旗舰"),
            _m("gpt-4.1-mini", 1047576, 32768, True, False, "超长上下文轻量"),
            _m("gpt-4.1-nano", 1047576, 32768, True, False, "超长上下文极轻"),
            _m("o3", 200000, 100000, False, True, "深度推理"),
            _m("o3-mini", 200000, 100000, False, True, "轻量推理"),
            _m("o4-mini", 200000, 100000, False, True, "新一代小推理"),
            _m("o1", 200000, 100000, False, True, "旧代推理"),
        ],
    },
    # ═══════════════ Anthropic ═══════════════
    "Anthropic": {
        "api_url": "https://api.anthropic.com",
        "default_model": "claude-sonnet-4-20250514",
        "supports_vision": True,
        "supports_thinking": True,
        "description": "Anthropic Claude",
        "models": [
            _m("claude-sonnet-4-20250514", 200000, 64000, True, True, "均衡旗舰（默认）"),
            _m("claude-4-opus-20250514", 200000, 32000, True, True, "最强旗舰"),
            _m("claude-opus-4-20250514", 200000, 32000, True, True, "Opus 4 别名"),
            _m("claude-3-5-sonnet-20241022", 200000, 8192, True, True, "旧代 Sonnet"),
            _m("claude-3-opus-20240229", 200000, 8192, True, False, "旧代 Opus"),
            _m("claude-3-haiku-20240307", 200000, 8192, True, False, "旧代快模型"),
            _m("claude-sonnet-4-5", 200000, 64000, True, True, "Sonnet 4.5"),
            _m("claude-opus-4-5", 200000, 64000, True, True, "Opus 4.5"),
        ],
    },
    # ═══════════════ Google Gemini ═══════════════
    "Gemini": {
        "api_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "default_model": "gemini-2.5-pro",
        "supports_vision": True,
        "supports_thinking": True,
        "description": "Google Gemini（OpenAI 兼容端点）",
        "models": [
            _m("gemini-2.5-pro", 1048576, 65536, True, True, "旗舰，1M 窗口"),
            _m("gemini-2.5-pro-exp-03-25", 1048576, 65536, True, True, "Pro 实验版"),
            _m("gemini-2.5-flash", 1048576, 65536, True, True, "快速，1M 窗口"),
            _m("gemini-2.5-flash-preview-04-17", 1048576, 65536, True, True, "Flash 预览"),
            _m("gemini-2.0-flash", 1048576, 8192, True, True, "旧代 Flash"),
            _m("gemini-2.0-flash-lite", 1048576, 8192, True, False, "旧代极轻"),
            _m("gemini-2.5-flash-lite", 1048576, 65536, True, True, "极轻 Flash"),
        ],
    },
    # ═══════════════ DeepSeek ═══════════════
    "DeepSeek": {
        "api_url": "https://api.deepseek.com",
        "default_model": "deepseek-chat",
        "supports_thinking": True,
        "supports_vision": True,
        "description": "DeepSeek（deepseek-v4-flash-vision-exp 为视觉模型）",
        "models": [
            _m("deepseek-chat", 131072, 8192, False, True, "对话/工具主力"),
            _m("deepseek-reasoner", 131072, 65536, False, True, "深度推理（R1 系）"),
            _m("deepseek-chat-v3-0324", 131072, 8192, False, True, "V3.2 快照"),
            _m("deepseek-v4-flash", 1048576, 131072, False, True, "V4 轻旗舰，1M 窗口"),
            _m("deepseek-v4-flash-vision-exp", 1048576, 131072, True, True, "V4 视觉实验"),
            _m("deepseek-v4-pro", 1048576, 131072, False, True, "V4 旗舰"),
        ],
    },
    # ═══════════════ Alibaba / Qwen ═══════════════
    "Alibaba": {
        "api_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "default_model": "qwen-max",
        "supports_vision": True,
        "supports_thinking": True,
        "description": "阿里云百炼（Qwen）",
        "models": [
            _m("qwen-max", 131072, 8192, False, False, "Max 档"),
            _m("qwen-plus", 131072, 8192, False, False, "Plus 档"),
            _m("qwen-turbo", 131072, 8192, False, False, "Turbo 快档"),
            _m("qwen-long", 10000000, 8192, False, False, "长文档档"),
            _m("qwen-vl-max", 32768, 8192, True, False, "视觉 Max"),
            _m("qwen-vl-plus", 32768, 8192, True, False, "视觉 Plus"),
            _m("qwen3-max", 262144, 8192, False, True, "Qwen3 旗舰"),
            _m("qwen3-235b-a22b", 262144, 16384, False, True, "Qwen3 MoE 大杯"),
            _m("qwen3-30b-a3b", 131072, 16384, False, True, "Qwen3 MoE 小杯"),
            _m("qwen3-flash", 131072, 8192, False, True, "Qwen3 快档"),
            _m("qwen3.5-max", 262144, 16384, False, True, "Qwen3.5 旗舰"),
        ],
    },
    # ═══════════════ Zhipu / GLM ═══════════════
    "ZhipuAI": {
        "api_url": "https://open.bigmodel.cn/api/paas/v4",
        "default_model": "GLM-5.2-Flash",
        "supports_vision": True,
        "supports_thinking": True,
        "description": "智谱 GLM",
        "models": [
            _m("GLM-5.2-Flash", 262144, 16384, True, True, "新旗舰快档"),
            _m("GLM-5.2-Plus", 262144, 32768, True, True, "新旗舰 Plus"),
            _m("GLM-5-Flash", 131072, 8192, True, True, "5 代快档"),
            _m("GLM-4-Plus", 131072, 8192, False, False, "4 代 Plus"),
            _m("GLM-4-Air", 131072, 8192, False, False, "4 代轻量"),
            _m("GLM-4V-Plus", 131072, 8192, True, False, "4 代视觉"),
            _m("glm-4.5", 131072, 8192, True, True, "4.5 快档"),
            _m("glm-4.6", 131072, 8192, True, True, "4.6 快档"),
        ],
    },
    # ═══════════════ Moonshot / Kimi ═══════════════
    "Moonshot": {
        "api_url": "https://api.moonshot.cn/v1",
        "default_model": "kimi-k2",
        "supports_thinking": True,
        "description": "月之暗面 Kimi",
        "models": [
            _m("kimi-k2", 131072, 16384, False, True, "K2 主力"),
            _m("kimi-k2-thinking", 131072, 16384, False, True, "K2 推理增强"),
            _m("kimi-latest", 131072, 16384, False, False, "最新快档"),
            _m("moonshot-v1-8k", 8192, 4096, False, False, "V1 8K"),
            _m("moonshot-v1-32k", 32768, 4096, False, False, "V1 32K"),
            _m("moonshot-v1-128k", 131072, 4096, False, False, "V1 128K"),
        ],
    },
    # ═══════════════ Groq ═══════════════
    "Groq": {
        "api_url": "https://api.groq.com/openai/v1",
        "default_model": "llama-4-scout-17b-16e-instruct",
        "supports_thinking": True,
        "description": "极速推理 API",
        "models": [
            _m("llama-4-scout-17b-16e-instruct", 1048576, 8192, True, False, "Llama4 Scout"),
            _m("llama-4-maverick-17b-128e-instruct", 1048576, 8192, True, False, "Llama4 Maverick"),
            _m("llama-3.3-70b-versatile", 131072, 32768, False, False, "Llama3.3 70B"),
            _m("llama-3.1-8b-instant", 131072, 8192, False, False, "Llama3.1 8B"),
            _m("deepseek-r1-distill-llama-70b", 131072, 32768, False, True, "R1 蒸馏 70B"),
            _m("qwen-2.5-coder-32b", 131072, 8192, False, False, "Qwen 编程 32B"),
            _m("mixtral-8x7b-32768", 32768, 8192, False, False, "Mixtral MoE"),
        ],
    },
    # ═══════════════ Mistral ═══════════════
    "Mistral": {
        "api_url": "https://api.mistral.ai/v1",
        "default_model": "mistral-large-latest",
        "supports_vision": True,
        "description": "Mistral AI",
        "models": [
            _m("mistral-large-latest", 131072, 32768, False, False, "Large 旗舰"),
            _m("mistral-medium-latest", 32768, 8192, False, False, "Medium"),
            _m("mistral-small-latest", 32768, 8192, False, False, "Small 轻量"),
            _m("mistral-moderation-latest", 32768, 1024, False, False, "审核"),
            _m("codestral-latest", 131072, 32768, False, False, "编程专用"),
            _m("pixtral-large-latest", 131072, 32768, True, False, "视觉 Large"),
        ],
    },
    # ═══════════════ xAI ═══════════════
    "xAI": {
        "api_url": "https://api.x.ai/v1",
        "default_model": "grok-3",
        "supports_vision": True,
        "supports_thinking": True,
        "description": "xAI Grok",
        "models": [
            _m("grok-4", 262144, 131072, True, True, "Grok 4 旗舰"),
            _m("grok-4-fast", 262144, 131072, True, True, "Grok 4 快档"),
            _m("grok-3", 131072, 65536, True, True, "Grok 3"),
            _m("grok-3-mini", 131072, 32768, True, True, "Grok 3 轻量"),
            _m("grok-2", 131072, 32768, True, False, "Grok 2"),
            _m("grok-beta", 131072, 8192, False, False, "Beta"),
        ],
    },
    # ═══════════════ Cohere ═══════════════
    "Cohere": {
        "api_url": "https://api.cohere.com/v1",
        "default_model": "command-a",
        "description": "Cohere Command",
        "models": [
            _m("command-a", 262144, 8192, False, False, "旗舰"),
            _m("command-r-plus", 131072, 4096, False, False, "R+"),
            _m("command-r", 131072, 4096, False, False, "R"),
            _m("command-r7b", 131072, 4096, False, False, "7B 轻量"),
        ],
    },
    # ═══════════════ Perplexity ═══════════════
    "Perplexity": {
        "api_url": "https://api.perplexity.ai",
        "default_model": "sonar-pro",
        "supports_thinking": True,
        "description": "Perplexity Sonar（联网搜索）",
        "models": [
            _m("sonar-pro", 200000, 16384, False, True, "Pro"),
            _m("sonar", 131072, 8192, False, False, "标准"),
            _m("sonar-reasoning", 131072, 8192, False, True, "推理档"),
        ],
    },
    # ═══════════════ OpenRouter ═══════════════
    "OpenRouter": {
        "api_url": "https://openrouter.ai/api/v1",
        "default_model": "anthropic/claude-sonnet-4",
        "supports_vision": True,
        "supports_thinking": True,
        "description": "300+ 模型统一接口",
        "models": [
            _m("anthropic/claude-sonnet-4", 200000, 64000, True, True, "Claude Sonnet 4"),
            _m("anthropic/claude-opus-4", 200000, 32000, True, True, "Claude Opus 4"),
            _m("anthropic/claude-3.5-sonnet", 200000, 8192, True, True, "Claude 3.5"),
            _m("openai/gpt-4o", 128000, 16384, True, False, "GPT-4o"),
            _m("openai/o3-mini", 200000, 100000, False, True, "o3-mini"),
            _m("google/gemini-2.5-pro", 1048576, 65536, True, True, "Gemini 2.5 Pro"),
            _m("deepseek/deepseek-chat", 131072, 8192, False, False, "DeepSeek Chat"),
            _m("deepseek/deepseek-r1", 131072, 65536, False, True, "DeepSeek R1"),
            _m("meta-llama/llama-4-scout", 1048576, 8192, True, False, "Llama4 Scout"),
            _m("qwen/qwen-3-235b-a22b", 262144, 16384, False, True, "Qwen3 235B"),
            _m("mistral/mistral-large", 131072, 32768, False, False, "Mistral Large"),
            _m("cohere/command-r-plus", 131072, 4096, False, False, "Command R+"),
            _m("x-ai/grok-3", 131072, 65536, True, True, "Grok 3"),
        ],
    },
    # ═══════════════ SiliconFlow ═══════════════
    "SiliconFlow": {
        "api_url": "https://api.siliconflow.cn/v1",
        "default_model": "Qwen/Qwen3-235B-A22B",
        "supports_thinking": True,
        "supports_vision": True,
        "description": "硅基流动（开源模型托管）",
        "models": [
            _m("Qwen/Qwen3-235B-A22B", 262144, 16384, False, True, "Qwen3 MoE"),
            _m("Qwen/Qwen3-30B-A3B", 131072, 16384, False, True, "Qwen3 轻 MoE"),
            _m("Qwen/Qwen3-8B", 131072, 16384, False, True, "Qwen3 8B"),
            _m("deepseek-ai/DeepSeek-V3.2", 131072, 8192, False, True, "DeepSeek V3.2"),
            _m("deepseek-ai/DeepSeek-R1", 131072, 65536, False, True, "DeepSeek R1"),
            _m("meta-llama/Llama-4-Scout-17B-16E-Instruct", 1048576, 8192, True, False, "Llama4 Scout"),
            _m("THUDM/GLM-4.6", 131072, 8192, True, True, "GLM 4.6"),
            _m("Pro/Qwen/Qwen2.5-VL-7B-Instruct", 32768, 8192, True, False, "Qwen VL 7B"),
        ],
    },
    # ═══════════════ Together ═══════════════
    "Together": {
        "api_url": "https://api.together.xyz/v1",
        "default_model": "meta-llama/Llama-4-Scout-17B-16E-Instruct",
        "supports_vision": True,
        "supports_thinking": True,
        "description": "Together AI（开源模型云）",
        "models": [
            _m("meta-llama/Llama-4-Scout-17B-16E-Instruct", 1048576, 8192, True, False, "Llama4 Scout"),
            _m("meta-llama/Llama-3.3-70B-Instruct-Turbo", 131072, 32768, False, False, "Llama3.3 70B"),
            _m("meta-llama/Llama-3.1-405B-Instruct-Turbo", 131072, 8192, False, False, "Llama3.1 405B"),
            _m("deepseek-ai/DeepSeek-V3.2", 131072, 8192, False, True, "DeepSeek V3.2"),
            _m("Qwen/Qwen3-235B-A22B", 262144, 16384, False, True, "Qwen3 MoE"),
            _m("mistralai/Mixtral-8x22B-Instruct-v0.1", 65536, 8192, False, False, "Mixtral 8x22B"),
        ],
    },
    # ═══════════════ Fireworks ═══════════════
    "Fireworks": {
        "api_url": "https://api.fireworks.ai/inference/v1",
        "default_model": "accounts/fireworks/models/llama-v4-scout-17b-16e-instruct",
        "supports_vision": True,
        "description": "Fireworks AI 快速推理",
        "models": [
            _m("accounts/fireworks/models/llama-v4-scout-17b-16e-instruct", 1048576, 8192, True, False, "Llama4 Scout"),
            _m(
                "accounts/fireworks/models/llama-v4-maverick-17b-128e-instruct",
                1048576,
                8192,
                True,
                False,
                "Llama4 Maverick",
            ),
            _m("accounts/fireworks/models/llama-v3p1-70b-instruct", 131072, 8192, False, False, "Llama3.3 70B"),
            _m("accounts/fireworks/models/qwen3-235b-a22b-instruct", 262144, 16384, False, True, "Qwen3 MoE"),
        ],
    },
    # ═══════════════ DeepInfra ═══════════════
    "DeepInfra": {
        "api_url": "https://api.deepinfra.com/v1/openai",
        "default_model": "meta-llama/Llama-4-Scout-17B-16E-Instruct",
        "supports_vision": True,
        "supports_thinking": True,
        "description": "DeepInfra 托管推理",
        "models": [
            _m("meta-llama/Llama-4-Scout-17B-16E-Instruct", 1048576, 8192, True, False, "Llama4 Scout"),
            _m("meta-llama/Llama-3.3-70B-Instruct", 131072, 8192, False, False, "Llama3.3 70B"),
            _m("deepseek-ai/DeepSeek-R1", 131072, 65536, False, True, "DeepSeek R1"),
            _m("Qwen/Qwen3-235B-A22B", 262144, 16384, False, True, "Qwen3 MoE"),
        ],
    },
    # ═══════════════ Ollama（本地） ═══════════════
    "Ollama": {
        "api_url": "http://127.0.0.1:11434/v1",
        "default_model": "llama3.1",
        "supports_vision": True,
        "supports_thinking": True,
        "description": "本地 Ollama（需安装并拉取模型）",
        "models": [
            _m("llama3.1", 131072, 8192, False, False, "Llama3.1"),
            _m("llama3.2", 131072, 8192, False, False, "Llama3.2"),
            _m("llama3.3", 131072, 8192, False, False, "Llama3.3"),
            _m("llama4", 1048576, 8192, True, False, "Llama4"),
            _m("qwen3", 131072, 16384, False, True, "Qwen3"),
            _m("qwen3.5", 131072, 16384, False, True, "Qwen3.5"),
            _m("qwen2.5", 131072, 8192, False, False, "Qwen2.5"),
            _m("deepseek-r1", 131072, 65536, False, True, "DeepSeek R1"),
            _m("deepseek-v4-flash", 1048576, 131072, False, True, "DeepSeek V4 Flash"),
            _m("mistral", 32768, 8192, False, False, "Mistral"),
            _m("gemma3", 131072, 8192, True, False, "Gemma3"),
        ],
    },
    # ═══════════════ MiniMax ═══════════════
    "MiniMax": {
        "api_url": "https://api.minimax.chat/v1",
        "default_model": "MiniMax-M2",
        "supports_thinking": True,
        "supports_vision": True,
        "description": "MiniMax 大模型",
        "models": [
            _m("MiniMax-M2", 1048576, 131072, True, True, "M2 旗舰"),
            _m("MiniMax-M1", 1048576, 32768, True, True, "M1"),
            _m("MiniMax-Text-01", 1048576, 8192, False, False, "Text-01"),
            _m("minimax-text-01", 1048576, 8192, False, False, "Text-01 别名"),
        ],
    },
    # ═══════════════ Baidu 文心 ═══════════════
    "Baidu": {
        "api_url": "https://qianfan.baidubce.com/v2",
        "default_model": "ernie-4.5-8k",
        "supports_thinking": True,
        "description": "百度文心千帆",
        "models": [
            _m("ernie-4.5-8k", 8192, 8192, False, True, "4.5 标准"),
            _m("ernie-4.5-128k", 131072, 8192, False, True, "4.5 长窗"),
            _m("ernie-4.0-8k", 8192, 2048, False, False, "4.0"),
            _m("ernie-3.5-8k", 8192, 2048, False, False, "3.5"),
            _m("ernie-x1-32k", 32768, 8192, False, True, "X1 推理"),
            _m("ernie-4.5-vl-8k", 8192, 8192, True, True, "4.5 视觉"),
        ],
    },
    # ═══════════════ Volcengine 豆包 ═══════════════
    "Volcengine": {
        "api_url": "https://ark.cn-beijing.volces.com/api/v3",
        "default_model": "doubao-1.6-pro-256k",
        "supports_vision": True,
        "supports_thinking": True,
        "description": "火山方舟（豆包 / Seed）",
        "models": [
            _m("doubao-1.6-pro-256k", 262144, 8192, False, True, "Pro 长窗"),
            _m("doubao-1.6-pro-32k", 32768, 8192, False, True, "Pro 标准"),
            _m("doubao-seed-1.6-flash", 131072, 8192, False, False, "Seed Flash"),
            _m("doubao-1.5-vision-pro-32k", 32768, 8192, True, True, "视觉 Pro"),
            _m("doubao-pro-32k", 32768, 8192, False, False, "旧 Pro"),
            _m("doubao-seed-1.6-thinking", 131072, 8192, False, True, "Seed 推理"),
        ],
    },
    # ═══════════════ NVIDIA NIM ═══════════════
    "NVIDIA": {
        "api_url": "https://integrate.api.nvidia.com/v1",
        "default_model": "meta/llama-3.3-70b-instruct",
        "supports_vision": True,
        "supports_thinking": True,
        "description": "NVIDIA NIM 托管推理",
        "models": [
            _m("meta/llama-3.3-70b-instruct", 131072, 8192, False, False, "Llama3.3 70B"),
            _m("meta/llama-4-scout-17b-16e-instruct", 1048576, 8192, True, False, "Llama4 Scout"),
            _m("deepseek-ai/deepseek-r1", 131072, 65536, False, True, "DeepSeek R1"),
            _m("qwen/qwen2.5-72b-instruct", 131072, 8192, False, False, "Qwen2.5 72B"),
            _m("nvidia/llama-3.1-nemotron-70b-instruct", 131072, 8192, False, False, "Nemotron 70B"),
        ],
    },
    # ═══════════════ Cerebras ═══════════════
    "Cerebras": {
        "api_url": "https://api.cerebras.ai/v1",
        "default_model": "llama-3.3-70b",
        "supports_thinking": True,
        "description": "Cerebras 极速推理",
        "models": [
            _m("llama-3.3-70b", 131072, 32768, False, False, "Llama3.3 70B"),
            _m("llama-3.1-8b", 131072, 8192, False, False, "Llama3.1 8B"),
            _m("llama4-scout", 1048576, 8192, True, False, "Llama4 Scout"),
            _m("deepseek-r1-distill-llama-70b", 131072, 32768, False, True, "R1 蒸馏"),
        ],
    },
    # ═══════════════ Hyperbolic ═══════════════
    "Hyperbolic": {
        "api_url": "https://api.hyperbolic.xyz/v1",
        "default_model": "meta-llama/Llama-3.3-70B-Instruct",
        "supports_vision": True,
        "supports_thinking": True,
        "description": "Hyperbolic 开源云",
        "models": [
            _m("meta-llama/Llama-3.3-70B-Instruct", 131072, 8192, False, False, "Llama3.3 70B"),
            _m("meta-llama/Llama-4-Scout-17B-16E-Instruct", 1048576, 8192, True, False, "Llama4 Scout"),
            _m("deepseek-ai/DeepSeek-R1", 131072, 65536, False, True, "DeepSeek R1"),
            _m("Qwen/Qwen3-235B-A22B", 262144, 16384, False, True, "Qwen3 MoE"),
        ],
    },
    # ═══════════════ 阶跃星辰 StepFun ═══════════════
    "StepFun": {
        "api_url": "https://api.stepfun.com/v1",
        "default_model": "step-2-16k",
        "supports_vision": True,
        "supports_thinking": True,
        "description": "阶跃星辰 Step",
        "models": [
            _m("step-2-16k", 16384, 4096, False, False, "Step-2 16K"),
            _m("step-2-32k", 32768, 4096, False, False, "Step-2 32K"),
            _m("step-2-256k", 262144, 4096, False, False, "Step-2 256K"),
            _m("step-1v-32k", 32768, 2048, True, False, "视觉"),
            _m("step-2-mini", 32768, 4096, False, False, "Mini"),
        ],
    },
    # ═══════════════ 零一万物 01.AI ═══════════════
    "01.AI": {
        "api_url": "https://api.lingyiwanwu.com/v1",
        "default_model": "yi-lightning",
        "description": "零一万物 Yi",
        "models": [
            _m("yi-lightning", 131072, 8192, False, False, "Lightning"),
            _m("yi-large", 32768, 4096, False, False, "Large"),
            _m("yi-medium", 32768, 4096, False, False, "Medium"),
        ],
    },
    # ═══════════════ 智谱兼容网关（自定义示例保留区） ═══════════════
    # 自定义供应商由 model_manager 管理（~/.tea_agent/custom_providers.yaml），
    # 这里不再内嵌私有网关。
}


# ── Provider 查询 ──────────────────────────────────────────


def list_providers() -> list[dict]:
    """返回所有 Provider 的公开信息列表（models 收敛为 id 列表）。

    Returns:
        [{name, api_url, default_model, models:[id...], catalog:[富条目],
          supports_*, description, model_count, max_context_window,
          max_output_tokens}]
    """
    result = []
    for name, info in sorted(PROVIDERS.items()):
        ids = model_ids(info)
        entries = model_entries(info)
        caps = [e.get("context_window", 0) for e in entries]
        outs = [e.get("max_output_tokens", 0) for e in entries]
        catalog = []
        for entry in entries:
            catalog.append(
                {
                    "id": entry["id"],
                    "context_window": entry.get("context_window", 0) or 0,
                    "max_output_tokens": entry.get("max_output_tokens", 0) or 0,
                    "supports_vision": bool(entry.get("supports_vision", info.get("supports_vision", False))),
                    "supports_thinking": bool(entry.get("supports_thinking", info.get("supports_thinking", False))),
                    "description": entry.get("description", "") or "",
                }
            )
        result.append(
            {
                "name": name,
                "api_url": info["api_url"],
                "default_model": info["default_model"],
                "models": ids,
                "catalog": catalog,
                "supports_thinking": any(m["supports_thinking"] for m in catalog),
                "supports_vision": any(m["supports_vision"] for m in catalog),
                "description": info.get("description", ""),
                "model_count": len(ids),
                "max_context_window": max(caps) if caps else 0,
                "max_output_tokens": max(outs) if outs else 0,
            }
        )
    return result


def get_provider(name: str) -> dict | None:
    """根据名称查找 Provider（不区分大小写）。

    Args:
        name: Provider 名称

    Returns:
        {name, **info, models: [id...]}；不存在返回 None
    """
    name_lower = (name or "").lower()
    for pname, info in PROVIDERS.items():
        if pname.lower() == name_lower:
            result = {"name": pname, **info}
            result["models"] = model_ids(info)
            return result
    return None


def generate_config(provider_name: str, api_key: str, model: str = "", use_as_cheap: bool = False) -> str:
    """生成指定 Provider 的 YAML 配置片段。

    Args:
        provider_name: Provider 名称
        api_key: API Key
        model: 模型 id；留空使用 default_model
        use_as_cheap: 是否为 cheap_model 生成（仅影响注释语义）

    Returns:
        YAML 片段
    """
    provider = get_provider(provider_name)
    if not provider:
        raise ValueError(f"Unknown provider: {provider_name}")

    model = model or provider["default_model"]
    meta = get_model(PROVIDERS[provider["name"]], model) or {}
    lines = [
        f"  api_key: {api_key}",
        f"  api_url: {provider['api_url']}",
        f'  model_name: "{model}"',
        "  temperature: 0.65",
        f"  max_tokens: {meta.get('max_output_tokens') or 131072}",
        "  options:",
        f"    supports_vision: {'true' if meta.get('supports_vision', provider.get('supports_vision', False)) else 'false'}",
        f"    supports_reasoning: {'true' if meta.get('supports_thinking', provider.get('supports_thinking', False)) else 'false'}",
    ]
    return "\n".join(lines)


def switch_provider(
    config_path: str,
    provider_name: str,
    api_key: str,
    model: str = "",
    use_cheap: bool = False,
    cheap_provider: str = "",
    cheap_api_key: str = "",
    cheap_model: str = "",
) -> dict:
    """切换配置到指定 Provider（写 config.yaml）。

    Args:
        config_path: 配置文件路径
        provider_name: 主 Provider 名称
        api_key: 主 API Key
        model: 主模型 id（留空用 default_model）
        use_cheap: 是否同时配置 cheap_model
        cheap_provider: cheap Provider 名称
        cheap_api_key: cheap API Key
        cheap_model: cheap 模型 id

    Returns:
        {"ok": True, "provider": ..., "model": ...} 或 {"ok": False, "error": ...}
    """
    from tea_agent.config import load_config, save_config

    cfg = load_config(config_path)
    provider = get_provider(provider_name)
    if not provider:
        return {"ok": False, "error": f"Unknown provider: {provider_name}"}

    model = model or provider["default_model"]
    meta = get_model(PROVIDERS[provider["name"]], model) or {}
    _apply_model_into(cfg.main_model, provider, model, api_key, meta)

    if cheap_provider:
        cp = get_provider(cheap_provider)
        if cp:
            cheap_model = cheap_model or cp["default_model"]
            cmeta = get_model(PROVIDERS[cp["name"]], cheap_model) or {}
            _apply_model_into(cfg.cheap_model, cp, cheap_model, cheap_api_key or api_key, cmeta)

    save_config(cfg, config_path)
    return {"ok": True, "provider": provider_name, "model": cfg.main_model.model_name}


def _apply_model_into(target, provider: dict, model: str, api_key: str, meta: dict) -> None:
    """把 Provider + 模型元数据写入某个 ModelConfig。

    Args:
        target: ModelConfig 实例（main/cheap/vision）
        provider: Provider 公开信息 dict
        model: 模型 id
        api_key: API Key
        meta: 富模型条目（含有效能力/窗口）
    """
    target.api_key = api_key
    target.api_url = provider["api_url"]
    target.model_name = model
    # 写真布尔值，避免 "false" 字符串在 supports_vision 判定里恒真
    target.options["supports_vision"] = bool(meta.get("supports_vision", provider.get("supports_vision", False)))
    target.options["supports_reasoning"] = bool(meta.get("supports_thinking", provider.get("supports_thinking", False)))
    if meta.get("context_window"):
        target.max_context_tokens = int(meta["context_window"])
    if meta.get("max_output_tokens"):
        target.max_tokens = int(meta["max_output_tokens"])
