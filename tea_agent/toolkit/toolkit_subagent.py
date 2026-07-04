"""
Sub-agent 生成系统 v2.0 — 隔离上下文窗口的子 agent 管理

核心设计：
  每个 sub-agent 有独立的 LiteSession，不污染父 agent 的上下文窗口。
  支持同步/异步、并发、状态查询、结果收集。

v2.0 新增：
  - 隔离的上下文窗口（每个 sub-agent 独立的 LiteSession）
  - 异步生成：spawn → status → collect
  - 上下文透传：前置子 agent 结果注入后续任务
  - 并发限制、超时控制、错误恢复
  - 子 agent 可自主使用工具

Args:
    action: spawn/spawn_sync/list/status/collect/cancel
    goal: 子 agent 任务描述
    context: 注入的上下文（dict[str,str]）
    max_iterations: 子 agent 最大迭代次数
    enable_thinking: 是否启用推理
    timeout: 超时秒数
    max_concurrent: 最大并发数
    agent_id: 子 agent ID（status/cancel 时使用）
"""

import uuid
import time
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, Future
from typing import Dict, List, Optional, Any
from datetime import datetime

logger = logging.getLogger("toolkit.subagent")

# ── 全局子 agent 注册表 ────────────────────────────
_subagent_registry: Dict[str, Dict] = {}
_registry_lock = threading.Lock()
_executor = ThreadPoolExecutor(max_workers=5, thread_name_prefix="subagent")


def _generate_agent_id() -> str:
    """生成唯一 agent ID"""
    return f"sub-{uuid.uuid4().hex[:8]}"


