"""会话分叉（session fork）— 共享实现。

把「创建目标主题 → 复制会话记录 → 复制事件流 → 取血统」这套组合抽成唯一事实源，
避免 Web 端（跳转栏 #分叉）与 Agent 工具（toolkit_fork_session）各自实现而漂移。

## 边界语义

``boundary_conv_id`` 指定分叉点，语义为**包含该条**（``rowid <= boundary_rowid``）：
用户选中某条历史消息作为 tag 时，期望该 tag 及其之前的对话都进入分支。

## 标题策略

标题由调用方给定（本模块不拼前缀）：
- Web ``#分叉`` → ``#分叉: <描述>``（受 ``is_title_protected`` 保护，不被自动摘要覆盖）
- Agent 工具 → ``※ <title> ← <源标题>``
"""

from __future__ import annotations

import logging
import uuid

logger = logging.getLogger("session_fork")


__all__ = ["fork_session"]



def fork_session(
    storage,
    source_topic_id: str,
    title: str,
    boundary_conv_id: str = "",
) -> dict:
    """从源主题分叉出新主题（复制历史到边界为止）。

    Args:
        storage: Storage 实例
        source_topic_id: 源主题 ID（必须已存在）
        title: 新主题标题（由调用方决定前缀策略）
        boundary_conv_id: 边界会话 ID；空串 = 复制全部历史

    Returns:
        ``{"ok", "target_topic_id", "title", "source_topic_id",
        "copied", "events_copied", "lineage"}``；失败时含 ``"error"``。
    """
    if not source_topic_id:
        return {"ok": False, "error": "source_topic_id required"}

    try:
        src = storage.topics.get_topic(source_topic_id)
        if not src:
            return {"ok": False, "error": f"源主题不存在: {source_topic_id}"}

        target_id = uuid.uuid4().hex
        storage.topics.create_topic(title, topic_id=target_id)

        result = storage.conversations.fork_topic(
            source_topic_id=source_topic_id,
            target_topic_id=target_id,
            title=title,
            boundary_conv_id=boundary_conv_id or "",
        )
        if not result.get("ok", True):
            # fork_topic 失败（如重复 fork）→ 清理刚建的主题，避免留下空壳
            try:
                storage.topics.delete_topic(target_id)
            except Exception:
                logger.debug("清理空壳主题失败: %s", target_id, exc_info=True)
            result.setdefault("target_topic_id", target_id)
            return result

        # P2 事件溯源：复制事件流（按 boundary 截断）；失败隔离
        events_copied = 0
        try:
            events_copied = storage.events.fork_events(
                source_topic_id, target_id,
                boundary_conv_id=boundary_conv_id or "",
            )
        except Exception:
            logger.exception("fork_events failed (isolated)")

        try:
            lineage = storage.conversations.get_fork_lineage(target_id)
        except Exception:
            lineage = []

        result.update({
            "target_topic_id": target_id,
            "title": title,
            "source_topic_id": source_topic_id,
            "events_copied": events_copied,
            "lineage": lineage,
        })
        logger.info("fork_session: %s -> %s (boundary=%s, copied=%s)",
                    source_topic_id, target_id, boundary_conv_id or "-",
                    result.get("copied"))
        return result
    except Exception as e:
        logger.exception("fork_session failed")
        return {"ok": False, "error": str(e)}
