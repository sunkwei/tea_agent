
import logging

logger = logging.getLogger("toolkit")

PRI = {0: "CRITICAL", 1: "HIGH", 2: "MEDIUM", 3: "LOW"}
VALID_CATEGORIES = ("instruction", "preference", "fact", "reminder", "general")



def _m_add(storage, content, category, priority, importance, expires_at, tags):
    """
    M add.

    Args:
        storage: Description.
        content: Description.
        category: Description.
        priority: Description.
        importance: Description.
        expires_at: Description.
        tags: Description.
    """
    if not content:
        return "❌ add 操作需要 content 参数"
    if priority < 0 or priority > 3:
        return f"❌ 优先级必须在 0-3 之间，收到: {priority}"
    if importance < 1 or importance > 5:
        return f"❌ 重要度必须在 1-5 之间，收到: {importance}"
    if category not in VALID_CATEGORIES:
        return f"❌ 分类无效: {category}"
    if expires_at is not None and str(expires_at).strip() == "":
        expires_at = None
    try:
        mid = storage.add_memory(content=content, category=category, priority=priority,
                                 importance=importance, expires_at=expires_at, tags=tags)
        pl = PRI.get(priority, str(priority))
        return f"✅ 记忆 #{mid} 已添加 [{pl}/{category}]: {content}"
    except Exception as e:
        return f"❌ 添加失败: {e}"


def _m_list(storage, limit):
    """
    M list.

    Args:
        storage: Description.
        limit: Description.
    """
    try:
        memories = storage.get_active_memories(limit=limit)
        if not memories:
            return "📭 当前没有活跃的记忆。"
        stats = storage.get_memory_stats()
        lines = [f"🧠 活跃记忆: {stats['total']} 条 (指令:{stats['by_priority'].get(0,0)} 高:{stats['by_priority'].get(1,0)} 中:{stats['by_priority'].get(2,0)} 低:{stats['by_priority'].get(3,0)})", ""]
        for m in memories[:limit]:
            pl = PRI.get(m["priority"], str(m["priority"]))
            cat = m.get("category", "general")
            imp = "⭐" * m.get("importance", 3)
            exp = f" ⏳{m['expires_at']}" if m.get("expires_at") else ""
            lines.append(f"  #{m['id']} [{pl}/{cat}]{exp} {imp}")
            lines.append(f"     {m['content']}")
        if len(memories) > limit:
            lines.append(f"  ... 还有 {len(memories) - limit} 条未显示")
        return "\n".join(lines)
    except Exception as e:
        return f"❌ 列出失败: {e}"


def _m_search(storage, query, category, tags, min_importance, limit):
    """
    M search.

    Args:
        storage: Description.
        query: Description.
        category: Description.
        tags: Description.
        min_importance: Description.
        limit: Description.
    """
    try:
        tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else None
        results = storage.search_memories(query=query, category=category, tags=tag_list,
                                          min_importance=min_importance, limit=limit)
        if not results:
            return "📭 未找到匹配的记忆。"
        lines = [f"📋 找到 {len(results)} 条记忆:"]
        for m in results:
            pl = PRI.get(m["priority"], str(m["priority"]))
            exp = f" ⏳{m['expires_at']}" if m.get("expires_at") else ""
            cat = m.get("category", "general")
            lines.append(f"  #{m['id']} [{pl}/{cat}]{exp}: {m['content']}")
        return "\n".join(lines)
    except Exception as e:
        return f"❌ 搜索失败: {e}"


def _m_forget(storage, mid, hard):
    """
    M forget.

    Args:
        storage: Description.
        mid: Description.
        hard: Description.
    """
    if not mid:
        return "❌ forget 操作需要 id 参数"
    try:
        if hard:
            ok = storage.delete_memory(mid)
            return f"🗑️ 记忆 #{mid} 已彻底删除。" if ok else f"❌ 记忆 #{mid} 不存在。"
        else:
            ok = storage.deactivate_memory(mid)
            return f"💤 记忆 #{mid} 已标记失效（软删除）。" if ok else f"❌ 记忆 #{mid} 不存在。"
    except Exception as e:
        return f"❌ 操作失败: {e}"


