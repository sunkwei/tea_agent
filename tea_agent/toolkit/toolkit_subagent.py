"""
Sub-agent Generation System v2.1 — 隔离上下文窗口 + 消息传递 + 持久化 + 权限控制

v2.1 新增（Phase 1）:
  - 消息传递: 子 Agent 可通过 toolkit_subagent_msg 互相通信
  - 收件箱注入: 启动子 Agent 时自动注入等它的消息
  - 持久化: sub-agent 状态写入 chat_history.db，崩溃可恢复
  - 权限控制: allowed_tools / denied_tools 参数已废弃（自由奔放模式）
  - Auto-wake: 子 Agent 完成自动通知父 Agent 下次会话

核心设计：
  每个 sub-agent 有独立的 LiteSession，不污染父 agent 的上下文窗口。
  支持同步/异步、并发、状态查询、结果收集、上下文注入。
"""

import json
import logging
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

logger = logging.getLogger("toolkit.subagent")

# ── 全局子 agent 注册表 ────────────────────────────
_subagent_registry: dict[str, dict] = {}
_registry_lock = threading.Lock()
_executor = ThreadPoolExecutor(max_workers=5, thread_name_prefix="subagent")

# 自动唤醒通知: {parent_session_id: [sub_agent_id, ...]}
_pending_notifications: dict[str, list[str]] = {}
_notification_lock = threading.Lock()

# ── 持久化 ──────────────────────────────────────────
_PERSIST_TABLE = "subagent_registry"
_persist_loaded = False


def _get_db():
    """获取数据库连接（延迟初始化）。"""
    try:
        from tea_agent.store.localstore import get_or_create_localstore
        store = get_or_create_localstore()
        return store.db if hasattr(store, 'db') else None
    except Exception:
        return None


def _save_to_db():
    """将注册表持久化到数据库。"""
    db = _get_db()
    if not db:
        return False
    try:
        with _registry_lock:
            data = {
                aid: {k: v for k, v in entry.items() if k != 'future'}
                for aid, entry in _subagent_registry.items()
            }
        blob = json.dumps(data, ensure_ascii=False, default=str)
        # upsert
        db.execute(
            f"INSERT OR REPLACE INTO {_PERSIST_TABLE} (key, value, updated_at) VALUES (?, ?, ?)",
            ("registry", blob, datetime.now().isoformat())
        )
        db.commit()
        return True
    except Exception as e:
        logger.warning(f"Save subagent registry to DB failed: {e}")
        return False


def _load_from_db():
    """从数据库恢复注册表。"""
    global _persist_loaded
    if _persist_loaded:
        return True
    db = _get_db()
    if not db:
        return False
    try:
        # 确保表存在
        db.execute(
            f"CREATE TABLE IF NOT EXISTS {_PERSIST_TABLE} ("
            "key TEXT PRIMARY KEY, value TEXT, updated_at TEXT)"
        )
        db.commit()

        row = db.execute(
            f"SELECT value FROM {_PERSIST_TABLE} WHERE key=?", ("registry",)
        ).fetchone()
        if row and row[0]:
            data = json.loads(row[0])
            with _registry_lock:
                for aid, entry in data.items():
                    if aid not in _subagent_registry:
                        _subagent_registry[aid] = entry
            logger.info(f"Restored {len(data)} subagents from DB")
        _persist_loaded = True
        return True
    except Exception as e:
        logger.warning(f"Load subagent registry from DB failed: {e}")
        _persist_loaded = True  # 防止重复尝试
        return False


def _add_notification(sub_agent_id: str, parent_session_id: str | None = None):
    """添加自动唤醒通知。"""
    with _notification_lock:
        key = parent_session_id or "_default"
        if key not in _pending_notifications:
            _pending_notifications[key] = []
        _pending_notifications[key].append(sub_agent_id)


def check_notifications(session_id: str = "") -> dict:
    """检查指定 session 的自动唤醒通知。

    被父 Agent 调用，在每次工具调用前检查。
    """
    with _notification_lock:
        key = session_id or "_default"
        notifications = _pending_notifications.pop(key, [])
    if not notifications:
        return {"notifications": [], "count": 0}
    details = []
    with _registry_lock:
        for aid in notifications:
            entry = _subagent_registry.get(aid, {})
            details.append({
                "agent_id": aid,
                "status": entry.get("status", "unknown"),
                "goal": entry.get("goal", ""),
                "result": (entry.get("result") or "")[:200],
                "error": entry.get("error"),
            })
    return {"notifications": details, "count": len(details)}


def _generate_agent_id() -> str:
    """生成唯一 agent ID。"""
    return f"sub-{uuid.uuid4().hex[:8]}"


