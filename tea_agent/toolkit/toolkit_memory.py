# @2026-04-29 gen by deepseek-v4-pro, 合并5个memory工具为一个统一入口
# version: 1.0.0

def toolkit_memory(action: str, content: str = "", category: str = "general", priority: int = 2, importance: int = 3, expires_at: str = None, tags: str = "", id: int = 0, hard: bool = False, query: str = "", min_importance: int = 0, limit: int = 10, topic_id: int = -1, max_chars: int = 4000):
    """
    统一长期记忆管理入口。根据 action 执行不同操作：

    - "add": 添加一条记忆。需 content。可选 category/priority/importance/expires_at/tags。
      分类: instruction(有效指令)/preference(用户偏好)/fact(技术事实)/reminder(提醒)/general(一般)
      优先级: 0=CRITICAL, 1=HIGH, 2=MEDIUM, 3=LOW。重要度: 1-5。
    - "list": 列出当前活跃记忆。可选 limit（默认20）。
    - "search": 搜索记忆。可选 query/category/tags/min_importance/limit。
    - "forget": 删除/失效记忆。需 id。可选 hard（true=硬删除, false=软删除）。
    - "extract": 从对话中提取待分析文本。可选 topic_id/max_chars。
    """
    try:
        from tea_agent.store import get_storage
        storage = get_storage()
    except Exception as e:
        return f"❌ 无法连接存储: {e}"

    priority_labels = {0: "CRITICAL", 1: "HIGH", 2: "MEDIUM", 3: "LOW"}

    # ── action: add ──
    if action == "add":
        if not content:
            return "❌ add 操作需要 content 参数"
        if priority < 0 or priority > 3:
            return f"❌ 优先级必须在 0-3 之间，收到: {priority}"
        if importance < 1 or importance > 5:
            return f"❌ 重要度必须在 1-5 之间，收到: {importance}"
        if category not in ("instruction", "preference", "fact", "reminder", "general"):
            return f"❌ 分类无效: {category}"
        if expires_at is not None and str(expires_at).strip() == "":
            expires_at = None
        try:
            mid = storage.add_memory(content=content, category=category, priority=priority,
                                     importance=importance, expires_at=expires_at, tags=tags)
            pl = priority_labels.get(priority, str(priority))
            return f"✅ 记忆 #{mid} 已添加 [{pl}/{category}]: {content}"
        except Exception as e:
            return f"❌ 添加失败: {e}"

    # ── action: list ──
    elif action == "list":
        try:
            memories = storage.get_active_memories(limit=limit)
            if not memories:
                return "📭 当前没有活跃的记忆。"
            stats = storage.get_memory_stats()
            lines = [f"🧠 活跃记忆: {stats['total']} 条 (指令:{stats['by_priority'].get(0,0)} 高:{stats['by_priority'].get(1,0)} 中:{stats['by_priority'].get(2,0)} 低:{stats['by_priority'].get(3,0)})", ""]
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
            return f"❌ 列出失败: {e}"

    # ── action: search ──
    elif action == "search":
        try:
            tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else None
            results = storage.search_memories(query=query, category=category, tags=tag_list,
                                              min_importance=min_importance, limit=limit)
            if not results:
                return "📭 未找到匹配的记忆。"
            lines = [f"📋 找到 {len(results)} 条记忆:"]
            for m in results:
                pl = priority_labels.get(m["priority"], str(m["priority"]))
                exp = f" ⏳{m['expires_at']}" if m.get("expires_at") else ""
                cat = m.get("category", "general")
                lines.append(f"  #{m['id']} [{pl}/{cat}]{exp}: {m['content']}")
            return "\n".join(lines)
        except Exception as e:
            return f"❌ 搜索失败: {e}"

    # ── action: forget ──
    elif action == "forget":
        if not id:
            return "❌ forget 操作需要 id 参数"
        try:
            if hard:
                ok = storage.delete_memory(id)
                return f"🗑️ 记忆 #{id} 已彻底删除。" if ok else f"❌ 记忆 #{id} 不存在。"
            else:
                ok = storage.deactivate_memory(id)
                return f"💤 记忆 #{id} 已标记失效（软删除）。" if ok else f"❌ 记忆 #{id} 不存在。"
        except Exception as e:
            return f"❌ 操作失败: {e}"

    # ── action: extract ──
    elif action == "extract":
        try:
            unsummarized = storage.get_unsummarized_conversations(topic_id) if topic_id > 0 else []
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

    else:
        return f"❌ 未知 action: '{action}'，可选: add/list/search/forget/extract"


def meta_toolkit_memory() -> dict:
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
