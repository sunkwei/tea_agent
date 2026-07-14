"""
WorkflowEngine — 高级工作流编排引擎。

在 Phase 5 (ExecutionPool) 之上构建：
  • WorkflowNode  — 6 种节点类型（Task/Condition/Loop/Parallel/Wait/End）
  • WorkflowDAG   — DAG 定义引擎（拓扑排序 + 循环检测 + 校验）
  • WorkflowExec  — 状态机执行器（集成 ExecutionPool 并发执行）
  • 条件分支 / 循环 / 并行扇入扇出 / 错误处理

用法:
    dag = WorkflowDAG()
    dag.add_node(WorkflowNode("start", TASK, fn=lambda ctx: {"data": 42}))
    dag.add_node(WorkflowNode("check", CONDITION, fn=lambda ctx: ctx["data"] > 10))
    dag.add_node(WorkflowNode("process", TASK, fn=lambda ctx: {"result": ctx["data"] * 2}))
    dag.add_edge("start", "check")
    dag.add_edge("check", "process", condition_key="true")
    dag.add_edge("check", "end", condition_key="false")

    wf = WorkflowExec(dag)
    result = wf.run({"start": {}})
    print(result.status)  # "completed"
"""

import enum
import logging
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

from .execution_pool import ExecutionPool, get_execution_pool

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════
# Pass 6.1 — WorkflowNode 节点类型系统
# ═══════════════════════════════════════════════


class NodeType(str, enum.Enum):
    """工作流节点类型。"""
    TASK = "task"               # 普通任务
    CONDITION = "condition"     # 条件分支（if/elif/else）
    LOOP = "loop"              # 循环（for-each / while）
    PARALLEL = "parallel"      # 并行扇出（fan-out + fan-in）
    WAIT = "wait"              # 等待（定时 / 条件满足后继续）
    END = "end"                # 工作流终止节点


class NodeState(str, enum.Enum):
    """节点执行状态。"""
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


