"""toolkit_fork_session — 会话分支工具（Session Fork）。

借鉴 DeepSeek Harness 的 fork 能力：从源 topic 复制全部对话到新 topic，
形成可独立实验的分支（fork lineage 记录在 conversations.fork_source_id + forks 表）。

用途：
- 对当前主题做"实验分支"，在不影响原对话的情况下尝试新方向
- 回滚实验：若分支失败，原主题不受影响
- 边界 fork：只复制到某个会话为止，之后的对话从分支重新开始

用法：
    toolkit_fork_session(source_topic_id="...", title="实验分支")
    # 返回新 topic_id，可用 toolkit_query_chat_history action=topic 查看分支内容
"""

import logging
import uuid

from tea_agent.store import get_storage

logger = logging.getLogger("toolkit")


def toolkit_fork_session(source_topic_id: str = "", title: str = "fork", boundary_conv_id: str = ""):
    """创建会话分支：复制源主题对话到新主题。

    Args:
        source_topic_id: 源主题 ID；为空时自动使用最近活跃主题
        title: 新分支主题标题
        boundary_conv_id: 边界会话 ID（可选）；非空时仅复制该会话之前的对话

    Returns:
        {"ok": bool, "target_topic_id": str, "title": str,
         "copied": int, "lineage": list, "error": str}
    """
    storage = get_storage()
    try:
        if not source_topic_id:
            # 自动定位最近活跃主题
            topics = storage.topics.list_topics(limit=1) if hasattr(storage.topics, "list_topics") else []
            if not topics:
                # 回退：从 conversations 找最近 topic
                rows = storage.conversations.get_recent_conversations("", limit=1) if False else []
                c = storage.conn.cursor()
                c.execute("SELECT topic_id FROM conversations ORDER BY stamp DESC LIMIT 1")
                row = c.fetchone()
                c.close()
                if not row:
                    return {"ok": False, "error": "无可用主题，请指定 source_topic_id"}
                source_topic_id = row["topic_id"]
            else:
                source_topic_id = topics[0].get("topic_id", "") if isinstance(topics[0], dict) else getattr(topics[0], "topic_id", "")

        if not source_topic_id:
            return {"ok": False, "error": "无法确定源主题，请指定 source_topic_id"}

        # 确认源主题存在
        src = storage.topics.get_topic(source_topic_id)
        if not src:
            return {"ok": False, "error": f"源主题不存在: {source_topic_id}"}

        # 创建目标主题
        target_id = uuid.uuid4().hex
        src_title = (src.get("title") if isinstance(src, dict) else getattr(src, "title", "")) or title
        new_title = f"※ {title} ← {src_title}" if title and title != "fork" else f"{src_title} (fork)"
        storage.topics.create_topic(new_title, topic_id=target_id)

        # 执行 fork 复制
        result = storage.conversations.fork_topic(
            source_topic_id=source_topic_id,
            target_topic_id=target_id,
            title=new_title,
            boundary_conv_id=boundary_conv_id or "",
        )

        # P2 事件溯源：复制事件流（message fork 时按 boundary 截断）
        events_copied = 0
        try:
            events_copied = storage.events.fork_events(
                source_topic_id,
                target_id,
                boundary_conv_id=boundary_conv_id or "",
            )
            result["events_copied"] = events_copied
        except Exception:
            logger.exception("fork_events failed (isolated)")
            result["events_copied"] = 0

        # 血统信息
        lineage = storage.conversations.get_fork_lineage(target_id)
        result["target_topic_id"] = target_id
        result["title"] = new_title
        result["source_topic_id"] = source_topic_id
        result["lineage"] = lineage
        logger.info(f"fork_session: {source_topic_id} → {target_id}, title={new_title}")
        return result
    except Exception as e:
        logger.exception("fork_session failed")
        return {"ok": False, "error": str(e)}


def meta_toolkit_fork_session() -> dict:
    """Meta toolkit fork session."""
    return {
        "type": "function",
        "function": {
            "description": "创建会话分支（Session Fork）：复制源主题全部对话到新主题，用于分支实验/回滚测试。借鉴 DeepSeek Harness fork 能力，fork lineage 持久化到 forks 表。支持边界 fork（只复制到某个会话为止）。",
            "name": "toolkit_fork_session",
            "parameters": {
                "type": "object",
                "properties": {
                    "source_topic_id": {
                        "type": "string",
                        "description": "源主题 ID；为空自动使用最近活跃主题",
                    },
                    "title": {
                        "type": "string",
                        "description": "新分支主题标题，默认 'fork'",
                        "default": "fork",
                    },
                    "boundary_conv_id": {
                        "type": "string",
                        "description": "边界会话 ID（可选）；非空时仅复制该会话之前的对话",
                    },
                },
                "required": [],
            },
        },
    }
