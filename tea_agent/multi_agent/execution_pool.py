"""
ExecutionPool — 高性能双通道并行执行池。

架构设计:
    ExecutionPool (统一入口)
        ├── ThreadPoolChannel  ── 同步/IO/CPU 密集型任务
        ├── AsyncChannel       ── async/await 协程任务
        ├── PriorityQueue      ── 优先级调度
        └── Monitor            ── 健康监控 + 统计

使用方法:
    pool = ExecutionPool(max_workers=8)

    # 提交同步任务
    future = pool.submit(func, arg1, arg2=value)
    result = future.result(timeout=30)

    # 提交异步任务
    future = pool.submit_async(async_func, arg1)
    result = future.result(timeout=30)

    # 批量
    results = pool.map(func, [item1, item2])

    # 检查状态
    stats = pool.status()

    # 优雅关闭
    pool.shutdown()
"""

import asyncio
import logging
import queue
import threading
import time
import uuid
from collections.abc import Callable, Coroutine
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

logger = logging.getLogger(__name__)


# ── 状态枚举 ──────────────────────────────────


class TaskState(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


class PoolState(str, Enum):
    INIT = "init"
    RUNNING = "running"
    DRAINING = "draining"
    SHUTDOWN = "shutdown"


# ── 任务元数据 ────────────────────────────────


@dataclass
class TaskInfo:
    """单个任务的完整元数据。"""
    id: str = field(default_factory=lambda: f"task-{uuid.uuid4().hex[:12]}")
    name: str = ""
    fn: str = ""
    state: TaskState = TaskState.PENDING
    priority: int = 5  # 1=最高，10=最低
    created_at: float = field(default_factory=time.time)
    started_at: float = 0.0
    finished_at: float = 0.0
    duration: float = 0.0
    error: str | None = None
    result_size: int = 0
    channel: str = "thread"  # thread | async

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "fn": self.fn,
            "state": self.state.value,
            "priority": self.priority,
            "created_at": datetime.fromtimestamp(self.created_at).isoformat(),
            "started_at": datetime.fromtimestamp(self.started_at).isoformat() if self.started_at else "",
            "duration": round(self.duration, 3),
            "error": self.error,
            "channel": self.channel,
        }


# ── 执行池核心 ────────────────────────────────


