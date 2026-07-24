"""
WorkflowViz — DAG 工作流实时可视化引擎。

实时推送 WorkflowExec 的执行状态到前端，通过 SSE (Server-Sent Events)
驱动前端 <img> 标签，服务端通过 Graphviz dot 渲染 SVG 实时更新。

用法:
    viz = WorkflowVisualizer(dag, pool=pool)
    viz.run(context, port=8084)      # 启动 HTTP + SSE 服务器
    # 浏览器打开 http://127.0.0.1:8084

架构:
    WorkflowExec (后台线程)
        │
        ▼
    EventEmitter (状态变化事件)
        │
        ▼
    SSE Stream ────► 浏览器 Canvas 实时渲染
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import threading
import time
import uuid

from .execution_pool import ExecutionPool, get_execution_pool
from .workflow_engine import (
    WorkflowDAG,
    WorkflowExec,
    WorkflowState,
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════
# DagVizRegistry — 全局可视化实例注册表
# ═══════════════════════════════════════════════

class DagVizRegistry:
    """全局 DAG 可视化实例注册表。

    使 tea_agent server 能够通过 viz_id 查找活跃的 WorkflowVisualizer
    实例，从而提供 /dag/{viz_id} 路由和 SSE 事件流。
    """
    _instances: dict[str, WorkflowVisualizer] = {}

    @classmethod
    def register(cls, viz_id: str, viz: WorkflowVisualizer):
        """注册可视化实例。"""
        cls._instances[viz_id] = viz
        logger.info(f"DagViz 已注册: {viz_id}")

    @classmethod
    def get(cls, viz_id: str) -> WorkflowVisualizer | None:
        """获取可视化实例。"""
        return cls._instances.get(viz_id)

    @classmethod
    def remove(cls, viz_id: str):
        """移除可视化实例。"""
        cls._instances.pop(viz_id, None)
        logger.debug(f"DagViz 已移除: {viz_id}")

    @classmethod
    def list_ids(cls) -> list[str]:
        """列出所有活跃的 viz_id。"""
        return list(cls._instances.keys())

    @classmethod
    def get_status_snapshot(cls, viz_id: str) -> dict | None:
        """
        获取 DAG 状态快照（JSON 格式），供轮询端点使用。

        返回:
            {
                "viz_id": str,
                "title": str,
                "state": "running"|"completed"|"failed"|...,
                "progress": {"completed": int, "total": int},
                "started_at": float | None,
                "nodes": [{"id": str, "label": str, "type": str, "state": str,
                           "duration": float, "error": str | None, "level": int}],
                "edges": [{"from": str, "to": str, "condition_key": str | None}],
                "dot_available": bool,
            }
            或 None 如果 viz_id 未找到。
        """
        viz = cls._instances.get(viz_id)
        if not viz:
            return None

        # 构建节点状态列表
        nodes = []
        levels = viz._compute_levels()

        if viz._exec:
            results = viz._exec.results
            wf_state = viz._exec.state.value
        else:
            results = {}
            wf_state = "pending"

        completed = 0
        total = len(viz.dag.nodes)

        for nid, node in viz.dag.nodes.items():
            nr = results.get(nid)
            state = nr.state.value if nr else "pending"
            if state in ("completed", "failed", "skipped"):
                completed += 1

            nodes.append({
                "id": nid,
                "label": node.label or nid,
                "type": node.type.value if hasattr(node.type, 'value') else str(node.type),
                "state": state,
                "duration": round(nr.duration, 3) if nr and nr.duration else 0,
                "error": nr.error if nr else None,
                "level": levels.get(nid, 0),
            })

        edges = []
        for e in viz.dag.edges:
            edges.append({
                "from": e["from"],
                "to": e["to"],
                "condition_key": e.get("condition_key"),
            })

        from tea_agent.multi_agent.dag_dot_renderer import check_dot_available

        return {
            "viz_id": viz_id,
            "title": viz.title,
            "state": wf_state,
            "progress": {"completed": completed, "total": total},
            "started_at": viz._started_at,
            "finished_at": viz._finished_at,
            "nodes": nodes,
            "edges": edges,
            "dot_available": check_dot_available(),
        }


def get_viz_html(dag_structure: dict, title: str = "Workflow DAG", viz_id: str = "") -> str:
    """生成 DAG 可视化 HTML 页面。

    供 server 路由使用，将 DAG 结构数据注入模板。

    Args:
        dag_structure: _build_dag_structure() 的输出
        title: 页面标题
        viz_id: DAG 可视化实例 ID，用于 SSR 时注入图片 URL

    Returns:
        完整的 HTML 字符串
    """
    return _VIZ_HTML_TEMPLATE.replace(
        "{{DAG_STRUCTURE}}",
        json.dumps(dag_structure, ensure_ascii=False),
    ).replace("{{TITLE}}", title).replace("{{VIZ_ID}}", viz_id)


# ═══════════════════════════════════════════════
# Event Emitter — 轻量事件发布
# ═══════════════════════════════════════════════

class EventEmitter:
    """线程安全的事件发射器。"""

    def __init__(self):
        self._listeners: list[asyncio.Queue] = []
        self._lock = threading.Lock()

    def subscribe(self) -> asyncio.Queue:
        """订阅事件流，返回队列。"""
        q: asyncio.Queue = asyncio.Queue()
        with self._lock:
            self._listeners.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue):
        with self._lock:
            if q in self._listeners:
                self._listeners.remove(q)

    def emit(self, event: dict):
        """向所有订阅者发送事件。"""
        with self._lock:
            listeners = list(self._listeners)

        for q in listeners:
            with contextlib.suppress(asyncio.QueueFull):
                q.put_nowait(event)


# ═══════════════════════════════════════════════
# WorkflowVisualizer — 核心可视化引擎
# ═══════════════════════════════════════════════

class WorkflowVisualizer:
    """
    DAG 工作流实时可视化器。

    包装 WorkflowExec，在执行过程中通过 SSE 推送节点状态变化，
    前端 Canvas 实时渲染。

    两种运行模式：
    - run()：独立模式，启动自己的 HTTP 服务器
    - run_registered()：集成模式，注册到 DagVizRegistry，由主服务器提供路由

    Attributes:
        dag: 工作流 DAG 定义
        pool: 执行线程池
        emitter: 事件发射器
        viz_id: 唯一标识（用于注册表）
        _exec: WorkflowExec 实例
    """

    def __init__(
        self,
        dag: WorkflowDAG,
        pool: ExecutionPool | None = None,
        title: str = "Workflow DAG",
        auto_open: bool = True,
        auto_register: bool = True,
    ):
        self.dag = dag
        self.pool = pool or get_execution_pool()
        self.title = title
        self.auto_open = auto_open
        self.emitter = EventEmitter()
        self.viz_id = uuid.uuid4().hex[:12]
        self._auto_register = auto_register

        self._exec: WorkflowExec | None = None
        self._poll_thread: threading.Thread | None = None
        self._started_at: float | None = None
        self._finished_at: float | None = None

    def run_registered(
        self,
        context: dict | None = None,
    ) -> str:
        """
        集成模式：注册到 DagVizRegistry，不启动独立服务器。

        由主 tea_agent server 通过 /dag/{viz_id} 路由提供可视化页面。
        工具调用此方法后，返回 viz_id，前端通过 SSE 事件嵌入 IFRAME。

        Args:
            context: 工作流初始上下文

        Returns:
            viz_id 字符串（用于构造 URL）
        """
        self._started_at = time.time()

        # 注册到全局注册表
        if self._auto_register:
            DagVizRegistry.register(self.viz_id, self)

        # 预推送 DAG 结构
        dag_structure = self._build_dag_structure()
        self.emitter.emit({
            "type": "dag_structure",
            "data": dag_structure,
            "timestamp": time.time(),
        })

        logger.info(f"DAG viz 已注册: {self.viz_id} | "
                    f"{len(dag_structure['nodes'])} 节点, "
                    f"{len(dag_structure['edges'])} 边")

        # 在后台线程执行工作流
        self._exec = WorkflowExec(self.dag, pool=self.pool)
        exec_thread = threading.Thread(
            target=self._exec.run,
            kwargs={"initial_context": context},
            daemon=True,
        )
        exec_thread.start()

        # 轮询状态变化
        self._poll_thread = threading.Thread(
            target=self._poll_state,
            daemon=True,
        )
        self._poll_thread.start()

        # 后台等待完成 + 清理
        def _cleanup():
            exec_thread.join()
            self._finished_at = time.time()
            if self._exec:
                self._push_full_state()
                self.emitter.emit({
                    "type": "workflow_end",
                    "data": {
                        "state": self._exec.state.value,
                        "duration": self._exec.duration,
                        "started_at": self._started_at,
                        "finished_at": self._finished_at,
                    },
                    "timestamp": time.time(),
                })
            # 延迟清理，给 SSE 客户端时间接收最终事件
            time.sleep(5)
            if self._auto_register:
                DagVizRegistry.remove(self.viz_id)

        threading.Thread(target=_cleanup, daemon=True).start()

        return self.viz_id

    def get_viz_url(self, host: str = "127.0.0.1", port: int = 8080) -> str:
        """获取可视化页面 URL。

        Args:
            host: 服务器地址
            port: 服务器端口

        Returns:
            完整 URL，如 http://127.0.0.1:8080/dag/abc123
        """
        return f"http://{host}:{port}/dag/{self.viz_id}"

    def run(
        self,
        context: dict | None = None,
        port: int = 8084,
        host: str = "127.0.0.1",
    ) -> dict:
        """
        启动可视化+执行。

        1. 启动 HTTP/SSE 服务器
        2. 在后台线程执行工作流
        3. 轮询状态变化并通过 SSE 推送
        4. 阻塞直到工作流完成

        Returns:
            WorkflowExec.status() 结果字典
        """
        self._started_at = time.time()

        # 预推送 DAG 结构
        dag_structure = self._build_dag_structure()
        logger.info(f"DAG 结构: {len(dag_structure['nodes'])} 节点, "
                    f"{len(dag_structure['edges'])} 边, "
                    f"levels={dag_structure.get('levels',{})}")
        print(f"  [Viz] DAG 结构: {len(dag_structure['nodes'])} 节点, "
              f"{len(dag_structure['edges'])} 边")
        self.emitter.emit({
            "type": "dag_structure",
            "data": dag_structure,
            "timestamp": time.time(),
        })

        # 在后台线程执行工作流
        self._exec = WorkflowExec(self.dag, pool=self.pool)
        exec_thread = threading.Thread(
            target=self._exec.run,
            kwargs={"initial_context": context},
            daemon=True,
        )
        exec_thread.start()

        # 轮询状态变化
        self._poll_thread = threading.Thread(
            target=self._poll_state,
            daemon=True,
        )
        self._poll_thread.start()

        # 启动 HTTP + SSE 服务器
        with contextlib.suppress(KeyboardInterrupt):
            self._start_server(port, host)

        exec_thread.join(timeout=5)
        self._finished_at = time.time()

        # 推送最终状态
        if self._exec:
            self._push_full_state()
            self.emitter.emit({
                "type": "workflow_end",
                "data": {
                    "state": self._exec.state.value,
                    "duration": self._exec.duration,
                    "started_at": self._started_at,
                    "finished_at": self._finished_at,
                },
                "timestamp": time.time(),
            })

        return self._exec.status() if self._exec else {}

    def _poll_state(self):
        """后台轮询工作流状态，检测变化后推送。"""
        prev_states: dict[str, str] = {}
        prev_outputs: dict[str, object] = {}

        while self._exec and self._exec.state in (
            WorkflowState.PENDING,
            WorkflowState.RUNNING,
        ):
            try:
                results = self._exec.results
                for nid, nr in results.items():
                    new_state = nr.state.value
                    old_state = prev_states.get(nid)
                    if new_state != old_state:
                        prev_states[nid] = new_state
                        self.emitter.emit({
                            "type": "node_state",
                            "data": {
                                "node_id": nid,
                                "state": new_state,
                                "label": self.dag.get_node(nid).label if self.dag.get_node(nid) else nid,
                                "duration": nr.duration,
                                "error": nr.error,
                                "retries": nr.retries,
                                "started_at": nr.started_at,
                                "finished_at": nr.finished_at,
                            },
                            "timestamp": time.time(),
                        })

                    # 输出变化
                    new_output = nr.output
                    if new_output != prev_outputs.get(nid):
                        prev_outputs[nid] = new_output
                        if new_output:
                            self.emitter.emit({
                                "type": "node_output",
                                "data": {
                                    "node_id": nid,
                                    "output": json.dumps(new_output, default=str, ensure_ascii=False),
                                },
                                "timestamp": time.time(),
                            })

                # 工作流级别事件
                if self._exec.state == WorkflowState.RUNNING and not getattr(self, '_sent_running', False):
                    self._sent_running = True
                    self.emitter.emit({
                        "type": "workflow_start",
                        "data": {"state": "running"},
                        "timestamp": time.time(),
                    })

                time.sleep(0.25)  # 250ms 轮询间隔

            except Exception as e:
                logger.warning(f"轮询异常: {e}")
                time.sleep(0.5)

    def _push_full_state(self):
        """推送完整状态快照。"""
        if not self._exec:
            return
        for nid, nr in self._exec.results.items():
            node = self.dag.get_node(nid)
            self.emitter.emit({
                "type": "node_state",
                "data": {
                    "node_id": nid,
                    "state": nr.state.value,
                    "label": node.label if node else nid,
                    "duration": nr.duration,
                    "error": nr.error,
                    "retries": nr.retries,
                    "started_at": nr.started_at,
                    "finished_at": nr.finished_at,
                },
                "timestamp": time.time(),
            })

    def _build_dag_structure(self) -> dict:
        """构建 DAG 结构数据供前端渲染。"""
        nodes = []
        for nid, node in self.dag.nodes.items():
            nodes.append({
                "id": nid,
                "type": node.type.value,
                "label": node.label or nid,
                "state": "pending",
                "config": node.config,
            })

        # 简单分层布局：按拓扑排序层
        levels = self._compute_levels()

        edges = []
        for e in self.dag.edges:
            edges.append({
                "from": e["from"],
                "to": e["to"],
                "condition": e.get("condition_key"),
            })

        return {
            "workflow_id": self.dag.workflow_id,
            "title": self.title,
            "viz_id": self.viz_id,
            "nodes": nodes,
            "edges": edges,
            "levels": levels,
        }

    def _compute_levels(self) -> dict[str, int]:
        """BFS 计算每个节点的层级（用于布局）。"""
        try:
            order = self.dag.topological_sort()
        except ValueError:
            return dict.fromkeys(self.dag.nodes, 0)

        # 从拓扑序计算层级：节点的 level = max(前驱 level) + 1
        levels: dict[str, int] = {}
        for nid in order:
            incoming = self.dag.get_edges_to(nid)
            pred_levels = [
                levels.get(e["from"], 0)
                for e in incoming
                if e.get("from") in levels
            ]
            levels[nid] = (max(pred_levels) + 1) if pred_levels else 0

        return levels

    # ── HTTP + SSE 服务器 ─────────────────────

    def _start_server(self, port: int, host: str):
        """启动 Starlette HTTP 服务器。"""
        try:
            import uvicorn
            from starlette.applications import Starlette
            from starlette.responses import (
                HTMLResponse,
                JSONResponse,
                Response,
                StreamingResponse,
            )
            from starlette.routing import Route
        except ImportError:
            logger.error("需要安装 starlette 和 uvicorn: pip install starlette uvicorn")
            return

        emitter = self.emitter
        dag_structure = self._build_dag_structure()

        async def handle_root(request):
            """GET / — 可视化页面"""
            html = _VIZ_HTML_TEMPLATE.replace(
                "{{DAG_STRUCTURE}}",
                json.dumps(dag_structure, ensure_ascii=False),
            ).replace("{{TITLE}}", self.title).replace("{{VIZ_ID}}", self.viz_id)
            return HTMLResponse(html)

        async def handle_dag_structure(request):
            """GET /api/dag — DAG 结构"""
            return JSONResponse(dag_structure)

        async def handle_status(request):
            """GET /api/status — 当前执行状态"""
            if self._exec:
                return JSONResponse(self._exec.status())
            return JSONResponse({"state": "pending"})

        async def handle_sse(request):
            """GET /api/events — SSE 事件流"""
            q = emitter.subscribe()

            async def event_stream():
                try:
                    # 先推送全量状态
                    if self._exec:
                        for nid, nr in self._exec.results.items():
                            node = self.dag.get_node(nid)
                            yield (
                                "data: "
                                + json.dumps({
                                    "type": "node_state",
                                    "data": {
                                        "node_id": nid,
                                        "state": nr.state.value,
                                        "label": node.label if node else nid,
                                        "duration": nr.duration,
                                        "error": nr.error,
                                        "started_at": nr.started_at,
                                    },
                                    "timestamp": time.time(),
                                }, ensure_ascii=False)
                                + "\n\n"
                            )

                    while True:
                        if await request.is_disconnected():
                            break
                        try:
                            event = await asyncio.wait_for(q.get(), timeout=1.0)
                            yield "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"
                        except asyncio.TimeoutError:
                            # 心跳
                            yield ": heartbeat\n\n"
                finally:
                    emitter.unsubscribe(q)

            return StreamingResponse(
                event_stream(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                },
            )

        async def handle_image(request):
            """GET /dag/{viz_id}/image — 返回 dot 渲染的 SVG/PNG/DOT"""
            fmt = request.query_params.get("format", "svg")

            from tea_agent.multi_agent.dag_dot_renderer import (
                check_dot_available,
                dag_to_dot,
                render_dot_to_png,
                render_dot_to_svg,
            )
            node_states = self._exec.results if self._exec else {}
            dot_source = dag_to_dot(self.dag, node_states=node_states, title=self.title)

            if fmt == "dot":
                return Response(dot_source, media_type="text/plain")

            if not check_dot_available():
                return Response(dot_source, media_type="text/plain",
                                headers={"X-Fallback": "dot-not-available"})

            try:
                if fmt == "png":
                    img_data = render_dot_to_png(dot_source)
                    mime = "image/png"
                else:
                    img_data = render_dot_to_svg(dot_source)
                    mime = "image/svg+xml"
                if img_data is None:
                    return Response(dot_source, media_type="text/plain",
                                    headers={"X-Fallback": "dot-render-failed"})
                return Response(img_data, media_type=mime)
            except Exception as e:
                return JSONResponse({"error": str(e), "dot_source": dot_source}, status_code=500)

        routes = [
            Route("/", endpoint=handle_root),
            Route("/dag/{viz_id}/image", endpoint=handle_image),
            Route("/api/dag", endpoint=handle_dag_structure),
            Route("/api/status", endpoint=handle_status),
            Route("/api/events", endpoint=handle_sse),
        ]

        app = Starlette(debug=False, routes=routes)

        print(f"\n{'='*60}")
        print("  🎬 DAG 可视化已启动")
        print(f"  📍 http://{host}:{port}")
        print(f"  📊 {self.title}")
        print(f"  📦 {len(dag_structure['nodes'])} 节点 · {len(dag_structure['edges'])} 边")
        print(f"{'='*60}\n")

        if self.auto_open:
            import webbrowser
            threading.Thread(
                target=lambda: webbrowser.open(f"http://{host}:{port}"),
                daemon=True,
            ).start()

        with contextlib.suppress(KeyboardInterrupt):
            uvicorn.run(app, host=host, port=port, log_level="warning")


# ═══════════════════════════════════════════════
# HTML 模板（内嵌，无需外部文件）
# ═══════════════════════════════════════════════

_VIZ_HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{{TITLE}}</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Segoe UI',system-ui,sans-serif;background:#0d1117;color:#c9d1d9;overflow:hidden;height:100vh;display:flex;flex-direction:column}
#header{display:flex;align-items:center;justify-content:space-between;padding:12px 20px;background:#161b22;border-bottom:1px solid #30363d;flex-shrink:0}
#header h1{font-size:18px;font-weight:600}
#status-bar{display:flex;gap:12px;align-items:center;font-size:13px}
.badge{padding:3px 10px;border-radius:12px;font-weight:600;font-size:12px}
.badge-pending{background:#30363d;color:#8b949e}
.badge-running{background:#1f6feb33;color:#58a6ff}
.badge-completed{background:#23863633;color:#3fb950}
.badge-failed{background:#da363333;color:#f85149}
#img-wrapper{flex:1;display:flex;align-items:center;justify-content:center;overflow:auto;background:#0d1117}
#dag-img{max-width:100%;max-height:100%;object-fit:contain}
#legend{position:absolute;bottom:16px;right:16px;display:flex;gap:8px;flex-wrap:wrap;font-size:11px;opacity:.85}
.legend-item{display:flex;align-items:center;gap:4px}
.legend-dot{width:10px;height:10px;border-radius:3px}
</style>
</head>
<body>
<div id="header">
  <h1>📊 {{TITLE}}</h1>
  <div id="status-bar">
    <span id="wf-state" class="badge badge-pending">PENDING</span>
    <span id="wf-timer">00:00</span>
    <span id="wf-progress">0/0</span>
  </div>
</div>
<div id="img-wrapper">
  <img id="dag-img" src="/dag/{{VIZ_ID}}/image?format=svg" alt="DAG 流程图" style="display:none">
  <div id="legend">
    <div class="legend-item"><div class="legend-dot" style="background:#30363d"></div>待执行</div>
    <div class="legend-item"><div class="legend-dot" style="background:#1f6feb"></div>运行中</div>
    <div class="legend-item"><div class="legend-dot" style="background:#3fb950"></div>已完成</div>
    <div class="legend-item"><div class="legend-dot" style="background:#f85149"></div>失败</div>
    <div class="legend-item"><div class="legend-dot" style="background:#8b949e"></div>跳过</div>
  </div>
</div>
<script>
// ── DAG 数据 ──
const DAG = {{DAG_STRUCTURE}};
console.log('[DAG Viz] 已加载:', DAG.nodes?.length, '节点,', DAG.edges?.length, '边');
if (!DAG.nodes || !DAG.nodes.length) {
    document.body.innerHTML = '<div style="color:#f85149;padding:40px;font-size:16px">❌ DAG 数据为空，请检查后端</div>';
    throw new Error('DAG 数据为空');
}

// ── DAG SVG 图片更新 ──
const dagImg = document.getElementById('dag-img');

let nodeStates = {};
let nodeOutputs = {};

// 初始化状态
for (const n of DAG.nodes) {
    nodeStates[n.id] = 'pending';
}

function refreshDagImage() {
    dagImg.src = '/dag/{{VIZ_ID}}/image?format=svg&t=' + Date.now();
}

// 图片加载完成后显示
if (dagImg) {
    dagImg.onload = function() { dagImg.style.display = 'block'; };
    dagImg.onerror = function() { dagImg.style.display = 'block'; dagImg.alt = 'DAG 渲染失败 (Graphviz dot 不可用?)'; };
}

// ── SSE 连接 ──
const evtSource = new EventSource('/api/events');
let completedCount = 0;
const totalNodes = DAG.nodes.length;

evtSource.addEventListener('node_state', (e) => {
    const msg = JSON.parse(e.data);
    const d = msg.data;
    nodeStates[d.node_id] = d.state;
    if (d.state === 'completed' || d.state === 'failed' || d.state === 'skipped') {
        completedCount++;
    }
    updateUI(d);
    refreshDagImage();
});

evtSource.addEventListener('node_output', (e) => {
    const msg = JSON.parse(e.data);
    nodeOutputs[msg.data.node_id] = msg.data.output;
});

evtSource.addEventListener('workflow_start', () => {
    document.getElementById('wf-state').textContent = 'RUNNING';
    document.getElementById('wf-state').className = 'badge badge-running';
});

evtSource.addEventListener('workflow_end', (e) => {
    const msg = JSON.parse(e.data);
    const state = msg.data.state;
    const el = document.getElementById('wf-state');
    el.textContent = state.toUpperCase();
    el.className = 'badge ' + (state === 'completed' ? 'badge-completed' : 'badge-failed');
    evtSource.close();
});

evtSource.onerror = () => {
    // SSE 连接断开（正常，工作流结束）
};

// ── UI 更新 ──
let startTime = Date.now();
let timerInterval = null;

function updateUI(data) {
    // 进度
    document.getElementById('wf-progress').textContent = `${completedCount}/${totalNodes}`;

    // 计时器
    if (!timerInterval) {
        timerInterval = setInterval(() => {
            const elapsed = Math.floor((Date.now() - startTime) / 1000);
            const m = Math.floor(elapsed/60).toString().padStart(2,'0');
            const s = (elapsed%60).toString().padStart(2,'0');
            document.getElementById('wf-timer').textContent = `${m}:${s}`;
        }, 250);
    }
}

// ── 初始加载 ──
refreshDagImage();
</script>
</body>
</html>"""
