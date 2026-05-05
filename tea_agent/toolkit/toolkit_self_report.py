## llm generated tool func, created Thu Apr 16 10:51:32 2026

def toolkit_self_report() -> dict:
    """
    Generates a comprehensive status report of the Agent.
    """
    import os
    import json
    import sqlite3

    # 1. Robustly find the base directory
    # Start from cwd and walk up to find the root .tea_agent directory
    base_dir = os.getcwd()
    found = False
    temp = base_dir
    for _ in range(10):
        if os.path.exists(os.path.join(temp, "chat_history.db")):
            base_dir = temp
            found = True
            break
        parent = os.path.dirname(temp)
        if parent == temp: break
        temp = parent

# NOTE: 2026-05-04 17:57:38, self-evolved by tea_agent --- toolkit_self_report 使用 config.paths 查找 base_dir 和 toolkit_dir
    # Fallback if not found by walking up：优先从 config 读取
    if not found:
        try:
            from tea_agent.config import get_config
            base_dir = get_config().paths.data_dir_abs
        except Exception:
            base_dir = os.path.join(os.path.expanduser("~"), ".tea_agent")
        if not os.path.exists(base_dir):
            base_dir = os.getcwd()

    try:
        from tea_agent.config import get_config
        toolkit_dir = get_config().paths.toolkit_dir_abs
    except Exception:
        toolkit_dir = os.path.join(base_dir, "toolkit")
    
    # 2. Tool Count (File-based custom tools)
    tool_count = 0
    if os.path.isdir(toolkit_dir):
        try:
            for f in os.listdir(toolkit_dir):
                if f.startswith("toolkit_") and f.endswith(".py"):
                    tool_count += 1
        except Exception:
            pass

    # 3. Strategy & Counter Info
    counter_file = os.path.join(toolkit_dir, ".chat_counter.json")

    counter_data = {}
    if os.path.exists(counter_file):
        try:
            with open(counter_file, 'r', encoding='utf-8') as f: counter_data = json.load(f)
        except Exception:
            pass

    return {
        "status": "online",
        "tool_count": tool_count,
        "current_chat_count": counter_data.get("count", 0)
    }

def meta_toolkit_self_report() -> dict:
    return {"type": "function", "function": {"name": "toolkit_self_report", "description": "生成当前 Agent 的状态报告，包括工具数量。", "parameters": {"type": "object", "properties": {}, "required": []}}}
