"""生成「P0 修复工作流 DAG」SVG 图示"""
from tea_agent.multi_agent.workflow_engine import (
    WorkflowDAG, WorkflowNode, NodeType, NodeState, WorkflowExec, NodeResult,
)
from tea_agent.multi_agent.dag_dot_renderer import dag_to_dot, render_dot_to_svg

# ── 构建 DAG ──
dag = WorkflowDAG("P0 严重缺陷修复工作流")

dag.add_node(WorkflowNode("p0_1", NodeType.TASK, label="P0-1: 修复 providers.py\nsave_config 参数顺序"))
dag.add_node(WorkflowNode("p0_2", NodeType.TASK, label="P0-2: 修复 prompts.py\nqwen-2 子串碰撞"))
dag.add_node(WorkflowNode("p0_3", NodeType.TASK, label="P0-3: 修复 execution_pool\n_current 调度失效"))
dag.add_node(WorkflowNode("p0_4", NodeType.TASK, label="P0-4: 添加 server.py\nAPI Key 认证中间件"))
dag.add_node(WorkflowNode("p0_5", NodeType.TASK, label="P0-5: 修复 basesession.py\n7处 bare except:pass"))
dag.add_node(WorkflowNode("p0_6", NodeType.TASK, label="P0-6: 修复 store\n200硬限制→分页"))
dag.add_node(WorkflowNode("dag_viz", NodeType.TASK, label="创建 DAG 工作流\n并展示图示化效果"))

# 依赖关系（6个P0可并行，最后汇总）
dag.add_edge("p0_1", "dag_viz")
dag.add_edge("p0_2", "dag_viz")
dag.add_edge("p0_3", "dag_viz")
dag.add_edge("p0_4", "dag_viz")
dag.add_edge("p0_5", "dag_viz")
dag.add_edge("p0_6", "dag_viz")

# ── 模拟全部完成状态 ──
node_states = {}
for nid in ["p0_1", "p0_2", "p0_3", "p0_4", "p0_5", "p0_6", "dag_viz"]:
    node_states[nid] = NodeResult(
        node_id=nid,
        state=NodeState.COMPLETED,
        output={},
        started_at=0,
        finished_at=1,
        retries=0,
    )

# ── 渲染 DOT → SVG ──
dot = dag_to_dot(dag, node_states, title="P0 严重缺陷修复工作流", orientation="TB")
svg = render_dot_to_svg(dot)
if svg:
    with open("p0_fix_dag.svg", "w", encoding="utf-8") as f:
        f.write(svg)
    print(f"✅ SVG 已生成: p0_fix_dag.svg ({len(svg)} 字节)")
    # 也保存 DOT 源码
    with open("p0_fix_dag.dot", "w", encoding="utf-8") as f:
        f.write(dot)
    print(f"✅ DOT 已生成: p0_fix_dag.dot")
else:
    print("❌ SVG 渲染失败 (dot 命令返回空)")
