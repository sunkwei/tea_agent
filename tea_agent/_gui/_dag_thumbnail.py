"""
DAG 缩略图 + 查看器 — 任务面板中的 DAG 工作流可视化组件。

功能:
  - DagThumbnailCard: Tkinter Frame 卡片（缩略图 + 标题 + 状态），双击放大
  - DagViewerDialog: 独立弹窗，HtmlFrame 渲染实时 SVG，自动刷新
  - get_active_dag_vizes(): 从 DagVizRegistry 获取活跃 DAG 列表
  - render_dag_png(): DAG → PNG bytes（通过 Graphviz dot）

依赖:
  - tkinter (内置)
  - PIL/Pillow (可选，降级到文字卡片)
  - tkinterweb.HtmlFrame (可选，放大查看)
  - Graphviz dot (可选，无则显示 DOT 源码)
"""

from __future__ import annotations

import html
import io
import logging
import threading
import time
import tkinter as tk
from tkinter import ttk

logger = logging.getLogger(__name__)

# 尝试导入 PIL
try:
    from PIL import Image, ImageTk
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

# 尝试导入 tkinterweb
try:
    from tkinterweb import HtmlFrame
    HAS_TKINTERWEB = True
except ImportError:
    HAS_TKINTERWEB = False

# ── 缩略图默认尺寸 ──────────────────────────
THUMB_WIDTH = 260
THUMB_HEIGHT = 180


# ═══════════════════════════════════════════════
# 从 DagVizRegistry + SimpleDagRegistry 获取活跃 DAG
# ═══════════════════════════════════════════════

def get_active_dag_vizes() -> list[dict]:
    """
    从 DagVizRegistry + SimpleDagRegistry 获取所有活跃 DAG 的状态摘要。

    Returns:
        [{"viz_id": str, "title": str, "state": str, "progress": {...},
          "nodes": [...], "edges": [...], "dot_available": bool}, ...]
    """
    result = []

    # 1) 从正式 DagVizRegistry 获取（WorkflowVisualizer）
    try:
        from tea_agent.multi_agent.workflow_viz import DagVizRegistry
        for viz_id in DagVizRegistry.list_ids():
            snap = DagVizRegistry.get_status_snapshot(viz_id)
            if snap:
                result.append(snap)
    except ImportError:
        pass

    # 2) 从简易注册表获取（并行子任务、子Agent 等）
    result.extend(SimpleDagRegistry.list_all())

    return result


# ═══════════════════════════════════════════════
# SimpleDagRegistry — 轻量 DAG 注册表
# ═══════════════════════════════════════════════

