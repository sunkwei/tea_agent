"""
Agent-as-Tool — 将 RoleAgent 包装为可调用工具。

核心设计:
  任何 RoleAgent 可以把自己注册为一个「工具」，
  其他 Agent（或 Flow）可以通过标准的工具调用接口来调用它。

这实现了一个关键模式：
  1. Agent A 发现 Agent B 暴露的工具接口
  2. Agent A 像调用普通工具一样调用 Agent B
  3. Agent B 在自己的上下文中执行，返回结构化结果
  4. 调用方不需要知道 B 的内部实现

使用场景:
  - 专家 Agent 暴露能力供主 Agent 调用
  - 多 Agent 分工协作
  - 工具化的子任务执行（比直接 spawn 更可控）

架构:
  AgentTool       — 包装单个 Agent 为可调用对象
  AgentToolRegistry — 管理 Agent-as-Tool 的生命周期
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid

from collections.abc import Callable
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


class AgentTool:
    """
    将 RoleAgent 包装为一个可调用的「工具」。

    每个 AgentTool 对外暴露一个标准接口:
      - name: 工具名（如 "senior_analyst"）
      - description: 工具描述
      - parameters: 工具参数 schema
      - call(task): 执行入口

    可以被注册到 ToolRegistry 或直接注入另一个 Agent 的 toolkit。
    """

    def __init__(
        self,
        agent,
        name: str = "",
        description: str = "",
        max_concurrent: int = 3,
        timeout: int = 120,
    ):
        """
        Args:
            agent: RoleAgent 实例（或任何有 execute_sync 方法的对象）
            name: 工具名（默认使用 agent.role 的 slug 化）
            description: 工具描述
            max_concurrent: 最大并发调用数
            timeout: 单次调用超时秒数
        """
        self.agent = agent
        self.name = name or self._slugify(getattr(agent, "role", "agent"))
        self.description = description or self._build_description(agent)
        self.max_concurrent = max_concurrent
        self.timeout = timeout

        # 内部状态
        self._lock = threading.Lock()
        self._active_calls: dict[str, dict] = {}
        self._call_history: list[dict] = []
        self._max_history = 100

        # 统计
        self.total_calls = 0
        self.successful_calls = 0
        self.failed_calls = 0

    def call(self, task: str, context: dict | None = None, **kwargs) -> dict:
        """
        调用此 Agent 工具。

        Args:
            task: 任务描述
            context: 额外上下文

        Returns:
            {"result": str, "error": str or None, "tool_calls": int, ...}
        """
        call_id = str(uuid.uuid4())[:8]
        start_time = time.time()

        # 并发控制
        with self._lock:
            if len(self._active_calls) >= self.max_concurrent:
                return {
                    "error": f"达到最大并发数 ({self.max_concurrent})",
                    "call_id": call_id,
                }
            self._active_calls[call_id] = {"status": "running", "start": start_time}

        try:
            self.total_calls += 1

            # 执行 agent（兼容 RoleAgent.execute 和 LiteAgent.execute_sync）
            if context:
                if hasattr(self.agent, 'execute_with_context'):
                    raw = self.agent.execute_with_context(task, context)
                elif hasattr(self.agent, 'execute'):
                    raw = self.agent.execute(task, context=context)
                else:
                    raw = self.agent.execute_sync(task)
            else:
                if hasattr(self.agent, 'execute'):
                    raw = self.agent.execute(task)
                else:
                    raw = self.agent.execute_sync(task)

            # 统一提取文本结果
            if isinstance(raw, dict) and 'output' in raw:
                result = raw['output']
            elif hasattr(raw, 'output'):
                result = raw.output
            elif isinstance(raw, str):
                result = raw
            else:
                result = str(raw)

            elapsed = time.time() - start_time
            self.successful_calls += 1

            entry = {
                "call_id": call_id,
                "task": task[:100],
                "elapsed": round(elapsed, 2),
                "success": True,
            }

            with self._lock:
                self._call_history.append(entry)
                if len(self._call_history) > self._max_history:
                    self._call_history = self._call_history[-self._max_history:]

            return {
                "result": result,
                "call_id": call_id,
                "elapsed": round(elapsed, 2),
                "error": None,
            }

        except Exception as e:
            elapsed = time.time() - start_time
            self.failed_calls += 1
            logger.error(f"❌ AgentTool [{self.name}] 调用失败: {e}")

            entry = {
                "call_id": call_id,
                "task": task[:100],
                "elapsed": round(elapsed, 2),
                "success": False,
                "error": str(e),
            }

            with self._lock:
                self._call_history.append(entry)
                if len(self._call_history) > self._max_history:
                    self._call_history = self._call_history[-self._max_history:]

            return {
                "error": str(e),
                "call_id": call_id,
                "elapsed": round(elapsed, 2),
            }

        finally:
            with self._lock:
                self._active_calls.pop(call_id, None)

    def call_async(self, task: str, context: dict | None = None) -> str:
        """异步调用，返回 call_id（后续可通过 get_result 查询）。"""
        call_id = str(uuid.uuid4())[:8]
        thread = threading.Thread(
            target=self._async_worker,
            args=(call_id, task, context),
            daemon=True,
        )
        thread.start()
        return call_id

    def get_result(self, call_id: str) -> dict | None:
        """查询异步调用结果。"""
        with self._lock:
            for entry in reversed(self._call_history):
                if entry.get("call_id") == call_id:
                    return entry
        return None

    def _async_worker(self, call_id: str, task: str, context: dict | None):
        """异步执行工作器。"""
        result = self.call(task, context)
        # 结果已记录到 _call_history
        pass

    def to_tool_schema(self) -> dict:
        """
        生成 OpenAI 工具格式的 schema，
        方便注入到其他 Agent 的 toolkit 中。
        """
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "task": {
                            "type": "string",
                            "description": f"给 {self.name} 的任务描述",
                        },
                    },
                    "required": ["task"],
                },
            },
        }

    def to_dict(self) -> dict:
        """工具信息快照。"""
        return {
            "name": self.name,
            "description": self.description,
            "agent_role": getattr(self.agent, "role", "unknown"),
            "max_concurrent": self.max_concurrent,
            "timeout": self.timeout,
            "stats": {
                "total_calls": self.total_calls,
                "successful": self.successful_calls,
                "failed": self.failed_calls,
            },
            "active_calls": len(self._active_calls),
        }

    @staticmethod
    def _slugify(text: str) -> str:
        """将角色名转为工具名。"""
        return text.lower().replace(" ", "_").replace("-", "_")[:40]

    def _build_description(self, agent) -> str:
        """从 agent 信息构建工具描述。"""
        role = getattr(agent, "role", "助手")
        goal = getattr(agent, "goal", "")
        backstory = getattr(agent, "backstory", "")

        parts = [f"🎭 {role}"]
        if goal:
            parts.append(f"目标: {goal[:200]}")
        if backstory:
            parts.append(f"背景: {backstory[:200]}")

        return "\n".join(parts)


class AgentToolManager:
    """
    Agent-as-Tool 管理器。

    管理多个 AgentTool 的生命周期:
      - 注册/注销
      - 发现/查询
      - 分组/标签
      - 注入到目标 Agent 的 toolkit
    """

    def __init__(self):
        self._tools: dict[str, AgentTool] = {}
        self._lock = threading.Lock()

    def register(self, agent_tool: AgentTool, tags: list[str] | None = None) -> str:
        """注册一个 AgentTool。"""
        with self._lock:
            self._tools[agent_tool.name] = agent_tool
            logger.info(f"📦 AgentTool 注册: {agent_tool.name}")
            return agent_tool.name

    def unregister(self, name: str) -> bool:
        """注销。"""
        with self._lock:
            if name in self._tools:
                del self._tools[name]
                logger.info(f"🗑️ AgentTool 注销: {name}")
                return True
            return False

    def get(self, name: str) -> AgentTool | None:
        """获取 AgentTool。"""
        with self._lock:
            return self._tools.get(name)

    def list(self, tag: str | None = None) -> list[dict]:
        """列出所有注册的工具。"""
        with self._lock:
            tools = list(self._tools.values())
            return [t.to_dict() for t in tools]

    def call(self, name: str, task: str, **kwargs) -> dict:
        """调用指定 AgentTool。"""
        tool = self.get(name)
        if not tool:
            return {"error": f"AgentTool '{name}' 未找到"}
        return tool.call(task, **kwargs)

    def inject_all(self, target_agent) -> list[str]:
        """
        将所有注册的 AgentTool 注入到目标 Agent 的 tools 白名单。

        返回注入的工具名列表。
        """
        injected = []
        for name, tool in self._tools.items():
            schema = tool.to_tool_schema()
            # 注入到 agent 的工具列表
            target_agent.add_extra_tool(schema)
            injected.append(name)
        return injected

    def count(self) -> int:
        return len(self._tools)

    def clear(self):
        with self._lock:
            self._tools.clear()
