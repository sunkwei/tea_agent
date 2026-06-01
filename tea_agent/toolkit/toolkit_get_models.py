## llm generated tool func, created Fri May 15 13:15:33 2026
# version: 1.0.0

def toolkit_get_models():
    """
    获取当前 Agent 配置的模型信息。

    Returns:
        dict: 包含 main_model, cheap_model, embedding_model 的字典。
    """
    try:
        # 尝试绝对导入
        from tea_agent.config import load_config
        cfg = load_config()
        return {
            "main_model": cfg.main_model.model_name or "未配置",
            "cheap_model": cfg.cheap_model.model_name or "未配置",
            "embedding_model": cfg.embedding.model_name or "未配置",
        }
    except ImportError:
        # 兼容相对导入
        try:
            from .config import load_config
            cfg = load_config()
            return {
                "main_model": cfg.main_model.model_name or "未配置",
                "cheap_model": cfg.cheap_model.model_name or "未配置",
                "embedding_model": cfg.embedding.model_name or "未配置",
            }
        except Exception:
            return {"error": "无法加载配置模块"}
    except Exception as e:
        return {"error": str(e)}

def meta_toolkit_get_models() -> dict:
    return {"type": "function", "function": {"name": "toolkit_get_models", "description": "获取当前配置的所有模型信息（主模型、摘要模型、嵌入模型）。无需参数。", "parameters": {"type": "object", "properties": {}, "required": []}}}
