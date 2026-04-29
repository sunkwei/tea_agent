## llm generated tool func, created Wed Apr 29 09:41:22 2026
# version: 1.0.0

# @2026-04-29 gen by deepseek-v4-pro, 内置工具: 搜索长期记忆
def toolkit_memory_search(query: str = "", category: str = "", tags: str = "", min_importance: int = 0, limit: int = 10):
    """
    搜索长期记忆（关键词 + 分类 + 标签 + 重要度过滤）。
    """
    try:
        from tea_agent.store import get_storage
        storage = get_storage()
        
        tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else None
        
        results = storage.search_memories(
            query=query,
            category=category,
            tags=tag_list,
            min_importance=min_importance,
            limit=limit,
        )
        
        if not results:
            return "📭 未找到匹配的记忆。"
        
        priority_labels = {0: "CRITICAL", 1: "HIGH", 2: "MEDIUM", 3: "LOW"}
        lines = [f"📋 找到 {len(results)} 条记忆:"]
        for m in results:
            pl = priority_labels.get(m["priority"], str(m["priority"]))
            exp = f" ⏳{m['expires_at']}" if m.get("expires_at") else ""
            cat = m.get("category", "general")
            lines.append(f"  #{m['id']} [{pl}/{cat}]{exp}: {m['content']}")
        
        return "\n".join(lines)
    except Exception as e:
        return f"❌ 搜索记忆失败: {e}"

def meta_toolkit_memory_search() -> dict:
    return {"type": "function", "function": {"name": "toolkit_memory_search", "description": "搜索长期记忆。支持关键词模糊匹配、分类过滤、标签过滤、最低重要度过滤。", "parameters": {"type": "object", "properties": {"query": {"type": "string", "description": "在记忆内容中搜索的关键词", "default": ""}, "category": {"type": "string", "enum": ["", "instruction", "preference", "fact", "reminder", "general"], "description": "按分类过滤，空=不过滤", "default": ""}, "tags": {"type": "string", "description": "逗号分隔标签过滤", "default": ""}, "min_importance": {"type": "integer", "description": "最低重要度 1-5", "default": 0}, "limit": {"type": "integer", "description": "返回数量上限", "default": 10}}, "required": []}}}


def meta_toolkit_memory_search() -> dict:
    return {"type": "function", "function": {"name": "toolkit_memory_search", "description": "搜索长期记忆。支持关键词模糊匹配、分类过滤、标签过滤、最低重要度过滤。返回匹配的有效记忆列表。", "parameters": {"type": "object", "properties": {"query": {"type": "string", "description": "在记忆内容中搜索的关键词", "default": ""}, "category": {"type": "string", "enum": ["", "instruction", "preference", "fact", "reminder", "general"], "description": "按分类过滤，空=不过滤", "default": ""}, "tags": {"type": "string", "description": "逗号分隔标签过滤，匹配任一即可", "default": ""}, "min_importance": {"type": "integer", "description": "最低重要度 1-5", "default": 0}, "limit": {"type": "integer", "description": "返回数量上限", "default": 10}}, "required": []}}}
