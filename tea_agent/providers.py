"""LLM Provider 目录 — 纯引导目录（模型属性唯一来源 = provider.yaml）

自 2026-09-06 起，代码内**不再内置任何模型属性**（context_window /
max_output_tokens / supports_vision / supports_thinking 等）。本文件的
PROVIDERS 仅作「新装引导/面板端点参考」：

  - api_url / default_model / description：供应商端点的静态引导信息
  - models: 纯 id 字符串列表（仅 id，无任何能力/窗口元数据）

模型运行期属性（max_context_tokens / max_output_tokens / 能力标记）一律从
~/.tea_agent/provider.yaml 的 models.<m_name> 条目解析；未收录模型 → 0=未知，
需在 provider.yaml 显式配置（tool_profile 分档等据此保守处理）。

兼容说明：model_entries()/get_model() 仍接受外部传入的富条目 dict
（来自 provider.yaml / custom / config profile 迁移），以支持历史数据；
但内置 PROVIDERS 自身不再携带富条目。
"""

from __future__ import annotations

from typing import Any


# ── 模型条目小工具 ──────────────────────────────────────────


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
            "gpt-4o",
            "gpt-4o-mini",
            "gpt-4-turbo",
            "gpt-4.1",
            "gpt-4.1-mini",
            "gpt-4.1-nano",
            "o3",
            "o3-mini",
            "o4-mini",
            "o1",
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
            "claude-sonnet-4-20250514",
            "claude-4-opus-20250514",
            "claude-opus-4-20250514",
            "claude-3-5-sonnet-20241022",
            "claude-3-opus-20240229",
            "claude-3-haiku-20240307",
            "claude-sonnet-4-5",
            "claude-opus-4-5",
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
            "gemini-2.5-pro",
            "gemini-2.5-pro-exp-03-25",
            "gemini-2.5-flash",
            "gemini-2.5-flash-preview-04-17",
            "gemini-2.0-flash",
            "gemini-2.0-flash-lite",
            "gemini-2.5-flash-lite",
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
            "deepseek-chat",
            "deepseek-reasoner",
            "deepseek-chat-v3-0324",
            "deepseek-v4-flash",
            "deepseek-v4-flash-vision-exp",
            "deepseek-v4-pro",
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
            "qwen-max",
            "qwen-plus",
            "qwen-turbo",
            "qwen-long",
            "qwen-vl-max",
            "qwen-vl-plus",
            "qwen3-max",
            "qwen3-235b-a22b",
            "qwen3-30b-a3b",
            "qwen3-flash",
            "qwen3.5-max",
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
            "GLM-5.2-Flash",
            "GLM-5.2-Plus",
            "GLM-5-Flash",
            "GLM-4-Plus",
            "GLM-4-Air",
            "GLM-4V-Plus",
            "glm-4.5",
            "glm-4.6",
        ],
    },
    # ═══════════════ Moonshot / Kimi ═══════════════
    "Moonshot": {
        "api_url": "https://api.moonshot.cn/v1",
        "default_model": "kimi-k2",
        "supports_thinking": True,
        "description": "月之暗面 Kimi",
        "models": [
            "kimi-k2",
            "kimi-k2-thinking",
            "kimi-latest",
            "moonshot-v1-8k",
            "moonshot-v1-32k",
            "moonshot-v1-128k",
        ],
    },
    # ═══════════════ Groq ═══════════════
    "Groq": {
        "api_url": "https://api.groq.com/openai/v1",
        "default_model": "llama-4-scout-17b-16e-instruct",
        "supports_thinking": True,
        "description": "极速推理 API",
        "models": [
            "llama-4-scout-17b-16e-instruct",
            "llama-4-maverick-17b-128e-instruct",
            "llama-3.3-70b-versatile",
            "llama-3.1-8b-instant",
            "deepseek-r1-distill-llama-70b",
            "qwen-2.5-coder-32b",
            "mixtral-8x7b-32768",
        ],
    },
    # ═══════════════ Mistral ═══════════════
    "Mistral": {
        "api_url": "https://api.mistral.ai/v1",
        "default_model": "mistral-large-latest",
        "supports_vision": True,
        "description": "Mistral AI",
        "models": [
            "mistral-large-latest",
            "mistral-medium-latest",
            "mistral-small-latest",
            "mistral-moderation-latest",
            "codestral-latest",
            "pixtral-large-latest",
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
            "grok-4",
            "grok-4-fast",
            "grok-3",
            "grok-3-mini",
            "grok-2",
            "grok-beta",
        ],
    },
    # ═══════════════ Cohere ═══════════════
    "Cohere": {
        "api_url": "https://api.cohere.com/v1",
        "default_model": "command-a",
        "description": "Cohere Command",
        "models": [
            "command-a",
            "command-r-plus",
            "command-r",
            "command-r7b",
        ],
    },
    # ═══════════════ Perplexity ═══════════════
    "Perplexity": {
        "api_url": "https://api.perplexity.ai",
        "default_model": "sonar-pro",
        "supports_thinking": True,
        "description": "Perplexity Sonar（联网搜索）",
        "models": [
            "sonar-pro",
            "sonar",
            "sonar-reasoning",
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
            "anthropic/claude-sonnet-4",
            "anthropic/claude-opus-4",
            "anthropic/claude-3.5-sonnet",
            "openai/gpt-4o",
            "openai/o3-mini",
            "google/gemini-2.5-pro",
            "deepseek/deepseek-chat",
            "deepseek/deepseek-r1",
            "meta-llama/llama-4-scout",
            "qwen/qwen-3-235b-a22b",
            "mistral/mistral-large",
            "cohere/command-r-plus",
            "x-ai/grok-3",
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
            "Qwen/Qwen3-235B-A22B",
            "Qwen/Qwen3-30B-A3B",
            "Qwen/Qwen3-8B",
            "deepseek-ai/DeepSeek-V3.2",
            "deepseek-ai/DeepSeek-R1",
            "meta-llama/Llama-4-Scout-17B-16E-Instruct",
            "THUDM/GLM-4.6",
            "Pro/Qwen/Qwen2.5-VL-7B-Instruct",
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
            "meta-llama/Llama-4-Scout-17B-16E-Instruct",
            "meta-llama/Llama-3.3-70B-Instruct-Turbo",
            "meta-llama/Llama-3.1-405B-Instruct-Turbo",
            "deepseek-ai/DeepSeek-V3.2",
            "Qwen/Qwen3-235B-A22B",
            "mistralai/Mixtral-8x22B-Instruct-v0.1",
        ],
    },
    # ═══════════════ Fireworks ═══════════════
    "Fireworks": {
        "api_url": "https://api.fireworks.ai/inference/v1",
        "default_model": "accounts/fireworks/models/llama-v4-scout-17b-16e-instruct",
        "supports_vision": True,
        "description": "Fireworks AI 快速推理",
        "models": [
            "accounts/fireworks/models/llama-v4-scout-17b-16e-instruct",
            "accounts/fireworks/models/llama-v4-maverick-17b-128e-instruct",
            "accounts/fireworks/models/llama-v3p1-70b-instruct",
            "accounts/fireworks/models/qwen3-235b-a22b-instruct",
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
            "meta-llama/Llama-4-Scout-17B-16E-Instruct",
            "meta-llama/Llama-3.3-70B-Instruct",
            "deepseek-ai/DeepSeek-R1",
            "Qwen/Qwen3-235B-A22B",
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
            "llama3.1",
            "llama3.2",
            "llama3.3",
            "llama4",
            "qwen3",
            "qwen3.5",
            "qwen2.5",
            "deepseek-r1",
            "deepseek-v4-flash",
            "mistral",
            "gemma3",
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
            "MiniMax-M2",
            "MiniMax-M1",
            "MiniMax-Text-01",
            "minimax-text-01",
        ],
    },
    # ═══════════════ Baidu 文心 ═══════════════
    "Baidu": {
        "api_url": "https://qianfan.baidubce.com/v2",
        "default_model": "ernie-4.5-8k",
        "supports_thinking": True,
        "description": "百度文心千帆",
        "models": [
            "ernie-4.5-8k",
            "ernie-4.5-128k",
            "ernie-4.0-8k",
            "ernie-3.5-8k",
            "ernie-x1-32k",
            "ernie-4.5-vl-8k",
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
            "doubao-1.6-pro-256k",
            "doubao-1.6-pro-32k",
            "doubao-seed-1.6-flash",
            "doubao-1.5-vision-pro-32k",
            "doubao-pro-32k",
            "doubao-seed-1.6-thinking",
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
            "meta/llama-3.3-70b-instruct",
            "meta/llama-4-scout-17b-16e-instruct",
            "deepseek-ai/deepseek-r1",
            "qwen/qwen2.5-72b-instruct",
            "nvidia/llama-3.1-nemotron-70b-instruct",
        ],
    },
    # ═══════════════ Cerebras ═══════════════
    "Cerebras": {
        "api_url": "https://api.cerebras.ai/v1",
        "default_model": "llama-3.3-70b",
        "supports_thinking": True,
        "description": "Cerebras 极速推理",
        "models": [
            "llama-3.3-70b",
            "llama-3.1-8b",
            "llama4-scout",
            "deepseek-r1-distill-llama-70b",
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
            "meta-llama/Llama-3.3-70B-Instruct",
            "meta-llama/Llama-4-Scout-17B-16E-Instruct",
            "deepseek-ai/DeepSeek-R1",
            "Qwen/Qwen3-235B-A22B",
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
            "step-2-16k",
            "step-2-32k",
            "step-2-256k",
            "step-1v-32k",
            "step-2-mini",
        ],
    },
    # ═══════════════ 零一万物 01.AI ═══════════════
    "01.AI": {
        "api_url": "https://api.lingyiwanwu.com/v1",
        "default_model": "yi-lightning",
        "description": "零一万物 Yi",
        "models": [
            "yi-lightning",
            "yi-large",
            "yi-medium",
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
