## llm generated tool func, created Wed Apr 29 09:41:57 2026
# version: 1.0.0

# @2026-04-29 gen by deepseek-v4-pro, 内置工具: 删除/失效记忆
def toolkit_memory_forget(id: int, hard: bool = False):
    """
    删除或失效一条记忆。
    
    Args:
        id: 记忆 ID
        hard: True=硬删除(彻底移除)，False=软删除(标记为失效)
    """
    try:
        from tea_agent.store import get_storage
        storage = get_storage()
        
        if hard:
            ok = storage.delete_memory(id)
            if ok:
                return f"🗑️ 记忆 #{id} 已彻底删除。"
            else:
                return f"❌ 记忆 #{id} 不存在，无法删除。"
        else:
            ok = storage.deactivate_memory(id)
            if ok:
                return f"💤 记忆 #{id} 已标记为失效（软删除），可通过 update_memory 重新激活。"
            else:
                return f"❌ 记忆 #{id} 不存在，无法失效。"
    except Exception as e:
        return f"❌ 操作失败: {e}"

def meta_toolkit_memory_forget() -> dict:
    return {"type": "function", "function": {"name": "toolkit_memory_forget", "description": "删除或失效指定记忆。默认软删除(标记失效)，hard=True 时硬删除(彻底移除)。", "parameters": {"type": "object", "properties": {"id": {"type": "integer", "description": "记忆ID"}, "hard": {"type": "boolean", "description": "是否硬删除（彻底移除），默认 false", "default": False}}, "required": ["id"]}}}
