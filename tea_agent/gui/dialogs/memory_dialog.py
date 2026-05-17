# -*- coding: utf-8 -*-
# @2026-05-17 gen by tea_agent, 从 gui_dialogs.py 拆分 — 记忆管理对话框
"""记忆管理对话框：查看/添加/删除/导出长期记忆"""
import tkinter as tk
from tkinter import ttk
import logging

from ._common import _init_fonts, _fs, SYSTEM_FONT


class MemoryDialog(tk.Toplevel):
    """记忆管理弹窗"""
    PRIORITY_LABELS = {0: "CRITICAL", 1: "HIGH", 2: "MEDIUM", 3: "LOW"}
    CATEGORY_LABELS = {
        "instruction": "指令", "preference": "偏好",
        "fact": "事实", "reminder": "提醒", "general": "一般"
    }

    def __init__(self, parent, storage):
        super().__init__(parent)
        self.db = storage
        self.title("🧠 长期记忆管理")
        self.geometry("800x600")
        self.minsize(600, 400)
        self.transient(parent)
        self.grab_set()

        _init_fonts()
        self._create_ui()
        self._refresh()

    def _create_ui(self):
        top = ttk.Frame(self)
        top.pack(fill=tk.X, padx=10, pady=8)

        self.stats_var = tk.StringVar(value="加载中...")
        ttk.Label(top, textvariable=self.stats_var, font=(SYSTEM_FONT, _fs(10))).pack(side=tk.LEFT)

        ttk.Separator(self, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=10)

        toolbar = ttk.Frame(self)
        toolbar.pack(fill=tk.X, padx=10, pady=4)

        ttk.Button(toolbar, text="➕ 添加", command=self._add_dialog).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="🔄 刷新", command=self._refresh).pack(side=tk.LEFT, padx=2)

        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *a: self._refresh())
        search_entry = ttk.Entry(toolbar, textvariable=self.search_var, width=20)
        search_entry.pack(side=tk.LEFT, padx=(20, 2))
        ttk.Label(toolbar, text="搜索").pack(side=tk.LEFT)

        self.cat_var = tk.StringVar(value="")
        cat_combo = ttk.Combobox(toolbar, textvariable=self.cat_var,
                                 values=["", "instruction", "preference", "fact", "reminder", "general"],
                                 width=12, state="readonly")
        cat_combo.pack(side=tk.LEFT, padx=(10, 2))
        ttk.Label(toolbar, text="分类").pack(side=tk.LEFT)
        cat_combo.bind("<<ComboboxSelected>>", lambda e: self._refresh())

        list_frame = ttk.Frame(self)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=4)

        columns = ("id", "priority", "category", "content", "importance", "expires", "tags")
        self.tree = ttk.Treeview(list_frame, columns=columns, show="headings", height=15)

        for col, text, width, anchor in [
            ("id", "ID", 40, tk.CENTER), ("priority", "优先级", 70, tk.CENTER),
            ("category", "分类", 60, tk.CENTER), ("content", "内容", 320, tk.W),
            ("importance", "重要度", 60, tk.CENTER), ("expires", "过期", 80, tk.CENTER),
            ("tags", "标签", 100, tk.W),
        ]:
            self.tree.heading(col, text=text, command=lambda c=col: self._sort(c) if c in ("id", "priority") else None)
            self.tree.column(col, width=width, anchor=anchor)

        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill=tk.X, padx=10, pady=6)
        ttk.Button(btn_frame, text="💤 软删除", command=self._soft_delete).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="🗑️ 硬删除", command=self._hard_delete).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="📋 导出...", command=self._export).pack(side=tk.RIGHT, padx=2)

        self.tree.bind("<Double-1>", self._on_double_click)
        self.bind("<Escape>", lambda e: self.destroy())
        self.bind("<Delete>", lambda e: self._soft_delete())

    def _refresh(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        try:
            memories = self.db.get_active_memories(limit=100)
            stats = self.db.get_memory_stats()
            total = stats.get("total", 0)
            by_cat = stats.get("by_category", {})
            by_pri = stats.get("by_priority", {})
            cat_str = " ".join(f"{self.CATEGORY_LABELS.get(k, k)}:{v}" for k, v in sorted(by_cat.items()))
            pri_str = " ".join(f"{'!!!' if p == 0 else '▲' if p == 1 else '●' if p == 2 else '○'}:{c}"
                               for p, c in sorted(by_pri.items()))
            self.stats_var.set(f"活跃: {total} 条 | 分类: {cat_str} | 优先级: {pri_str}")

            query = self.search_var.get().strip().lower()
            cat_filter = self.cat_var.get().strip()

            for m in memories:
                content = m.get("content", "")
                if query and query not in content.lower() and query not in (m.get("tags", "") or "").lower():
                    continue
                if cat_filter and m.get("category", "") != cat_filter:
                    continue

                priority = self.PRIORITY_LABELS.get(m.get("priority", 2), str(m["priority"]))
                category = self.CATEGORY_LABELS.get(m.get("category", ""), m["category"])
                expires = (m.get("expires_at", "") or "永不过期")[:16]
                importance = "⭐" * m.get("importance", 3)
                tags = (m.get("tags") or "")[:60]

                self.tree.insert("", tk.END,
                                 values=(m["id"], priority, category, content, importance, expires, tags),
                                 iid=str(m["id"]))
        except Exception as e:
            self.stats_var.set(f"加载失败: {e}")

    def _sort(self, col):
        items = [(str(self.tree.set(i, col)), i) for i in self.tree.get_children("")]
        if col == "priority":
            order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
            items.sort(key=lambda x: order.get(x[0], 99))
        elif col == "id":
            items.sort(key=lambda x: int(x[0]))
        else:
            items.sort()
        for idx, (_, iid) in enumerate(items):
            self.tree.move(iid, "", idx)

    def _add_dialog(self):
        dlg = tk.Toplevel(self)
        dlg.title("添加记忆")
        dlg.transient(self)
        dlg.grab_set()
        dlg.geometry("500x420")

        ttk.Label(dlg, text="内容 (必填):").place(x=10, y=10)
        content_text = tk.Text(dlg, height=3, width=55, font=(SYSTEM_FONT, _fs(10)))
        content_text.place(x=10, y=32)

        ttk.Label(dlg, text="分类:").place(x=10, y=100)
        cat_var = tk.StringVar(value="general")
        ttk.Combobox(dlg, textvariable=cat_var,
                     values=["instruction", "preference", "fact", "reminder", "general"],
                     width=14, state="readonly").place(x=60, y=98)

        ttk.Label(dlg, text="优先级 (0-3):").place(x=10, y=132)
        pri_var = tk.IntVar(value=2)
        ttk.Spinbox(dlg, from_=0, to=3, textvariable=pri_var, width=4).place(x=100, y=130)
        ttk.Label(dlg, text="0=CRITICAL  1=HIGH  2=MEDIUM  3=LOW",
                  font=("", _fs(8)), foreground="#666").place(x=150, y=133)

        ttk.Label(dlg, text="重要度 (1-5):").place(x=10, y=164)
        imp_var = tk.IntVar(value=3)
        ttk.Spinbox(dlg, from_=1, to=5, textvariable=imp_var, width=4).place(x=100, y=162)

        ttk.Label(dlg, text="标签 (逗号分隔):").place(x=10, y=196)
        tags_var = tk.StringVar()
        ttk.Entry(dlg, textvariable=tags_var, width=30).place(x=130, y=194)

        ttk.Label(dlg, text="过期时间 (ISO):").place(x=10, y=228)
        expires_var = tk.StringVar()
        ttk.Entry(dlg, textvariable=expires_var, width=30).place(x=130, y=226)
        ttk.Label(dlg, text="留空=永不过期  格式: 2026-05-01T08:00:00",
                  font=("", _fs(8)), foreground="#666").place(x=130, y=252)

        result_label = ttk.Label(dlg, text="", foreground="#cc0000")
        result_label.place(x=10, y=290)

        def do_add():
            content = content_text.get("1.0", tk.END).strip()
            if not content:
                result_label.config(text="内容不能为空")
                return
            try:
                mid = self.db.add_memory(
                    content=content, category=cat_var.get(), priority=pri_var.get(),
                    importance=imp_var.get(), expires_at=expires_var.get() or None, tags=tags_var.get(),
                )
                result_label.config(text=f"✅ 记忆 #{mid} 已添加", foreground="#008800")
                dlg.after(800, dlg.destroy)
                self._refresh()
            except Exception as e:
                result_label.config(text=f"❌ {e}")

        ttk.Button(dlg, text="添加", command=do_add).place(x=10, y=330, width=80)
        ttk.Button(dlg, text="取消", command=dlg.destroy).place(x=100, y=330, width=80)

    def _soft_delete(self):
        for iid in self.tree.selection():
            try:
                self.db.deactivate_memory(int(iid))
            except Exception:
                pass
        self._refresh()

    def _hard_delete(self):
        for iid in self.tree.selection():
            try:
                self.db.delete_memory(int(iid))
            except Exception:
                pass
        self._refresh()

    def _on_double_click(self, event):
        sel = self.tree.selection()
        if not sel:
            return
        iid = sel[0]
        values = self.tree.item(iid)["values"]
        dlg = tk.Toplevel(self)
        dlg.title(f"记忆 #{iid}")
        dlg.transient(self)
        dlg.geometry("500x300")
        text = tk.Text(dlg, font=(SYSTEM_FONT, _fs(11)), wrap=tk.WORD)
        text.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        text.insert("1.0", values[3])
        text.config(state=tk.DISABLED)
        info = f"优先级: {values[1]} | 分类: {values[2]} | 重要度: {values[4]} | 过期: {values[5]}"
        ttk.Label(dlg, text=info).pack(pady=(0, 10))

    def _export(self):
        from tkinter import filedialog
        memories = self.db.get_active_memories(limit=200)
        if not memories:
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".md", filetypes=[("Markdown", "*.md"), ("Text", "*.txt")])
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write("# 长期记忆导出\n\n")
                for m in memories:
                    f.write(f"## #{m['id']} [{self.PRIORITY_LABELS.get(m['priority'], '?')}] {m['content']}\n")
                    f.write(f"分类: {m['category']} | 重要度: {m['importance']} | 标签: {m.get('tags', '')}\n")
                    if m.get("expires_at"):
                        f.write(f"过期: {m['expires_at']}\n")
                    f.write("\n")
            self.stats_var.set(f"已导出 {len(memories)} 条到 {path}")
        except Exception as e:
            self.stats_var.set(f"导出失败: {e}")