class ExecutionPool:
    """
    双通道并行执行池。

    Features:
        - 线程池通道：同步/IO/CPU 密集型任务
        - 异步通道：async/await 协程任务
        - 优先级调度：数字越小优先级越高
        - 健康监控：实时统计 + 任务追踪
        - 优雅关闭：drain → shutdown
    """

    def __init__(
        self,
        max_workers: int = 8,
        max_async_workers: int = 16,
        queue_size: int = 1000,
        pool_name: str = "default",
    ):
        self.pool_name = pool_name
        self._state = PoolState.INIT
        self._lock = threading.RLock()

        # 线程池通道
        self._thread_pool = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix=f"execpool_{pool_name}",
        )

        # 异步通道
        self._max_async_workers = max_async_workers
        self._async_loop: asyncio.AbstractEventLoop | None = None
        self._async_thread: threading.Thread | None = None

        # 任务队列 & 追踪
        self._priority_queue: queue.PriorityQueue = queue.PriorityQueue(maxsize=queue_size)
        self._tasks: dict[str, TaskInfo] = {}
        self._futures: dict[str, Future] = {}
        self._current: int = 0  # 当前活跃（已提交未完成）任务数
        self._seq: int = 0  # 提交序号，用于同优先级FIFO

        # 统计
        self._stats = {
            "submitted": 0,
            "completed": 0,
            "failed": 0,
            "cancelled": 0,
            "timeout": 0,
            "total_duration": 0.0,
        }

        # 启动
        self._state = PoolState.RUNNING
        self._scheduler_thread = threading.Thread(
            target=self._scheduler_loop,
            name=f"pool-scheduler-{pool_name}",
            daemon=True,
        )
        self._scheduler_thread.start()

        self._start_async_loop()
        logger.info(
            f"🚀 ExecutionPool[{pool_name}] 启动 | "
            f"workers={max_workers} async={max_async_workers}"
        )

    # ── 公共 API ───────────────────────────────

    def submit(
        self,
        fn: Callable,
        *args,
        priority: int = 5,
        name: str = "",
        timeout: float | None = None,
        **kwargs,
    ) -> Future:
        """
        提交同步/阻塞任务到线程池通道。

        Args:
            fn: 可调用对象
            priority: 优先级 1-10 (1=最高)
            name: 任务名称
            timeout: 超时秒数

        Returns:
            concurrent.futures.Future
        """
        tid = f"task-{uuid.uuid4().hex[:12]}"
        task = TaskInfo(
            id=tid,
            name=name or getattr(fn, "__name__", str(type(fn).__name__)),
            fn=getattr(fn, "__name__", str(type(fn).__name__)),
            priority=max(1, min(10, priority)),
            channel="thread",
        )
        with self._lock:
            self._tasks[tid] = task
            self._stats["submitted"] += 1
            self._seq += 1
            seq = self._seq

        future: Future = Future()
        self._futures[tid] = future

        # 通过优先队列调度：(priority, seq, tid, fn, args, kwargs, task, future)
        try:
            self._priority_queue.put_nowait(
                (priority, seq, tid, fn, args, kwargs, task, future)
            )
        except queue.Full:
            # 队列满时降级为直接提交
            def _run_direct():
                task.state = TaskState.RUNNING
                task.started_at = time.time()
                self._current += 1
                try:
                    result = fn(*args, **kwargs)
                    task.state = TaskState.COMPLETED
                    task.finished_at = time.time()
                    task.duration = task.finished_at - task.started_at
                    with self._lock:
                        self._stats["completed"] += 1
                        self._stats["total_duration"] += task.duration
                    future.set_result(result)
                    return result
                except Exception as e:
                    task.state = TaskState.FAILED
                    task.finished_at = time.time()
                    task.duration = task.finished_at - task.started_at
                    task.error = f"{type(e).__name__}: {e}"
                    with self._lock:
                        self._stats["failed"] += 1
                    future.set_exception(e)
                    raise
                finally:
                    self._current = max(0, self._current - 1)
            self._thread_pool.submit(_run_direct)
        return future

    def submit_async(
        self,
        coro_fn: Callable[..., Coroutine],
        *args,
        priority: int = 5,
        name: str = "",
        **kwargs,
    ) -> Future:
        """
        提交异步协程任务到异步通道。

        Args:
            coro_fn: 返回 Coroutine 的异步函数
            priority: 优先级 1-10
            name: 任务名称

        Returns:
            concurrent.futures.Future
        """
        tid = f"task-{uuid.uuid4().hex[:12]}"
        task = TaskInfo(
            id=tid,
            name=name or getattr(coro_fn, "__name__", str(type(coro_fn).__name__)),
            fn=getattr(coro_fn, "__name__", str(type(coro_fn).__name__)),
            priority=max(1, min(10, priority)),
            channel="async",
        )
        with self._lock:
            self._tasks[tid] = task
            self._stats["submitted"] += 1

        future: Future = Future()

        async def _run_async():
            task.state = TaskState.RUNNING
            task.started_at = time.time()
            try:
                result = await coro_fn(*args, **kwargs)
                task.state = TaskState.COMPLETED
                task.finished_at = time.time()
                task.duration = task.finished_at - task.started_at
                with self._lock:
                    self._stats["completed"] += 1
                    self._stats["total_duration"] += task.duration
                if not future.done():
                    future.set_result(result)
                return result
            except Exception as e:
                task.state = TaskState.FAILED
                task.finished_at = time.time()
                task.duration = task.finished_at - task.started_at
                task.error = f"{type(e).__name__}: {e}"
                with self._lock:
                    self._stats["failed"] += 1
                if not future.done():
                    future.set_exception(e)
                raise

        def _schedule():
            try:
                asyncio.run_coroutine_threadsafe(_run_async(), self._async_loop)
            except Exception as e:
                if not future.done():
                    future.set_exception(e)

        self._async_loop.call_soon_threadsafe(_schedule)
        self._futures[tid] = future
        return future

    def map(
        self,
        fn: Callable,
        items: list,
        priority: int = 5,
        timeout: float | None = None,
    ) -> list:
        """
        批量执行，返回有序结果列表。

        Args:
            fn: 处理函数
            items: 参数列表
            priority: 优先级
            timeout: 超时秒数

        Returns:
            list 结果列表（保持 items 顺序）
        """
        futures = [self.submit(fn, item, priority=priority) for item in items]
        results = []
        for future in as_completed(futures, timeout=timeout):
            try:
                results.append(future.result())
            except Exception as e:
                results.append(e)
        # 恢复原始顺序
        ordered = []
        for f in futures:
            try:
                ordered.append(f.result(timeout=0))
            except Exception as e:
                ordered.append(e)
        return ordered if len(futures) == len(items) else results

    def shutdown(self, wait: bool = True, timeout: float = 10):
        """优雅关闭执行池。"""
        self._state = PoolState.DRAINING
        logger.info(f"🔄 ExecutionPool[{self.pool_name}] 正在 drain...")

        # 等待排空
        if wait:
            deadline = time.time() + timeout
            while time.time() < deadline:
                active = self.active_count()
                if active == 0:
                    break
                time.sleep(0.1)

        self._state = PoolState.SHUTDOWN
        self._thread_pool.shutdown(wait=False)
        if self._async_loop:
            self._async_loop.call_soon_threadsafe(self._async_loop.stop)
        logger.info(f"🛑 ExecutionPool[{self.pool_name}] 已关闭")

    # ── 状态查询 ───────────────────────────────

    def status(self) -> dict:
        """返回执行池的全面状态。"""
        with self._lock:
            state_counts = {"pending": 0, "running": 0, "completed": 0, "failed": 0}
            for t in self._tasks.values():
                s = t.state.value
                if s in state_counts:
                    state_counts[s] += 1

            stats = dict(self._stats)
            stats["avg_duration"] = (
                round(stats["total_duration"] / max(1, stats["completed"]), 3)
                if stats["completed"]
                else 0
            )

        return {
            "pool_name": self.pool_name,
            "state": self._state.value,
            "max_workers": self._thread_pool._max_workers,
            "tasks": state_counts,
            "stats": stats,
            "active": self.active_count(),
            "queue_size": self._priority_queue.qsize(),
        }

    def get_task(self, task_id: str) -> dict | None:
        """获取单个任务信息。"""
        task = self._tasks.get(task_id)
        return task.to_dict() if task else None

    def list_tasks(self, state: TaskState | None = None, limit: int = 100) -> list[dict]:
        """列出任务（按创建时间降序）。"""
        tasks = list(self._tasks.values())
        if state:
            tasks = [t for t in tasks if t.state == state]
        tasks.sort(key=lambda t: t.created_at, reverse=True)
        return [t.to_dict() for t in tasks[:limit]]

    def active_count(self) -> int:
        """当前活跃任务数（running + pending）。"""
        count = 0
        with self._lock:
            for t in self._tasks.values():
                if t.state in (TaskState.PENDING, TaskState.RUNNING):
                    count += 1
        return count

    def cancel(self, task_id: str) -> bool:
        """取消待执行任务。"""
        task = self._tasks.get(task_id)
        if not task or task.state != TaskState.PENDING:
            return False
        future = self._futures.get(task_id)
        if future:
            cancelled = future.cancel()
            if cancelled:
                task.state = TaskState.CANCELLED
                with self._lock:
                    self._stats["cancelled"] += 1
                return True
        return False

    # ── 内部机制 ───────────────────────────────

    def _scheduler_loop(self):
        """后台调度循环：从优先队列取任务，按优先级提交到线程池。"""
        while self._state in (PoolState.RUNNING, PoolState.DRAINING):
            try:
                # 从优先队列取任务（1秒超时以便检查状态）
                item = self._priority_queue.get(timeout=1)
                priority, seq, tid, fn, args, kwargs, task, future = item

                # 检查任务是否已被取消
                if task.state == TaskState.CANCELLED:
                    if not future.done():
                        future.cancel()
                    continue

                def _run():
                    task.state = TaskState.RUNNING
                    task.started_at = time.time()
                    self._current += 1
                    try:
                        result = fn(*args, **kwargs)
                        task.state = TaskState.COMPLETED
                        task.finished_at = time.time()
                        task.duration = task.finished_at - task.started_at
                        with self._lock:
                            self._stats["completed"] += 1
                            self._stats["total_duration"] += task.duration
                        if not future.done():
                            future.set_result(result)
                        return result
                    except Exception as e:
                        task.state = TaskState.FAILED
                        task.finished_at = time.time()
                        task.duration = task.finished_at - task.started_at
                        task.error = f"{type(e).__name__}: {e}"
                        with self._lock:
                            self._stats["failed"] += 1
                        if not future.done():
                            future.set_exception(e)
                        raise
                    finally:
                        self._current = max(0, self._current - 1)

                self._thread_pool.submit(_run)

            except queue.Empty:
                # 队列空，继续等待
                continue
            except Exception:
                logger.debug("_scheduler_loop 异常", exc_info=True)

        # 关闭时清理残留 futures
        with self._lock:
            for tid, future in list(self._futures.items()):
                if not future.done():
                    try:
                        future.cancel()
                    except Exception:
                        pass

    def _start_async_loop(self):
        """启动专用事件循环线程。"""
        self._async_loop = asyncio.new_event_loop()

        def _run_loop():
            asyncio.set_event_loop(self._async_loop)
            self._async_loop.run_forever()

        self._async_thread = threading.Thread(
            target=_run_loop,
            name=f"pool-asyncio-{self.pool_name}",
            daemon=True,
        )
        self._async_thread.start()


