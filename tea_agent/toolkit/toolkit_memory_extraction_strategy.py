## llm generated tool func, created Thu Apr 16 10:47:14 2026

def toolkit_memory_extraction_strategy(action: str, extract_interval: int = 5, auto_extract: bool = True) -> dict:
    import os
    import json
    import time

    toolkit_dir = None
    try:
        f_dir = os.path.dirname(os.path.abspath(__file__))
        if os.path.basename(f_dir) == "toolkit" and os.path.isdir(f_dir): toolkit_dir = f_dir
        elif os.path.exists(os.path.join(f_dir, "toolkit")): toolkit_dir = os.path.join(f_dir, "toolkit")
    except: pass
    if not toolkit_dir:
        curr = os.getcwd()
        for _ in range(8):
            if os.path.basename(curr) == "toolkit" and os.path.isdir(curr): toolkit_dir = curr; break
            if os.path.exists(os.path.join(curr, "toolkit")): toolkit_dir = os.path.join(curr, "toolkit"); break
            curr = os.path.dirname(curr)
            if not curr: break
    if not toolkit_dir: return {"error": "Toolkit directory not found"}

    strategy_file = os.path.join(toolkit_dir, ".memory_strategy.json")
    counter_file = os.path.join(toolkit_dir, ".chat_counter.json")
    now_str = time.strftime("%Y-%m-%dT%H:%M:%S")

    strategy = {"extract_interval": 5, "auto_extract": True, "last_extract_count": 0, "total_extractions": 0, "created_at": now_str}
    if os.path.exists(strategy_file):
        try:
            with open(strategy_file, 'r', encoding='utf-8') as f: strategy.update(json.load(f))
        except: pass

    counter = {"count": 0}
    if os.path.exists(counter_file):
        try:
            with open(counter_file, 'r', encoding='utf-8') as f: counter.update(json.load(f))
        except: pass

    current_count = counter.get("count", 0)

    if action == "configure":
        strategy["extract_interval"] = extract_interval
        strategy["auto_extract"] = auto_extract
        with open(strategy_file, 'w', encoding='utf-8') as f: json.dump(strategy, f, ensure_ascii=False, indent=2)
        return {"status": "configured", "extract_interval": extract_interval, "auto_extract": auto_extract}
    elif action == "check":
        chats_since = current_count - strategy.get("last_extract_count", 0)
        should = strategy.get("auto_extract", True) and chats_since >= strategy.get("extract_interval", 5)
        return {"should_extract": should, "current_count": current_count, "chats_since_last_extract": chats_since, "extract_interval": strategy.get("extract_interval", 5)}
    elif action == "trigger":
        strategy["last_extract_count"] = current_count
        strategy["total_extractions"] = strategy.get("total_extractions", 0) + 1
        strategy["last_extracted_at"] = now_str
        with open(strategy_file, 'w', encoding='utf-8') as f: json.dump(strategy, f, ensure_ascii=False, indent=2)
        return {"status": "triggered", "extraction_count": strategy["total_extractions"], "at_count": current_count}
    elif action == "status":
        return {"auto_extract": strategy.get("auto_extract"), "extract_interval": strategy.get("extract_interval"), "current_chat_count": current_count, "last_extract_count": strategy.get("last_extract_count", 0), "total_extractions": strategy.get("total_extractions", 0), "created_at": strategy.get("created_at")}
    else:
        return {"error": f"Unknown action: {action}"}

def meta_toolkit_memory_extraction_strategy() -> dict:
    return {"type": "function", "function": {"name": "toolkit_memory_extraction_strategy", "description": "管理 LLM 记忆提取策略，控制何时触发记忆提取。", "parameters": {"type": "object", "properties": {"action": {"type": "string", "description": "操作类型：configure, check, trigger, status", "enum": ["configure", "check", "trigger", "status"]}, "extract_interval": {"type": "integer", "description": "提取间隔，默认 5"}, "auto_extract": {"type": "boolean", "description": "是否启用自动提取"}}, "required": ["action"]}}}
