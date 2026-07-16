"""
Sub-agent Message Passing — 子 Agent 之间的消息传递渠道。

每个子 Agent 有独立收件箱（内存 dict）。
支持：发送消息、检查收件箱、父 Agent 轮询所有消息。

与 toolkit_subagent 配合使用：
  1. 子 Agent 在 system prompt 中获知自己的 agent_id
  2. 子 Agent 调用 toolkit_subagent_msg(action='send', ...) 发送消息
  3. 父 Agent 调用 toolkit_subagent_msg(action='poll') 收集所有消息
  4. 消息在下一轮 spawn 时注入上下文

使用场景：
  - 并行子 Agent 间的数据交换
  - 分工协作（A 发现信息 → 告诉 B → B 利用）
"""

import logging
import threading
from datetime import datetime

logger = logging.getLogger("toolkit.subagent_msg")

# ── 全局消息注册表 ────────────────────────────
_message_registry: dict[str, list[dict]] = {}
# 结构: {recipient_agent_id: [{"from": str, "text": str, "timestamp": str}, ...]}
_registry_lock = threading.Lock()


def toolkit_subagent_msg(
    action: str = "check_inbox",
    to: str = "",
    message: str = "",
    agent_id: str = "",
    limit: int = 50,
) -> dict:
    """
    子 Agent 消息传递工具 — 收/发/查消息。

    Args:
        action: send=发送, check_inbox=查收件箱, poll=父Agent轮询, clear=清空
        to: [send] 目标 agent ID
        message: [send] 消息文本内容
        agent_id: [check_inbox/clear] 要操作的 agent ID
        limit: 返回消息数上限

    Returns:
        操作结果 dict
    """
    if action == "send":
        return _send_message(to=to, message=message)
    elif action == "check_inbox":
        return _check_inbox(agent_id=agent_id, limit=limit)
    elif action == "poll":
        return _poll_all(limit=limit)
    elif action == "clear":
        return _clear_inbox(agent_id=agent_id)
    else:
        return {"error": f"Unknown action: {action}"}


def _send_message(to: str, message: str) -> dict:
    """发送消息到指定 agent 的收件箱。"""
    if not to:
        return {"error": "Missing 'to' (recipient agent_id)"}
    if not message:
        return {"error": "Missing 'message' content"}

    entry = {
        "from": "sender",  # 由注入时填充真实 sender
        "text": message,
        "timestamp": datetime.now().isoformat(),
        "read": False,
    }

    with _registry_lock:
        if to not in _message_registry:
            _message_registry[to] = []
        _message_registry[to].append(entry)

    logger.debug(f"Message sent to {to}: {message[:60]}...")
    return {"ok": True, "to": to, "message": f"Message sent to {to}"}


def _check_inbox(agent_id: str, limit: int = 50) -> dict:
    """检查指定 agent 的收件箱。"""
    if not agent_id:
        return {"error": "Missing agent_id"}

    with _registry_lock:
        messages = _message_registry.get(agent_id, [])
        # 标记为已读
        unread = [m for m in messages if not m.get("read")]
        for m in messages:
            m["read"] = True

    return {
        "ok": True,
        "agent_id": agent_id,
        "total": len(messages),
        "unread": len(unread),
        "messages": messages[-limit:],
    }


def _poll_all(limit: int = 50) -> dict:
    """父 Agent 轮询所有未读消息。"""
    with _registry_lock:
        all_unread = {}
        for aid, msgs in _message_registry.items():
            unread = [m for m in msgs if not m.get("read")]
            if unread:
                all_unread[aid] = unread[-limit:]

    count = sum(len(v) for v in all_unread.values())
    return {
        "ok": True,
        "total_unread": count,
        "agents_with_messages": len(all_unread),
        "messages": all_unread,
    }


def _clear_inbox(agent_id: str) -> dict:
    """清空指定 agent 的收件箱。"""
    if not agent_id:
        return {"error": "Missing agent_id"}

    with _registry_lock:
        count = len(_message_registry.get(agent_id, []))
        if agent_id in _message_registry:
            del _message_registry[agent_id]

    return {"ok": True, "agent_id": agent_id, "cleared": count}


# ── 供 toolkit_subagent 内部使用 ──────────────


def inject_messages_into_context(agent_id: str, context: dict | None = None) -> dict:
    """从收件箱提取消息并注入到上下文中。

    被 _execute_subagent 调用，在子 Agent 启动前提取等它的消息。
    """
    with _registry_lock:
        messages = _message_registry.get(agent_id, [])
        unread = [m for m in messages if not m.get("read")]
        # 标记为已读
        for m in messages:
            m["read"] = True

    if not unread:
        return context or {}

    # 构建消息摘要
    msg_text = "\n\n".join([
        f"[From: {m.get('from', 'unknown')} @ {m.get('timestamp', '?')}]\n{m.get('text', '')}"
        for m in unread
    ])

    inbox_context = {"## Incoming Messages": msg_text}

    if context:
        merged = dict(context)
        merged.update(inbox_context)
        return merged
    return inbox_context


def send_message_as(from_agent: str, to: str, text: str) -> bool:
    """以 from_agent 名义发送消息。"""
    if not to:
        return False
    entry = {
        "from": from_agent,
        "text": text,
        "timestamp": datetime.now().isoformat(),
        "read": False,
    }
    with _registry_lock:
        if to not in _message_registry:
            _message_registry[to] = []
        _message_registry[to].append(entry)
    return True


def get_message_stats() -> dict:
    """获取消息统计（用于持久化）。"""
    with _registry_lock:
        return {
            aid: len(msgs)
            for aid, msgs in _message_registry.items()
        }


# ── Meta ──────────────────────────────────────


def meta_toolkit_subagent_msg() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "toolkit_subagent_msg",
            "description": "Sub-agent message passing. Send/receive/check messages between sub-agents. Use 'send' to send a message to another agent by ID, 'check_inbox' to read your own inbox, 'poll' for parent to collect all pending messages.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["send", "check_inbox", "poll", "clear"],
                        "description": "send=send message to agent, check_inbox=read your inbox, poll=parent collects all, clear=clear inbox"
                    },
                    "to": {
                        "type": "string",
                        "description": "[send] Target agent ID"
                    },
                    "message": {
                        "type": "string",
                        "description": "[send] Message text content"
                    },
                    "agent_id": {
                        "type": "string",
                        "description": "[check_inbox/clear] Your agent ID"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max messages to return",
                        "default": 50
                    }
                },
                "required": ["action"]
            }
        }
    }