# ── 模块级便利函数 ────────────────────────────

_default_pool: ExecutionPool | None = None
_pool_lock = threading.Lock()


def get_execution_pool(
    max_workers: int = 8,
    pool_name: str = "default",
) -> ExecutionPool:
    """获取/创建全局默认执行池（单例）。"""
    global _default_pool
    if _default_pool is None:
        with _pool_lock:
            if _default_pool is None:
                _default_pool = ExecutionPool(
                    max_workers=max_workers,
                    pool_name=pool_name,
                )
    return _default_pool


# ═══════════════════════════════════════════════
# LoadBalancer — 智能负载均衡
# ═══════════════════════════════════════════════


class LoadBalancerStrategy(str, Enum):
    ROUND_ROBIN = "round_robin"
    LEAST_CONNECTIONS = "least_connections"
    WEIGHTED = "weighted"
    RANDOM = "random"


@dataclass
class PoolNode:
    """负载均衡节点（一个执行池）。"""
    name: str
    pool: ExecutionPool
    weight: float = 1.0
    max_concurrent: int = 10
    _current: int = 0
    _total_submitted: int = 0
    _total_duration: float = 0.0

    def load_ratio(self) -> float:
        """当前负载比例 0.0~1.0（基于池实际活跃任务数）。"""
        active = self.pool.active_count() if self.pool else self._current
        return min(1.0, active / max(1, self.max_concurrent))

    def avg_duration(self) -> float:
        if self._total_submitted == 0:
            return 0.0
        return self._total_duration / self._total_submitted


