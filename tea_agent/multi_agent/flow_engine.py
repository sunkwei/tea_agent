"""
FlowEngine — 事件驱动流程引擎。

借鉴 CrewAI Flows + LangGraph StateGraph，实现：
  - @start() / @listen() 装饰器驱动
  - 条件路由（根据状态选择分支）
  - 循环检测
  - 状态管理 + 上下文透传
  - Mermaid 可视化

核心概念:
  - Flow: 一个可执行的工作流，由多个 Step 组成
  - Step: 一个执行节点（由 @start/@listen 方法定义）
  - Event: step 完成时触发的事件（step_name.completed）
  - State: 跨步骤共享的状态字典

用法:
    from tea_agent.multi_agent import FlowEngine, flow_start, flow_listen

    class MyFlow(FlowEngine):
        @flow_start()
        def analyze(self):
            return "分析完成"

        @flow_listen(analyze)
        def implement(self):
            return "实现完成"

    flow = MyFlow()
    result = flow.run()
"""

import inspect
import json
import logging
import re
import traceback
from collections import OrderedDict
from datetime import datetime
from enum import Enum
from typing import Any, Callable

logger = logging.getLogger(__name__)


# ───────────────────────────────────────────────
# Step 定义
# ───────────────────────────────────────────────

class StepStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class FlowState:
    """
    流程状态 — 跨步骤共享的上下文。

    设计:
      - 类似 LangGraph 的 State
      - 可以存储任意键值
      - 写入即记录变更历史
    """

    def __init__(self, initial: dict | None = None):
        self._data: dict[str, Any] = dict(initial or {})
        self._history: list[dict] = []
        self._change_id = 0

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def __setitem__(self, key: str, value: Any):
        self._change_id += 1
        old = self._data.get(key)
        self._data[key] = value
        self._history.append({
            "change_id": self._change_id,
            "key": key,
            "old_value": old,
            "new_value": value,
            "timestamp": datetime.now().isoformat(),
        })

    def __contains__(self, key: str) -> bool:
        return key in self._data

    def __repr__(self) -> str:
        return f"FlowState({self._data})"

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def setdefault(self, key: str, default: Any = None) -> Any:
        if key not in self._data:
            self[key] = default
        return self._data[key]

    def update(self, data: dict):
        for k, v in data.items():
            self[k] = v

    def keys(self):
        return self._data.keys()

    def values(self):
        return self._data.values()

    def items(self):
        return self._data.items()

    def to_dict(self) -> dict:
        return dict(self._data)

    @property
    def change_history(self) -> list[dict]:
        return list(self._history)


# ───────────────────────────────────────────────
# 装饰器
# ───────────────────────────────────────────────

_STEP_REGISTRY: dict[str, dict] = {}


def flow_start():
    """
    标记方法为 Flow 的起始节点。

    起始节点在 run() 时自动触发，无需等待其他事件。
    """
    def decorator(func: Callable):
        func.__flow_start__ = True
        func.__flow_listen__ = None
        return func
    return decorator


def flow_listen(*sources, condition: Callable | None = None):
    """
    标记方法为事件监听节点。

    Args:
        *sources: 监听的源（可以是函数引用或事件名称字符串）
        condition: 可选的条件函数 fn(state) → bool，决定是否执行
    """
    def decorator(func: Callable):
        func.__flow_start__ = False
        func.__flow_listen__ = {
            "sources": sources,
            "condition": condition,
        }
        return func
    return decorator


def flow_route(output_map: dict[str, str] | None = None):
    """
    标记方法为路由节点——根据输出决定后续分支。

    Args:
        output_map: 输出值到事件名的映射，如 {"refactor": "deep_clean", "fix": "quick_fix"}
                     返回的字符串将被映射为事件触发
    """
    def decorator(func: Callable):
        func.__flow_start__ = False
        func.__flow_listen__ = None
        func.__flow_route__ = output_map or {}
        return func
    return decorator


