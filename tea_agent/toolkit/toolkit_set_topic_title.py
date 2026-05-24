import logging

logger = logging.getLogger("toolkit")

def toolkit_set_topic_title(title: str) -> dict:
    """
    手动设置当前主题的标题。设置后标题显示为 "※{title}"，
    且该主题将不再自动生成摘要标题。

    Args:
        title: 新的主题标题（不含※前缀，会自动添加）

    Returns:
        {"ok": True, "title": "※...", "topic_id": int} 或 {"error": str}
    """
    logger.info(f"toolkit_set_topic_title called: title={title!r}")

    try:
        from tea_agent.session_ref import get_agent
    except ImportError:
        return {"error": "session_ref 模块不可用"}

    agent = get_agent()
    if agent is not None:
        topic_id = agent.current_topic_id
    else:
        try:
            from tea_agent.store import get_storage
            s = get_storage()
            topics = s.list_topics()
            topic_id = topics[0]["topic_id"] if topics else ""
        except Exception:
            topic_id = ""

    if not topic_id:
        return {"error": "当前无活跃主题"}

    new_title = f"※{title}"
    try:
        if agent is not None:
            agent.db.update_topic_title(topic_id, new_title)
        else:
            from tea_agent.store import get_storage
            get_storage().update_topic_title(topic_id, new_title)
    except Exception as e:
        logger.warning(f"更新主题标题失败: {e}")
        return {"error": f"数据库更新失败: {e}"}

    try:
        if hasattr(agent, '_on_summary_updated'):
            agent._on_summary_updated(topic_id, new_title)
    except Exception:
        pass

    logger.info(f"主题标题已手动设置: topic={topic_id} → {new_title}")
    return {"ok": True, "title": new_title, "topic_id": topic_id}

def meta_toolkit_set_topic_title():
    """Meta toolkit set topic title"""
    return {
        "type": "function",
        "function": {
            "name": "toolkit_set_topic_title",
            "description": "手动设置当前主题的标题。设置后标题显示为「※自定义标题」，该主题将不再自动生成摘要。",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "新的主题标题（不含※前缀，系统会自动添加），建议不超过20字"
                    }
                },
                "required": ["title"]
            }
        }
    }