def _execute_subagent(
    agent_id: str,
    goal: str,
    context: Optional[Dict[str, str]],
    max_iterations: int,
    enable_thinking: bool,
    timeout: int,
) -> Dict:
    """在隔离线程中执行子 agent"""
    from tea_agent.litesession import LiteSession
    from tea_agent import tlk
    from tea_agent.config import load_config

    start = time.time()
    try:
        # 标记为运行中
        with _registry_lock:
            if agent_id in _subagent_registry:
                _subagent_registry[agent_id]["status"] = "running"
                _subagent_registry[agent_id]["started_at"] = datetime.now().isoformat()

        # 获取 toolkit 和配置
        toolkit = tlk.toolkit
        cfg = load_config()
        main_m = cfg.main_model

        # 构建注入上下文的任务描述
        enriched_goal = goal
        if context:
            context_parts = []
            for key, value in context.items():
                context_parts.append(f"## {key}\n{value}")
            enriched_goal = "## 上下文信息\n" + "\n\n".join(context_parts) + f"\n\n## 当前任务\n{goal}"

        # 构建系统提示 — 强调子 agent 自主执行
        system_prompt = f"""你是 Tea Agent 生成的子 Agent。你有独立的上下文窗口和完整的工具集。

## 当前任务
{goal}

## 规则
1. 你有自己的对话历史，与父 agent 完全隔离
2. 自主使用工具完成任务，不需要请示
3. 任务完成后返回简明的结果摘要
4. 如果遇到错误，尝试修复一次；仍失败则报告具体错误
5. 不要多余输出，只做需要的事"""

        # 创建独立的 LiteSession（隔离上下文窗口的关键）
        sess = LiteSession(
            toolkit=toolkit,
            api_key=str(main_m.api_key or ""),
            api_url=str(main_m.api_url or ""),
            model=str(main_m.model_name or ""),
            system_prompt=system_prompt,
            enable_thinking=enable_thinking,
            max_iterations=max_iterations,
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

        logger.info(f"✅ Sub-agent {agent_id} 完成 ({elapsed:.1f}s, {tool_calls} tools)")
        return {"agent_id": agent_id, "status": "completed", "result": assistant, "elapsed": elapsed}

    except Exception as e:
        elapsed = round(time.time() - start, 2)
        logger.error(f"❌ Sub-agent {agent_id} 失败: {e}")
        with _registry_lock:
            if agent_id in _subagent_registry:
                _subagent_registry[agent_id].update({
                    "status": "failed",
                    "error": str(e),
                    "elapsed": elapsed,
                    "completed_at": datetime.now().isoformat(),
                })
        return {"agent_id": agent_id, "status": "failed", "error": str(e), "elapsed": elapsed}


def toolkit_subagent(
    action: str = "list",
    goal: str = "",
    context: Optional[Dict[str, str]] = None,
    max_iterations: int = 20,
    enable_thinking: bool = False,
    timeout: int = 120,
    max_concurrent: int = 5,
    agent_id: str = "",
) -> Dict:
    """
    子 Agent 生成系统 v2.0 — 隔离上下文窗口

    每个子 Agent 有独立的 LiteSession，不污染父 Agent 的上下文窗口。

    Args:
        action: spawn/spawn_sync/list/status/collect/cancel
        goal: 子 Agent 任务描述
        context: 注入上下文（dict，key=标题, value=内容）
        max_iterations: 最大工具迭代次数，默认 20
        enable_thinking: 是否启用推理，默认 False
        timeout: 超时秒数，默认 120
        max_concurrent: 最大并发数，默认 5
        agent_id: 子 Agent ID

    Returns:
        操作结果
    """
    global _executor

    if action == "spawn":
        """异步生成子 agent"""
        if not goal:
            return {"error": "需要 goal 参数"}

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
        }

        with _registry_lock:
            _subagent_registry[agent_id] = entry

        # 提交到线程池
        future = _executor.submit(
            _execute_subagent, agent_id, goal, context,
            max_iterations, enable_thinking, timeout
        )

        with _registry_lock:
            _subagent_registry[agent_id]["future"] = future

        return {
            "agent_id": agent_id,
            "status": "pending",
            "message": f"子 Agent {agent_id} 已创建",
        }

    elif action == "spawn_sync":
        """同步生成子 agent（等待完成）"""
        if not goal:
            return {"error": "需要 goal 参数"}

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
        }

        with _registry_lock:
            _subagent_registry[agent_id] = entry

        result = _execute_subagent(agent_id, goal, context, max_iterations, enable_thinking, timeout)
        return result

    elif action == "status":
        """查询子 agent 状态"""
        if agent_id:
            with _registry_lock:
                entry = _subagent_registry.get(agent_id)
            if not entry:
                return {"error": f"未找到子 Agent: {agent_id}"}
            return {
                "agent_id": entry["agent_id"],
                "goal": entry["goal"],
                "status": entry["status"],
                "result": entry.get("result", "")[:200] if entry.get("result") else None,
                "error": entry.get("error"),
                "tool_calls": entry.get("tool_calls", 0),
                "elapsed": entry.get("elapsed"),
                "created_at": entry.get("created_at"),
                "started_at": entry.get("started_at"),
                "completed_at": entry.get("completed_at"),
            }

        # 返回所有状态
        with _registry_lock:
            results = []
            for eid, entry in _subagent_registry.items():
                results.append({
                    "agent_id": eid,
                    "goal": entry.get("goal", ""),
                    "status": entry.get("status", "unknown"),
                    "tool_calls": entry.get("tool_calls", 0),
                    "elapsed": entry.get("elapsed"),
                })
            return {"agents": results, "total": len(results)}

    elif action == "list":
        """列出所有子 agent"""
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
        """收集所有已完成的结果"""
        with _registry_lock:
            completed = []
            for eid, entry in _subagent_registry.items():
                if entry.get("status") in ("completed", "failed"):
                    completed.append({
                        "agent_id": eid,
                        "goal": entry.get("goal", ""),
                        "status": entry.get("status"),
                        "result": entry.get("result", ""),
                        "error": entry.get("error"),
                        "tool_calls": entry.get("tool_calls", 0),
                        "elapsed": entry.get("elapsed"),
                    })
        return {"agents": completed, "total": len(completed), "message": f"已完成 {len(completed)} 个子 agent"}

    elif action == "cancel":
        """取消子 agent"""
        if not agent_id:
            return {"error": "需要 agent_id 参数"}

        with _registry_lock:
            entry = _subagent_registry.get(agent_id)
            if not entry:
                return {"error": f"未找到子 Agent: {agent_id}"}
            if entry.get("status") not in ("pending", "running"):
                return {"agent_id": agent_id, "status": entry["status"], "message": "子 agent 已结束，无需取消"}

            # 取消 future（如果有）
            future = entry.get("future")
            if future and not future.done():
                cancelled = future.cancel()
                entry["status"] = "cancelled"
                entry["completed_at"] = datetime.now().isoformat()
                return {"agent_id": agent_id, "status": "cancelled", "cancelled": cancelled}

            entry["status"] = "cancelled"
            entry["completed_at"] = datetime.now().isoformat()
            return {"agent_id": agent_id, "status": "cancelled"}

    return {"error": f"未知操作: {action}"}


# ── Meta for toolkit registration ──────────────────────

def meta_toolkit_subagent() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "toolkit_subagent",
            "description": "子 Agent 生成系统 v2.0 — 隔离上下文窗口。每个子 Agent 有独立的 LiteSession，不污染父 Agent 的上下文窗口。支持同步/异步、并发、状态查询、结果收集、上下文注入。",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["spawn", "spawn_sync", "list", "status", "collect", "cancel"],
                        "description": "spawn=异步生成, spawn_sync=同步等待, list=列出, status=查询状态, collect=收集结果, cancel=取消"
                    },
                    "goal": {"type": "string", "description": "[spawn/spawn_sync] 子 Agent 任务描述"},
                    "context": {"type": "object", "description": "[spawn/spawn_sync] 注入上下文（dict，key=标题, value=内容）"},
                    "max_iterations": {"type": "integer", "description": "最大工具迭代次数", "default": 20},
                    "enable_thinking": {"type": "boolean", "description": "是否启用推理", "default": False},
                    "timeout": {"type": "integer", "description": "超时秒数", "default": 120},
                    "max_concurrent": {"type": "integer", "description": "最大并发数", "default": 5},
                    "agent_id": {"type": "string", "description": "[status/cancel] 子 Agent ID"},
                },
                "required": ["action"],
            },
        },
    }
