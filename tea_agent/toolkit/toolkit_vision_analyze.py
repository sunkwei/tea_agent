# version: 1.0.0
"""
toolkit_vision_analyze — 视觉模型委托分析工具（"灵机一动"能力）。

场景：会话进行中，主模型（不支持视觉）遇到图片路径/URL/data URL 时，
主动调用本工具，委托已配置的 vision_model（或支持视觉的主模型）分析图片，
将视觉模型的文本结果返回给主模型继续推理。

输入：
    image: 图片路径（本地文件）或 URL（http/https）或 data URL（data:image/...;base64,...）
    prompt: 分析指令（可选，默认「请描述这张图片的内容」）
    max_tokens: 最大输出 token 数（默认 1024）

返回：
    {'ok': True, 'text': '视觉模型的分析文本', 'model': '模型名'}
    或 {'ok': False, 'error': '原因'}
"""

import logging
import os

logger = logging.getLogger("toolkit")

# 模块级客户端缓存：key=(api_key, api_url) → OpenAI client，避免每次重建
_client_cache = {}


def _get_vision_client():
    """从配置获取视觉模型（优先 vision_model，回退支持视觉的主模型）。

    Returns:
        (client, model_name, model_options) 或 (None, None, None)
    """
    from openai import OpenAI

    from tea_agent.config import get_config

    cfg = get_config()
    vm = getattr(cfg, "vision_model", None)
    if vm is not None and vm.is_configured:
        model_cfg = vm
    elif cfg.main_model.supports_vision and cfg.main_model.is_configured:
        model_cfg = cfg.main_model
    else:
        return None, None, None

    key = (model_cfg.api_key, model_cfg.api_url)
    client = _client_cache.get(key)
    if client is None:
        client = OpenAI(api_key=model_cfg.api_key, base_url=model_cfg.api_url)
        _client_cache[key] = client
    return client, model_cfg.model_name, model_cfg.options or {}


def _to_data_url(image: str) -> str | None:
    """将图片路径/URL/data URL 统一为可发送的 data URL（远程 URL 原样透传）。"""
    if not image or not isinstance(image, str):
        return None
    image = image.strip()
    if image.startswith("data:"):
        return image
    if image.startswith(("http://", "https://")):
        # 远程 URL 原样透传（需模型端支持 URL 拉取）
        return image
    if os.path.isfile(image):
        import base64

        try:
            with open(image, "rb") as f:
                b64 = base64.b64encode(f.read()).decode("utf-8")
        except Exception as e:
            logger.warning(f"图片编码失败 {image}: {e}")
            return None
        ext = os.path.splitext(image)[1].lower()
        mime_map = {
            ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".gif": "image/gif", ".webp": "image/webp", ".bmp": "image/bmp",
        }
        mime = mime_map.get(ext, "image/png")
        return f"data:{mime};base64,{b64}"
    return None


def _build_image_block(data_url: str, detail: str = "") -> dict:
    """构造 OpenAI 兼容的 image_url 内容块。

    detail 为 DeepSeek/OpenAI 视觉 API 的细节级别参数（low/high/original/auto），
    仅在显式提供且取值合法时附带，否则省略（服务端按 auto 处理）。
    """
    block = {"type": "image_url", "image_url": {"url": data_url}}
    if detail and detail.lower() in ("low", "high", "original", "auto"):
        block["image_url"]["detail"] = detail.lower()
    return block


def toolkit_vision_analyze(image: str, prompt: str = "请描述这张图片的内容", max_tokens: int = 1024, detail: str = "") -> dict:
    """调用已配置的视觉模型分析图片，返回文本结果。

    Args:
        image: 图片路径 / http(s) URL / data URL
        prompt: 分析指令
        max_tokens: 最大输出 token 数
        detail: 图片细节级别（DeepSeek/OpenAI 视觉 API）: low/high/original/auto。
            空字符串时回退 vision_model.options.detail；再缺省不传（服务端默认）。

    Returns:
        {'ok': True, 'text': str, 'model': str} 或 {'ok': False, 'error': str}
    """
    logger.info(f"toolkit_vision_analyze called: image={str(image)[:80]!r}, prompt={prompt[:60]!r}")

    client, model_name, options = _get_vision_client()
    if client is None:
        return {
            "ok": False,
            "error": "未配置视觉模型：请在配置中设置 vision_model（支持视觉），或使用 supports_vision 的主模型",
        }

    data_url = _to_data_url(image)
    if data_url is None:
        return {"ok": False, "error": f"无法解析图片输入（路径不存在或格式不支持）: {str(image)[:100]}"}

    try:
        detail_opt = (options or {}).get("detail", "") if options else ""
        messages = [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                _build_image_block(data_url, detail or detail_opt),
            ],
        }]
        kwargs = {"model": model_name, "messages": messages, "max_tokens": max_tokens}
        # 透传模型 options（如 supports_reasoning 需要的 extra_body）
        if options:
            extra_body = {}
            if options.get("supports_reasoning"):
                extra_body["thinking"] = {"type": "enabled"}
            if extra_body:
                kwargs["extra_body"] = extra_body

        resp = client.chat.completions.create(**kwargs)
        text = ""
        if resp.choices and resp.choices[0].message:
            text = resp.choices[0].message.content or ""
        return {"ok": True, "text": text, "model": model_name}
    except Exception as e:
        logger.warning(f"视觉模型分析失败: {e}")
        return {"ok": False, "error": f"视觉模型调用失败: {e}"}


def meta_toolkit_vision_analyze() -> dict:
    """工具元描述（OpenAI function schema）。"""
    return {
        "type": "function",
        "function": {
            "name": "toolkit_vision_analyze",
            "description": (
                "调用已配置的视觉模型（vision_model）分析图片并返回文本结果。"
                "适用于：当前模型不支持视觉时，对话中出现图片路径/URL/data URL，"
                "或需要理解截图、图表、照片内容。支持本地文件路径、http(s) URL、"
                "data:image/...;base64 三种图片输入。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "image": {
                        "type": "string",
                        "description": "图片输入：本地文件路径 / http(s) URL / data URL（data:image/png;base64,...）",
                    },
                    "prompt": {
                        "type": "string",
                        "description": "分析指令，如「描述这张图片的内容」「提取图中的文字」「判断图表趋势」，默认「请描述这张图片的内容」",
                        "default": "请描述这张图片的内容",
                    },
                    "max_tokens": {
                        "type": "integer",
                        "description": "最大输出 token 数，默认 1024",
                        "default": 1024,
                    },
                    "detail": {
                        "type": "string",
                        "description": "图片细节级别（DeepSeek/OpenAI 视觉 API）: low/high/original/auto。默认空=用 vision_model.options.detail 或服务端默认",
                        "default": "",
                    },
                },
                "required": ["image"],
            },
        },
    }
