"""
DAG 可视化端到端演示 — 模拟完整工作流
"""
import sys, os, time, json, threading, uuid

# 确保路径正确
os.chdir(os.path.dirname(os.path.abspath(__file__)))

from tea_agent.multi_agent.workflow_engine import (
    WorkflowDAG, WorkflowNode, WorkflowExec, NodeType, NodeState, NodeResult, WorkflowState
)
from tea_agent.multi_agent.workflow_viz import WorkflowVisualizer, DagVizRegistry

print("=" * 60)
print("🔧 构建 DAG 工作流 (10 节点)")
print("=" * 60)

dag = WorkflowDAG()

# 定义节点
nodes_def = [
    ("init",      NodeType.TASK,      "🚀 初始化环境"),
    ("fetch",     NodeType.TASK,      "📥 拉取数据"),
    ("validate",  NodeType.CONDITION, "🔍 数据校验"),
    ("clean",     NodeType.TASK,      "🧹 数据清洗"),
    ("transform", NodeType.TASK,      "🔄 特征变换"),
    ("train",     NodeType.TASK,      "🧠 模型训练"),
    ("eval",      NodeType.TASK,      "📊 模型评估"),
    ("deploy",    NodeType.TASK,      "🚀 部署上线"),
    ("notify",    NodeType.TASK,      "✉️ 发送通知"),
    ("end",       NodeType.END,       "✅ 完成"),
]
for nid, ntype, label in nodes_def:
    dag.add_node(WorkflowNode(nid, ntype, label=label))

# 连线
edges = [
    ("init", "fetch"), ("fetch", "validate"),
    ("validate", "clean", "valid"), ("validate", "end", "invalid"),
    ("clean", "transform"), ("transform", "train"),
    ("train", "eval"), ("eval", "deploy"),
    ("deploy", "notify"), ("notify", "end"),
]
for e in edges:
    dag.add_edge(e[0], e[1], condition_key=e[2] if len(e) > 2 else None)

print(f"   ✅ {len(dag.nodes)} 节点, {len(dag.edges)} 条边")
print(f"   拓扑顺序: {' → '.join(dag.topological_sort()[:6])}...")

# ═══ 检查 dot ═══
from tea_agent.multi_agent.dag_dot_renderer import check_dot_available, dag_to_dot, render_dot_to_svg
dot_ok = check_dot_available()
print(f"\n📐 Graphviz dot: {'✅ 可用' if dot_ok else '❌ 不可用（将返回 DOT 源码）'}")

# ═══ 创建 WorkflowVisualizer + 手动注册 ═══
viz = WorkflowVisualizer(dag, title="🎯 ML 训练流水线", auto_open=False, auto_register=False)
viz_id = viz.viz_id
DagVizRegistry.register(viz_id, viz)
print(f"\n📌 已注册 viz_id: {viz_id}")

# ═══ 创建 WorkflowExec 并挂到 viz ═══
viz._started_at = time.time()
viz._exec = WorkflowExec(dag)

# 初始化所有节点为 PENDING
for nid in dag.nodes:
    viz._exec.results[nid] = NodeResult(node_id=nid)

# 推送初始 DAG 结构
viz.emitter.emit({
    "type": "dag_structure",
    "data": viz._build_dag_structure(),
    "timestamp": time.time(),
})

# ═══ 测试 dot 渲染 ═══
print(f"\n{'=' * 60}")
print("📐 测试 SVG 渲染")
print("=" * 60)

dot = dag_to_dot(dag, viz._exec.results, viz.title)
if dot_ok:
    svg = render_dot_to_svg(dot)
    if svg:
        svg_path = "demo_dag_output.svg"
        with open(svg_path, "w", encoding="utf-8") as f:
            f.write(svg)
        print(f"   ✅ SVG 已生成: {svg_path} ({len(svg)} 字符)")
    else:
        print("   ⚠️ SVG 渲染失败")
else:
    print(f"   ⚠️ dot 不可用，DOT 源码长度: {len(dot)}")

