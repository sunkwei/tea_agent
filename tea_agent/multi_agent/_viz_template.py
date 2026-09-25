"""可视化页面 HTML 模板（由 workflow_viz.py 抽出，纯数据、零依赖）。"""


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
