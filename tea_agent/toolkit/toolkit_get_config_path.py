## llm generated tool func, created Thu May 29 12:12:00 2026

import logging

logger = logging.getLogger("toolkit")

def toolkit_get_config_path() -> dict:
    """
    获取当前 Agent 正在使用的配置文件路径。
    
    读取 tea_agent.config 模块的 _last_config_path 变量，
    该变量在 load_config(config_path) 被调用时设置。
    
    Returns:
        dict: {"config_path": str|None, "resolved_path": str|None, "note": str}
            - config_path: 原始传入的路径（可能为 None）
            - resolved_path: 实际解析后加载的 YAML 文件路径
            - note: 说明信息
    """
    logger.info("toolkit_get_config_path called")
    
    import sys
    import os
    from pathlib import Path
    
    try:
        if 'tea_agent.config' in sys.modules:
            config_mod = sys.modules['tea_agent.config']
            last_path = getattr(config_mod, '_last_config_path', None)
            cfg = getattr(config_mod, '_config_cache', None)
            
            result = {
                "config_path": last_path,
                "note": "从已加载的 tea_agent.config 模块读取"
            }
            
            if last_path is None and cfg is not None:
                default_path = str(Path.home() / ".tea_agent" / "config.yaml")
                fallback = str(Path(__file__).parent / "config.yaml") if hasattr(config_mod, '__file__') and config_mod.__file__ else ""
                
                if os.path.isfile(default_path):
                    result["resolved_path"] = default_path
                    result["note"] += "，回退到 ~/.tea_agent/config.yaml"
                elif fallback and os.path.isfile(fallback):
                    result["resolved_path"] = fallback
                    result["note"] += "，回退到项目默认路径"
            else:
                result["resolved_path"] = last_path
            
            return result
        else:
            sys.path.insert(0, os.getcwd())
            import tea_agent.config
            last_path = getattr(tea_agent.config, '_last_config_path', None)
            
            result = {
                "config_path": last_path,
                "note": "新导入 tea_agent.config 模块读取"
            }
            
            if last_path is None:
                default_path = str(Path.home() / ".tea_agent" / "config.yaml")
                if os.path.isfile(default_path):
                    result["resolved_path"] = default_path
                    result["note"] += "，回退到默认路径"
            
            return result
    except Exception as e:
        return {
            "config_path": None,
            "error": str(e),
            "note": "读取配置路径失败"
        }


def meta_toolkit_get_config_path() -> dict:
    """Meta for toolkit_get_config_path."""
    return {
        "type": "function",
        "function": {
            "name": "toolkit_get_config_path",
            "description": "获取当前 Agent 正在使用的配置文件路径。读取 tea_agent.config._last_config_path 模块变量。",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    }
