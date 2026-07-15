"""
WorkflowViz — DAG 工作流实时可视化引擎。

实时推送 WorkflowExec 的执行状态到前端，通过 SSE (Server-Sent Events)
驱动 Canvas 渲染。零侵入：包装 WorkflowExec.run() 即可。

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
import json
import logging
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from .workflow_engine import (
    WorkflowDAG,
    WorkflowExec,
    WorkflowNode,
    NodeType,
    NodeState,
    WorkflowState,
)
from .execution_pool import ExecutionPool, get_execution_pool

logger = logging.getLogger(__name__)


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
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass


# ═══════════════════════════════════════════════
# WorkflowVisualizer — 核心可视化引擎
# ═══════════════════════════════════════════════

class WorkflowVisualizer:
    """
    DAG 工作流实时可视化器。

    包装 WorkflowExec，在执行过程中通过 SSE 推送节点状态变化，
    前端 Canvas 实时渲染。

    Attributes:
        dag: 工作流 DAG 定义
        pool: 执行线程池
        emitter: 事件发射器
        _exec: WorkflowExec 实例
    """

    def __init__(
        self,
        dag: WorkflowDAG,
        pool: ExecutionPool | None = None,
        title: str = "Workflow DAG",
        auto_open: bool = True,
    ):
        self.dag = dag
        self.pool = pool or get_execution_pool()
        self.title = title
        self.auto_open = auto_open
        self.emitter = EventEmitter()

        self._exec: WorkflowExec | None = None
        self._poll_thread: threading.Thread | None = None
        self._started_at: float | None = None
        self._finished_at: float | None = None

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
        try:
            self._start_server(port, host)
        except KeyboardInterrupt:
            pass

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
            "nodes": nodes,
            "edges": edges,
            "levels": levels,
        }

    def _compute_levels(self) -> dict[str, int]:
        """BFS 计算每个节点的层级（用于布局）。"""
        try:
            order = self.dag.topological_sort()
        except ValueError:
            return {nid: 0 for nid in self.dag.nodes}

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
            from starlette.applications import Starlette
            from starlette.responses import (
                StreamingResponse,
                HTMLResponse,
                JSONResponse,
            )
            from starlette.routing import Route
            import uvicorn
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
            ).replace("{{TITLE}}", self.title)
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

        routes = [
            Route("/", endpoint=handle_root),
            Route("/api/dag", endpoint=handle_dag_structure),
            Route("/api/status", endpoint=handle_status),
            Route("/api/events", endpoint=handle_sse),
        ]

        app = Starlette(debug=False, routes=routes)

        print(f"\n{'='*60}")
        print(f"  🎬 DAG 可视化已启动")
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

        try:
            uvicorn.run(app, host=host, port=port, log_level="warning")
        except KeyboardInterrupt:
            pass


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
#canvas-wrapper{flex:1;position:relative;overflow:hidden}
#dag-canvas{position:absolute;top:0;left:0}
#tooltip{position:absolute;display:none;background:#1c2128;border:1px solid #30363d;border-radius:8px;padding:12px 16px;font-size:12px;z-index:100;pointer-events:none;min-width:200px;box-shadow:0 8px 24px rgba(0,0,0,.4)}
#tooltip .tt-label{font-weight:700;font-size:13px;margin-bottom:4px}
#tooltip .tt-state{font-size:11px}
#tooltip .tt-duration{color:#8b949e;margin-top:4px}
#tooltip .tt-error{color:#f85149;margin-top:4px;max-width:300px;word-wrap:break-word}
#tooltip .tt-output{color:#58a6ff;margin-top:4px;max-width:300px;word-wrap:break-word;max-height:100px;overflow-y:auto}
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
<div id="canvas-wrapper">
  <canvas id="dag-canvas"></canvas>
  <div id="tooltip"></div>
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

// ── Canvas 设置 ──
const canvas = document.getElementById('dag-canvas');
const ctx = canvas.getContext('2d');
const wrapper = document.getElementById('canvas-wrapper');
const tooltip = document.getElementById('tooltip');

// ── 颜色映射 ──
const STATE_COLORS = {
    pending:    {fill:'#21262d',stroke:'#30363d',text:'#8b949e'},
    ready:      {fill:'#1f6feb22',stroke:'#1f6feb',text:'#58a6ff'},
    running:    {fill:'#1f6feb44',stroke:'#58a6ff',text:'#ffffff',glow:true},
    completed:  {fill:'#23863622',stroke:'#3fb950',text:'#3fb950'},
    failed:     {fill:'#da363322',stroke:'#f85149',text:'#f85149'},
    skipped:    {fill:'#161b22',stroke:'#484f58',text:'#484f58'},
    cancelled:  {fill:'#161b22',stroke:'#8b949e',text:'#8b949e'}
};

const NODE_W = 180, NODE_H = 56, H_GAP = 220, V_GAP = 80, PAD = 40;
const ROUND_R = 8;

// ── 布局计算 ──
function layout() {
    const levels = DAG.levels || {};
    // 按 level 分组
    const levelGroups = {};
    for (const n of DAG.nodes) {
        const lvl = levels[n.id] !== undefined ? levels[n.id] : 0;
        if (!levelGroups[lvl]) levelGroups[lvl] = [];
        levelGroups[lvl].push(n);
    }
    const maxLevel = Math.max(...Object.keys(levelGroups).map(Number), 0);

    // 分配位置
    for (const [lvl, nodes] of Object.entries(levelGroups)) {
        const y = PAD + Number(lvl) * (NODE_H + V_GAP);
        const totalW = nodes.length * (NODE_W + H_GAP) - H_GAP;
        const startX = PAD;

        nodes.forEach((n, i) => {
            n._x = startX + i * (NODE_W + H_GAP);
            n._y = y;
        });
    }

    // 坐标映射
    const pos = {};
    for (const n of DAG.nodes) {
        pos[n.id] = {x: n._x, y: n._y};
    }

    // canvas 尺寸
    const maxNodesInLevel = Math.max(...Object.values(levelGroups).map(g => g.length), 1);
    canvas.width = PAD * 2 + maxNodesInLevel * (NODE_W + H_GAP);
    canvas.height = PAD * 2 + (maxLevel + 1) * (NODE_H + V_GAP);

    return pos;
}

let nodePositions = {};
let nodeStates = {};
let nodeOutputs = {};

// 初始化状态
for (const n of DAG.nodes) {
    nodeStates[n.id] = 'pending';
}
nodePositions = layout();

// ── 绘制 ──
function draw() {
    const w = canvas.width, h = canvas.height;
    ctx.clearRect(0, 0, w, h);

    // 网格背景
    ctx.strokeStyle = '#1a2230';
    ctx.lineWidth = 0.5;
    for (let x = 0; x < w; x += 40) { ctx.beginPath(); ctx.moveTo(x,0); ctx.lineTo(x,h); ctx.stroke(); }
    for (let y = 0; y < h; y += 40) { ctx.beginPath(); ctx.moveTo(0,y); ctx.lineTo(w,y); ctx.stroke(); }

    // 边
    for (const e of DAG.edges) {
        const from = nodePositions[e.from], to = nodePositions[e.to];
        if (!from || !to) continue;

        const x1 = from.x + NODE_W / 2, y1 = from.y + NODE_H;
        const x2 = to.x + NODE_W / 2, y2 = to.y;

        ctx.beginPath();
        ctx.strokeStyle = '#30363d';
        ctx.lineWidth = 1.5;
        ctx.moveTo(x1, y1);
        ctx.lineTo(x2, y2);

        // 箭头
        const angle = Math.atan2(y2 - y1, x2 - x1);
        const arrowLen = 8;
        ctx.lineTo(
            x2 - arrowLen * Math.cos(angle - 0.5),
            y2 - arrowLen * Math.sin(angle - 0.5)
        );
        ctx.moveTo(x2, y2);
        ctx.lineTo(
            x2 - arrowLen * Math.cos(angle + 0.5),
            y2 - arrowLen * Math.sin(angle + 0.5)
        );
        ctx.stroke();

        // 条件标签
        if (e.condition) {
            const midX = (x1 + x2) / 2, midY = (y1 + y2) / 2;
            ctx.fillStyle = '#8b949e';
            ctx.font = '10px system-ui';
            ctx.fillText(e.condition, midX + 6, midY - 6);
        }
    }

    // 节点
    for (const n of DAG.nodes) {
        const pos = nodePositions[n.id];
        if (!pos) continue;

        const state = nodeStates[n.id] || 'pending';
        const colors = STATE_COLORS[state] || STATE_COLORS.pending;

        // 发光效果（运行中）
        if (colors.glow) {
            const t = Date.now() / 1000;
            const alpha = 0.3 + 0.2 * Math.sin(t * 3);
            ctx.shadowColor = `rgba(88, 166, 255, ${alpha})`;
            ctx.shadowBlur = 16;
        }

        // 节点背景
        const x = pos.x, y = pos.y;
        ctx.beginPath();
        ctx.fillStyle = colors.fill;
        ctx.strokeStyle = colors.stroke;
        ctx.lineWidth = 2;
        roundRect(ctx, x, y, NODE_W, NODE_H, ROUND_R);
        ctx.fill();
        ctx.stroke();

        ctx.shadowColor = 'transparent';
        ctx.shadowBlur = 0;

        // 图标 + 类型
        const typeIcons = {task:'⚙',condition:'◇',loop:'↻',parallel:'∥',wait:'⏳',end:'⏹'};
        const icon = typeIcons[n.type] || '⚙';
        ctx.fillStyle = colors.text;
        ctx.font = 'bold 13px system-ui';
        ctx.fillText(icon, x + 10, y + 22);

        // 标签
        const label = n.label || n.id;
        ctx.fillStyle = colors.text;
        ctx.font = '12px system-ui';
        const truncated = label.length > 18 ? label.slice(0,17)+'…' : label;
        ctx.fillText(truncated, x + 30, y + 22);

        // 状态文字
        ctx.fillStyle = colors.text;
        ctx.font = '10px system-ui';
        ctx.globalAlpha = 0.7;
        ctx.fillText(state.toUpperCase(), x + 10, y + 44);
        ctx.globalAlpha = 1.0;
    }
}

function roundRect(ctx, x, y, w, h, r) {
    ctx.moveTo(x+r, y); ctx.lineTo(x+w-r, y);
    ctx.quadraticCurveTo(x+w, y, x+w, y+r);
    ctx.lineTo(x+w, y+h-r);
    ctx.quadraticCurveTo(x+w, y+h, x+w-r, y+h);
    ctx.lineTo(x+r, y+h);
    ctx.quadraticCurveTo(x, y+h, x, y+h-r);
    ctx.lineTo(x, y+r);
    ctx.quadraticCurveTo(x, y, x+r, y);
}

// ── 鼠标交互 ──
let hoveredNode = null;

canvas.addEventListener('mousemove', (e) => {
    const rect = canvas.getBoundingClientRect();
    const mx = e.clientX - rect.left, my = e.clientY - rect.top;

    hoveredNode = null;
    for (const n of DAG.nodes) {
        const pos = nodePositions[n.id];
        if (!pos) continue;
        if (mx >= pos.x && mx <= pos.x + NODE_W &&
            my >= pos.y && my <= pos.y + NODE_H) {
            hoveredNode = n;
            break;
        }
    }

    if (hoveredNode) {
        const state = nodeStates[hoveredNode.id] || 'pending';
        const output = nodeOutputs[hoveredNode.id];
        const colors = STATE_COLORS[state];
        tooltip.style.display = 'block';
        tooltip.style.left = (e.clientX + 15) + 'px';
        tooltip.style.top = (e.clientY - 10) + 'px';
        tooltip.innerHTML = `
            <div class="tt-label">${hoveredNode.label||hoveredNode.id}</div>
            <div class="tt-state" style="color:${colors?colors.text:'#8b949e'}">● ${state.toUpperCase()}</div>
            <div class="tt-state" style="color:#8b949e">类型: ${hoveredNode.type}</div>
            ${output ? `<div class="tt-output">📤 ${escapeHtml(output)}</div>` : ''}
        `;
    } else {
        tooltip.style.display = 'none';
    }
});

canvas.addEventListener('mouseleave', () => { tooltip.style.display = 'none'; });

function escapeHtml(s) {
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
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
    draw();
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

// ── 窗口缩放 ──
function resize() {
    const w = wrapper.clientWidth;
    const h = wrapper.clientHeight;
    canvas.style.width = w + 'px';
    canvas.style.height = h + 'px';
    // 居中
    const scale = Math.min(1, w / canvas.width, (h - 60) / canvas.height);
    canvas.style.transform = `translate(${(w-canvas.width*scale)/2}px,${(h-canvas.height*scale)/2}px) scale(${scale})`;
}

window.addEventListener('resize', resize);
resize();
draw();
</script>
</body>
</html>"""
