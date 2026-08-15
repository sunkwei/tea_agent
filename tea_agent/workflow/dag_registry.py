"""
轻量 DAG 注册表 — SimpleDagRegistry。

自核心 `tea_agent._gui._dag_thumbnail.py`（历史上是 GUI 的 DAG 可视化组件）迁移而来。
该类本身是纯核心能力（不依赖 tkinter），被 server 路由与 toolkit_parallel_subtasks
用于向任务面板推送 DAG 缩略图状态。随「删除 gui/tui 接口」迁移至 workflow 目录。

用法:
    from tea_agent.workflow.dag_registry import SimpleDagRegistry
    viz_id = SimpleDagRegistry.register(
        title="parallel subtasks",
        nodes=[{"id": "a", "label": "task a", "state": "running", "type": "task"}],
        edges=[{"from": "a", "to": "b"}],
    )
    SimpleDagRegistry.update_node(viz_id, "a", state="completed")
    SimpleDagRegistry.unregister(viz_id)
"""

from __future__ import annotations

import threading
import time

__all__ = ["SimpleDagRegistry"]


class SimpleDagRegistry:
    """轻量 DAG 注册表 — 不依赖 WorkflowVisualizer。

    任何工具都可以调用 SimpleDagRegistry.register() 向任务面板推送 DAG 缩略图。
    """

    _instances: dict[str, dict] = {}
    _lock = threading.Lock()

    @classmethod
    def register(cls, title: str, nodes: list[dict],
                 edges: list[dict] | None = None,
                 viz_id: str | None = None) -> str:
        """注册简易 DAG。返回 viz_id。"""
        import uuid
        if viz_id is None:
            viz_id = f"simple-{uuid.uuid4().hex[:8]}"

        total = len(nodes)
        completed = sum(1 for n in nodes if n.get("state") in
                        ("completed", "failed", "skipped"))

        cls._instances[viz_id] = {
            "viz_id": viz_id,
            "title": title,
            "state": "running",
            "progress": {"completed": completed, "total": total},
            "started_at": time.time(),
            "finished_at": None,
            "nodes": nodes,
            "edges": edges or [],
            "dot_available": False,
            "_created_at": time.time(),
        }
        return viz_id

    @classmethod
    def update_node(cls, viz_id: str, node_id: str,
                    state: str | None = None,
                    error: str | None = None,
                    duration: float | None = None):
        """更新单个节点状态并重新计算进度。"""
        entry = cls._instances.get(viz_id)
        if not entry:
            return
        for n in entry["nodes"]:
            if n["id"] == node_id:
                if state is not None:
                    n["state"] = state
                if error is not None:
                    n["error"] = error
                if duration is not None:
                    n["duration"] = duration
                break
        total = len(entry["nodes"])
        completed = sum(1 for n in entry["nodes"] if n.get("state") in
                        ("completed", "failed", "skipped"))
        entry["progress"] = {"completed": completed, "total": total}
        if completed >= total:
            has_failed = any(n.get("state") == "failed" for n in entry["nodes"])
            entry["state"] = "failed" if has_failed else "completed"
            entry["finished_at"] = time.time()

    @classmethod
    def unregister(cls, viz_id: str):
        """移除 DAG 条目。"""
        cls._instances.pop(viz_id, None)

    @classmethod
    def list_all(cls) -> list[dict]:
        """列出所有简易 DAG（清理过期条目）。"""
        now = time.time()
        stale = [vid for vid, entry in cls._instances.items()
                 if now - entry.get("_created_at", 0) > 1800]
        for vid in stale:
            cls._instances.pop(vid, None)
        return list(cls._instances.values())
