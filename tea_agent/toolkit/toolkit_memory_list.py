## llm generated tool func, created Wed Apr 29 09:41:41 2026
# version: 1.0.0

# @2026-04-29 gen by deepseek-v4-pro, 内置工具: 列出活跃记忆
def toolkit_memory_list(limit: int = 20):
    """
    列出当前活跃的长期记忆。
    """
    try:
        from tea_agent.store import get_storage
        storage = get_storage()
        
        memories = storage.get_active_memories(limit=limit)
        
        if not memories:
            return "📭 当前没有活跃的记忆。"
        
        # 获取统计
        stats = storage.get_memory_stats()
        
        priority_labels = {0: "CRITICAL", 1: "HIGH", 2: "MEDIUM", 3: "LOW"}
        lines = [f"🧠 活跃记忆: {stats['total']} 条 (指令:{stats['by_priority'].get(0,0)} 高:{stats['by_priority'].get(1,0)} 中:{stats['by_priority'].get(2,0)} 低:{stats['by_priority'].get(3,0)})"]
        lines.append("")
        
        for m in memories[:limit]:
            pl = priority_labels.get(m["priority"], str(m["priority"]))
            cat = m.get("category", "general")
            imp = "⭐" * m.get("importance", 3)
            exp = f" ⏳{m['expires_at']}" if m.get("expires_at") else ""
            lines.append(f"  #{m['id']} [{pl}/{cat}]{exp} {imp}")
            lines.append(f"     {m['content']}")
        
        if len(memories) > limit:
            lines.append(f"  ... 还有 {len(memories) - limit} 条未显示")
        
        return "\n".join(lines)
    except Exception as e:
        return f"❌ 列出记忆失败: {e}"

def meta_toolkit_memory_list() -> dict:
    return {"type": "function", "function": {"name": "toolkit_memory_list", "description": "列出当前所有活跃的长期记忆，按优先级排序。", "parameters": {"type": "object", "properties": {"limit": {"type": "integer", "description": "返回数量上限", "default": 20}}, "required": []}}}


def meta_toolkit_memory_list() -> dict:
    return {"type": "function", "function": {"name": "toolkit_memory_list", "description": "列出当前所有活跃的长期记忆，按优先级排序。可用于查看有哪些记忆存在。", "parameters": {"type": "object", "properties": {"limit": {"type": "integer", "description": "返回数量上限", "default": 20}}, "required": []}}}
