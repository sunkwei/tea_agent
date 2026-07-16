"""
DAG 工作流 Demo — 模拟一个完整的代码审查工作流。

在 web 界面中展示 DAG SVG 缩略图卡片及放大查看效果。
复制以下内容在 Python 中执行即可看到效果。

使用方式:
    1. python dag_demo.py          → 创建 DAG + 启动服务器
    2. 浏览器打开 http://localhost:8080/dag/simple-demo
    3. 或在 web 聊天界面发送任意消息，查看 DAG 卡片
"""

import time
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tea_agent._gui._dag_thumbnail import SimpleDagRegistry


def create_demo_dag():
    """创建模拟的代码审查 DAG 工作流。"""
    nodes = [
        {
            "id": "init",
            "label": "初始化审查\n扫描代码库",
            "type": "task",
            "state": "completed",
            "duration": 0.8,
        },
        {
            "id": "lint",
            "label": "Lint 检查\nruff/flake8",
            "type": "task",
            "state": "completed",
            "duration": 2.3,
            "error": None,
        },
        {
            "id": "security",
            "label": "安全审计\nbandit/semgrep",
            "type": "task",
            "state": "running",
            "duration": 1.5,
        },
        {
            "id": "complexity",
            "label": "复杂度分析\n圈复杂度检测",
            "type": "task",
            "state": "completed",
            "duration": 0.6,
        },
... [截断 1771B→943B] ...
            "label": "最终报告\n汇总并评级",
            "type": "task",
            "state": "pending",
            "duration": 0,
        },
    ]

    edges = [
        {"from": "init", "to": "lint"},
        {"from": "init", "to": "security"},
        {"from": "init", "to": "complexity"},
        {"from": "lint", "to": "type_check"},
        {"from": "security", "to": "type_check"},
        {"from": "complexity", "to": "type_check"},
        {"from": "type_check", "to": "report"},
    ]

    viz_id = SimpleDagRegistry.register(
        title="代码审查工作流 — CI/CD Pipeline",
        nodes=nodes,
        edges=edges,
        viz_id="simple-demo",
    )
    print(f"✅ DAG 已注册: viz_id={viz_id}")
    print(f"   节点: {len(nodes)}, 边: {len(edges)}")
    print(f"\n📊 在浏览器中查看:")
    print(f"   http://localhost:8080/dag/simple-demo")
    print(f"   或 http://localhost:8080/dag/simple-demo/image?format=svg")
    return viz_id


if __name__ == "__main__":
    create_demo_dag()
    print("\n⏳ 保持运行中（Ctrl+C 退出）...")
    try:
        while True:
            time.sleep(10)
    except KeyboardInterrupt:
        print("\n👋 已退出")
