# llm generated tool func, created Wed Apr 15 13:13:21 2026

def toolkit_dir() -> str:
    from pathlib import Path
    return str(Path.home() / ".tea_agent" / "toolkit")


def meta_toolkit_dir() -> dict:
    return {"type": "function", "function": {"name": "toolkit_dir", "description": "返回工具目录路径", "parameters": {"type": "object", "properties": {}, "required": []}}}
