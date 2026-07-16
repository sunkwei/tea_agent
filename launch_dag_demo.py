"""
Tea Agent Server + DAG Demo 启动器

用法: python launch_dag_demo.py
然后浏览器访问 http://localhost:8080
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ═══════════════════════════════════════════════
# 1. 注册 DAG 工作流
# ═══════════════════════════════════════════════
from tea_agent._gui._dag_thumbnail import SimpleDagRegistry

nodes = [
    {"id":"init","label":"初始化审查\n扫描代码库","type":"task","state":"completed","duration":0.8},
    {"id":"lint","label":"Lint 检查\nruff/flake8","type":"task","state":"completed","duration":2.3},
    {"id":"security","label":"安全审计\nbandit/semgrep","type":"task","state":"running","duration":1.5},
    {"id":"complexity","label":"复杂度分析\n圈复杂度检测","type":"task","state":"completed","duration":0.6},
    {"id":"type_check","label":"类型检查\nmypy strict","type":"task","state":"pending","duration":0},
    {"id":"report","label":"最终报告\n汇总并评级","type":"task","state":"pending","duration":0},
]
edges = [
    {"from":"init","to":"lint"},
    {"from":"init","to":"security"},
    {"from":"init","to":"complexity"},
    {"from":"lint","to":"type_check"},
    {"from":"security","to":"type_check"},
    {"from":"complexity","to":"type_check"},
    {"from":"type_check","to":"report"},
]

viz_id = SimpleDagRegistry.register(
    title="代码审查工作流 — CI/CD Pipeline",
    nodes=nodes,
    edges=edges,
    viz_id="simple-demo",
)
print(f"✅ DAG 已注册: {viz_id}")
print(f"   节点: {len(nodes)}, 边: {len(edges)}")

# 验证 SVG 渲染
from tea_agent._gui._dag_thumbnail import render_dag_svg_text
svg = render_dag_svg_text(dag_data=SimpleDagRegistry._instances.get(viz_id))
if svg:
    print(f"✅ SVG 渲染成功: {len(svg)} chars")
else:
    print("⚠️ SVG 渲染失败（Graphviz 可能不可用）")

# ═══════════════════════════════════════════════
# 2. 启动服务器
# ═══════════════════════════════════════════════
print("\n🚀 启动服务器...")
print("📊 DAG 可视化: http://localhost:8080/dag/simple-demo")
print("📊 DAG SVG 直接: http://localhost:8080/dag/simple-demo/image?format=svg")
print("💬 Web 聊天: http://localhost:8080")
print()

from tea_agent.server.server import run_server
run_server(host="127.0.0.1", port=8080)