# ───────────────────────────────────────────────
# 核心引擎
# ───────────────────────────────────────────────

class FlowEngine:
    """
    事件驱动流程引擎基类。

    子类通过定义 @flow_start() 和 @flow_listen() 方法来构建工作流。
    """

    def __init__(self, name: str | None = None):
        self.name = name or self.__class__.__name__
        self.state = FlowState()
        self._steps: OrderedDict[str, dict] = OrderedDict()
        self._results: dict[str, Any] = {}
        self._statuses: dict[str, StepStatus] = {}
        self._errors: dict[str, str] = {}
        self._timings: dict[str, float] = {}
        self._completed_events: set[str] = set()
        self._execution_log: list[dict] = []
        self._max_iterations = 100  # 防止死循环
        self._iteration_count = 0

        # 解析步骤
        self._discover_steps()

    # ───────────────────────────────────────────────
    # 公共 API
    # ───────────────────────────────────────────────

    def run(self, initial_state: dict | None = None) -> dict:
        """
        执行流程。

        Args:
            initial_state: 初始状态

        Returns:
            {"success": bool, "state": dict, "results": dict, "errors": dict, ...}
        """
        if initial_state:
            self.state.update(initial_state)

        logger.info(f"🔀 Flow [{self.name}] 开始执行 ({len(self._steps)} 个步骤)")
        self._execution_log = []
        self._results = {}
        self._statuses = {step_name: StepStatus.PENDING for step_name in self._steps}
        self._errors = {}
        self._timings = {}
        self._completed_events = set()
        self._iteration_count = 0

        # 查找起始步骤
        start_steps = [name for name, info in self._steps.items() if info.get("is_start")]

        if not start_steps:
            # 如果没有标注 @start，则尝试第一个无依赖的步骤
            start_steps = self._find_root_steps()

        if not start_steps:
            logger.error(f"❌ Flow [{self.name}] 没有找到起始步骤")
            return self._build_result(success=False, error="没有起始步骤")

        # 激活起始步骤
        active = list(start_steps)

        while active and self._iteration_count < self._max_iterations:
            self._iteration_count += 1
            step_name = active.pop(0)

            # 跳过已完成的
            if self._statuses.get(step_name) in (StepStatus.COMPLETED, StepStatus.FAILED, StepStatus.SKIPPED):
                continue

            # 检查前置条件是否满足
            step_info = self._steps[step_name]
            if not self._check_dependencies(step_name, step_info):
                # 前置条件尚未满足，放回队列尾部
                active.append(step_name)
                if self._iteration_count > self._max_iterations * 0.8:
                    logger.warning(f"⚠️ Step [{step_name}] 前置条件长时间未满足，跳过")
                    self._statuses[step_name] = StepStatus.SKIPPED
                continue

            # 执行
            self._execute_step(step_name, step_info)

            # 触发后续步骤
            next_steps = self._find_downstream_steps(step_name)
            for ns in next_steps:
                if ns not in active:
                    active.append(ns)

        # 检查是否有步骤未执行
        pending = [n for n, s in self._statuses.items() if s == StepStatus.PENDING]
        if pending:
            logger.warning(f"⚠️ Flow [{self.name}] 有 {len(pending)} 个步骤未执行: {pending}")

        success = all(s == StepStatus.COMPLETED for s in self._statuses.values() if s != StepStatus.SKIPPED)
        logger.info(f"✅ Flow [{self.name}] 执行完成 (success={success})")
        return self._build_result(success=success)

    def get_result(self, step_name: str) -> Any:
        """获取某个步骤的执行结果。"""
        return self._results.get(step_name)

    def get_status(self, step_name: str) -> StepStatus:
        """获取某个步骤的状态。"""
        return self._statuses.get(step_name, StepStatus.PENDING)

    def get_step_output(self, step_name: str) -> str | None:
        """获取某个步骤的输出文本。"""
        result = self._results.get(step_name)
        if isinstance(result, str):
            return result
        if isinstance(result, dict):
            return result.get("output", json.dumps(result, ensure_ascii=False))
        if result is not None:
            return str(result)
        return None

    def visualize(self) -> str:
        """
        生成 Mermaid 流程图。
        """
        lines = [
            f"```mermaid",
            "flowchart TD",
        ]

        # 为每个步骤生成节点
        node_ids = {}
        for i, (name, info) in enumerate(self._steps.items()):
            nid = f"S{i}"
            node_ids[name] = nid
            label = info.get("label", name)
            is_start = info.get("is_start", False)
            shape = f"{nid}[{label}]" if not is_start else f"{nid}(({label}))"
            lines.append(f"    {shape}")

        # 生成边
        for name, info in self._steps.items():
            if name not in node_ids:
                continue
            sources = info.get("listen_sources", [])
            for src in sources:
                src_name = self._resolve_source_name(src)
                if src_name and src_name in node_ids:
                    lines.append(f"    {node_ids[src_name]} --> {node_ids[name]}")

        # 路由条件
        for name, info in self._steps.items():
            route_map = info.get("route_map", {})
            if route_map and name in node_ids:
                for value, target in route_map.items():
                    if target in node_ids:
                        lines.append(f"    {node_ids[name]} -->|{value}| {node_ids[target]}")

        lines.append("```")
        return "\n".join(lines)

    def set_max_iterations(self, n: int):
        """设置最大迭代次数（防止死循环）。"""
        self._max_iterations = n

    # ───────────────────────────────────────────────
    # 内部：步骤发现
    # ───────────────────────────────────────────────

    def _discover_steps(self):
        """扫描子类方法，识别 flow_start / flow_listen 标记。"""
        self._steps.clear()

        for name, method in inspect.getmembers(self, predicate=inspect.ismethod):
            if name.startswith("_"):
                continue

            info = {}

            # 检查是否是 @flow_start
            if getattr(method, "__flow_start__", False):
                info["is_start"] = True
                info["label"] = name
                info["method"] = method
                self._steps[name] = info
                continue

            # 检查是否是 @flow_listen
            listen_info = getattr(method, "__flow_listen__", None)
            if listen_info is not None:
                info["is_start"] = False
                info["label"] = name
                info["method"] = method
                info["listen_sources"] = listen_info["sources"]
                info["condition"] = listen_info.get("condition")
                self._steps[name] = info
                continue

            # 检查是否是 @flow_route
            route_map = getattr(method, "__flow_route__", None)
            if route_map is not None:
                info["is_start"] = False
                info["label"] = f"{name} [路由]"
                info["method"] = method
                info["route_map"] = route_map
                self._steps[name] = info
                continue

    # ───────────────────────────────────────────────
    # 内部：执行控制
    # ───────────────────────────────────────────────

    def _find_root_steps(self) -> list[str]:
        """查找没有依赖的步骤（作为起始）。"""
        all_source_names = set()
        for name, info in self._steps.items():
            sources = info.get("listen_sources", [])
            for src in sources:
                src_name = self._resolve_source_name(src)
                if src_name:
                    all_source_names.add(src_name)

        return [n for n in self._steps if n not in all_source_names]

    def _check_dependencies(self, step_name: str, step_info: dict) -> bool:
        """检查步骤的前置事件是否都已完成。"""
        sources = step_info.get("listen_sources", [])
        if not sources:
            return True  # 起始步骤无依赖

        for src in sources:
            src_name = self._resolve_source_name(src)
            if src_name is None:
                # 可能是字符串事件名
                if isinstance(src, str) and src not in self._completed_events:
                    return False
                continue
            if self._statuses.get(src_name) != StepStatus.COMPLETED:
                return False

        # 检查条件函数
        condition = step_info.get("condition")
        if condition:
            try:
                if not condition(self.state):
                    return False
            except Exception as e:
                logger.warning(f"⚠️ Step [{step_name}] 条件函数异常: {e}")
                return False

        return True

    def _execute_step(self, step_name: str, step_info: dict):
        """执行单个步骤。"""
        method = step_info["method"]
        self._statuses[step_name] = StepStatus.RUNNING

        if logger.isEnabledFor(logging.INFO):
            deps = step_info.get("listen_sources", [])
            dep_str = f" ← {[str(d) for d in deps]}" if deps else " [起始]"
            logger.info(f"  ⚡ [{step_name}]{dep_str}")

        start = datetime.now()

        try:
            # 调用方法，注入 state
            sig = inspect.signature(method)
            if any(p.name == "state" for p in sig.parameters.values()):
                result = method(self.state)
            else:
                result = method()

            elapsed = (datetime.now() - start).total_seconds()
            self._results[step_name] = result
            self._statuses[step_name] = StepStatus.COMPLETED
            self._timings[step_name] = elapsed

            # 触发完成事件
            self._completed_events.add(f"{step_name}.completed")
            self._completed_events.add(step_name)

            # 处理路由
            route_map = step_info.get("route_map")
            if route_map and result in route_map:
                target = route_map[result]
                self._completed_events.add(target)
                logger.info(f"    ↪ 路由: {result} → {target}")

            self._execution_log.append({
                "step": step_name,
                "status": "completed",
                "time_seconds": round(elapsed, 2),
            })

            result_preview = str(result)[:100] if result else ""
            logger.info(f"  ✅ [{step_name}] 完成 ({elapsed:.1f}s) {result_preview}")

        except Exception as e:
            elapsed = (datetime.now() - start).total_seconds()
            self._statuses[step_name] = StepStatus.FAILED
            self._errors[step_name] = str(e)
            self._timings[step_name] = elapsed
            self._execution_log.append({
                "step": step_name,
                "status": "failed",
                "error": str(e),
                "time_seconds": round(elapsed, 2),
            })
            logger.error(f"  ❌ [{step_name}] 失败 ({elapsed:.1f}s): {e}")

    def _find_downstream_steps(self, completed_step: str) -> list[str]:
        """查找监听 completed_step 的后续步骤。"""
        downstream = []
        for name, info in self._steps.items():
            if self._statuses.get(name) != StepStatus.PENDING:
                continue
            sources = info.get("listen_sources", [])
            for src in sources:
                src_name = self._resolve_source_name(src)
                if src_name == completed_step:
                    downstream.append(name)
                    break
                # 也支持字符串事件名
                if isinstance(src, str) and src == completed_step:
                    downstream.append(name)
                    break
        return downstream

    @staticmethod
    def _resolve_source_name(source: Any) -> str | None:
        """
        将 source 解析为步骤名称。
        source 可以是函数引用、方法对象或字符串。
        """
        if isinstance(source, str):
            return source
        if inspect.ismethod(source) or inspect.isfunction(source):
            return source.__name__
        if hasattr(source, "__name__"):
            return source.__name__
        return None

    def _build_result(self, success: bool, error: str | None = None) -> dict:
        """构建执行结果。"""
        total = len(self._steps)
        completed = sum(1 for s in self._statuses.values() if s == StepStatus.COMPLETED)
        failed = sum(1 for s in self._statuses.values() if s == StepStatus.FAILED)
        skipped = sum(1 for s in self._statuses.values() if s == StepStatus.SKIPPED)
        total_time = sum(self._timings.values())

        return {
            "flow": self.name,
            "success": success,
            "total_steps": total,
            "completed_steps": completed,
            "failed_steps": failed,
            "skipped_steps": skipped,
            "total_time_seconds": round(total_time, 1),
            "state": self.state.to_dict(),
            "results": {k: v for k, v in self._results.items()},
            "errors": dict(self._errors),
            "timings": dict(self._timings),
            "execution_log": self._execution_log,
            "error": error,
        }