def _m_extract(storage, topic_id, max_chars):
    """
    M extract.

    Args:
        storage: Description.
        topic_id: Description.
        max_chars: Description.
    """
    try:
        unsummarized = storage.get_unsummarized_conversations(topic_id) if isinstance(topic_id, str) and topic_id else []
        if not unsummarized:
            return "📭 没有未摘要的对话可提取。可以手动使用 toolkit_memory(action='add', ...) 添加记忆。"
        lines = [f"📄 从 topic #{topic_id} 的 {len(unsummarized)} 条未摘要对话中提取:", ""]
        total_chars = 0
        for i, conv in enumerate(unsummarized):
            user = conv.get("user_msg", "")[:300]
            ai = conv.get("ai_msg", "")[:500]
            entry = f"--- 对话 {i+1} ---\n用户: {user}\n助手: {ai}\n"
            if total_chars + len(entry) > max_chars:
                lines.append(f"... 还有 {len(unsummarized) - i} 条对话因长度限制未显示")
                break
            lines.append(entry)
            total_chars += len(entry)
        lines.append("")
        lines.append("--- 请分析以上对话，识别值得长期保存的信息 ---")
        lines.append("使用 toolkit_memory(action='add', ...) 逐条添加记忆。")
        lines.append("分类参考: instruction(指令)/preference(偏好)/fact(事实)/reminder(提醒)/general(一般)")
        lines.append("优先级: 0=CRITICAL(必须遵循) 1=HIGH 2=MEDIUM 3=LOW")
        return "\n".join(lines)
    except Exception as e:
        return f"❌ 提取记忆文本失败: {e}"



def toolkit_memory(action: str, content: str = "", category: str = "general", priority: int = 2, importance: int = 3, expires_at: str = None, tags: str = "", id: int = 0, hard: bool = False, query: str = "", min_importance: int = 0, limit: int = 10, topic_id: int = -1, max_chars: int = 4000):
    """
    统一长期记忆管理入口。根据 action 执行不同操作：

    Args:
        action (str): Description.
        content (str): Description.
        category (str): Description.
        priority (int): Description.
        importance (int): Description.
        expires_at (str): Description.
        tags (str): Description.
        id (int): Description.
        hard (bool): Description.
        query (str): Description.
        min_importance (int): Description.
        limit (int): Description.
        topic_id (int): Description.
        max_chars (int): Description.
    """
    logger.info(f"toolkit_memory called: action={action!r}, content={repr(content)[:80]}, category={category!r}, priority={priority!r}, importance={importance!r}, expires_at={expires_at!r}, tags={tags!r}, id={id!r}, hard={hard!r}, query={repr(query)[:80]}, min_importance={min_importance!r}, limit={limit!r}, topic_id={topic_id!r}, max_chars={max_chars!r}")

    try:
        from tea_agent.store import get_storage
        storage = get_storage()
    except Exception as e:
        return f"❌ 无法连接存储: {e}"

    priority_labels = {0: "CRITICAL", 1: "HIGH", 2: "MEDIUM", 3: "LOW"}
    logger.info(f"toolkit_memory called: action={action!r}")

    try:
        from tea_agent.store import get_storage
        storage = get_storage()
    except Exception as e:
        return f"❌ 无法连接存储: {e}"

    handlers = {
        "add":    lambda: _m_add(storage, content, category, priority, importance, expires_at, tags),
        "list":   lambda: _m_list(storage, limit),
        "search": lambda: _m_search(storage, query, category, tags, min_importance, limit),
        "forget": lambda: _m_forget(storage, id, hard),
        "extract": lambda: _m_extract(storage, topic_id, max_chars),
    }
    handler = handlers.get(action)
    if handler is None:
        return f"❌ 未知 action: '{action}'，可选: add/list/search/forget/extract"
    return handler()
def meta_toolkit_memory() -> dict:
    """
    Meta toolkit memory

    Returns:
        dict: Description.
    """
    return {
        "type": "function",
        "function": {
            "name": "toolkit_memory",
            "description": "统一长期记忆管理。action: add(添加)/list(列出)/search(搜索)/forget(删除)/extract(提取对话)。add需content；forget需id；search可选query；list可选limit。",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["add", "list", "search", "forget", "extract"],
                        "description": "操作类型"
                    },
                    "content": {"type": "string", "description": "[add] 记忆内容，精简摘要"},
                    "category": {"type": "string", "enum": ["instruction", "preference", "fact", "reminder", "general"], "description": "[add/search] 分类", "default": "general"},
                    "priority": {"type": "integer", "description": "[add] 优先级 0-3，0=CRITICAL, 1=HIGH, 2=MEDIUM, 3=LOW", "default": 2},
                    "importance": {"type": "integer", "description": "[add] 重要度 1-5", "default": 3},
                    "expires_at": {"type": "string", "description": "[add] 过期时间 ISO datetime，null=永不过期"},
                    "tags": {"type": "string", "description": "[add/search] 逗号分隔标签"},
                    "id": {"type": "integer", "description": "[forget] 记忆ID"},
                    "hard": {"type": "boolean", "description": "[forget] 是否硬删除，默认false(软删除)", "default": False},
                    "query": {"type": "string", "description": "[search] 搜索关键词", "default": ""},
                    "min_importance": {"type": "integer", "description": "[search] 最低重要度 1-5", "default": 0},
                    "limit": {"type": "integer", "description": "[list/search] 返回数量上限", "default": 10},
                    "topic_id": {"type": "integer", "description": "[extract] topic ID，-1=当前活跃topic", "default": -1},
                    "max_chars": {"type": "integer", "description": "[extract] 返回文本最大字符数", "default": 4000},
                },
                "required": ["action"],
            },
        },
    }
