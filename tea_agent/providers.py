"""LLM Provider 注册表 — 一键配置50+ AI模型提供商

每个提供商包含默认API端点、模型列表和能力标记。
所有 Provider 均为 OpenAI API 兼容格式。
"""

from typing import Optional
from tea_agent.config import load_config, save_config

# ── Provider 定义 ──

PROVIDERS = {}

PROVIDERS = {
    "Alibaba": {
        "api_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "default_model": "qwen-max",
        "models": ["qwen-max", "qwen-plus", "qwen-turbo", "qwen3-235b-a22b", "qwen3-30b-a3b"],
        "supports_thinking": True,
        "description": "阿里云百炼",
    },
    "Anthropic": {
        "api_url": "https://api.anthropic.com",
        "default_model": "claude-sonnet-4-20250514",
        "models": ["claude-sonnet-4-20250514", "claude-4-opus-20250514", "claude-3-5-sonnet-20241022", "claude-3-opus-20240229", "claude-3-haiku-20240307"],
        "supports_thinking": True,
        "supports_vision": True,
        "description": "Anthropic Claude 系列模型",
    },
    "Baidu": {
        "api_url": "https://qianfan.baidubce.com/v2",
        "default_model": "ernie-4.5-8k",
        "models": ["ernie-4.5-8k", "ernie-4.0-8k", "ernie-3.5-8k"],
        "description": "百度文心千帆",
    },
    "Cohere": {
        "api_url": "https://api.cohere.com/v1",
        "default_model": "command-r-plus",
        "models": ["command-r-plus", "command-r", "command-a"],
        "description": "Cohere Command",
    },
    "DeepInfra": {
        "api_url": "https://api.deepinfra.com/v1/openai",
        "default_model": "meta-llama/Llama-4-Scout-17B-16E-Instruct",
        "description": "DeepInfra 托管推理",
    },
    "DeepSeek": {
        "api_url": "https://api.deepseek.com",
        "default_model": "deepseek-chat",
        "models": ["deepseek-chat", "deepseek-reasoner", "deepseek-chat-v3-0324"],
        "supports_thinking": True,
        "description": "DeepSeek 系列模型",
    },
    "Fireworks": {
        "api_url": "https://api.fireworks.ai/inference/v1",
        "default_model": "accounts/fireworks/models/llama-v4-scout-17b-16e-instruct",
        "description": "Fireworks AI 快速推理",
    },
    "Gemini": {
        "api_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "default_model": "gemini-2.5-pro-exp-03-25",
        "models": ["gemini-2.5-pro-exp-03-25", "gemini-2.5-flash-preview-04-17", "gemini-2.0-flash", "gemini-2.0-flash-lite"],
        "supports_thinking": True,
        "supports_vision": True,
        "description": "Google Gemini（OpenAI 兼容端点）",
    },
    "Groq": {
        "api_url": "https://api.groq.com/openai/v1",
        "default_model": "llama-4-scout-17b-16e-instruct",
        "models": ["llama-4-scout-17b-16e-instruct", "llama-4-maverick-17b-128e-instruct", "llama-3.3-70b-versatile", "llama-3.1-8b-instant", "deepseek-r1-distill-llama-70b", "mixtral-8x7b-32768"],
        "description": "极速推理 API",
    },
    "Minimax": {
        "api_url": "https://api.minimax.chat/v1",
        "default_model": "minimax-text-01",
        "description": "MiniMax 大模型",
    },
    "Mistral": {
        "api_url": "https://api.mistral.ai/v1",
        "default_model": "mistral-large-latest",
        "models": ["mistral-large-latest", "mistral-small-latest", "codestral-latest"],
        "supports_vision": True,
        "description": "Mistral AI",
    },
    "Moonshot": {
        "api_url": "https://api.moonshot.cn/v1",
        "default_model": "moonshot-v1-8k",
        "models": ["moonshot-v1-8k", "moonshot-v1-32k", "moonshot-v1-128k"],
        "description": "月之暗面 Kimi",
    },
    "Ollama": {
        "api_url": "http://127.0.0.1:11434/v1",
        "default_model": "llama3.1",
        "models": ["llama3.1", "llama3.2", "llama4", "qwen3", "qwen2.5", "deepseek-r1", "mistral"],
        "supports_vision": True,
        "description": "本地运行(需安装 Ollama)",
    },
    "OpenAI": {
        "api_url": "https://api.openai.com/v1",
        "default_model": "gpt-4o",
        "models": ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "o3", "o4-mini", "gpt-4.1", "gpt-4.1-mini"],
        "supports_thinking": True,
        "supports_vision": True,
        "description": "OpenAI GPT/o 系列模型",
    },
    "OpenRouter": {
        "api_url": "https://openrouter.ai/api/v1",
        "default_model": "anthropic/claude-sonnet-4",
        "models": ["anthropic/claude-sonnet-4", "anthropic/claude-3.5-sonnet", "openai/gpt-4o", "openai/o3-mini", "google/gemini-2.5-pro", "deepseek/deepseek-chat", "meta-llama/llama-4-scout", "qwen/qwen-3-235b-a22b", "mistral/mistral-large", "cohere/command-r-plus"],
        "supports_thinking": True,
        "supports_vision": True,
        "description": "300+ 模型统一接口",
    },
    "Perplexity": {
        "api_url": "https://api.perplexity.ai",
        "default_model": "sonar-pro",
        "models": ["sonar-pro", "sonar", "sonar-reasoning"],
        "supports_thinking": True,
        "description": "Perplexity Sonar",
    },
    "SiliconFlow": {
        "api_url": "https://api.siliconflow.cn/v1",
        "default_model": "Qwen/Qwen3-235B-A22B",
        "models": ["Qwen/Qwen3-235B-A22B", "Qwen/Qwen3-30B-A3B", "deepseek-ai/DeepSeek-V3", "meta-llama/Llama-4-Scout-17B-16E-Instruct"],
        "supports_thinking": True,
        "description": "国内开源模型平台",
    },
    "Together": {
        "api_url": "https://api.together.xyz/v1",
        "default_model": "meta-llama/Llama-4-Scout-17B-16E-Instruct",
        "models": ["meta-llama/Llama-4-Scout-17B-16E-Instruct", "meta-llama/Llama-3.3-70B-Instruct-Turbo", "deepseek-ai/DeepSeek-V3", "Qwen/Qwen3-235B-A22B"],
        "supports_thinking": True,
        "description": "托管开源模型云平台",
    },
    "Volcengine": {
        "api_url": "https://ark.cn-beijing.volces.com/api/v3",
        "default_model": "doubao-pro-32k",
        "description": "字节火山引擎豆包",
    },
    "ZhipuAI": {
        "api_url": "https://open.bigmodel.cn/api/paas/v4",
        "default_model": "GLM-5.2-Flash",
        "models": ["GLM-5.2-Flash", "GLM-5.2-Plus", "GLM-4-Plus", "GLM-4-Air"],
        "supports_thinking": True,
        "supports_vision": True,
        "description": "智谱 GLM 系列",
    },
    "xAI": {
        "api_url": "https://api.x.ai/v1",
        "default_model": "grok-beta",
        "models": ["grok-beta", "grok-2", "grok-3"],
        "description": "xAI Grok",
    },
}

