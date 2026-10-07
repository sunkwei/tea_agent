"""测试 DAG 可视化服务器路由"""
import sys, os, time, json, threading, urllib.request

os.chdir(r'C:\Users\Hetin\work\git\tea_agent')

from tea_agent.multi_agent.workflow_engine import (
    WorkflowDAG, WorkflowNode, WorkflowExec, NodeType, NodeState, NodeResult, WorkflowState
)
from tea_agent.multi_agent.workflow_viz import WorkflowVisualizer, DagVizRegistry

# ═══ 创建 DAG 并注册 ═══
dag = WorkflowDAG()
nodes = [
    ('init', NodeType.TASK, '🚀 初始化'),
    ('fetch', NodeType.TASK, '📥 拉取数据'),
    ('validate', NodeType.CONDITION, '🔍 校验'),
    ('train', NodeType.TASK, '🧠 训练'),
    ('deploy', NodeType.TASK, '🚀 部署'),
    ('end', NodeType.END, '✅ 完成'),
]
for nid, nt, label in nodes:
    dag.add_node(WorkflowNode(nid, nt, label=label))
edges = [('init','fetch'),('fetch','validate'),('validate','train','valid'),('train','deploy'),('deploy','end')]
for e in edges:
    dag.add_edge(e[0], e[1])

viz = WorkflowVisualizer(dag, title='🎯 ML 训练流水线', auto_open=False, auto_register=False)
viz_id = viz.viz_id
DagVizRegistry.register(viz_id, viz)

# 模拟部分节点完成
viz._started_at = time.time()
viz._exec = WorkflowExec(dag)
for nid in dag.nodes:
    viz._exec.results[nid] = NodeResult(node_id=nid)

t = time.time()
for nid, state in [('init','completed'),('fetch','completed'),('validate','running')]:
    nr = viz._exec.results[nid]
    nr.state = getattr(NodeState, state.upper())
    if state == 'completed':
        nr.started_at = t
        nr.finished_at = t + 1.2
    elif state == 'running':
        nr.started_at = t

viz._exec._state = WorkflowState.RUNNING

print(f'DAG 已注册: viz_id={viz_id}')
print(f'节点状态: init=✅ fetch=✅ validate=🔄 train=⬜ deploy=⬜ end=⬜')

# ═══ 启动服务器 ═══
from tea_agent.server import run_server
t_server = threading.Thread(target=run_server, kwargs={'host':'127.0.0.1','port':8080}, daemon=True)
t_server.start()
time.sleep(3)

# ═══ 测试路由 ═══
base = f'http://127.0.0.1:8080/dag/{viz_id}'

print('\n--- 路由测试 ---')

# 1. /status
resp = urllib.request.urlopen(f'{base}/status', timeout=5)
snap = json.loads(resp.read())
print(f'✅ GET /status  → state={snap["state"]}, progress={snap["progress"]["completed"]}/{snap["progress"]["total"]}')

# 2. /image?format=svg  
resp = urllib.request.urlopen(f'{base}/image?format=svg', timeout=5)
ct = resp.headers.get('Content-Type','')
svg_data = resp.read()
print(f'✅ GET /image  → Content-Type={ct}, size={len(svg_data)} bytes')

# 3. /
resp = urllib.request.urlopen(f'{base}', timeout=5)
html = resp.read().decode()
print(f'✅ GET /       → HTML size={len(html)}, title: {"🎯 ML" in html}')

# 4. 测试 index.html 主页
resp = urllib.request.urlopen(f'http://127.0.0.1:8080/', timeout=5)
main_html = resp.read().decode()
print(f'✅ GET /       → 主页 size={len(main_html)}, 含 dag-lightbox: {"dag-lightbox" in main_html}')

print(f'\n🎉 全部路由测试通过!')
print(f'\n🌐 浏览器打开: http://127.0.0.1:8080')
print(f'   DAG 页面:    http://127.0.0.1:8080/dag/{viz_id}')