def _ensure_toolkit_loaded():
    """确保 toolkit_subagent_msg 已注册到全局 toolkit。"""
    try:
        from tea_agent import tlk
        if not hasattr(tlk, 'toolkit') or tlk.toolkit is None:
            return
        if "toolkit_subagent_msg" not in tlk.toolkit.func_map:
            from tea_agent.toolkit.toolkit_subagent_msg import (
                meta_toolkit_subagent_msg,
                toolkit_subagent_msg,
            )
            tlk.toolkit.register(
                "toolkit_subagent_msg",
                toolkit_subagent_msg,
                meta_toolkit_subagent_msg(),
            )
            logger.debug("toolkit_subagent_msg registered to global toolkit")
    except Exception as e:
        logger.debug(f"Cannot register toolkit_subagent_msg: {e}")


def _execute_subagent(
    agent_id: str,
    goal: str,
    context: dict[str, str] | None,
    max_iterations: int,
    enable_thinking: bool,
    timeout: int,
    allowed_tools: list[str] | None = None,
    denied_tools: list[str] | None = None,
    parent_session_id: str | None = None,
) -> dict:
    """在隔离线程中执行子 agent。"""
    from tea_agent import tlk
    from tea_agent.config import load_config
    from tea_agent.litesession import LiteSession
    from tea_agent.toolkit.toolkit_subagent_msg import inject_messages_into_context

    start = time.time()
    try:
        # 标记为运行中
        with _registry_lock:
            if agent_id in _subagent_registry:
                _subagent_registry[agent_id]["status"] = "running"
                _subagent_registry[agent_id]["started_at"] = datetime.now().isoformat()
                _save_to_db()

        # 获取 toolkit 和配置
        toolkit = tlk.toolkit
        cfg = load_config()
        main_m = cfg.main_model

        # 检查收件箱，注入等它的消息
        merged_context = inject_messages_into_context(agent_id, context)

        # 构建注入上下文的任务描述
        enriched_goal = goal
        if merged_context:
            context_parts = []
            for key, value in merged_context.items():
                context_parts.append(f"{key}\n{value}")
            enriched_goal = "\n\n".join(context_parts) + f"\n\n## Current Task\n{goal}"

        # 构建系统提示 — 包含 agent_id 以便消息传递
        system_prompt = f"""You are a Sub-Agent generated by Tea Agent. You have an isolated context window and full access to tools.

## Your Identity
- Agent ID: {agent_id}
- You can communicate with other agents using toolkit_subagent_msg

## Task
{goal}

## Rules
1. You have your own conversation history, fully isolated from the parent agent
2. Use tools independently - do not ask for permission
3. After completing the task, return a concise result summary
4. If you encounter an error, try once to fix it; if still failing, report the error
5. To send information to another agent, use toolkit_subagent_msg(action='send', to='sub-xxxx', message='...')
6. To check your incoming messages, use toolkit_subagent_msg(action='check_inbox', agent_id='{agent_id}')
7. Do not output unnecessary text, only do what is needed"""

        # 创建独立的 LiteSession（隔离上下文窗口的关键）
        sess = LiteSession(
            toolkit=toolkit,
            api_key=str(main_m.api_key or ""),
            api_url=str(main_m.api_url or ""),
            model=str(main_m.model_name or ""),
            system_prompt=system_prompt,
            enable_thinking=enable_thinking,
            max_iterations=max_iterations,
            allowed_tools=allowed_tools,
            denied_tools=denied_tools,
        )

        # 执行
        result = sess.chat(enriched_goal)

        elapsed = round(time.time() - start, 2)
        assistant = result.get("assistant", "")
        tool_calls = result.get("tool_calls", 0)
        error = result.get("error")

        # 更新注册表
        with _registry_lock:
            if agent_id in _subagent_registry:
                _subagent_registry[agent_id].update({
                    "status": "completed" if not error else "failed",
                    "result": assistant,
                    "error": error,
                    "tool_calls": tool_calls,
                    "elapsed": elapsed,
                    "completed_at": datetime.now().isoformat(),
                })
                _save_to_db()

        # Auto-wake: 通知父 Agent
        if parent_session_id:
            _add_notification(agent_id, parent_session_id)

        logger.info(f"Sub-agent {agent_id} completed ({elapsed:.1f}s, {tool_calls} tools)")
        return {"agent_id": agent_id, "status": "completed" if not error else "failed",
                "result": assistant, "elapsed": elapsed}

    except Exception as e:
        elapsed = round(time.time() - start, 2)
        logger.error(f"Sub-agent {agent_id} failed: {e}")
        with _registry_lock:
            if agent_id in _subagent_registry:
                _subagent_registry[agent_id].update({
                    "status": "failed",
                    "error": str(e),
                    "elapsed": elapsed,
                    "completed_at": datetime.now().isoformat(),
                })
                _save_to_db()

        # Auto-wake: 即使失败也通知
        if parent_session_id:
            _add_notification(agent_id, parent_session_id)

        return {"agent_id": agent_id, "status": "failed", "error": str(e), "elapsed": elapsed}