class LoadBalancer:
    """
    智能负载均衡器。

    将任务分发到多个 ExecutionPool 节点，支持多种策略。

    Usage:
        lb = LoadBalancer()
        lb.add_node("cpu", ExecutionPool(max_workers=4))
        lb.add_node("io", ExecutionPool(max_workers=8), weight=2.0)

        # 自动选择最佳节点
        pool = lb.select(task_type="cpu", priority=3)
        future = pool.submit(fn, arg)

        # 或直接提交
        future = lb.submit(fn, arg, task_type="io")
    """

    def __init__(self, strategy: LoadBalancerStrategy = LoadBalancerStrategy.LEAST_CONNECTIONS):
        self.strategy = strategy
        self._nodes: dict[str, PoolNode] = {}
        self._rr_index = 0
        self._lock = threading.RLock()

    def add_node(
        self,
        name: str,
        pool: ExecutionPool,
        weight: float = 1.0,
        max_concurrent: int = 10,
    ):
        """注册执行池节点。"""
        with self._lock:
            self._nodes[name] = PoolNode(
                name=name,
                pool=pool,
                weight=weight,
                max_concurrent=max_concurrent,
            )
        logger.info(f"🔀 LoadBalancer 添加节点: {name} (weight={weight})")

    def remove_node(self, name: str):
        """移除节点。"""
        with self._lock:
            self._nodes.pop(name, None)

    def select(self, task_type: str = "general", priority: int = 5) -> ExecutionPool:
        """
        根据策略选择最优执行池。

        Returns:
            ExecutionPool 实例
        """
        nodes = list(self._nodes.values())
        if not nodes:
            raise RuntimeError("LoadBalancer: 没有注册的执行池节点")

        if self.strategy == LoadBalancerStrategy.ROUND_ROBIN:
            with self._lock:
                idx = self._rr_index % len(nodes)
                self._rr_index += 1
            return nodes[idx].pool

        elif self.strategy == LoadBalancerStrategy.LEAST_CONNECTIONS:
            # 选择当前连接数最少的节点
            best = min(nodes, key=lambda n: n.load_ratio())
            return best.pool

        elif self.strategy == LoadBalancerStrategy.WEIGHTED:
            # 加权随机选择
            import random
            total_weight = sum(n.weight for n in nodes)
            r = random.uniform(0, total_weight)
            cumulative = 0
            for n in nodes:
                cumulative += n.weight
                if r <= cumulative:
                    return n.pool
            return nodes[-1].pool

        else:  # RANDOM
            import random
            return random.choice(nodes).pool

    def submit(
        self,
        fn: Callable,
        *args,
        task_type: str = "general",
        priority: int = 5,
        name: str = "",
        **kwargs,
    ) -> Future:
        """自动选择节点并提交任务。"""
        pool = self.select(task_type=task_type, priority=priority)
        node = self._get_node_for_pool(pool)
        if node:
            node._current += 1
            node._total_submitted += 1
        future = pool.submit(fn, *args, priority=priority, name=name, **kwargs)
        if node:
            def _on_done(f, n=node):
                n._current = max(0, n._current - 1)
                try:
                    result = f.result()
                except Exception:
                    result = None
            future.add_done_callback(_on_done)
        return future

    def submit_async(
        self,
        coro_fn: Callable[..., Coroutine],
        *args,
        task_type: str = "general",
        priority: int = 5,
        name: str = "",
        **kwargs,
    ) -> Future:
        """自动选择节点并提交异步任务。"""
        pool = self.select(task_type=task_type, priority=priority)
        node = self._get_node_for_pool(pool)
        if node:
            node._current += 1
            node._total_submitted += 1
        future = pool.submit_async(coro_fn, *args, priority=priority, name=name, **kwargs)
        if node:
            def _on_done(f, n=node):
                n._current = max(0, n._current - 1)
            future.add_done_callback(_on_done)
        return future

    def _get_node_for_pool(self, pool):
        # type: (ExecutionPool) -> PoolNode | None
        """根据 ExecutionPool 实例查找对应的 PoolNode。"""
        for node in self._nodes.values():
            if node.pool is pool:
                return node
        return None

    def status(self) -> dict:
        """返回所有节点的状态。"""
        with self._lock:
            nodes_status = {}
            for name, node in self._nodes.items():
                nodes_status[name] = {
                    "weight": node.weight,
                    "current": node._current,
                    "max_concurrent": node.max_concurrent,
                    "load_ratio": round(node.load_ratio(), 3),
                    "total_submitted": node._total_submitted,
                    "pool_status": node.pool.status(),
                }
        return {
            "strategy": self.strategy.value,
            "nodes": nodes_status,
            "total_nodes": len(self._nodes),
        }

    def shutdown_all(self):
        """关闭所有节点。"""
        for name, node in self._nodes.items():
            logger.info(f"🛑 关闭负载均衡节点: {name}")
            node.pool.shutdown(wait=False)