# ═══ 检查状态端点输出 ═══
print(f"\n{'=' * 60}")
print("📊 测试 /dag/{viz_id}/status 端点数据")
print("=" * 60)
snap = DagVizRegistry.get_status_snapshot(viz_id)
print(f"   state:    {snap['state']}")
print(f"   progress: {snap['progress']['completed']}/{snap['progress']['total']}")
print(f"   nodes:    {len(snap['nodes'])}")
print(f"   edges:    {len(snap['edges'])}")
for n in snap['nodes'][:4]:
    print(f"     • {n['label']:20s}  state={n['state']:10s}  level={n['level']}")

# ═══ 模拟逐步执行 ═══
print(f"\n{'=' * 60}")
print("⏳ 模拟工作流执行（每 2 秒推进一个节点）")
print("=" * 60)

node_order = ["init", "fetch", "validate", "clean", "transform",
              "train", "eval", "deploy", "notify", "end"]

for i, nid in enumerate(node_order):
    time.sleep(2)
    nr = viz._exec.results[nid]
    nr.state = NodeState.RUNNING
    viz._exec.results[nid] = nr
    # 推送状态
    viz.emitter.emit({
        "type": "node_state",
        "data": {
            "node_id": nid,
            "state": "running",
            "label": dag.get_node(nid).label if dag.get_node(nid) else nid,
            "duration": 0,
            "error": None,
            "started_at": time.time(),
        },
        "timestamp": time.time(),
    })
    time.sleep(0.3)
    
    # 标记完成
    nr = viz._exec.results[nid]
    nr.state = NodeState.COMPLETED
    nr.finished_at = time.time()
    nr.started_at = nr.finished_at - 1.2
    if nid == "validate":
        nr.output = {"condition_key": "valid", "result": "数据有效"}
    else:
        nr.output = {f"{nid}_out": "ok"}
    viz._exec.results[nid] = nr
    
    viz.emitter.emit({
        "type": "node_state",
        "data": {
            "node_id": nid,
            "state": "completed",
            "label": dag.get_node(nid).label,
            "duration": 1.2,
            "error": None,
        },
        "timestamp": time.time(),
    })
    
    # 刷新快照
    snap = DagVizRegistry.get_status_snapshot(viz_id)
    elapsed = time.time() - viz._started_at
    print(f"   [{snap['progress']['completed']}/{snap['progress']['total']}] "
          f"{nid:12s} → COMPLETED  ({elapsed:.1f}s)")

# 标记工作流完成
viz._exec._state = WorkflowState.COMPLETED
viz._finished_at = time.time()

# ═══ 最终 SVG ═══
print(f"\n{'=' * 60}")
print("📐 生成最终 SVG（所有节点完成）")
print("=" * 60)
dot = dag_to_dot(dag, viz._exec.results, viz.title)
if dot_ok:
    svg = render_dot_to_svg(dot)
    if svg:
        final_path = "demo_dag_final.svg"
        with open(final_path, "w", encoding="utf-8") as f:
            f.write(svg)
        print(f"   ✅ 最终 SVG: {final_path} ({len(svg)} 字符)")

# ═══ 最终快照 ═══
snap = DagVizRegistry.get_status_snapshot(viz_id)
print(f"\n📊 最终状态:")
print(f"   state:    {snap['state']}")
print(f"   progress: {snap['progress']['completed']}/{snap['progress']['total']}")
print(f"   nodes:")
for n in snap['nodes']:
    icon = {"completed": "✅", "failed": "❌", "pending": "⬜", "running": "🔄"}.get(n['state'], "❓")
    print(f"     {icon} {n['label']:25s}  {n['state']:10s}  {n['duration']}s")

print(f"\n{'=' * 60}")
print("🎉 演示完毕！")
print("=" * 60)
print(f"\n  状态 JSON:   GET /dag/{viz_id}/status")
print(f"  SVG 图:      GET /dag/{viz_id}/image?format=svg")
print(f"  HTML 页面:   GET /dag/{viz_id}")
print(f"  SSE 流:      GET /dag/{viz_id}/events")
print(f"\n💡 提示: 启动 tea_agent server 后访问 http://127.0.0.1:8080")
print(f"   在任务面板中应能看到 DAG 缩略图\n")