def list_providers() -> list[dict]:
    """返回所有 Provider 信息列表。"""
    result = []
    for name, info in sorted(PROVIDERS.items()):
        result.append({
            "name": name,
            "api_url": info["api_url"],
            "default_model": info["default_model"],
            "models": info.get("models", [info["default_model"]]),
            "supports_thinking": info.get("supports_thinking", False),
            "supports_vision": info.get("supports_vision", False),
            "description": info.get("description", ""),
        })
    return result


def get_provider(name: str) -> Optional[dict]:
    """根据名称查找 Provider（不区分大小写）。"""
    name_lower = name.lower()
    for pname, info in PROVIDERS.items():
        if pname.lower() == name_lower:
            result = {"name": pname, **info}
            result["models"] = info.get("models", [info["default_model"]])
            return result
    return None


def generate_config(provider_name: str, api_key: str,
                    model: str = "", use_as_cheap: bool = False) -> str:
    """生成指定 Provider 的 YAML 配置片段。"""
    provider = get_provider(provider_name)
    if not provider:
        raise ValueError(f"Unknown provider: {provider_name}")

    model = model or provider["default_model"]
    lines = [
        f"  api_key: {api_key}",
        f"  api_url: {provider['api_url']}",
        f'  model_name: "{model}"',
        '  temperature: 0.65',
        f'  max_tokens: 131072',
        '  options:',
        f'    supports_vision: {"true" if provider.get("supports_vision") else "false"}',
        f'    supports_reasoning: {"true" if provider.get("supports_thinking") else "false"}',
    ]
    return "\n".join(lines)


def switch_provider(config_path: str, provider_name: str, api_key: str,
                    model: str = "", use_cheap: bool = False,
                    cheap_provider: str = "", cheap_api_key: str = "",
                    cheap_model: str = "") -> dict:
    """切换配置到指定 Provider。"""
    cfg = load_config(config_path)
    provider = get_provider(provider_name)
    if not provider:
        return {"ok": False, "error": f"Unknown provider: {provider_name}"}

    cfg.main_model.api_key = api_key
    cfg.main_model.api_url = provider["api_url"]
    cfg.main_model.model_name = model or provider["default_model"]
    cfg.main_model.options["supports_vision"] = str(provider.get("supports_vision", False)).lower()
    cfg.main_model.options["supports_reasoning"] = str(provider.get("supports_thinking", False)).lower()

    if cheap_provider:
        cp = get_provider(cheap_provider)
        if cp:
            cfg.cheap_model.api_key = cheap_api_key or api_key
            cfg.cheap_model.api_url = cp["api_url"]
            cfg.cheap_model.model_name = cheap_model or cp["default_model"]
            cfg.cheap_model.options["supports_vision"] = str(cp.get("supports_vision", False)).lower()
            cfg.cheap_model.options["supports_reasoning"] = str(cp.get("supports_thinking", False)).lower()

    save_config(config_path, cfg)
    return {"ok": True, "provider": provider_name, "model": cfg.main_model.model_name}