# ═══════════════════════════════════════════════
# ResourceGuard — 资源隔离与保护
# ═══════════════════════════════════════════════


@dataclass
class ResourceLimit:
    """资源限制配置。"""
    max_cpu_time: float = 60.0       # 单任务最大 CPU 时间（秒）
    max_memory_mb: float = 512.0     # 单任务最大内存（MB）
    max_duration: float = 300.0      # 单任务最大墙上时间（秒）
    max_concurrent: int = 20         # 最大并发任务数


class ResourceGuard:
    """
    资源隔离与保护。

    通过监控任务执行时的资源消耗来防止资源滥用。
    - CPU 时间限制
    - 内存限制
    - 执行时间限制
    - 并发限制

    Usage:
        guard = ResourceGuard()
        guard.set_limit("cpu_bound", ResourceLimit(max_cpu_time=30, max_memory_mb=256))

        with guard.monitor("task-1", "cpu_bound") as ctx:
            result = expensive_computation()
    """

    def __init__(self):
        self._limits: dict[str, ResourceLimit] = {}
        self._default_limit = ResourceLimit()
        self._active: dict[str, dict] = {}
        self._lock = threading.RLock()
        self._violations: list[dict] = []

    def set_limit(self, name: str, limit: ResourceLimit):
        """设置某类任务的资源限制。"""
        with self._lock:
            self._limits[name] = limit

    def get_limit(self, task_type: str = "default") -> ResourceLimit:
        """获取某类任务的资源限制。"""
        with self._lock:
            return self._limits.get(task_type, self._default_limit)

    def acquire(self, task_id: str, task_type: str = "default") -> bool:
        """尝试获取执行许可（并发限制检查）。"""
        limit = self.get_limit(task_type)

        with self._lock:
            # 检查并发
            count = sum(1 for v in self._active.values() if v["type"] == task_type)
            if count >= limit.max_concurrent:
                self._violations.append({
                    "task_id": task_id,
                    "reason": f"max_concurrent exceeded ({count}/{limit.max_concurrent})",
                    "time": time.time(),
                })
                logger.warning(f"⚠️ ResourceGuard: 并发限制 {task_id} ({count}/{limit.max_concurrent})")
                return False

            self._active[task_id] = {
                "type": task_type,
                "started_at": time.time(),
                "cpu_start": time.process_time(),
            }
            return True

    def release(self, task_id: str):
        """释放执行许可。"""
        with self._lock:
            self._active.pop(task_id, None)

    def check_timeout(self, task_id: str) -> bool:
        """检查任务是否超时。"""
        with self._lock:
            info = self._active.get(task_id)
            if not info:
                return False
            limit = self.get_limit(info["type"])
            elapsed = time.time() - info["started_at"]
            cpu_elapsed = time.process_time() - info["cpu_start"]

            if elapsed > limit.max_duration:
                self._violations.append({
                    "task_id": task_id,
                    "reason": f"wall_time exceeded ({elapsed:.1f}/{limit.max_duration}s)",
                    "time": time.time(),
                })
                return True
            if cpu_elapsed > limit.max_cpu_time:
                self._violations.append({
                    "task_id": task_id,
                    "reason": f"cpu_time exceeded ({cpu_elapsed:.1f}/{limit.max_cpu_time}s)",
                    "time": time.time(),
                })
                return True
            return False

    def status(self) -> dict:
        """资源保护状态。"""
        with self._lock:
            return {
                "active_tasks": len(self._active),
                "limits_configured": list(self._limits.keys()),
                "violations_total": len(self._violations),
                "recent_violations": self._violations[-10:] if self._violations else [],
            }

    def cleanup(self, max_age: float = 3600):
        """清理过期违规记录。"""
        now = time.time()
        with self._lock:
            self._violations = [
                v for v in self._violations
                if now - v["time"] < max_age
            ]


