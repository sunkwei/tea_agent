## llm generated tool func, created Thu Apr 16 10:51:32 2026

def toolkit_self_report() -> dict:
    """
    Generates a comprehensive status report of the Agent.
    """
    import os
    import json
    import sqlite3

    # 1. Robustly find the base directory (containing memory.db)
    # Start from cwd and walk up to find the root .tea_agent directory
    base_dir = os.getcwd()
    found = False
    temp = base_dir
    for _ in range(10):
        if os.path.exists(os.path.join(temp, "memory.db")):
            base_dir = temp
            found = True
            break
        parent = os.path.dirname(temp)
        if parent == temp: break
        temp = parent

    # Fallback if not found by walking up
    if not found:
        base_dir = os.path.join(os.path.expanduser("~"), ".tea_agent")
        if not os.path.exists(base_dir): base_dir = os.getcwd()

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

    # 3. Memory Stats
    memory_stats = {"total_records": 0, "categories": {}}
    db_path = os.path.join(base_dir, "memory.db")
    if os.path.exists(db_path):
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM memories")
            res = cursor.fetchone()
            if res: memory_stats["total_records"] = res[0]
            
            cursor.execute("SELECT category, COUNT(*) FROM memories GROUP BY category")
            rows = cursor.fetchall()
            for row in rows:
                memory_stats["categories"][row[0]] = row[1]
            conn.close()
        except Exception as e:
            memory_stats["error"] = str(e)

    # 4. Strategy & Counter Info
    strategy_file = os.path.join(toolkit_dir, ".memory_strategy.json")
    counter_file = os.path.join(toolkit_dir, ".chat_counter.json")

    strategy_data = {}
    if os.path.exists(strategy_file):
        try:
            with open(strategy_file, 'r', encoding='utf-8') as f: strategy_data = json.load(f)
        except Exception:
            pass

    counter_data = {}
    if os.path.exists(counter_file):
        try:
            with open(counter_file, 'r', encoding='utf-8') as f: counter_data = json.load(f)
        except Exception:
            pass

    return {
        "status": "online",
        "tool_count": tool_count,
        "memory": memory_stats,
        "strategy": {
            "auto_extract": strategy_data.get("auto_extract"),
            "extract_interval": strategy_data.get("extract_interval"),
            "current_chat_count": counter_data.get("count", 0),
            "total_extractions": strategy_data.get("total_extractions", 0)
        }
    }

def meta_toolkit_self_report() -> dict:
    return {"type": "function", "function": {"name": "toolkit_self_report", "description": "生成当前 Agent 的状态报告，包括工具数量、记忆统计和策略配置。", "parameters": {"type": "object", "properties": {}, "required": []}}}
