import json
import urllib.error as urllib_err
import urllib.request as urllib_req


def toolkit_list_provider_models(provider: str = "all", api_url: str = None, api_key: str = None):
    """
    根据当前配置文件查询指定 API 提供商的可用模型列表。

    支持两种模式：
    1. 从配置文件读取：传入 provider 参数指定 main_model/cheap_model/embedding_model/all
    2. 直接指定端点：传入 api_url + api_key 查询任意 OpenAI 兼容 API
    """
    # 外部直接指定模式
    if api_url and api_key:
        return _query_models_formatted(api_url, api_key, label="自定义端点")

    # 从配置文件读取
    try:
        from tea_agent.config import load_config
        cfg = load_config()
    except Exception as e:
        return {"error": f"加载配置失败: {e}", "hint": "请稍后重试"}

    # 收集要查询的 provider
    providers = {}
    model_sections = ["main_model", "cheap_model", "embedding_model"]

    if provider == "all":
        for key in model_sections:
            if hasattr(cfg, key):
                providers[key] = getattr(cfg, key)
    elif provider in model_sections:
        if not hasattr(cfg, provider):
            return {"error": f"配置中未找到 {provider}"}
        providers[provider] = getattr(cfg, provider)
    else:
        return {"error": f"未知 provider: {provider}, 可选: all, main_model, cheap_model, embedding_model"}

    results = {}
    for name, prov in providers.items():
        url = getattr(prov, "api_url", None) or ""
        key = getattr(prov, "api_key", None) or ""
        model_name = getattr(prov, "model_name", None) or ""

        if not url or not key:
            results[name] = {"error": "缺少 api_url 或 api_key", "configured_model": model_name}
            continue

        r = _query_models_formatted(url, key, label=name)
        r["configured_model"] = model_name
        results[name] = r

    # 格式化输出
    lines = []
    for name, data in results.items():
        if "error" in data and "models" not in data:
            lines.append(f"\n## {name} \u274c [{data.get('error')}]")
            lines.append(f"  当前配置模型: {data.get('configured_model', 'N/A')}")
        else:
            endpoint = data.get("endpoint", "?")
            lines.append(f"\n## {name} (端点: {endpoint})")
            lines.append(f"  当前配置模型: {data.get('configured_model', 'N/A')}")
            models = data.get("models", [])
            lines.append(f"  可用模型 ({len(models)} 个):")
            for m in models:
                owned = f" (by {m['owned_by']})" if m.get("owned_by") else ""
                lines.append(f"    - {m['id']}{owned}")

    return "\n".join(lines).strip()


def _query_models_formatted(api_url: str, api_key: str, label: str = "") -> dict:
    """查询 OpenAI 兼容 /v1/models 端点"""
    url = api_url.rstrip("/")
    models_url = f"{url}/v1/models"

    req = urllib_req.Request(
        models_url,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )

    try:
        with urllib_req.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib_err.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace") if e.fp else ""
        return {
            "error": f"HTTP {e.code}: {e.reason}",
            "detail": body[:500],
            "endpoint": models_url,
        }
    except Exception as e:
        return {"error": str(e), "endpoint": models_url}

    models = []
    if "data" in data:
        for item in data["data"]:
            entry = {"id": item.get("id", "?")}
            if "owned_by" in item:
                entry["owned_by"] = item["owned_by"]
            models.append(entry)

    return {
        "models": models,
        "endpoint": models_url,
        "total": len(models),
    }


def meta_toolkit_list_provider_models() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "toolkit_list_provider_models",
            "description": "根据当前配置文件查询指定 API 提供商的可用模型列表。支持按配置文件中的模型名（main_model/cheap_model/embedding_model）查询，也支持直接传入 api_url 和 api_key 查询任意 OpenAI 兼容端点。",
            "parameters": {
                "type": "object",
                "properties": {
                    "provider": {
                        "type": "string",
                        "description": "配置中的模型键名: main_model, cheap_model, embedding_model, 或 'all' 查询全部。默认 all",
                        "default": "all",
                    },
                    "api_url": {
                        "type": "string",
                        "description": "[可选] 直接指定 API 端点，如 https://api.deepseek.com",
                    },
                    "api_key": {
                        "type": "string",
                        "description": "[可选] 直接指定 API Key",
                    },
                },
                "required": [],
            },
        },
    }