def toolkit_subagent(
    action: str = "list",
    goal: str = "",
    context: dict[str, str] | None = None,
    max_iterations: int = 20,
    enable_thinking: bool = False,
    timeout: int = 120,
    max_concurrent: int = 5,
    agent_id: str = "",
    allowed_tools: list[str] | None = None,
    denied_tools: list[str] | None = None,
    parent_session_id: str | None = None,
) -> dict:
    """
    Sub-agent Generation System v2.1 — Isolated context window sub-agent management.

    Each sub-agent has an independent LiteSession, isolated from the parent agent's context.

    Args:
        action: spawn/spawn_sync/list/status/collect/cancel
        goal: Sub-agent task description
        context: Injected context dict (key=title, value=content)
        max_iterations: Max tool iterations, default 20
        enable_thinking: Enable reasoning, default False
        timeout: Timeout in seconds, default 120
        max_concurrent: Max concurrent sub-agents, default 5
        agent_id: Sub-agent ID (for status/cancel)
        allowed_tools: [DEPRECATED] List of allowed tool names (None=all allowed)
        denied_tools: [DEPRECATED] List of denied tool names (none denied)
        parent_session_id: Parent session ID for auto-wake notifications

    Returns:
        Operation result dict
    """
    global _executor

    # 确保 msg 工具已注册
    try:
        _ensure_toolkit_loaded()
    except Exception:
        pass

    # 尝试从 DB 恢复（仅在首次调用时）
    try:
        _load_from_db()
    except Exception:
        pass

    if action == "spawn":
        """Async spawn sub-agent (fire-and-forget)."""
        if not goal:
            return {"error": "goal parameter is required"}

        agent_id = _generate_agent_id()
        entry = {
            "agent_id": agent_id,
            "goal": goal[:80],
            "status": "pending",
            "created_at": datetime.now().isoformat(),
            "started_at": None,
            "completed_at": None,
            "result": None,
            "error": None,
            "tool_calls": 0,
            "elapsed": None,
            "allowed_tools": allowed_tools,
            "denied_tools": denied_tools,
        }

        with _registry_lock:
            _subagent_registry[agent_id] = entry
            _save_to_db()

        # 提交到线程池
        future = _executor.submit(
            _execute_subagent, agent_id, goal, context,
            max_iterations, enable_thinking, timeout,
            allowed_tools, denied_tools, parent_session_id,
        )

        with _registry_lock:
            _subagent_registry[agent_id]["future"] = future

        return {
            "agent_id": agent_id,
            "status": "pending",
            "message": f"Sub-agent {agent_id} created (async)",
        }

    elif action == "spawn_sync":
        """Sync spawn sub-agent (block until complete)."""
        if not goal:
            return {"error": "goal parameter is required"}

        agent_id = _generate_agent_id()
        entry = {
            "agent_id": agent_id,
            "goal": goal[:80],
            "status": "running",
            "created_at": datetime.now().isoformat(),
            "started_at": datetime.now().isoformat(),
            "completed_at": None,
            "result": None,
            "error": None,
            "tool_calls": 0,
            "elapsed": None,
            "allowed_tools": allowed_tools,
            "denied_tools": denied_tools,
        }

        with _registry_lock:
            _subagent_registry[agent_id] = entry
            _save_to_db()

        result = _execute_subagent(
            agent_id, goal, context, max_iterations,
            enable_thinking, timeout,
            allowed_tools, denied_tools, parent_session_id,
        )
        return result

    elif action == "status":
        """Query sub-agent status."""
        if agent_id:
            with _registry_lock:
                entry = _subagent_registry.get(agent_id)
            if not entry:
                return {"error": f"Sub-agent not found: {agent_id}"}
            return {
                "agent_id": entry["agent_id"],
                "goal": entry["goal"],
                "status": entry["status"],
                "result": (entry.get("result") or "")[:200],
                "error": entry.get("error"),
                "tool_calls": entry.get("tool_calls", 0),
                "elapsed": entry.get("elapsed"),
                "created_at": entry.get("created_at"),
                "started_at": entry.get("started_at"),
                "completed_at": entry.get("completed_at"),
                "allowed_tools": entry.get("allowed_tools"),
                "denied_tools": entry.get("denied_tools"),
            }

        # Return all statuses
        with _registry_lock:
            results = [
                {
                    "agent_id": eid,
                    "goal": entry.get("goal", ""),
                    "status": entry.get("status", "unknown"),
                    "tool_calls": entry.get("tool_calls", 0),
                    "elapsed": entry.get("elapsed"),
                }
                for eid, entry in _subagent_registry.items()
            ]
        return {"agents": results, "total": len(results)}

    elif action == "list":
        """List all sub-agents."""
        with _registry_lock:
            agents = [
                {
                    "agent_id": aid,
                    "goal": entry.get("goal", ""),
                    "status": entry.get("status", "unknown"),
                    "tool_calls": entry.get("tool_calls", 0),
                    "elapsed": entry.get("elapsed"),
                    "created_at": entry.get("created_at", ""),
                }
                for aid, entry in _subagent_registry.items()
            ]
        agents.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return {"agents": agents, "total": len(agents)}

    elif action == "collect":
        """Collect all completed results."""
        with _registry_lock:
            completed = [
                {
                    "agent_id": eid,
                    "goal": entry.get("goal", ""),
                    "status": entry.get("status"),
                    "result": entry.get("result", ""),
                    "error": entry.get("error"),
                    "tool_calls": entry.get("tool_calls", 0),
                    "elapsed": entry.get("elapsed"),
                }
                for eid, entry in _subagent_registry.items()
                if entry.get("status") in ("completed", "failed")
            ]
        return {
            "agents": completed,
            "total": len(completed),
            "message": f"{len(completed)} sub-agents completed",
        }

    elif action == "cancel":
        """Cancel a sub-agent."""
        if not agent_id:
            return {"error": "agent_id parameter is required"}

        with _registry_lock:
            entry = _subagent_registry.get(agent_id)
            if not entry:
                return {"error": f"Sub-agent not found: {agent_id}"}
            if entry.get("status") not in ("pending", "running"):
                return {"agent_id": agent_id, "status": entry["status"],
                        "message": "Sub-agent already finished"}

            future = entry.get("future")
            if future and not future.done():
                cancelled = future.cancel()
                entry["status"] = "cancelled"
                entry["completed_at"] = datetime.now().isoformat()
                _save_to_db()
                return {"agent_id": agent_id, "status": "cancelled", "cancelled": cancelled}

            entry["status"] = "cancelled"
            entry["completed_at"] = datetime.now().isoformat()
            _save_to_db()
            return {"agent_id": agent_id, "status": "cancelled"}

    elif action == "check_notifications":
        """Check auto-wake notifications for a session."""
        return check_notifications(session_id=parent_session_id or "")

    elif action == "cleanup":
        """Remove old completed sub-agents from registry."""
        with _registry_lock:
            before = len(_subagent_registry)
            to_remove = [
                aid for aid, entry in _subagent_registry.items()
                if entry.get("status") in ("completed", "failed", "cancelled")
            ]
            for aid in to_remove:
                del _subagent_registry[aid]
            _save_to_db()
        return {"removed": len(to_remove), "remaining": before - len(to_remove)}

    return {"error": f"Unknown action: {action}"}


