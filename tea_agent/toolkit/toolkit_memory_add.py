## llm generated tool func, created Wed Apr 29 09:41:02 2026
# version: 1.0.0

# @2026-04-29 gen by deepseek-v4-pro, 内置工具: 添加长期记忆
def toolkit_memory_add(content: str, category: str = "general", priority: int = 2, importance: int = 3, expires_at: str = None, tags: str = ""):
    """
    添加一条长期记忆到数据库。
    """
    try:
        from tea_agent.store import get_storage
        storage = get_storage()
        
        # 参数校验
        if priority < 0 or priority > 3:
            return f"❌ 优先级必须在 0-3 之间，收到: {priority}"
        if importance < 1 or importance > 5:
            return f"❌ 重要度必须在 1-5 之间，收到: {importance}"
        if category not in ("instruction", "preference", "fact", "reminder", "general"):
            return f"❌ 分类无效: {category}，可选: instruction/preference/fact/reminder/general"
        
        # 处理 expires_at：空字符串视为 None
        if expires_at is not None and expires_at.strip() == "":
            expires_at = None
        
        mid = storage.add_memory(
            content=content,
            category=category,
            priority=priority,
            importance=importance,
            expires_at=expires_at,
            tags=tags,
        )
        
        priority_label = {0: "CRITICAL", 1: "HIGH", 2: "MEDIUM", 3: "LOW"}.get(priority, str(priority))
        return f"✅ 记忆 #{mid} 已添加 [{priority_label}/{category}]: {content}"
    except Exception as e:
        return f"❌ 添加记忆失败: {e}"

def meta_toolkit_memory_add() -> dict:
    return {"type": "function", "function": {"name": "toolkit_memory_add", "description": "添加一条长期记忆。分类: instruction(有效指令,最高优先级)/preference(用户偏好)/fact(技术事实)/reminder(有时效提醒)/general(一般信息)。优先级: 0=CRITICAL(必须遵循)/1=HIGH/2=MEDIUM/3=LOW。重要度: 1-5，5为最高。", "parameters": {"type": "object", "properties": {"content": {"type": "string", "description": "记忆内容，精简摘要"}, "category": {"type": "string", "enum": ["instruction", "preference", "fact", "reminder", "general"], "description": "分类", "default": "general"}, "priority": {"type": "integer", "description": "优先级 0-3，0=CRITICAL, 1=HIGH, 2=MEDIUM, 3=LOW", "default": 2}, "importance": {"type": "integer", "description": "重要度 1-5", "default": 3}, "expires_at": {"type": "string", "description": "过期时间 ISO datetime，null=永不过期"}, "tags": {"type": "string", "description": "逗号分隔标签，如 'code,rule'", "default": ""}}, "required": ["content"]}}}


def meta_toolkit_memory_add() -> dict:
    return {"type": "function", "function": {"name": "toolkit_memory_add", "description": "添加一条长期记忆。分类: instruction(有效指令,最高优先级)/preference(用户偏好)/fact(技术事实)/reminder(有时效提醒)/general(一般信息)。优先级: 0=CRITICAL(必须遵循)/1=HIGH/2=MEDIUM/3=LOW。重要度: 1-5，5为最高。过期时间设为 ISO datetime 格式如 '2026-05-01T08:00:00'，或 null 表示永不过期。", "parameters": {"type": "object", "properties": {"content": {"type": "string", "description": "记忆内容，精简摘要"}, "category": {"type": "string", "enum": ["instruction", "preference", "fact", "reminder", "general"], "description": "分类", "default": "general"}, "priority": {"type": "integer", "description": "优先级 0-3，0=CRITICAL, 1=HIGH, 2=MEDIUM, 3=LOW", "default": 2}, "importance": {"type": "integer", "description": "重要度 1-5", "default": 3}, "expires_at": {"type": "string", "description": "过期时间 ISO datetime，null=永不过期"}, "tags": {"type": "string", "description": "逗号分隔标签，如 'code,rule'", "default": ""}}, "required": ["content"]}}}