# ═══════════════════════════════════════════════
# FaultTolerant — 容错机制
# ═══════════════════════════════════════════════


class CircuitState(str, Enum):
    CLOSED = "closed"          # 正常
    OPEN = "open"              # 熔断开启
    HALF_OPEN = "half_open"    # 半开（尝试恢复）


class CircuitBreaker:
    """
    熔断器。

    当连续失败达到阈值时切断链路，避免级联故障。
    支持自动半开恢复。

    Usage:
        cb = CircuitBreaker(failure_threshold=5, recovery_timeout=30.0)

        async with cb:
            result = await risky_call()
    """

    def __init__(
        self,
        name: str = "default",
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        half_open_max_trials: int = 3,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_trials = half_open_max_trials

        self.state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time = 0.0
        self._half_open_trials = 0
        self._total_success = 0
        self._total_failure = 0
        self._lock = threading.RLock()

    def __enter__(self):
        if not self._try_acquire():
            raise RuntimeError(
                f"CircuitBreaker[{self.name}] OPEN: 熔断开启"
            )
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            self._record_failure()
        else:
            self._record_success()

    async def __aenter__(self):
        if not self._try_acquire():
            raise RuntimeError(
                f"CircuitBreaker[{self.name}] OPEN: 熔断开启"
            )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            self._record_failure()
        else:
            self._record_success()

    def _try_acquire(self) -> bool:
        """检查是否允许请求通过。"""
        with self._lock:
            if self.state == CircuitState.CLOSED:
                return True

            if self.state == CircuitState.OPEN:
                # 检查是否到达恢复时间
                if time.time() - self._last_failure_time >= self.recovery_timeout:
                    self.state = CircuitState.HALF_OPEN
                    self._half_open_trials = 0
                    logger.info(f"🔓 CircuitBreaker[{self.name}] HALF_OPEN 尝试恢复")
                    return True
                return False

            if self.state == CircuitState.HALF_OPEN:
                if self._half_open_trials < self.half_open_max_trials:
                    self._half_open_trials += 1
                    return True
                # 超过半开尝试上限，回到 OPEN
                self.state = CircuitState.OPEN
                self._last_failure_time = time.time()
                return False

            return False

    def _record_success(self):
        """记录成功。"""
        with self._lock:
            self._total_success += 1
            if self.state == CircuitState.HALF_OPEN:
                # 半开状态下成功 → 关闭熔断器
                self.state = CircuitState.CLOSED
                self._failure_count = 0
                self._half_open_trials = 0
                logger.info(f"🔒 CircuitBreaker[{self.name}] 已恢复 CLOSED")

    def _record_failure(self):
        """记录失败。"""
        with self._lock:
            self._total_failure += 1
            self._last_failure_time = time.time()

            if self.state == CircuitState.HALF_OPEN:
                # 半开状态下失败 → 重新开启
                self.state = CircuitState.OPEN
                logger.warning(f"🔴 CircuitBreaker[{self.name}] 半开测试失败，回到 OPEN")
                return

            self._failure_count += 1
            if self._failure_count >= self.failure_threshold:
                self.state = CircuitState.OPEN
                logger.warning(
                    f"🔴 CircuitBreaker[{self.name}] 触发熔断 "
                    f"({self._failure_count}/{self.failure_threshold})"
                )

    def reset(self):
        """手动重置熔断器。"""
        with self._lock:
            self.state = CircuitState.CLOSED
            self._failure_count = 0
            self._half_open_trials = 0

    def status(self) -> dict:
        """熔断器状态。"""
        with self._lock:
            return {
                "name": self.name,
                "state": self.state.value,
                "failure_count": self._failure_count,
                "threshold": self.failure_threshold,
                "total_success": self._total_success,
                "total_failure": self._total_failure,
                "half_open_trials": self._half_open_trials,
            }


class RetryPolicy:
    """
    重试策略（指数退避 + 抖动）。

    Usage:
        policy = RetryPolicy(max_retries=3, base_delay=1.0, max_delay=30.0)
        result = await policy.execute(risky_call, arg1, arg2=value)
    """

    def __init__(
        self,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 30.0,
        jitter: bool = True,
        retryable_exceptions: tuple = (
            ConnectionError, TimeoutError, OSError,
        ),
    ):
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.jitter = jitter
        self.retryable_exceptions = retryable_exceptions
        self._attempts = 0
        self._total_delay = 0.0

    def execute(self, fn: Callable, *args, **kwargs):
        """
        同步执行并带重试。

        Raises:
            最后一次尝试的异常
        """
        import random

        last_exception = None
        self._attempts = 0
        self._total_delay = 0.0

        while self._attempts <= self.max_retries:
            try:
                result = fn(*args, **kwargs)
                if self._attempts > 0:
                    logger.info(
                        f"🔄 重试成功 (attempt={self._attempts}/{self.max_retries})"
                    )
                return result
            except self.retryable_exceptions as e:
                last_exception = e
                self._attempts += 1
                if self._attempts > self.max_retries:
                    break

                delay = min(
                    self.base_delay * (2 ** (self._attempts - 1)),
                    self.max_delay,
                )
                if self.jitter:
                    delay = delay * (0.5 + random.random() * 0.5)
                self._total_delay += delay

                logger.warning(
                    f"🔄 重试 {self._attempts}/{self.max_retries} "
                    f"等待 {delay:.1f}s | {type(e).__name__}: {e}"
                )
                time.sleep(delay)

        raise RetryExhaustedError(
            f"重试耗尽 ({self.max_retries} 次)",
            self._attempts,
            last_exception,
        )

    async def execute_async(self, coro_fn, *args, **kwargs):
        """异步执行并带重试。"""
        import random

        last_exception = None
        self._attempts = 0
        self._total_delay = 0.0

        while self._attempts <= self.max_retries:
            try:
                result = await coro_fn(*args, **kwargs)
                if self._attempts > 0:
                    logger.info(
                        f"🔄 异步重试成功 (attempt={self._attempts}/{self.max_retries})"
                    )
                return result
            except self.retryable_exceptions as e:
                last_exception = e
                self._attempts += 1
                if self._attempts > self.max_retries:
                    break

                delay = min(
                    self.base_delay * (2 ** (self._attempts - 1)),
                    self.max_delay,
                )
                if self.jitter:
                    delay = delay * (0.5 + random.random() * 0.5)
                self._total_delay += delay

                logger.warning(
                    f"🔄 异步重试 {self._attempts}/{self.max_retries} "
                    f"等待 {delay:.1f}s | {type(e).__name__}: {e}"
                )
                await asyncio.sleep(delay)

        raise RetryExhaustedError(
            f"异步重试耗尽 ({self.max_retries} 次)",
            self._attempts,
            last_exception,
        )

    def status(self) -> dict:
        return {
            "max_retries": self.max_retries,
            "base_delay": self.base_delay,
            "attempts": self._attempts,
            "total_delay": round(self._total_delay, 2),
        }


class RetryExhaustedError(Exception):
    """重试耗尽异常。"""

    def __init__(self, message: str, attempts: int, last_exception: Exception | None):
        super().__init__(message)
        self.attempts = attempts
        self.last_exception = last_exception
