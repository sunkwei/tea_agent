"""
@2026-07-07 gen by tea_agent, 对话搜索对话框
跨主题全文搜索对话历史，支持关键词搜索、结果预览、点击跳转
"""
import logging
import tkinter as tk
from tkinter import ttk

logger = logging.getLogger(__name__)


class SearchDialog(tk.Toplevel):
    """对话搜索对话框 — 跨主题全文搜索历史对话"""

    def __init__(self, parent, db, on_switch_topic=None):
        """Initialize SearchDialog.

        Args:
            parent: 父窗口
            db: Storage 实例
            on_switch_topic: 跳转主题时的回调，接收 topic_id
        """
        super().__init__(parent)
        self.db = db
        self.on_switch_topic = on_switch_topic or (lambda tid: None)
        self._results: list[dict] = []

        self.title("🔍 搜索对话历史")
        self.geometry("650x500")
        self.minsize(400, 300)
        self.transient(parent)
        self.grab_set()

        self._build_ui()
        self.bind("<Escape>", lambda e: self.destroy())
        self.search_entry.focus_set()

    def _build_ui(self):
        """构建搜索对话框界面。"""
        # 搜索栏
        search_frame = ttk.Frame(self)
        search_frame.pack(fill=tk.X, padx=8, pady=(8, 4))

        ttk.Label(search_frame, text="关键词:").pack(side=tk.LEFT, padx=(0, 4))
        self.search_entry = ttk.Entry(search_frame, font=("", 12))
        self.search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))
        self.search_entry.bind("<Return>", lambda e: self._do_search())
        self.search_entry.bind("<KP_Enter>", lambda e: self._do_search())

        # 选项栏
        opt_frame = ttk.Frame(self)
        opt_frame.pack(fill=tk.X, padx=8, pady=2)

        self.include_ai_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(opt_frame, text="搜索 AI 回复",
                        variable=self.include_ai_var).pack(side=tk.LEFT, padx=(0, 8))

        self.include_rounds_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(opt_frame, text="搜索工具调用",
                        variable=self.include_rounds_var).pack(side=tk.LEFT, padx=(0, 8))

        ttk.Label(opt_frame, text="  结果数:").pack(side=tk.LEFT, padx=(0, 2))
        self.limit_var = tk.StringVar(value="30")
        limit_spin = ttk.Spinbox(opt_frame, from_=5, to=100,
                                 textvariable=self.limit_var, width=5)
        limit_spin.pack(side=tk.LEFT)

        ttk.Button(opt_frame, text="搜索", command=self._do_search).pack(
            side=tk.RIGHT, padx=(8, 0))

        # 状态栏
        self.status_var = tk.StringVar(value="输入关键词后按回车或点搜索")
        ttk.Label(self, textvariable=self.status_var,
                  foreground="#888").pack(anchor=tk.W, padx=8, pady=(0, 2))

        # 结果列表
        list_frame = ttk.Frame(self)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))

        columns = ("topic", "user_msg", "ai_msg")
        self.tree = ttk.Treeview(list_frame, columns=columns, show="headings",
                                  selectmode="browse")
        self.tree.heading("topic", text="主题")
        self.tree.heading("user_msg", text="用户消息")
        self.tree.heading("ai_msg", text="AI 回复")
        self.tree.column("topic", width=120, minwidth=80)
        self.tree.column("user_msg", width=250, minwidth=150)
        self.tree.column("ai_msg", width=250, minwidth=150)

        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL,
                                   command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.tree.bind("<Double-1>", self._on_item_double_click)
        self.tree.bind("<Return>", self._on_item_double_click)

    def _do_search(self, *_args):
        """执行搜索并显示结果。"""
        query = self.search_entry.get().strip()
        if not query:
            self.status_var.set("请输入搜索关键词")
            return

        try:
            limit = int(self.limit_var.get())
        except ValueError:
            limit = 30

        self.status_var.set(f"正在搜索「{query}」...")
        self.update_idletasks()

        try:
            results = self.db.search_conversations(
                query=query,
                limit=limit,
                include_ai=self.include_ai_var.get(),
                include_rounds=self.include_rounds_var.get(),
            )
        except Exception as e:
            import traceback
            self.status_var.set(f"❌ 搜索出错: {e}")
            logger.error(f"搜索失败: {traceback.format_exc()}")
            return

        self._results = results
        for item in self.tree.get_children():
            self.tree.delete(item)

        if not results:
            self.status_var.set(f"未找到包含「{query}」的结果")
            return

        for i, r in enumerate(results):
            topic_title = r.get("topic_title", "?") or "?"
            user_msg = r.get("user_msg", "") or ""
            ai_msg = r.get("ai_msg", "") or ""

            # 截断显示
            user_display = user_msg[:80] + ("..." if len(user_msg) > 80 else "")
            ai_display = ai_msg[:80] + ("..." if len(ai_msg) > 80 else "")

            # 移除换行
            user_display = user_display.replace("\n", " ").replace("\r", "")
            ai_display = ai_display.replace("\n", " ").replace("\r", "")

            self.tree.insert("", tk.END, values=(topic_title, user_display, ai_display),
                             tags=(i,))

        self.status_var.set(f"✅ 找到 {len(results)} 条结果")

    def _on_item_double_click(self, _event):
        """双击结果项时跳转到对应主题。"""
        sel = self.tree.selection()
        if not sel:
            return
        item = sel[0]
        tags = self.tree.item(item, "tags")
        if not tags:
            return
        idx = tags[0]
        if idx < 0 or idx >= len(self._results):
            return

        result = self._results[idx]
        topic_id = result.get("topic_id")
        if topic_id:
            self.on_switch_topic(topic_id)
            self.destroy()

    def _on_keyboard_select(self, _event):
        """回车键选中当前项。"""
        self._on_item_double_click(_event)