# ── Meta ──────────────────────────────────────


def meta_toolkit_subagent() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "toolkit_subagent",
            "description": "Sub-agent generation system v2.1. Each sub-agent has an independent LiteSession, isolated from parent context. Supports sync/async spawn, concurrency, status query, result collection, context injection, tool permissions, and inter-agent messaging.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["spawn", "spawn_sync", "list", "status", "collect", "cancel", "check_notifications", "cleanup"],
                        "description": "spawn=async, spawn_sync=sync blocking, list=all agents, status=query one, collect=completed results, cancel=stop, check_notifications=auto-wake check, cleanup=remove old"
                    },
                    "goal": {
                        "type": "string",
                        "description": "[spawn/spawn_sync] Sub-agent task description"
                    },
                    "context": {
                        "type": "object",
                        "description": "[spawn/spawn_sync] Injected context dict (key=title, value=content)"
                    },
                    "max_iterations": {
                        "type": "integer",
                        "description": "Max tool iterations",
                        "default": 20
                    },
                    "enable_thinking": {
                        "type": "boolean",
                        "description": "Enable reasoning",
                        "default": False
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Timeout in seconds",
                        "default": 120
                    },
                    "max_concurrent": {
                        "type": "integer",
                        "description": "Max concurrent agents",
                        "default": 5
                    },
                    "agent_id": {
                        "type": "string",
                        "description": "[status/cancel] Sub-agent ID"
                    },
                    "allowed_tools": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "[spawn/spawn_sync] Allowed tool names (None=all allowed)"
                    },
                    "denied_tools": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "[spawn/spawn_sync] Denied tool names (None=none denied)"
                    },
                    "parent_session_id": {
                        "type": "string",
                        "description": "[spawn/spawn_sync] Parent session ID for auto-wake notifications"
                    },
                },
                "required": ["action"],
            },
        },
    }