class SimpleDagRegistry:
    """轻量 DAG 注册表 — 不依赖 WorkflowVisualizer。

    任何工具都可以调用 SimpleDagRegistry.register() 向任务面板推送 DAG 缩略图。

    用法:
        from tea_agent._gui._dag_thumbnail import SimpleDagRegistry
        viz_id = SimpleDagRegistry.register(
            title="parallel subtasks",
            nodes=[{"id":"a","label":"task a","state":"running","type":"task"}],
            edges=[{"from":"a","to":"b"}],
        )
        SimpleDagRegistry.update_node(viz_id, "a", state="completed")
        SimpleDagRegistry.unregister(viz_id)
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


# ═══════════════════════════════════════════════
# DAG → PNG 渲染
# ═══════════════════════════════════════════════

def render_dag_png(viz_id: str | None = None,
                   dag_data: dict | None = None) -> bytes | None:
    """
    将 DAG 渲染为 PNG 图像字节。

    Args:
        viz_id: DagVizRegistry 中的 viz_id（从注册表获取状态）
        dag_data: 或直接提供 {nodes, edges, title} 字典

    Returns:
        PNG 字节，或 None 如果 Graphviz dot 不可用
    """
    from tea_agent.multi_agent.dag_dot_renderer import (
        check_dot_available,
        dag_to_dot,
        render_dot_to_png,
    )

    if not check_dot_available():
        return None

    # 构建 WorkflowDAG 的简化版用于渲染
    from tea_agent.multi_agent.workflow_engine import NodeType, WorkflowDAG, WorkflowNode

    if dag_data is None and viz_id is not None:
        try:
            from tea_agent.multi_agent.workflow_viz import DagVizRegistry
            snap = DagVizRegistry.get_status_snapshot(viz_id)
            if snap:
                dag_data = snap
        except ImportError:
            pass

    if dag_data is None:
        return None

    # 构建临时 DAG（用于 dag_to_dot）
    dag = WorkflowDAG()
    for n in dag_data.get("nodes", []):
        node = WorkflowNode(
            node_id=n["id"],
            type=NodeType(n.get("type", "task")),
            label=n.get("label", n["id"]),
        )
        dag.add_node(node)
    for e in dag_data.get("edges", []):
        dag.add_edge(e["from"], e["to"], condition_key=e.get("condition_key"))

    # 构建 node_states
    node_states = {}
    for n in dag_data.get("nodes", []):
        node_states[n["id"]] = type("_NR", (), {
            "state": type("_S", (), {"value": n.get("state", "pending")})(),
            "duration": n.get("duration", 0),
            "error": n.get("error"),
        })()

    title = dag_data.get("title", "Workflow DAG")
    dot = dag_to_dot(dag, node_states, title)
    return render_dot_to_png(dot)


def render_dag_svg_text(viz_id: str | None = None,
                        dag_data: dict | None = None) -> str | None:
    """
    将 DAG 渲染为 SVG 文本。

    Args:
        viz_id: DagVizRegistry 中的 viz_id
        dag_data: 或直接提供 {nodes, edges, title} 字典

    Returns:
        SVG 字符串，或 None
    """
    from tea_agent.multi_agent.dag_dot_renderer import (
        check_dot_available,
        dag_to_dot,
        render_dot_to_svg,
    )

    if not check_dot_available():
        return None

    from tea_agent.multi_agent.workflow_engine import NodeType, WorkflowDAG, WorkflowNode

    if dag_data is None and viz_id is not None:
        try:
            from tea_agent.multi_agent.workflow_viz import DagVizRegistry
            snap = DagVizRegistry.get_status_snapshot(viz_id)
            if snap:
                dag_data = snap
        except ImportError:
            pass

    if dag_data is None:
        return None

    dag = WorkflowDAG()
    for n in dag_data.get("nodes", []):
        node = WorkflowNode(
            node_id=n["id"],
            type=NodeType(n.get("type", "task")),
            label=n.get("label", n["id"]),
        )
        dag.add_node(node)
    for e in dag_data.get("edges", []):
        dag.add_edge(e["from"], e["to"], condition_key=e.get("condition_key"))

    node_states = {}
    for n in dag_data.get("nodes", []):
        node_states[n["id"]] = type("_NR", (), {
            "state": type("_S", (), {"value": n.get("state", "pending")})(),
            "duration": n.get("duration", 0),
            "error": n.get("error"),
        })()

    title = dag_data.get("title", "Workflow DAG")
    dot = dag_to_dot(dag, node_states, title)
    return render_dot_to_svg(dot)


# ═══════════════════════════════════════════════
# DagThumbnailCard — 缩略图卡片组件
# ═══════════════════════════════════════════════

_STATE_LABELS = {
    "pending": "⏸ 等待中",
    "running": "▶️ 运行中",
    "completed": "✅ 已完成",
    "failed": "❌ 失败",
    "cancelled": "⏹ 已取消",
}

_STATE_COLORS = {
    "pending": "#666",
    "running": "#1f6feb",
    "completed": "#3fb950",
    "failed": "#f85149",
    "cancelled": "#8b949e",
}


class DagThumbnailCard(ttk.Frame):
    """DAG 工作流缩略图卡片。

    显示：缩略图（PNG） + 标题 + 状态 + 进度
    行为：双击 → 打开 DagViewerDialog 放大查看
    """

    def __init__(self, parent, dag_data: dict, on_double_click=None):
        super().__init__(parent, relief=tk.GROOVE, borderwidth=1)
        self.dag_data = dag_data
        self.viz_id = dag_data.get("viz_id", "")
        self._on_double_click = on_double_click
        self._photo = None  # 持有 PhotoImage 引用防 GC
        self._build_ui()
        self._bind_events()

    def _build_ui(self):
        """构建卡片 UI。"""
        # 标题行
        title_frame = ttk.Frame(self)
        title_frame.pack(fill=tk.X, padx=6, pady=(4, 2))

        title = self.dag_data.get("title", "DAG 工作流")[:40]
        ttk.Label(title_frame, text=f"📊 {title}",
                  font=("Microsoft YaHei", 10, "bold")).pack(side=tk.LEFT)

        state = self.dag_data.get("state", "pending")
        color = _STATE_COLORS.get(state, "#666")
        label_text = _STATE_LABELS.get(state, state)
        ttk.Label(title_frame, text=label_text,
                  foreground=color, font=("Microsoft YaHei", 9)).pack(side=tk.RIGHT)

        # 进度条
        prog = self.dag_data.get("progress", {})
        completed = prog.get("completed", 0)
        total = prog.get("total", 0)
        if total > 0:
            progress_frame = ttk.Frame(self)
            progress_frame.pack(fill=tk.X, padx=6, pady=(0, 2))
            ttk.Label(progress_frame, text=f"{completed}/{total}",
                      font=("Microsoft YaHei", 8), foreground="#666").pack(side=tk.RIGHT)
            pbar = ttk.Progressbar(progress_frame, maximum=total, value=completed,
                                   length=THUMB_WIDTH - 60)
            pbar.pack(side=tk.LEFT, fill=tk.X)

        # 缩略图区域
        img_frame = ttk.Frame(self, width=THUMB_WIDTH, height=THUMB_HEIGHT)
        img_frame.pack(fill=tk.BOTH, expand=True, padx=6, pady=(0, 4))
        img_frame.pack_propagate(False)

        self._img_frame = img_frame
        self._img_label = ttk.Label(img_frame, text="加载中...",
                                     foreground="#aaa", anchor=tk.CENTER)
        self._img_label.pack(fill=tk.BOTH, expand=True)

        # 异步加载缩略图
        threading.Thread(target=self._load_thumbnail, daemon=True).start()

    def _load_thumbnail(self):
        """后台线程渲染 DAG 缩略图。"""
        try:
            png_bytes = render_dag_png(dag_data=self.dag_data)
            if png_bytes and HAS_PIL:
                img = Image.open(io.BytesIO(png_bytes))
                # 缩放到卡片尺寸
                img.thumbnail((THUMB_WIDTH - 12, THUMB_HEIGHT - 12), Image.LANCZOS)
                self._photo = ImageTk.PhotoImage(img)
                # 主线程更新
                self.after(0, self._set_thumbnail, self._photo)
            else:
                self.after(0, self._set_fallback)
        except Exception as e:
            logger.warning(f"DAG 缩略图加载失败: {e}")
            self.after(0, self._set_fallback)

    def _set_thumbnail(self, photo):
        """主线程：设置缩略图。"""
        try:
            self._img_label.configure(image=photo, text="")
        except Exception:
            pass

    def _set_fallback(self):
        """Graphviz 不可用时的降级显示。"""
        try:
            nodes = self.dag_data.get("nodes", [])
            edges = self.dag_data.get("edges", [])
            text = f"📊 {len(nodes)} 节点 · {len(edges)} 边\n\n(双击查看详情)"
            self._img_label.configure(text=text, foreground="#888",
                                       font=("Microsoft YaHei", 9))
        except Exception:
            pass

    def _bind_events(self):
        """绑定双击事件。"""
        # 绑定到自身及所有子控件
        def _on_dbl(e):
            if self._on_double_click:
                self._on_double_click(self.viz_id, self.dag_data)

        for widget in [self] + list(self.winfo_children()):
            widget.bind("<Double-Button-1>", _on_dbl, add="+")

    def update_state(self, dag_data: dict):
        """更新卡片状态（由定时刷新调用）。"""
        self.dag_data = dag_data
        # 重建UI（简单的刷新方式）
        for w in self.winfo_children():
            w.destroy()
        self._build_ui()


# ═══════════════════════════════════════════════
# DagViewerDialog — 放大查看弹窗
# ═══════════════════════════════════════════════

class DagViewerDialog(tk.Toplevel):
    """DAG 工作流放大查看器。

    使用 HtmlFrame 显示 SVG（如果可用），否则显示 DOT 源码。
    每 2 秒自动刷新状态。
    """

    def __init__(self, parent, viz_id: str, dag_data: dict):
        super().__init__(parent)
        self.viz_id = viz_id
        self.dag_data = dag_data
        self._timer_id = None
        self._svg_cache = ""  # 缓存上一次 SVG，避免无变化闪烁

        title = dag_data.get("title", "DAG 工作流")[:50]
        self.title(f"📊 {title}")

        # 窗口尺寸
        self.geometry("900x700")
        self.minsize(600, 400)

        self._build_ui()
        self._refresh_svg()

        # 自动刷新
        self._start_auto_refresh()

        # 关闭清理
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.bind("<Escape>", lambda e: self._on_close())

    def _build_ui(self):
        """构建查看器 UI。"""
        # 顶部状态栏
        top = ttk.Frame(self)
        top.pack(fill=tk.X, padx=10, pady=6)

        state = self.dag_data.get("state", "pending")
        color = _STATE_COLORS.get(state, "#666")
        label_text = _STATE_LABELS.get(state, state)
        self._state_label = ttk.Label(top, text=label_text,
                                       foreground=color,
                                       font=("Microsoft YaHei", 12, "bold"))
        self._state_label.pack(side=tk.LEFT)

        prog = self.dag_data.get("progress", {})
        self._progress_label = ttk.Label(top,
            text=f"进度: {prog.get('completed', 0)}/{prog.get('total', 0)}",
            font=("Microsoft YaHei", 10))
        self._progress_label.pack(side=tk.LEFT, padx=20)

        ttk.Button(top, text="🔄 刷新", command=self._refresh_svg).pack(side=tk.RIGHT, padx=4)
        ttk.Button(top, text="📋 DOT 源码",
                   command=self._show_dot_source).pack(side=tk.RIGHT, padx=4)
        ttk.Button(top, text="关闭", command=self._on_close).pack(side=tk.RIGHT, padx=4)

        ttk.Separator(self, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=10)

        # SVG 显示区域
        if HAS_TKINTERWEB:
            self._html_frame = HtmlFrame(self, messages_enabled=False)
            self._html_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=6)
        else:
            # 降级：用 ScrolledText 显示 DOT
            from tkinter import scrolledtext
            self._text_widget = scrolledtext.ScrolledText(
                self, font=("Consolas", 10), bg="#0d1117", fg="#c9d1d9",
                wrap=tk.WORD)
            self._text_widget.pack(fill=tk.BOTH, expand=True, padx=10, pady=6)

        # 底部图例
        legend = ttk.Frame(self)
        legend.pack(fill=tk.X, padx=10, pady=4)
        for state_key, color_hex in [
            ("pending", "#30363d"), ("ready", "#1f6feb"),
            ("running", "#58a6ff"), ("completed", "#3fb950"),
            ("failed", "#f85149"), ("skipped", "#8b949e"),
        ]:
            dot = tk.Canvas(legend, width=14, height=14, highlightthickness=0)
            dot.pack(side=tk.LEFT, padx=(0, 2))
            # 绘制小色块
            dot.create_rectangle(0, 0, 14, 14, fill=color_hex, outline="")
            ttk.Label(legend, text=_STATE_LABELS.get(state_key, state_key),
                      font=("Microsoft YaHei", 8)).pack(side=tk.LEFT, padx=(0, 10))

    def _refresh_svg(self):
        """刷新 SVG 显示。"""
        # 尝试从注册表获取最新状态
        try:
            from tea_agent.multi_agent.workflow_viz import DagVizRegistry
            snap = DagVizRegistry.get_status_snapshot(self.viz_id)
            if snap:
                self.dag_data = snap
        except ImportError:
            pass

        # 更新顶部状态
        state = self.dag_data.get("state", "pending")
        self._state_label.configure(
            text=_STATE_LABELS.get(state, state),
            foreground=_STATE_COLORS.get(state, "#666"),
        )
        prog = self.dag_data.get("progress", {})
        self._progress_label.configure(
            text=f"进度: {prog.get('completed', 0)}/{prog.get('total', 0)}")

        # 渲染 SVG
        svg = render_dag_svg_text(dag_data=self.dag_data)
        if svg and HAS_TKINTERWEB:
            # 将 SVG 嵌入 HTML
            svg_stripped = svg
            # 去掉 XML 声明
            if svg_stripped.startswith("<?xml"):
                svg_stripped = svg_stripped[svg_stripped.find("<svg"):]
            html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>body{{margin:0;background:#0d1117;display:flex;justify-content:center;align-items:center;min-height:100vh;}}</style>
</head><body>{svg_stripped}</body></html>"""
            if html != self._svg_cache:
                self._svg_cache = html
                self._html_frame.load_html(html)
        elif svg:
            # 有 SVG 但无 HtmlFrame，显示为纯文本
            if hasattr(self, '_text_widget'):
                self._text_widget.delete("1.0", tk.END)
                self._text_widget.insert("1.0", svg)
        else:
            # 无 Graphviz，显示 DOT 源码
            self._show_dot_source()

    def _show_dot_source(self):
        """显示 DOT 源码（Graphviz 不可用时的降级）。"""
        from tea_agent.multi_agent.dag_dot_renderer import dag_to_dot
        from tea_agent.multi_agent.workflow_engine import NodeType, WorkflowDAG, WorkflowNode

        dag = WorkflowDAG()
        for n in self.dag_data.get("nodes", []):
            node = WorkflowNode(
                node_id=n["id"],
                type=NodeType(n.get("type", "task")),
                label=n.get("label", n["id"]),
            )
            dag.add_node(node)
        for e in self.dag_data.get("edges", []):
            dag.add_edge(e["from"], e["to"], condition_key=e.get("condition_key"))

        node_states = {}
        for n in self.dag_data.get("nodes", []):
            node_states[n["id"]] = type("_NR", (), {
                "state": type("_S", (), {"value": n.get("state", "pending")})(),
                "duration": n.get("duration", 0),
                "error": n.get("error"),
            })()

        dot_text = dag_to_dot(dag, node_states, self.dag_data.get("title", "DAG"))
        if HAS_TKINTERWEB:
            escaped_dot = html.escape(dot_text)
            html_content = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<style>body{{background:#0d1117;color:#c9d1d9;font-family:monospace;padding:20px;}}
pre{{white-space:pre-wrap;word-break:break-all;}}</style></head>
<body><h2>DOT 源码</h2><p style="color:#f85149">⚠ Graphviz dot 不可用，显示 DOT 源码</p>
<pre>{escaped_dot}</pre></body></html>"""
            self._html_frame.load_html(html_content)
        elif hasattr(self, '_text_widget'):
            self._text_widget.delete("1.0", tk.END)
            self._text_widget.insert("1.0", dot_text)

    def _start_auto_refresh(self):
        """启动自动刷新。"""
        if self._timer_id:
            self.after_cancel(self._timer_id)
        self._timer_id = self.after(2000, self._auto_refresh_tick)

    def _auto_refresh_tick(self):
        if not self.winfo_exists():
            return
        self._refresh_svg()
        self._timer_id = self.after(2000, self._auto_refresh_tick)

    def _on_close(self):
        if self._timer_id:
            self.after_cancel(self._timer_id)
        self.destroy()
