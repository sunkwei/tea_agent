#!/usr/bin/env python3
"""
DAG 可视化演示 — 用 WorkflowVisualizer 实时展示 DAG 执行过程。

启动后自动打开浏览器，展示：
  • 18 个节点的拓扑分层布局
  • 实时节点状态（待执行→运行中→已完成/失败）
  • 执行耗时、进度条
  • 悬浮 tooltip 展示节点详情

用法:
    python dag_viz_demo.py              # 默认端口 8084
    python dag_viz_demo.py --port 9090  # 指定端口
    python dag_viz_demo.py --no-open    # 不自动打开浏览器
"""

import os
import sys
import time
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from tea_agent.multi_agent import (
    WorkflowDAG,
    WorkflowNode,
    NodeType,
    WorkflowVisualizer,
    get_execution_pool,
)


def make_task_node(nid: str, label: str, delay: float = 0.5):
    """创建带延迟的任务节点（演示用，模拟耗时操作）。"""
    return WorkflowNode(
        node_id=nid,
        type=NodeType.TASK,
        label=label,
        fn=lambda ctx, d=delay, n=label: _simulate_work(d, n),
    )


def _simulate_work(delay: float, name: str) -> dict:
    """模拟工作耗时。"""
    time.sleep(delay)
    return {"done": True, "name": name, "delay": round(delay, 2)}


def build_demo_dag() -> WorkflowDAG:
    r"""构建演示用 DAG：模拟一个数据处理流水线。

    结构:
           [数据采集]
          /    |    \\
    [清洗] [转换] [验证]
       |      \\    /
    [聚合]    [存储]
        \\      /
        [分析报告]
           |
        [通知]
    """
    dag = WorkflowDAG("demo-pipeline")

    # ── 第一层：入口 ──
    dag.add_node(make_task_node("fetch",    "📥 数据采集", 0.8))

    # ── 第二层：并行处理 ──
    dag.add_node(make_task_node("clean",    "🧹 数据清洗", 1.0))
    dag.add_node(make_task_node("transform","🔄 格式转换", 0.7))
    dag.add_node(make_task_node("validate", "✅ 数据验证", 0.6))

    dag.add_edge("fetch", "clean")
    dag.add_edge("fetch", "transform")
    dag.add_edge("fetch", "validate")

    # ── 第三层：聚合 + 存储 ──
    dag.add_node(make_task_node("aggregate","📊 数据聚合", 1.2))
    dag.add_node(make_task_node("store",    "💾 持久存储", 0.9))

    dag.add_edge("clean", "aggregate")
    dag.add_edge("validate", "aggregate")
    dag.add_edge("transform", "store")
    dag.add_edge("aggregate", "store")  # 聚合完也存一份

    # ── 第四层：分析 ──
    dag.add_node(make_task_node("analyze", "📈 分析报告", 1.5))
    dag.add_edge("store", "analyze")

    # ── 第五层：通知 ──
    dag.add_node(make_task_node("notify",  "🔔 发送通知", 0.4))
    dag.add_edge("analyze", "notify")

    # ── 结束 ──
    dag.add_node(WorkflowNode("end", NodeType.END, label="⏹ 完成"))

    # 所有最终任务连接到 end
    dag.add_edge("notify", "end")
    # 如果 store 走不通就到 end 的直接路径也加上
    dag.add_edge("store", "end")

    return dag


def main():
    parser = argparse.ArgumentParser(description="DAG 可视化演示")
    parser.add_argument("--port", type=int, default=8084, help="HTTP 端口 (默认 8084)")
    parser.add_argument("--no-open", action="store_true", help="不自动打开浏览器")
    args = parser.parse_args()

    print("=" * 60)
    print("  🎬 DAG 可视化演示")
    print("  数据处理流水线 — 9 个任务节点")
    print("=" * 60)

    dag = build_demo_dag()
    pool = get_execution_pool(max_workers=4, pool_name="viz-demo")

    errors = dag.validate()
    if errors:
        print(f"  ❌ DAG 校验失败: {errors}")
        return

    print(f"  ✅ DAG 校验通过: {len(dag.nodes)} 节点, {len(dag.edges)} 边")
    print(f"  🧵 执行池: max_workers=4")

    # 启动可视化
    viz = WorkflowVisualizer(
        dag=dag,
        pool=pool,
        title="🔄 数据处理流水线",
        auto_open=not args.no_open,
    )

    result = viz.run(
        context={"pipeline": "demo", "version": "1.0"},
        port=args.port,
    )

    print(f"\n  📊 执行完成: {result.get('state', 'unknown')}")
    print(f"  ⏱ 总耗时: {result.get('duration', 0):.2f}s")

    pool.shutdown(wait=False)


if __name__ == "__main__":
    main()