class WorkflowState(str, enum.Enum):
    """工作流状态。"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class NodeResult:
    """单节点执行结果。"""
    node_id: str
    state: NodeState = NodeState.PENDING
    output: dict | None = None
    error: str | None = None
    started_at: float | None = None
    finished_at: float | None = None
    retries: int = 0

    @property
    def duration(self) -> float:
        if self.started_at and self.finished_at:
            return self.finished_at - self.started_at
        return 0.0


@dataclass
class WorkflowNode:
    """
    工作流节点。

    Attributes:
        node_id: 节点唯一标识
        type: 节点类型
        label: 可读标签（可选）
        fn: 任务函数 fn(ctx: dict) -> dict
            - TASK: 执行此函数，返回值合并到上下文
            - CONDITION: 应返回 {"condition": bool} 或 {"next": "分支名"}
            - LOOP: 每次迭代执行，应返回 {"items": [...]} 或控制信号
            - PARALLEL: 内部自动 fan-out
            - WAIT: 应返回 {"ready": bool} 或等待指定秒数
        config: 节点配置
            - TASK: agent_id, timeout, retry
            - CONDITION: branches={"true":"node_a","false":"node_b"}
            - LOOP: iterator_key, max_iterations
            - PARALLEL: children=[...], gather_strategy="all"/"any"
            - WAIT: delay_seconds, condition_key
        timeout: 执行超时（秒）
        retry_policy: {"max_retries":3, "base_delay":1.0}
    """
    node_id: str
    type: NodeType
    label: str = ""
    fn: Callable | None = None
    config: dict = field(default_factory=dict)
    timeout: float = 300.0
    retry_policy: dict | None = None

    def __post_init__(self):
        if not self.label:
            self.label = self.node_id


# ═══════════════════════════════════════════════
# Pass 6.2 — WorkflowDAG DAG 定义引擎
# ═══════════════════════════════════════════════


class WorkflowDAG:
    """
    工作流 DAG 定义引擎。

    支持:
    - 节点增删改查
    - 有向边管理（支持条件边: edge.condition_key）
    - 拓扑排序 + 循环检测
    - 结构校验
    - 序列化/反序列化
    """

    def __init__(self, workflow_id: str | None = None):
        self.workflow_id = workflow_id or f"wf-{uuid.uuid4().hex[:8]}"
        self._nodes: dict[str, WorkflowNode] = {}
        self._edges: list[dict] = []  # [{"from":str,"to":str,"condition_key":str|None}]
        self._metadata: dict = {"created_at": datetime.now().isoformat()}

    # ── 节点管理 ───────────────────────────────

    def add_node(self, node: WorkflowNode) -> str:
        """添加节点，返回 node_id。"""
        if node.node_id in self._nodes:
            raise ValueError(f"节点 '{node.node_id}' 已存在")
        self._nodes[node.node_id] = node
        return node.node_id

    def get_node(self, node_id: str) -> WorkflowNode | None:
        return self._nodes.get(node_id)

    def remove_node(self, node_id: str) -> bool:
        """删除节点及关联边。"""
        if node_id not in self._nodes:
            return False
        del self._nodes[node_id]
        self._edges = [e for e in self._edges
                       if e["from"] != node_id and e["to"] != node_id]
        return True

    @property
    def nodes(self) -> dict[str, WorkflowNode]:
        return dict(self._nodes)

    @property
    def edges(self) -> list[dict]:
        return list(self._edges)

    # ── 边管理 ───────────────────────────────

    def add_edge(self, from_id: str, to_id: str,
                 condition_key: str | None = None) -> dict:
        """
        添加有向边。

        Args:
            from_id: 源节点
            to_id: 目标节点
            condition_key: 条件分支时使用（如 "true"/"false"/"default"）
        """
        if from_id not in self._nodes:
            raise ValueError(f"源节点 '{from_id}' 不存在")
        if to_id not in self._nodes:
            raise ValueError(f"目标节点 '{to_id}' 不存在")

        edge = {"from": from_id, "to": to_id, "condition_key": condition_key}
        self._edges.append(edge)
        return edge

    def get_edges_from(self, node_id: str,
                       condition_key: str | None = None) -> list[dict]:
        """获取从某节点出发的边（可选按条件过滤）。"""
        results = [e for e in self._edges if e["from"] == node_id]
        if condition_key is not None:
            results = [e for e in results
                       if e.get("condition_key") == condition_key]
        return results

    def get_edges_to(self, node_id: str) -> list[dict]:
        return [e for e in self._edges if e["to"] == node_id]

    # ── 拓扑排序 & 校验 ───────────────────────

    def topological_sort(self) -> list[str]:
        """
        Kahn 算法拓扑排序。
        返回有序节点 ID 列表，若有环则抛出 ValueError。
        """
        in_degree: dict[str, int] = {nid: 0 for nid in self._nodes}
        adj: dict[str, list[str]] = {nid: [] for nid in self._nodes}

        for e in self._edges:
            # 条件边不参与拓扑排序（运行时动态决策）
            if e.get("condition_key"):
                continue
            from_id, to_id = e["from"], e["to"]
            if from_id in adj and to_id in in_degree:
                adj[from_id].append(to_id)
                in_degree[to_id] += 1

        queue = deque([nid for nid, deg in in_degree.items() if deg == 0])
        sorted_nodes = []

        while queue:
            nid = queue.popleft()
            sorted_nodes.append(nid)
            for neighbor in adj.get(nid, []):
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        if len(sorted_nodes) != len(self._nodes):
            # 尝试找出包含条件边的环 — 条件边的环可能合法（运行时解开）
            # 只检查无条件边的环
            non_cond_nodes = {e["from"] for e in self._edges
                              if not e.get("condition_key")}
            non_cond_nodes |= {e["to"] for e in self._edges
                               if not e.get("condition_key")}
            cycles = non_cond_nodes - set(sorted_nodes)
            if cycles:
                raise ValueError(
                    f"DAG 存在环，涉及节点: {cycles}")
            # 剩余节点可能仅通过条件边连接，视为合法
            sorted_nodes.extend(nid for nid in self._nodes
                                if nid not in sorted_nodes)

        return sorted_nodes

    def validate(self) -> list[str]:
        """校验 DAG 合法性，返回错误列表。"""
        errors = []

        if not self._nodes:
            errors.append("DAG 没有节点")
            return errors

        # 检查每个节点的出边
        for nid, node in self._nodes.items():
            out_edges = self.get_edges_from(nid)

            if node.type == NodeType.END:
                if out_edges:
                    errors.append(f"END 节点 '{nid}' 不应有出边")

            elif node.type == NodeType.CONDITION:
                # 条件节点必须有 true/false 分支
                has_true = any(e.get("condition_key") == "true"
                               for e in out_edges)
                has_false = any(e.get("condition_key") == "false"
                                for e in out_edges)
                if not has_true:
                    errors.append(f"CONDITION 节点 '{nid}' 缺少 'true' 分支")
                if not has_false:
                    errors.append(f"CONDITION 节点 '{nid}' 缺少 'false' 分支")

        return errors

    # ── 序列化 ───────────────────────────────

    def to_dict(self) -> dict:
        return {
            "workflow_id": self.workflow_id,
            "metadata": self._metadata,
            "nodes": {nid: {
                "node_id": n.node_id,
                "type": n.type.value,
                "label": n.label,
                "config": n.config,
                "timeout": n.timeout,
                "retry_policy": n.retry_policy,
            } for nid, n in self._nodes.items()},
            "edges": self._edges,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "WorkflowDAG":
        dag = cls(workflow_id=data.get("workflow_id"))
        dag._metadata = data.get("metadata", {})
        for nid, nd in data.get("nodes", {}).items():
            dag._nodes[nid] = WorkflowNode(
                node_id=nd["node_id"],
                type=NodeType(nd["type"]),
                label=nd.get("label", ""),
                config=nd.get("config", {}),
                timeout=nd.get("timeout", 300.0),
                retry_policy=nd.get("retry_policy"),
            )
        dag._edges = list(data.get("edges", []))
        return dag

    def __repr__(self) -> str:
        return (f"WorkflowDAG(wf={self.workflow_id}, "
                f"nodes={len(self._nodes)}, edges={len(self._edges)})")


# ═══════════════════════════════════════════════
# Pass 6.3 — WorkflowExecutor 状态机执行器
# Pass 6.4 — 条件分支 / 循环 / 并行 / 错误处理
# ═══════════════════════════════════════════════


class WorkflowExec:
    """
    工作流状态机执行器。

    集成 ExecutionPool (Phase 5) 实现并发任务执行。
    支持: 顺序执行 / 条件分支 / 循环 / 并行扇入扇出 / 错误处理

    状态机: pending → running → completed | failed | cancelled
    """

    def __init__(
        self,
        dag: WorkflowDAG,
        pool: ExecutionPool | None = None,
        context: dict | None = None,
    ):
        self.dag = dag
        self.pool = pool or get_execution_pool(pool_name=f"wf-{dag.workflow_id}")
        self.context: dict = context or {}
        self._node_results: dict[str, NodeResult] = {
            nid: NodeResult(node_id=nid)
            for nid in dag.nodes
        }
        self._state: WorkflowState = WorkflowState.PENDING
        self._started_at: float | None = None
        self._finished_at: float | None = None
        self._cancelled: bool = False

        # 循环状态跟踪
        self._loop_counts: dict[str, int] = {}
        # 并行分支跟踪
        self._parallel_futures: list = []

    @property
    def workflow_id(self) -> str:
        return self.dag.workflow_id

    @property
    def state(self) -> WorkflowState:
        return self._state

    @property
    def results(self) -> dict[str, NodeResult]:
        return dict(self._node_results)

    @property
    def duration(self) -> float:
        if self._started_at and self._finished_at:
            return self._finished_at - self._started_at
        return 0.0

    # ── 主执行入口 ────────────────────────────

    def run(self, initial_context: dict | None = None) -> "WorkflowExec":
        """
        执行整个工作流 DAG。

        Args:
            initial_context: 初始上下文（注入工作流变量）

        Returns:
            self（便于链式调用）
        """
        if initial_context:
            self.context.update(initial_context)

        # 空 DAG → 直接完成（先于校验）
        if not self.dag.nodes:
            self._started_at = time.time()
            self._finished_at = time.time()
            self._set_state(WorkflowState.COMPLETED)
            logger.info(f"⏹️ 工作流 '{self.workflow_id}' 空 DAG，直接完成")
            return self

        errors = self.dag.validate()
        if errors:
            self._set_state(WorkflowState.FAILED)
            logger.error(f"❌ DAG 校验失败: {errors}")
            return self

        self._started_at = time.time()
        self._set_state(WorkflowState.RUNNING)
        logger.info(f"▶️ 工作流 '{self.workflow_id}' 开始执行")

        try:
            # 获取执行顺序（拓扑排序）
            order = self.dag.topological_sort()
            # 跟踪已完成的节点
            completed = set()

            while len(completed) < len(order) and not self._cancelled:
                progress = False

                for nid in order:
                    if nid in completed:
                        continue
                    node = self.dag.get_node(nid)
                    if not node:
                        continue

                    # 检查是否所有前置节点已完成
                    prereq = self._prerequisites_met(nid, completed)
                    if prereq is None:
                        # 条件不匹配 → 跳过此节点
                        self._node_results[nid].state = NodeState.SKIPPED
                        completed.add(nid)
                        progress = True
                        continue
                    if not prereq:
                        continue

                    # 执行节点
                    self._node_results[nid].started_at = time.time()
                    self._node_results[nid].state = NodeState.RUNNING

                    try:
                        output = self._execute_node(node)
                        # LOOP 节点循环未完成 → 留在 completed 外，下次重跑
                        if (node.type == NodeType.LOOP
                                and isinstance(output, dict)
                                and not output.get("_loop_done", True)):
                            self._node_results[nid].state = NodeState.RUNNING
                            progress = True
                            continue
                        self._node_results[nid].state = NodeState.COMPLETED
                        completed.add(nid)
                        progress = True
                    except Exception as e:
                        self._node_results[nid].state = NodeState.FAILED
                        self._node_results[nid].error = str(e)
                        logger.error(f"❌ 节点 '{nid}' 失败: {e}")

                        # 如果是条件/循环/并行节点内部错误，传播
                        if node.type in (NodeType.CONDITION, NodeType.LOOP,
                                         NodeType.PARALLEL):
                            self._set_state(WorkflowState.FAILED)
                            return self

                        # 普通任务节点失败 — 根据配置决定是否继续
                        if node.config.get("fail_fast", True):
                            self._set_state(WorkflowState.FAILED)
                            return self
                        # 跳过失败节点继续
                        completed.add(nid)
                        progress = True

                if not progress and len(completed) < len(order):
                    # 死锁检测（带限流日志）
                    stuck = set(order) - completed
                    reachable = self._find_reachable_from_start(completed)
                    unreachable = stuck - reachable
                    if unreachable:
                        logger.error(
                            f"🛑 死锁: 节点不可达 {unreachable}")
                        for nid in unreachable:
                            self._node_results[nid].state = NodeState.SKIPPED
                            completed.add(nid)
                        continue
                    # 防止无限循环 — 每 3 秒输出一次日志
                    if not hasattr(self, '_deadlock_log_ts'):
                        self._deadlock_log_ts = 0
                    if not self._cancelled:
                        now = time.time()
                        if now - self._deadlock_log_ts > 3.0:
                            logger.info("⏳ 等待条件满足...")
                            self._deadlock_log_ts = now
                        time.sleep(0.3)

            # 最终状态
            if self._cancelled:
                self._set_state(WorkflowState.CANCELLED)
            else:
                has_failed = any(
                    r.state == NodeState.FAILED
                    for r in self._node_results.values()
                )
                self._set_state(
                    WorkflowState.FAILED if has_failed
                    else WorkflowState.COMPLETED
                )

        except Exception as e:
            logger.error(f"💥 工作流执行异常: {e}")
            self._set_state(WorkflowState.FAILED)

        self._finished_at = time.time()
        return self

    def cancel(self):
        """取消工作流执行。"""
        self._cancelled = True
        for f in self._parallel_futures:
            f.cancel()
        self._set_state(WorkflowState.CANCELLED)
        logger.info(f"⏹️ 工作流 '{self.workflow_id}' 已取消")

    def _set_state(self, state: WorkflowState):
        self._state = state

    # ── 前置条件检查 ──────────────────────────

    def _prerequisites_met(self, nid: str,
                           completed: set[str]) -> bool | None:
        """
        检查节点的前置条件是否满足。

        Returns:
            True   → 满足，可以执行
            False  → 不满足，等待（前置节点未完成）
            None   → 条件不匹配，应跳过此节点
        """
        incoming = self.dag.get_edges_to(nid)

        for edge in incoming:
            from_id = edge["from"]
            cond_key = edge.get("condition_key")

            if not cond_key:
                # 无条件边：前置节点必须已完成
                if from_id not in completed:
                    return False
            else:
                # 条件边：前置节点必须已完成，且匹配条件
                if from_id not in completed:
                    return False
                from_result = self._node_results.get(from_id)
                if from_result and from_result.state != NodeState.COMPLETED:
                    return False
                # 检查条件匹配
                out = from_result.output or {}
                actual_key = out.get("condition_key", out.get("next"))
                if actual_key is not None and actual_key != cond_key:
                    return None  # 条件不匹配 → 跳过此节点

        return True

    def _find_reachable_from_start(self, completed: set[str]) -> set[str]:
        """BFS 从已完成节点出发找可达节点。"""
        reachable = set(completed)
        queue = deque(completed)

        while queue:
            current = queue.popleft()
            for edge in self.dag.get_edges_from(current):
                if edge["to"] not in reachable:
                    reachable.add(edge["to"])
                    queue.append(edge["to"])

        return reachable

    # ── 节点执行分发 ──────────────────────────

    def _execute_node(self, node: WorkflowNode) -> dict | None:
        """按节点类型分发执行。返回节点输出（LOOP 节点可能返回 None 表示未完成）。"""
        if self._cancelled:
            return None

        dispatch = {
            NodeType.TASK: self._execute_task,
            NodeType.CONDITION: self._execute_condition,
            NodeType.LOOP: self._execute_loop,
            NodeType.PARALLEL: self._execute_parallel,
            NodeType.WAIT: self._execute_wait,
            NodeType.END: self._execute_end,
        }

        handler = dispatch.get(node.type)
        if not handler:
            raise ValueError(f"未知节点类型: {node.type}")

        logger.info(f"  ▶ [{node.node_id}] {node.type.value}: {node.label}")

        # 重试包装
        retry = node.retry_policy or {}
        max_retries = retry.get("max_retries", 0)
        base_delay = retry.get("base_delay", 1.0)
        last_error = None
        output = None

        for attempt in range(max_retries + 1):
            try:
                if attempt > 0:
                    delay = base_delay * (2 ** (attempt - 1))
                    logger.info(f"    重试 {attempt}/{max_retries} 等待 {delay:.1f}s")
                    time.sleep(delay)
                    self._node_results[node.node_id].retries = attempt

                output = handler(node)
                self._node_results[node.node_id].output = output or {}
                self._node_results[node.node_id].error = None

                if output:
                    self.context[f"@{node.node_id}"] = output

                last_error = None
                break
            except Exception as e:
                last_error = e
                logger.warning(f"    尝试 {attempt + 1}/{max_retries + 1} 失败: {e}")
                continue

        if last_error:
            raise last_error

        return output

    def _execute_task(self, node: WorkflowNode) -> dict:
        """执行任务节点。"""
        if node.fn:
            result = node.fn(self.context)
            if result is None:
                result = {}
            return result

        # 通过 agent_id + task_description 执行
        agent_id = node.config.get("agent_id")
        task_desc = node.config.get("task_description", "")
        if agent_id and task_desc:
            # 支持通过 subagent_manager 执行
            from .subagent_manager import SubAgentManager

            sm = SubAgentManager()
            future = self.pool.submit(
                sm.run_agent,
                agent_id,
                task_desc,
                context=self.context.get(f"@{node.node_id}"),
                name=f"wf-{node.node_id}",
                timeout=node.timeout,
            )
            result = future.result(timeout=node.timeout)
            if isinstance(result, dict):
                return result
            return {"_result": str(result)}

        return {}

    def _execute_condition(self, node: WorkflowNode) -> dict:
        """
        条件分支节点。
        fn 应返回 {"condition": bool} 或 {"condition_key": "分支名"}
        """
        if not node.fn:
            raise ValueError(f"CONDITION 节点 '{node.node_id}' 缺少 fn")

        result = node.fn(self.context)
        if not isinstance(result, dict):
            result = {"condition": bool(result)}

        # 确定条件键
        condition_key = result.get("condition_key")
        if condition_key is None:
            condition_key = "true" if result.get("condition", False) else "false"

        result["condition_key"] = condition_key
        logger.info(f"    ➡ 条件: {condition_key}")
        return result

    def _execute_loop(self, node: WorkflowNode) -> dict:
        """
        循环节点。
        - for-each: fn 返回 {"items": [...]}，逐个处理
        - while: fn 返回 {"continue": bool}

        支持 max_iterations 限制。
        """
        max_iter = node.config.get("max_iterations", 100)
        iterator_key = node.config.get("iterator_key")
        iteration_count = self._loop_counts.get(node.node_id, 0)

        if not node.fn:
            raise ValueError(f"LOOP 节点 '{node.node_id}' 缺少 fn")

        result = node.fn(self.context)
        if not isinstance(result, dict):
            return {"_loop_result": str(result)}

        # 检查是否继续
        should_continue = result.get("continue", False)
        items = result.get("items")

        if items is not None:
            # for-each 模式
            current_index = iteration_count
            if current_index >= len(items):
                return {"_loop_done": True, "_items_processed": current_index}

            item = items[current_index]
            self._loop_counts[node.node_id] = current_index + 1
            logger.info(f"    🔄 for-each [{current_index}/{len(items)}]: {item}")

            if iterator_key:
                self.context[iterator_key] = item

            return {"_loop_item": item, "_loop_index": current_index,
                    "_loop_done": False, "_loop_total": len(items)}

        if should_continue:
            self._loop_counts[node.node_id] = iteration_count + 1
            logger.info(f"    🔄 while [{iteration_count + 1}/{max_iter}]")

            if iteration_count + 1 >= max_iter:
                return {"_loop_done": True, "_loop_iterations": iteration_count + 1}

            return {"_loop_done": False}

        return {"_loop_done": True, "_loop_iterations": iteration_count}

    def _execute_parallel(self, node: WorkflowNode) -> dict:
        """
        并行扇入扇出节点。
        config["children"]: [WorkflowNode, ...] 并行执行
        gather_strategy: "all" 等待全部 / "any" 首个完成
        """
        children = node.config.get("children", [])
        if not children:
            return {"_parallel_count": 0}

        strategy = node.config.get("gather_strategy", "all")
        timeout = node.config.get("parallel_timeout", 60.0)
        results = {}

        # 空上下文，每个子任务独立
        def _run_child(child: WorkflowNode) -> tuple[str, dict]:
            try:
                ctx = dict(self.context)
                ctx["_parallel_parent"] = node.node_id
                handler = {
                    NodeType.TASK: self._execute_task,
                    NodeType.CONDITION: self._execute_condition,
                    NodeType.LOOP: self._execute_loop,
                    NodeType.WAIT: self._execute_wait,
                }.get(child.type, self._execute_task)
                output = handler(child)
                return child.node_id, output or {}
            except Exception as e:
                return child.node_id, {"_error": str(e)}

        # 提交到 ExecutionPool
        futures = []
        for child in children:
            f = self.pool.submit(
                _run_child, child,
                name=f"parallel-{child.node_id}",
                timeout=timeout,
            )
            futures.append(f)
            self._parallel_futures.append(f)

        # 收集结果
        for f in futures:
            try:
                cid, output = f.result(timeout=timeout)
                results[cid] = output
                if strategy == "any":
                    break
            except Exception as e:
                results["_error"] = str(e)

        # 清理已完成的 future
        self._parallel_futures = [
            f for f in self._parallel_futures if not f.done()
        ]

        return {"_parallel_results": results, "_parallel_count": len(results)}

    def _execute_wait(self, node: WorkflowNode) -> dict:
        """
        等待节点。
        - delay_seconds: 固定等待
        - fn 返回 {"ready": bool} 轮询等待
        """
        delay = node.config.get("delay_seconds", 0)

        if delay > 0:
            logger.info(f"    ⏳ 等待 {delay}s...")
            time.sleep(delay)
            return {"_waited": delay}

        # 条件等待（轮询）
        if node.fn:
            timeout = node.config.get("wait_timeout", 60.0)
            poll_interval = node.config.get("poll_interval", 1.0)
            deadline = time.time() + timeout
            start = time.time()

            while time.time() < deadline and not self._cancelled:
                result = node.fn(self.context)
                if isinstance(result, dict) and result.get("ready", False):
                    return {"_ready": True, "_waited": round(time.time() - start, 3)}
                time.sleep(poll_interval)

            raise TimeoutError(f"WAIT 节点 '{node.node_id}' 等待超时 ({timeout}s)")

        return {"_ready": True}

    def _execute_end(self, node: WorkflowNode) -> dict:
        """结束节点。"""
        logger.info(f"    ⏹ 工作流结束")
        return {"_end": True}

    # ── 状态报告 ──────────────────────────────

    def status(self) -> dict:
        """执行状态摘要。"""
        node_states = {
            nid: {
                "state": r.state.value,
                "duration": r.duration,
                "error": r.error,
                "retries": r.retries,
            }
            for nid, r in self._node_results.items()
        }

        return {
            "workflow_id": self.workflow_id,
            "state": self._state.value,
            "duration": self.duration,
            "nodes": node_states,
            "context_keys": list(self.context.keys()),
        }

    def to_dict(self) -> dict:
        return {
            "workflow_id": self.workflow_id,
            "state": self._state.value,
            "started_at": self._started_at,
            "finished_at": self._finished_at,
            "duration": self.duration,
            "node_results": {
                nid: {
                    "state": r.state.value,
                    "output": r.output,
                    "error": r.error,
                    "started_at": r.started_at,
                    "finished_at": r.finished_at,
                    "retries": r.retries,
                }
                for nid, r in self._node_results.items()
            },
            "dag": self.dag.to_dict(),
        }


# ═══════════════════════════════════════════════
# WorkflowTemplate — 可复用工作流模板
# ═══════════════════════════════════════════════


class WorkflowTemplate:
    """
    可复用的工作流模板仓库。

    支持保存、加载、列出、删除模板。模板可以包含占位符 {{var}}，
    实例化时填充。
    """

    _store: dict[str, dict] = {}

    @classmethod
    def save(cls, name: str, dag: WorkflowDAG,
             description: str = "", tags: list[str] | None = None) -> str:
        """保存工作流为模板。"""
        cls._store[name] = {
            "name": name,
            "description": description,
            "tags": tags or [],
            "dag": dag.to_dict(),
            "created_at": datetime.now().isoformat(),
        }
        logger.info(f"📝 工作流模板 '{name}' 已保存")
        return name

    @classmethod
    def load(cls, name: str) -> WorkflowDAG | None:
        """加载工作流模板。"""
        data = cls._store.get(name)
        if not data:
            return None
        return WorkflowDAG.from_dict(data["dag"])

    @classmethod
    def list_templates(cls, query: str = "") -> list[dict]:
        """列出模板。"""
        results = list(cls._store.values())
        if query:
            results = [
                r for r in results
                if query.lower() in r["name"].lower()
                or query.lower() in r["description"].lower()
            ]
        return results

    @classmethod
    def delete(cls, name: str) -> bool:
        if name in cls._store:
            del cls._store[name]
            return True
        return False

    @classmethod
    def instantiate(cls, name: str,
                    variables: dict | None = None) -> WorkflowDAG | None:
        """
        实例化模板（替换占位符 {{var}}）。

        Args:
            name: 模板名称
            variables: 占位符变量，如 {"agent_id": "agent-a"}

        Returns: 新 WorkflowDAG 实例
        """
        dag = cls.load(name)
        if not dag:
            return None

        import json
        dag_dict = dag.to_dict()
        vars_dict = variables or {}

        def _replace(obj):
            if isinstance(obj, str):
                for k, v in vars_dict.items():
                    obj = obj.replace("{{" + k + "}}", str(v))
                return obj
            elif isinstance(obj, dict):
                return {k: _replace(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [_replace(item) for item in obj]
            return obj

        dag_dict = _replace(dag_dict)
        return WorkflowDAG.from_dict(dag_dict)
