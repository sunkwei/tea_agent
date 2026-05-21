# -*- coding: utf-8 -*-
# 2026-05-09 gen by tea_agent, 从 gui.py 拆分出的独立对话框模块
"""GUI 对话框：MemoryDialog / TopicDialog / ConfigDialog"""
import tkinter as tk
from tkinter import ttk, scrolledtext
import os
import re
import threading
import logging
# NOTE: 2026-05-15 07:53:34, self-evolved by tea_agent --- ConfigDialog.__init__ 调用 get_config 但未导入，在顶部添加 import
from pathlib import Path
from datetime import datetime
# NOTE: 2026-05-15 07:55:51, self-evolved by tea_agent --- 保存配置时 save_config 未导入，追加到顶部 import
from tea_agent.config import get_config, save_config, load_config
import platform as _platform

# ====================== 记忆管理对话框 ======================

# @2026-04-29 gen by deepseek-v4-pro, MemoryDialog记忆管理弹窗+on_status状态回调
# ====================== 字体检测（与 _gui/_fonts 独立副本） ======================
_IS_WINDOWS = _platform.system() == "Windows"
SYSTEM_FONT = "TkDefaultFont"
MONO_FONT = "TkFixedFont"
_FONTS_DETECTED = False
_SCALE_FACTOR = 1.0
_DEFAULT_FONT_SIZE = 16

def _fs(size):
    return max(1, int(size * _SCALE_FACTOR))

def _init_fonts():
    global SYSTEM_FONT, MONO_FONT, _FONTS_DETECTED, _SCALE_FACTOR, _DEFAULT_FONT_SIZE
    if _FONTS_DETECTED:
        return
    try:
        from tkinter import font as _tkfont
        available = set(_tkfont.families())
        def _detect(candidates):
            for f in candidates:
                if f in available:
                    return f
            return "TkDefaultFont"
        if _IS_WINDOWS:
            SYSTEM_FONT = _detect(["Microsoft YaHei", "Microsoft YaHei UI", "DengXian", "SimHei", "SimSun", "Noto Sans SC", "Microsoft JhengHei"])
            MONO_FONT = _detect(["Cascadia Code", "Cascadia Mono", "Consolas", "Courier New", "Lucida Console"])
        else:
            SYSTEM_FONT = _detect(["Noto Sans CJK SC", "Noto Sans SC", "WenQuanYi Micro Hei", "Source Han Sans SC", "DejaVu Sans"])
            MONO_FONT = _detect(["Noto Sans Mono CJK SC", "DejaVu Sans Mono", "Source Han Mono SC", "Courier New"])
    except Exception:
        pass
    try:
        import tkinter as _tk2
        root = _tk2._default_root
        if root:
            sf = float(root.tk.call("tk", "scaling"))
            if 1.0 < sf <= 4.0:
                _SCALE_FACTOR = sf
    except Exception:
        pass
    _DEFAULT_FONT_SIZE = max(12, int(16 * _SCALE_FACTOR))
    _FONTS_DETECTED = True


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

        _init_fonts()  # 延迟检测系统字体
        self._create_ui()
        self._refresh()

    def _create_ui(self):
        # 顶部统计栏
        top = ttk.Frame(self)
        top.pack(fill=tk.X, padx=10, pady=8)

        self.stats_var = tk.StringVar(value="加载中...")
# NOTE: 2026-04-30 20:04:00, self-evolved by tea_agent --- MemoryDialog 统计栏、添加对话框、查看对话框字体适配缩放
        ttk.Label(top, textvariable=self.stats_var, font=(SYSTEM_FONT, _fs(10))).pack(side=tk.LEFT)

        ttk.Separator(self, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=10)

        # 工具栏
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

        # 记忆列表
        list_frame = ttk.Frame(self)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=4)

        columns = ("id", "priority", "category", "content", "importance", "expires", "tags")
        self.tree = ttk.Treeview(list_frame, columns=columns, show="headings", height=15)

        self.tree.heading("id", text="ID", command=lambda: self._sort("id"))
        self.tree.heading("priority", text="优先级", command=lambda: self._sort("priority"))
        self.tree.heading("category", text="分类")
        self.tree.heading("content", text="内容")
        self.tree.heading("importance", text="重要度")
        self.tree.heading("expires", text="过期")
        self.tree.heading("tags", text="标签")

        self.tree.column("id", width=40, anchor=tk.CENTER)
        self.tree.column("priority", width=70, anchor=tk.CENTER)
        self.tree.column("category", width=60, anchor=tk.CENTER)
        self.tree.column("content", width=320)
        self.tree.column("importance", width=60, anchor=tk.CENTER)
        self.tree.column("expires", width=80, anchor=tk.CENTER)
        self.tree.column("tags", width=100)

        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)

        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # 操作按钮
        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill=tk.X, padx=10, pady=6)

        ttk.Button(btn_frame, text="💤 软删除 (失效)", command=self._soft_delete).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="🗑️ 硬删除", command=self._hard_delete).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="📋 导出记忆...", command=self._export).pack(side=tk.RIGHT, padx=2)

        # 绑定双击查看
        self.tree.bind("<Double-1>", self._on_double_click)

        # 快捷键
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

            cat_str = " ".join(f"{self.CATEGORY_LABELS.get(k,k)}:{v}" for k, v in sorted(by_cat.items()))
            pri_str = " ".join(f"{'!!!' if p==0 else '▲' if p==1 else '●' if p==2 else '○'}:{c}"
                                for p, c in sorted(by_pri.items()))
            self.stats_var.set(f"活跃: {total} 条 | 分类: {cat_str} | 优先级分布: {pri_str}")

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
                expires = m.get("expires_at", "") or "永不过期"
                if len(expires) > 16:
                    expires = expires[:16]
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

        fields = [
            ("内容 (content):", "content", tk.Text, {"height": 3}),
        ]

        ttk.Label(dlg, text="内容 (必填):").place(x=10, y=10)
# NOTE: 2026-04-30 20:04:07, self-evolved by tea_agent --- MemoryDialog 添加对话框的 content_text 字体 _fs(10) 和提示标签 _fs(8)
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
# NOTE: 2026-04-30 20:04:15, self-evolved by tea_agent --- MemoryDialog 添加对话框中的提示标签字体 _fs(8) 适配缩放
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
# NOTE: 2026-04-30 20:04:24, self-evolved by tea_agent --- MemoryDialog 过期时间提示标签和查看对话框字体适配缩放
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
                    content=content,
                    category=cat_var.get(),
                    priority=pri_var.get(),
                    importance=imp_var.get(),
                    expires_at=expires_var.get() or None,
                    tags=tags_var.get(),
                )
                result_label.config(text=f"✅ 记忆 #{mid} 已添加", foreground="#008800")
                dlg.after(800, dlg.destroy)
                self._refresh()
            except Exception as e:
                result_label.config(text=f"❌ {e}")

        ttk.Button(dlg, text="添加", command=do_add).place(x=10, y=330, width=80)
        ttk.Button(dlg, text="取消", command=dlg.destroy).place(x=100, y=330, width=80)

    def _soft_delete(self):
        selection = self.tree.selection()
        if not selection:
            return
        for iid in selection:
            try:
                self.db.deactivate_memory(int(iid))
            except Exception:
                pass
        self._refresh()

    def _hard_delete(self):
        selection = self.tree.selection()
        if not selection:
            return
        for iid in selection:
            try:
                self.db.delete_memory(int(iid))
            except Exception:
                pass
        self._refresh()

    def _on_double_click(self, event):
        selection = self.tree.selection()
        if not selection:
            return
        iid = selection[0]
        item = self.tree.item(iid)
        values = item["values"]
        content = values[3]

        dlg = tk.Toplevel(self)
        dlg.title(f"记忆 #{iid}")
        dlg.transient(self)
        dlg.geometry("500x300")

# NOTE: 2026-04-30 20:04:31, self-evolved by tea_agent --- MemoryDialog 查看对话框字体 _fs(11)
        text = tk.Text(dlg, font=(SYSTEM_FONT, _fs(11)), wrap=tk.WORD)
        text.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        text.insert("1.0", content)
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
                f.write("# 长期记忆导出\\n\\n")
                for m in memories:
                    f.write("## #" + str(m["id"]) + " [" + self.PRIORITY_LABELS.get(m["priority"], "?") + "] " + m["content"] + "\\n")
                    f.write("分类: " + m["category"] + " | 重要度: " + str(m["importance"]) + " | 标签: " + (m.get("tags") or "") + "\\n")
                    if m.get("expires_at"):
                        f.write("过期: " + m["expires_at"] + "\\n")
                    f.write("\\n")
            self.stats_var.set(f"已导出 {len(memories)} 条到 {path}")
        except Exception as e:
            self.stats_var.set(f"导出失败: {e}")


# @2026-04-29 gen by deepseek-v4-pro, 主题管理弹窗: 浏览/切换/导出/重命名/删除
class TopicDialog(tk.Toplevel):
    """主题管理弹窗 — 浏览/切换/导出/重命名/删除"""

# NOTE: 2026-05-06 19:20:44, self-evolved by tea_agent --- TopicDialog.__init__ 初始化搜索状态变量
    def __init__(self, parent, storage, on_switch=None):
        super().__init__(parent)
        self.db = storage
        self.on_switch = on_switch  # callback(topic_id) when user switches
        self.title("📁 主题管理")
        self.geometry("900x600")
        self.minsize(700, 400)
        self.transient(parent)
        self.grab_set()

        # 搜索状态
        self._is_search_mode = False
        self._search_results = []

        _init_fonts()
        self._create_ui()
        self._refresh()

    def _create_ui(self):
        # 顶部统计栏
        top = ttk.Frame(self)
        top.pack(fill=tk.X, padx=10, pady=8)
        self.stats_var = tk.StringVar(value="加载中...")
# NOTE: 2026-04-30 20:04:37, self-evolved by tea_agent --- TopicDialog 统计栏字体 _fs(10)
        ttk.Label(top, textvariable=self.stats_var, font=(SYSTEM_FONT, _fs(10))).pack(side=tk.LEFT)

        ttk.Separator(self, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=10)

        # 工具栏
        toolbar = ttk.Frame(self)
        toolbar.pack(fill=tk.X, padx=10, pady=4)

        ttk.Button(toolbar, text="➕ 新建主题", command=self._new_topic).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="✏️ 重命名", command=self._rename_dialog).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="🔄 刷新", command=self._refresh).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="🔗 切换到此主题", command=self._switch_to).pack(side=tk.LEFT, padx=(20, 2))

        # 导出模式
        ttk.Label(toolbar, text="  导出模式:").pack(side=tk.LEFT, padx=(20, 2))
        self.export_mode = tk.StringVar(value="all")
        ttk.Radiobutton(toolbar, text="完整", variable=self.export_mode, value="all").pack(side=tk.LEFT, padx=2)
        ttk.Radiobutton(toolbar, text="仅用户", variable=self.export_mode, value="user").pack(side=tk.LEFT, padx=2)

# NOTE: 2026-05-06 19:19:28, self-evolved by tea_agent --- TopicDialog._create_ui 在树形列表上方添加语义搜索栏
# NOTE: 2026-05-06 19:22:13, self-evolved by tea_agent --- TopicDialog 工具栏添加「生成向量」按钮用于批量向量化未处理消息
        ttk.Button(toolbar, text="🔄 生成向量", command=self._generate_vectors).pack(side=tk.RIGHT, padx=2)
        ttk.Button(toolbar, text="📋 导出选中", command=self._export_selected).pack(side=tk.RIGHT, padx=2)
        ttk.Button(toolbar, text="📦 导出全部", command=self._export_all).pack(side=tk.RIGHT, padx=2)

        # 语义搜索栏
        search_frame = ttk.Frame(self)
        search_frame.pack(fill=tk.X, padx=10, pady=(4, 0))

        ttk.Label(search_frame, text="🔍 搜索消息:", font=(SYSTEM_FONT, _fs(10))).pack(side=tk.LEFT, padx=(0, 4))
        self.search_var = tk.StringVar()
        self.search_entry = ttk.Entry(search_frame, textvariable=self.search_var, width=40,
                                       font=(SYSTEM_FONT, _fs(10)))
        self.search_entry.pack(side=tk.LEFT, padx=2)
        self.search_entry.bind("<Return>", lambda e: self._do_search())

        ttk.Button(search_frame, text="搜索", command=self._do_search).pack(side=tk.LEFT, padx=2)
        ttk.Button(search_frame, text="清除", command=self._clear_search).pack(side=tk.LEFT, padx=2)
        self.search_mode_var = tk.StringVar(value="")
        ttk.Label(search_frame, textvariable=self.search_mode_var,
                  font=(SYSTEM_FONT, _fs(9)), foreground="gray").pack(side=tk.LEFT, padx=(10, 0))

# NOTE: 2026-05-06 19:49:04, self-evolved by tea_agent --- TopicDialog 改用双 Treeview 模式（topic_tree + search_tree），避免列切换崩溃
        # 主题列表区域（双 Treeview 按模式显隐，避免列切换崩溃）
        self.list_frame = ttk.Frame(self)
        self.list_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=4)

        # --- 主题列表 Treeview ---
        topic_columns = ("id", "title", "created", "tokens", "convs", "active")
        self.topic_tree = ttk.Treeview(self.list_frame, columns=topic_columns, show="headings", height=12)
        self.topic_tree.heading("id", text="ID", command=lambda: self._sort("id"))
        self.topic_tree.heading("title", text="标题", command=lambda: self._sort("title"))
        self.topic_tree.heading("created", text="创建时间", command=lambda: self._sort("created"))
        self.topic_tree.heading("tokens", text="Token消耗", command=lambda: self._sort("tokens"))
        self.topic_tree.heading("convs", text="对话数", command=lambda: self._sort("convs"))
        self.topic_tree.heading("active", text="状态")
        self.topic_tree.column("id", width=50, anchor=tk.CENTER)
        self.topic_tree.column("title", width=280)
        self.topic_tree.column("created", width=140)
        self.topic_tree.column("tokens", width=100, anchor=tk.E)
        self.topic_tree.column("convs", width=70, anchor=tk.CENTER)
        self.topic_tree.column("active", width=60, anchor=tk.CENTER)
        self.topic_tree.bind("<Double-1>", lambda e: self._switch_to())

        self.topic_scrollbar = ttk.Scrollbar(self.list_frame, orient=tk.VERTICAL, command=self.topic_tree.yview)
        self.topic_tree.configure(yscrollcommand=self.topic_scrollbar.set)

        # --- 搜索结果 Treeview ---
        search_columns = ("sim", "user_msg", "topic", "ai_preview")
        self.search_tree = ttk.Treeview(self.list_frame, columns=search_columns, show="headings", height=12)
        self.search_tree.heading("sim", text="相似度")
        self.search_tree.heading("user_msg", text="用户消息")
        self.search_tree.heading("topic", text="所属主题")
        self.search_tree.heading("ai_preview", text="AI 回复预览")
        self.search_tree.column("sim", width=70, anchor=tk.CENTER)
        self.search_tree.column("user_msg", width=350)
        self.search_tree.column("topic", width=150)
        self.search_tree.column("ai_preview", width=250)
        self.search_tree.bind("<Double-1>", lambda e: self._switch_to())

        self.search_scrollbar = ttk.Scrollbar(self.list_frame, orient=tk.VERTICAL, command=self.search_tree.yview)
        self.search_tree.configure(yscrollcommand=self.search_scrollbar.set)

        # 默认显示主题列表
        self.topic_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.topic_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # 操作按钮
        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill=tk.X, padx=10, pady=6)

        ttk.Button(btn_frame, text="💤 停用主题", command=self._deactivate).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="✅ 启用主题", command=self._activate).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="🗑️ 硬删除", command=self._hard_delete).pack(side=tk.LEFT, padx=2)

# NOTE: 2026-05-06 19:51:22, self-evolved by tea_agent --- 移除残留的 self.tree.bind（双树各自已绑定）
        # 绑定（双树各自绑定在 _create_ui 中已设置）
        self.bind("<Escape>", lambda e: self.destroy())
        self.bind("<Delete>", lambda e: self._deactivate())

# NOTE: 2026-05-06 19:20:32, self-evolved by tea_agent --- TopicDialog._refresh 支持搜索模式：搜索时切换列和填充搜索结果
# NOTE: 2026-05-06 19:49:19, self-evolved by tea_agent --- _refresh 改用 topic_tree + 显隐切换逻辑
    def _refresh(self):
        """刷新列表：搜索模式下显示搜索结果，否则显示主题列表"""
        if self._is_search_mode:
            self._show_search_results()
            return

        # ---- 正常主题列表模式 ----
        # 显隐切换
        self.search_tree.pack_forget()
        self.search_scrollbar.pack_forget()
        self.topic_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.topic_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        for item in self.topic_tree.get_children():
            self.topic_tree.delete(item)

        try:
            topics = self.db.list_topics()
            total_tokens = 0
            total_conv = 0
            active_count = 0

            for tp in topics:
                tid = tp.get("topic_id", "?")
                title = tp.get("title", "")
                created = tp.get("create_stamp", "") or ""
                if len(created) > 19:
                    created = created[:19]
                ts = self.db.get_topic_tokens(tid)
                tokens = ts.get("total_tokens", 0) if ts else 0
# NOTE: 2026-04-30 12:02:19, self-evolved by tea_agent --- 修复对话数统计错误：get_conversations默认limit=5导致所有主题显示5
                convs_raw = self.db.get_conversations(tid, limit=-1, include_rounds=False)
                convs = len(convs_raw) if convs_raw else 0
                is_active = tp.get("is_active", 1)

                total_tokens += tokens
                total_conv += convs
                if is_active:
                    active_count += 1

                status = "🟢 活跃" if is_active else "⚫ 停用"
                display_tokens = f"{tokens:,}" if tokens > 0 else "-"

# NOTE: 2026-05-06 19:49:26, self-evolved by tea_agent --- _refresh 中 self.tree → self.topic_tree
                self.topic_tree.insert("", tk.END,
                                        values=(tid, title, created, display_tokens, convs, status),
                                        iid=str(tid))

            self.stats_var.set(
                f"共 {len(topics)} 个主题 (活跃: {active_count}) | "
                f"总 Token: {total_tokens:,} | 总对话: {total_conv}"
            )
        except Exception as e:
            self.stats_var.set(f"加载失败: {e}")

    # ── 搜索相关方法 ─────────────────────────────────────────────

# NOTE: 2026-05-06 19:50:54, self-evolved by tea_agent --- 删除无用的 _setup_topic_columns / _setup_search_columns
# NOTE: 2026-05-06 19:21:47, self-evolved by tea_agent --- _do_search 增加关键词回退：向量不可用时使用 LIKE 搜索
# NOTE: 2026-05-06 19:45:29, self-evolved by tea_agent --- _do_search 改为按向量模型配置分流：已配置→向量搜索，未配置→仅LIKE
    def _do_search(self):
        """执行搜索：向量模型已配置→语义向量搜索，否则→SQL LIKE"""
        query = self.search_var.get().strip()
        if not query:
            self._clear_search()
            return

        self._is_search_mode = True

        try:
            from tea_agent.config import get_config
            cfg = get_config()

            use_vector = cfg.embedding.is_configured
            if use_vector:
                # 向量模型已配置 → 语义向量搜索
                from tea_agent.embedding_util import get_embedding_engine
                engine = get_embedding_engine()
                self.search_mode_var.set(f"模式: {engine.mode}(向量) | 搜索中...")
                self.stats_var.set("正在向量语义搜索...")
                query_vec = engine.embed(query)
                results = self.db.search_by_vector(query_vec, top_k=50, min_similarity=0.15)
            else:
                # 未配置向量模型 → SQL LIKE 回退
                self.search_mode_var.set("模式: 关键词(LIKE) | 搜索中...")
                self.stats_var.set("正在关键词搜索...")
                results = self.db.search_by_keyword(query, top_k=50)

            self._search_results = results
            self._show_search_results()

            mode_str = "向量" if use_vector else "关键词"
            self.search_mode_var.set(f"模式: {mode_str} | 找到 {len(results)} 条结果")
        except Exception as e:
            self.stats_var.set(f"搜索失败: {e}")
            self.search_mode_var.set("搜索失败")
            import logging
            logging.getLogger("GUI").warning(f"搜索失败: {e}")

# NOTE: 2026-05-06 19:49:44, self-evolved by tea_agent --- _show_search_results 改用 search_tree + 显隐切换
    def _show_search_results(self):
        """在搜索结果 Treeview 中显示搜索结果"""
        # 显隐切换
        self.topic_tree.pack_forget()
        self.topic_scrollbar.pack_forget()
        self.search_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.search_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        for item in self.search_tree.get_children():
            self.search_tree.delete(item)

        results = getattr(self, "_search_results", [])
        if not results:
            self.stats_var.set("未找到匹配的消息，尝试更换关键词")
            return

        for r in results:
            sim_pct = f"{r['similarity'] * 100:.0f}%"
            user_msg = (r.get("user_msg", "") or "")[:80]
            topic_label = f"#{r.get('topic_id','?')} {r.get('topic_title','')}"[:30]
            ai_preview = (r.get("ai_msg", "") or "")[:60]
            conv_id = r.get("conversation_id", 0)

            self.search_tree.insert("", tk.END,
                                    values=(sim_pct, user_msg, topic_label, ai_preview),
                                    iid=str(conv_id))

        self.stats_var.set(f"搜索结果: {len(results)} 条匹配消息")

# NOTE: 2026-05-06 19:22:38, self-evolved by tea_agent --- TopicDialog 新增 _generate_vectors 批量向量化方法
    def _clear_search(self):
        """清除搜索，恢复主题列表"""
        self._is_search_mode = False
        self._search_results = []
        self.search_var.set("")
        self.search_mode_var.set("")
        self._refresh()

# NOTE: 2026-05-06 19:45:47, self-evolved by tea_agent --- _generate_vectors 先检查向量模型是否配置，未配置则提示
    def _generate_vectors(self):
        """批量生成未向量化消息的文本向量"""
        from tea_agent.config import get_config
        cfg = get_config()
        if not cfg.embedding.is_configured:
            self.stats_var.set("⚠️ 请先在「配置→向量模型」中设置 API URL 和模型名称")
            return

        from tea_agent.embedding_util import get_embedding_engine

        # 获取未向量化的 conversation
        unvec = self.db.get_unvectorized_conversations(limit=200)
        if not unvec:
            self.stats_var.set("✅ 所有消息已向量化，无需生成")
            return

        import threading

        def _run():
            try:
                engine = get_embedding_engine()
                self.stats_var.set(f"正在向量化 {len(unvec)} 条消息 (模式: {engine.mode})...")
                self.search_mode_var.set("批量向量化进行中...")

                # 先构建 TF-IDF 词汇表
                texts = [item["user_msg"] for item in unvec if item.get("user_msg")]
                if engine.mode == "tfidf":
                    engine.build_tfidf_vocabulary(texts)

                count = 0
                batch_size = 20
                for i in range(0, len(unvec), batch_size):
                    batch = unvec[i:i + batch_size]
                    batch_texts = [item["user_msg"] for item in batch if item.get("user_msg")]

                    try:
                        if engine.mode == "api":
                            embeddings = engine.embed_batch(batch_texts)
                        else:
                            embeddings = [engine.embed(t) for t in batch_texts]

                        # 存储
                        batch_data = []
                        for j, item in enumerate(batch):
                            if j < len(embeddings):
                                batch_data.append({
                                    "conversation_id": item["id"],
                                    "embedding": embeddings[j],
                                })
                        stored = self.db.batch_vectorize(batch_data, engine.model_name)
                        count += stored

                        self.stats_var.set(
                            f"向量化进度: {min(i + batch_size, len(unvec))}/{len(unvec)} (已存 {count})"
                        )
                    except Exception as e:
                        import logging
                        logging.getLogger("GUI").warning(f"批量向量化出错: {e}")
                        # 继续下一批
                        continue

                self.stats_var.set(f"✅ 向量化完成: {count}/{len(unvec)} 条消息")
                self.search_mode_var.set(f"向量总数: {self.db.get_vector_count()}")
            except Exception as e:
                self.stats_var.set(f"向量化失败: {e}")
                self.search_mode_var.set("向量化失败")

        threading.Thread(target=_run, daemon=True).start()

# NOTE: 2026-05-06 19:49:57, self-evolved by tea_agent --- _sort 改用 topic_tree
    def _sort(self, col):
        items = [(self.topic_tree.set(i, col), i) for i in self.topic_tree.get_children("")]
        if col == "id":
            items.sort(key=lambda x: int(x[0]))
        elif col == "tokens":
            def parse_tok(s):
                try:
                    return int(s.replace(",", ""))
                except Exception:
                    return 0 if s == "-" else int(s)
            items.sort(key=lambda x: parse_tok(x[0]), reverse=True)
        elif col == "convs":
            items.sort(key=lambda x: int(x[0]), reverse=True)
        else:
# NOTE: 2026-05-06 19:51:49, self-evolved by tea_agent --- TopicDialog._sort 中 tree.move → topic_tree.move
            items.sort()
        for idx, (_, iid) in enumerate(items):
            self.topic_tree.move(iid, "", idx)

# NOTE: 2026-05-06 19:49:51, self-evolved by tea_agent --- _selected_id 自动选择当前可见的 treeview
    def _selected_id(self):
        tree = self.search_tree if self._is_search_mode else self.topic_tree
        sel = tree.selection()
        return int(sel[0]) if sel else None

# NOTE: 2026-05-06 19:24:25, self-evolved by tea_agent --- TopicDialog._switch_to 搜索模式下使用 conversation 对应的 topic_id
    def _switch_to(self):
        tid = self._selected_id()
        if not tid:
            return
        # 搜索模式下，selected_id 是 conversation_id，需转换为 topic_id
        if self._is_search_mode:
            for r in self._search_results:
                if r.get("conversation_id") == tid:
                    tid = r.get("topic_id")
                    break
        if tid and self.on_switch:
            self.on_switch(tid)
            self.destroy()

    def _new_topic(self):
        title = f"主题 {datetime.now().strftime('%m-%d %H:%M:%S')}"
        self.db.create_topic(title)
        self._refresh()

    # NOTE: 2026-05-08 gen by tea_agent, 搜索模式下禁止重命名（防止误用 conversation_id）
    def _rename_dialog(self):
        if self._is_search_mode:
            return
        tid = self._selected_id()
        if not tid:
            return
        tp = self.db.get_topic(tid)
        old_title = tp.get("title", "") if tp else ""

        dlg = tk.Toplevel(self)
        dlg.title(f"重命名主题 #{tid}")
        dlg.transient(self)
        dlg.grab_set()
        dlg.geometry("400x140")

        ttk.Label(dlg, text="新标题:").pack(padx=10, pady=(15, 2), anchor=tk.W)
        title_var = tk.StringVar(value=old_title)
# NOTE: 2026-04-30 20:04:45, self-evolved by tea_agent --- TopicDialog 重命名输入框字体 _fs(11)
        entry = ttk.Entry(dlg, textvariable=title_var, width=50, font=(SYSTEM_FONT, _fs(11)))
        entry.pack(padx=10, pady=4)
        entry.select_range(0, tk.END)
        entry.focus()

        def do_rename():
            new_title = title_var.get().strip()
            if new_title:
                self.db.update_topic_title(tid, new_title)
                self._refresh()
                dlg.destroy()

        btn_frame = ttk.Frame(dlg)
        btn_frame.pack(pady=10)
        ttk.Button(btn_frame, text="确定", command=do_rename).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_frame, text="取消", command=dlg.destroy).pack(side=tk.LEFT, padx=4)
        dlg.bind("<Return>", lambda e: do_rename())

# NOTE: 2026-05-06 19:24:56, self-evolved by tea_agent --- TopicDialog._deactivate/_activate/_hard_delete 搜索模式下保护
    def _deactivate(self):
        if self._is_search_mode:
            return  # 搜索模式下禁用以防止误操作
        tid = self._selected_id()
        if tid:
            self.db.update_topic_active(tid, 0)
            self._refresh()

    def _activate(self):
        if self._is_search_mode:
            return
        tid = self._selected_id()
        if tid:
            self.db.update_topic_active(tid, 1)
            self._refresh()

# NOTE: 2026-05-06 19:25:02, self-evolved by tea_agent --- _hard_delete 和 _export_selected 搜索模式保护
    def _hard_delete(self):
        if self._is_search_mode:
            return
        tid = self._selected_id()
        if not tid:
            return
        from tkinter import messagebox
        tp = self.db.get_topic(tid)
        title = tp.get("title", f"#{tid}") if tp else f"#{tid}"
        ok = messagebox.askyesno(
            "确认删除",
            f"确定要永久删除主题「{title}」吗？\n\n"
            f"此操作不可撤销，所有对话记录将被删除。",
            parent=self,
            icon="warning",
        )
        if not ok:
            return
        self.db.delete_topic(tid)
        self.stats_var.set(f"✅ 主题 #{tid} 「{title}」已永久删除")
        self._refresh()

# NOTE: 2026-05-06 19:25:09, self-evolved by tea_agent --- _export_selected 搜索模式保护
    def _export_selected(self):
        if self._is_search_mode:
            return
        tid = self._selected_id()
        if not tid:
            return
        self._do_export([tid])

    def _export_all(self):
        topics = self.db.list_topics()
        if not topics:
            return
        tids = [t["topic_id"] for t in topics]
        self._do_export(tids)

    def _do_export(self, topic_ids: list):
        from tkinter import filedialog

        mode = self.export_mode.get()  # "all" or "user"
        mode_label = "完整" if mode == "all" else "仅用户输入"

        if len(topic_ids) == 1:
            tp = self.db.get_topic(topic_ids[0])
            default_name = f"topic_{topic_ids[0]}.md"
        else:
            default_name = f"topics_{datetime.now().strftime('%Y%m%d')}.md"

        path = filedialog.asksaveasfilename(
            defaultextension=".md",
            filetypes=[("Markdown", "*.md"), ("Text", "*.txt")],
            initialfile=default_name,
        )
        if not path:
            return

        try:
            with open(path, "w", encoding="utf-8") as f:
                if len(topic_ids) == 1:
                    self._write_topic_md(f, topic_ids[0], mode)
                else:
                    f.write(f"# 主题批量导出 ({mode_label}模式)\n\n")
                    f.write(f"**导出时间:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                    f.write(f"**主题数量:** {len(topic_ids)}\n\n")
                    f.write("---\n\n")
                    for tid in topic_ids:
                        self._write_topic_md(f, tid, mode)
                        f.write("\n---\n\n")

            self.stats_var.set(f"✅ 已导出 {len(topic_ids)} 个主题 → {path}")
        except Exception as e:
            self.stats_var.set(f"❌ 导出失败: {e}")

    def _write_topic_md(self, f, topic_id: str, mode: str):
        """Write a single topic as markdown to file handle."""
        tp = self.db.get_topic(topic_id)
        title = tp.get("title", f"主题 #{topic_id}") if tp else f"主题 #{topic_id}"
        created = tp.get("create_stamp", "") if tp else ""
        updated = tp.get("last_update_stamp", "") if tp else ""

        ts = self.db.get_topic_tokens(topic_id) or {}
# NOTE: 2026-04-30 12:02:39, self-evolved by tea_agent --- 修复导出功能中对话数同样被limit=5截断的问题
# NOTE: 2026-04-30 12:07:44, self-evolved by tea_agent --- 修复完整导出缺少tool calling中间数据：all模式需include_rounds=True
        if mode == "all":
            convs = self.db.get_conversations(topic_id, limit=-1, include_rounds=True) or []
        else:
            convs = self.db.get_conversations(topic_id, limit=-1, include_rounds=False) or []

        f.write(f"# {title}\n\n")
        f.write(f"- **ID:** {topic_id}\n")
        f.write(f"- **创建时间:** {created}\n")
        f.write(f"- **最后更新:** {updated}\n")
        f.write(f"- **对话数:** {len(convs)}\n")
# NOTE: 2026-05-07 13:14:32, self-evolved by tea_agent --- 主题导出文件增加嵌入模型 token 行
        f.write(f"- **Token消耗:** {ts.get('total_tokens', 0):,} "
                f"(P:{ts.get('total_prompt_tokens', 0):,} "
                f"C:{ts.get('total_completion_tokens', 0):,})\n")
        f.write(f"- **便宜模型:** {ts.get('total_cheap_tokens', 0):,} "
                f"(P:{ts.get('total_cheap_prompt_tokens', 0):,} "
                f"C:{ts.get('total_cheap_completion_tokens', 0):,})\n")
        f.write(f"- **嵌入模型:** {ts.get('total_embedding_tokens', 0):,} "
                f"(P:{ts.get('total_embedding_prompt_tokens', 0):,})\n")
        f.write(f"- **导出模式:** {'仅用户输入' if mode == 'user' else '完整（含AI回复与工具调用）'}\n")
        f.write("\n---\n\n")

        for c in convs:
            user_msg = c.get("user_msg", "") or ""
            ai_msg = c.get("ai_msg", "") or ""

            f.write(f"## 👤 用户\n\n{user_msg}\n\n")

            if mode == "all":
                rounds = c.get("rounds_json_parsed")
                if rounds and c.get("is_func_calling"):
                    f.write(f"### 🔧 工具调用链\n\n")
                    for rd in rounds:
                        role = rd.get("role", "")
                        if role == "assistant" and rd.get("tool_calls"):
                            for tc in rd["tool_calls"]:
                                fn = tc.get("function", {})
                                f.write(f"- **调用:** `{fn.get('name', '?')}({fn.get('arguments', '')})`\n")
                            if rd.get("content"):
                                f.write(f"- **AI:** {rd['content']}\n")
# NOTE: 2026-04-30 12:08:14, self-evolved by tea_agent --- 移除完整导出中工具结果的500字符截断，保持完整性
                        elif role == "tool":
                            result = rd.get("content", "") or ""
                            f.write(f"- **结果:** {result}\n")
                        elif role == "assistant" and rd.get("content"):
                            f.write(f"- **AI:** {rd['content']}\n")
                    f.write("\n")
                else:
                    f.write(f"## 🤖 AI\n\n{ai_msg}\n\n")

            f.write("---\n\n")



# NOTE: 2026-05-01 15:33:03, self-evolved by tea_agent --- 插入 ConfigDialog 类（在 TkGUI 之前）
# NOTE: 2026-05-01, self-evolved by tea_agent --- ConfigDialog: 用户级 config.yaml GUI 配置编辑弹窗
class ConfigDialog(tk.Toplevel):
# NOTE: 2026-05-06 19:32:03, self-evolved by tea_agent --- ConfigDialog 文档字符串更新，反映新增向量模型配置
    """配置编辑弹窗 — 编辑主模型/便宜模型/向量模型及运行时参数"""

    def __init__(self, parent, on_save=None, config_path=None):
        super().__init__(parent)
        self.on_save = on_save
        self._config_path = config_path
# NOTE: 2026-05-06 19:31:57, self-evolved by tea_agent --- ConfigDialog 窗口尺寸微调适配新增 Tab
        self.title("⚙️ 配置编辑")
# NOTE: 2026-05-17 08:55:29, self-evolved by tea_agent --- 增大 ConfigDialog 窗口以适应新增 Tab
        self.geometry("650x680")
        self.minsize(550, 500)
        self.transient(parent)
        self.grab_set()

        _init_fonts()
        self._cfg = load_config(self._config_path) if self._config_path else get_config()
        self._create_ui()
        self._load_values()

# NOTE: 2026-05-06 19:30:48, self-evolved by tea_agent --- ConfigDialog._create_ui 增加「向量模型」Tab
    def _create_ui(self):
        nb = ttk.Notebook(self)
        nb.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

# NOTE: 2026-05-06 19:31:49, self-evolved by tea_agent --- _create_ui 中向量模型 Tab 增加 dimension 字段
# NOTE: 2026-05-16 19:36:47, self-evolved by tea_agent --- 主模型 Tab 添加能力选项（supports_vision, supports_reasoning）
        self._model_tab(nb, "主模型", "main", options_prefix="main")
        self._model_tab(nb, "便宜模型", "cheap", options_prefix="cheap")
# NOTE: 2026-05-07 07:29:28, self-evolved by tea_agent --- 向量模型 Tab 增加 URL 格式提示
# NOTE: 2026-05-07 07:29:42, self-evolved by tea_agent --- 回退 hint 字段，改用 _model_tab 的 hint 参数渲染标签
# NOTE: 2026-05-17 08:54:27, self-evolved by tea_agent --- _create_ui 增加「模式参数」Tab
        self._model_tab(nb, "向量模型", "embedding", extra_fields=[
            ("向量维度", "dimension", 10),
        ], hint="API URL 示例: https://api.siliconflow.cn/v1")
        # @2026-05-17 gen by tea_agent, 模式参数 Tab
        self._mode_params_tab(nb)
        self._runtime_tab(nb)

        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill=tk.X, padx=10, pady=10)
        self._status_var = tk.StringVar(value="")
        ttk.Label(btn_frame, textvariable=self._status_var, foreground="#666").pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_frame, text="💾 保存", command=self._do_save).pack(side=tk.RIGHT, padx=2)
        ttk.Button(btn_frame, text="取消", command=self.destroy).pack(side=tk.RIGHT, padx=2)

# NOTE: 2026-05-06 19:31:41, self-evolved by tea_agent --- _model_tab 支持 extra_fields 参数，向量模型增加 dimension 输入
# NOTE: 2026-05-07 07:30:04, self-evolved by tea_agent --- _model_tab 支持 hint 参数，在字段下方渲染灰色提示
    def _model_tab(self, nb, label, prefix, extra_fields=None, hint=None, options_prefix=None):
        f = ttk.Frame(nb)
        nb.add(f, text=label)
        fields = [
            ("API Key", "api_key", 40),
            ("API URL", "api_url", 50),
            ("模型名称", "model_name", 50),
        ]
        if extra_fields:
            fields.extend(extra_fields)
# NOTE: 2026-05-07 07:30:10, self-evolved by tea_agent --- 初始化 row_idx 避免空 fields 时 NameError
        vars_map = {}
        for row_idx, (title, key, width) in enumerate(fields):
            ttk.Label(f, text=title + ":", font=(SYSTEM_FONT, _fs(11))).grid(
                row=row_idx, column=0, sticky=tk.W, padx=(10, 4), pady=8)
            var = tk.StringVar()
            ttk.Entry(f, textvariable=var, width=width, font=(SYSTEM_FONT, _fs(11))).grid(
                row=row_idx, column=1, sticky=tk.EW, padx=(4, 10), pady=8)
            vars_map[key] = var
        if hint:
            ttk.Label(f, text="ℹ️ " + hint, font=(SYSTEM_FONT, _fs(10)),
                      foreground="#888").grid(row=row_idx + 1, column=0, columnspan=2,
                                              sticky=tk.W, padx=(10, 4), pady=(0, 8))
        f.columnconfigure(1, weight=1)
        setattr(self, f"_{prefix}_vars", vars_map)

        # 模型能力选项 (supports_vision / supports_reasoning)
        if options_prefix:
            opts_key = f"_{options_prefix}_opts"
            opts_var = {}
            # NOTE: 2026-07-05 gen by tea_agent, ttk.Checkbutton font 通过 style 设置
            _cb_style = ttk.Style()
            _cb_style.configure(f"{options_prefix}.TCheckbutton", font=(SYSTEM_FONT, _fs(11)))
            # 在主模型能力之前加一行文字提示
            row_idx += 2
            ttk.Label(f, text="── 模型能力 ──", font=(SYSTEM_FONT, _fs(10)),
                      foreground="#888").grid(row=row_idx, column=0, columnspan=2,
                                              sticky=tk.W, padx=(10, 4), pady=(12, 4))
            for cb_label, cb_key, cb_default in [
                ("👁️ 支持视觉（发送 image_url 格式图片）", "supports_vision", False),
                ("🧠 支持推理（发送 reasoning_content 字段）", "supports_reasoning", True),
            ]:
                row_idx += 1
                var = tk.BooleanVar(value=cb_default)
                ttk.Checkbutton(f, text=cb_label, variable=var,
                                style=f"{options_prefix}.TCheckbutton").grid(
                    row=row_idx, column=0, columnspan=2,
                    sticky=tk.W, padx=(20, 10), pady=2)
                opts_var[cb_key] = var
# NOTE: 2026-05-17 08:53:37, self-evolved by tea_agent --- _model_tab 增加推理参数字段 (temperature/max_tokens/top_p)
            setattr(self, opts_key, opts_var)

        # @2026-05-17 gen by tea_agent, 推理参数字段（紧跟模型能力 Checkbutton）
        if options_prefix:
            row_idx += 2
            ttk.Label(f, text="── 推理参数 ──", font=(SYSTEM_FONT, _fs(10)),
                      foreground="#888").grid(row=row_idx, column=0, columnspan=2,
                                              sticky=tk.W, padx=(10, 4), pady=(12, 4))
            params_var = {}
            for p_key, p_label, p_default in [
                ("temperature", "Temperature", "0.7"),
                ("max_tokens", "Max Tokens", "4096"),
                ("top_p", "Top-P", "0.9"),
            ]:
                row_idx += 1
                ttk.Label(f, text=p_label + ":", font=(SYSTEM_FONT, _fs(11))).grid(
                    row=row_idx, column=0, sticky=tk.W, padx=(20, 4), pady=4)
                var = tk.StringVar(value=p_default)
                ttk.Entry(f, textvariable=var, width=10, font=(SYSTEM_FONT, _fs(11))).grid(
                    row=row_idx, column=1, sticky=tk.W, padx=(4, 10), pady=4)
                params_var[p_key] = var
            setattr(self, f"_{options_prefix}_params", params_var)

# NOTE: 2026-05-17 08:54:51, self-evolved by tea_agent --- 实现 _mode_params_tab 方法
    # @2026-05-17 gen by tea_agent, 模式参数 Tab — 按人格模式覆盖 temperature/top_p
    def _mode_params_tab(self, nb):
        f = ttk.Frame(nb)
        nb.add(f, text="模式参数")
        ttk.Label(f, text="不同人格模式下可覆盖 Temperature / Top-P（留空则使用模型默认值）",
                  font=(SYSTEM_FONT, _fs(10)), foreground="#888").pack(anchor=tk.W, padx=10, pady=(10, 4))

        self._mode_params_vars = {}
        modes = [
            ("pragmatic", "🎯 严谨模式", "代码开发 / Bug 排查 / 需求遵从", "0.3", "0.9"),
            ("creative", "🎨 创意模式", "头脑风暴 / 异想天开 / 发散联想", "0.8", "0.95"),
            ("mixed", "⚖️ 混合模式", "自动均衡", "0.6", "0.9"),
        ]
        for m_key, m_label, m_desc, def_temp, def_topp in modes:
            frame = ttk.LabelFrame(f, text=m_label, padding=8)
            frame.pack(fill=tk.X, padx=10, pady=6)
            ttk.Label(frame, text=m_desc, font=(SYSTEM_FONT, _fs(10)),
                      foreground="#666").grid(row=0, column=0, columnspan=4, sticky=tk.W, pady=(0, 4))

            ttk.Label(frame, text="Temperature:", font=(SYSTEM_FONT, _fs(11))).grid(
                row=1, column=0, sticky=tk.W, padx=(0, 4))
            temp_var = tk.StringVar(value=def_temp)
            ttk.Entry(frame, textvariable=temp_var, width=8, font=(SYSTEM_FONT, _fs(11))).grid(
                row=1, column=1, sticky=tk.W, padx=(0, 16))

            ttk.Label(frame, text="Top-P:", font=(SYSTEM_FONT, _fs(11))).grid(
                row=1, column=2, sticky=tk.W, padx=(0, 4))
            topp_var = tk.StringVar(value=def_topp)
            ttk.Entry(frame, textvariable=topp_var, width=8, font=(SYSTEM_FONT, _fs(11))).grid(
                row=1, column=3, sticky=tk.W)

# NOTE: 2026-05-17 09:13:14, self-evolved by tea_agent --- 修复：恢复 _runtime_tab 方法头（被 _mode_params_tab 覆盖吃掉）
            self._mode_params_vars[m_key] = {"temperature": temp_var, "top_p": topp_var}

    # @2026-05-17 gen by tea_agent, 运行时参数 Tab（原方法，修复被覆盖的方法头）
    def _runtime_tab(self, nb):
        f = ttk.Frame(nb)
        nb.add(f, text="运行时参数")

        canvas = tk.Canvas(f, highlightthickness=0)
        scrollbar = ttk.Scrollbar(f, orient=tk.VERTICAL, command=canvas.yview)
        scroll_frame = ttk.Frame(canvas)
        scroll_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scroll_frame, anchor=tk.NW)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)
        self._mw_binding = _on_mousewheel

        fields = [
            ("max_history", "最大历史消息数", int, 1, 100),
            ("max_iterations", "最大工具调用迭代数", int, 1, 200),
            ("enable_thinking", "启用 Thinking", bool, None, None),
            ("keep_turns", "保留最近 N 轮完整对话", int, 1, 50),
            ("max_tool_output", "工具输出截断字符数", int, 1024, 1048576),
            ("max_assistant_content", "助手回复截断字符数", int, 1024, 1048576),
            ("extra_iterations_on_continue", "续命时追加轮数", int, 1, 50),
            ("memory_extraction_threshold", "记忆提取阈值（消息数）", int, 1, 50),
            ("memory_dedup_threshold", "记忆去重相似度阈值", float, 0.0, 1.0),
            ("chat_page_size", "GUI 单页对话数", int, 5, 200),
        ]

        self._runtime_vars = {}
        for i, (key, label, typ, vmin, vmax) in enumerate(fields):
            ttk.Label(scroll_frame, text=label + ":", font=(SYSTEM_FONT, _fs(11))).grid(
                row=i, column=0, sticky=tk.W, padx=(10, 4), pady=6)

            if typ == bool:
                var = tk.BooleanVar()
                ttk.Checkbutton(scroll_frame, variable=var).grid(
                    row=i, column=1, sticky=tk.W, padx=(4, 10), pady=6)
            else:
                var = tk.StringVar()
                ttk.Entry(scroll_frame, textvariable=var, width=20, font=(SYSTEM_FONT, _fs(11))).grid(
                    row=i, column=1, sticky=tk.W, padx=(4, 10), pady=6)
                var._range = (vmin, vmax)
                var._typ = typ

            self._runtime_vars[key] = var

# NOTE: 2026-05-06 19:31:02, self-evolved by tea_agent --- ConfigDialog._load_values 加载 embedding 模型字段
    def _load_values(self):
        cfg = self._cfg
# NOTE: 2026-05-17 08:53:53, self-evolved by tea_agent --- _load_values 加载推理参数 (temperature/max_tokens/top_p)
        for prefix, model_cfg in [("main", cfg.main_model), ("cheap", cfg.cheap_model)]:
            vars_map = getattr(self, f"_{prefix}_vars")
            vars_map["api_key"].set(model_cfg.api_key)
            vars_map["api_url"].set(model_cfg.api_url)
            vars_map["model_name"].set(model_cfg.model_name)
            # @2026-05-17 gen by tea_agent, 加载推理参数
            params_map = getattr(self, f"_{prefix}_params", {})
            if "temperature" in params_map:
                params_map["temperature"].set(str(model_cfg.temperature))
            if "max_tokens" in params_map:
                params_map["max_tokens"].set(str(model_cfg.max_tokens))
            if "top_p" in params_map:
                params_map["top_p"].set(str(model_cfg.top_p))

        # 加载向量模型配置
        emb_vars = getattr(self, "_embedding_vars")
        emb_vars["api_key"].set(cfg.embedding.api_key)
        emb_vars["api_url"].set(cfg.embedding.api_url)
        emb_vars["model_name"].set(cfg.embedding.model_name)
        emb_vars["dimension"].set(str(cfg.embedding.dimension or ""))

# NOTE: 2026-05-17 08:55:04, self-evolved by tea_agent --- _load_values 加载 mode_params
        # 加载各模型 options
        for prefix in ("main", "cheap"):
            model_cfg = getattr(cfg, f"{prefix}_model")
            opts = model_cfg.options or {}
            opts_key = f"_{prefix}_opts"
            vars_map = getattr(self, opts_key, {})
            for key, var in vars_map.items():
                var.set(opts.get(key, var.get()))

        # @2026-05-17 gen by tea_agent, 加载模式参数
        for mode_name, vars_dict in self._mode_params_vars.items():
            mode_cfg = cfg.mode_params.get(mode_name, {})
            for k, var in vars_dict.items():
                var.set(str(mode_cfg.get(k, var.get())))

        for key, var in self._runtime_vars.items():
            val = getattr(cfg, key, None)
            if val is not None:
                if isinstance(var, tk.BooleanVar):
                    var.set(bool(val))
                else:
                    var.set(str(val))

    def _do_save(self):
        cfg = self._cfg
        errors = []

# NOTE: 2026-05-06 19:31:16, self-evolved by tea_agent --- ConfigDialog._do_save 保存 embedding 模型配置
# NOTE: 2026-05-17 08:54:14, self-evolved by tea_agent --- _do_save 保存推理参数到 ModelConfig
        for prefix, model_cfg in [("main", cfg.main_model), ("cheap", cfg.cheap_model)]:
            vars_map = getattr(self, f"_{prefix}_vars")
            model_cfg.api_key = vars_map["api_key"].get().strip()
            model_cfg.api_url = vars_map["api_url"].get().strip()
            model_cfg.model_name = vars_map["model_name"].get().strip()
            # @2026-05-17 gen by tea_agent, 保存推理参数
            params_map = getattr(self, f"_{prefix}_params", {})
            for p_key, p_attr in [("temperature", "temperature"), ("max_tokens", "max_tokens"), ("top_p", "top_p")]:
                if p_key in params_map:
                    try:
                        raw = params_map[p_key].get().strip()
                        if raw:
                            setattr(model_cfg, p_attr, float(raw) if p_attr != "max_tokens" else int(raw))
                    except (ValueError, TypeError):
                        errors.append(f"{prefix}_model.{p_key}: 格式错误")
            setattr(self, f"_{prefix}_params", params_map)  # ensure it exists

        # 保存向量模型配置
        ev = self._embedding_vars
        cfg.embedding.api_key = ev["api_key"].get().strip()
        cfg.embedding.api_url = ev["api_url"].get().strip()
        cfg.embedding.model_name = ev["model_name"].get().strip()
        try:
            cfg.embedding.dimension = int(ev["dimension"].get().strip() or "0")
# NOTE: 2026-05-17 08:55:20, self-evolved by tea_agent --- _do_save 保存 mode_params
        except ValueError:
            cfg.embedding.dimension = 0

        # @2026-05-17 gen by tea_agent, 保存模式参数
        cfg.mode_params = {}
        for mode_name, vars_dict in self._mode_params_vars.items():
            mode_cfg = {}
            for k, var in vars_dict.items():
                raw = var.get().strip()
                if raw:
                    try:
                        mode_cfg[k] = float(raw)
                    except ValueError:
                        errors.append(f"mode_params.{mode_name}.{k}: 格式错误")
            if mode_cfg:
                cfg.mode_params[mode_name] = mode_cfg

        # 保存各模型 options
        for prefix in ("main", "cheap"):
            model_cfg = getattr(cfg, f"{prefix}_model")
            model_cfg.options = {}
            opts_key = f"_{prefix}_opts"
            vars_map = getattr(self, opts_key, {})
            for key, var in vars_map.items():
                model_cfg.options[key] = var.get()

        for key, var in self._runtime_vars.items():
            try:
                if isinstance(var, tk.BooleanVar):
                    cfg.set(key, var.get())
                else:
                    raw = var.get().strip()
                    if not raw:
                        continue
                    typ = getattr(var, '_typ', str)
                    val = typ(raw)
                    vmin, vmax = getattr(var, '_range', (None, None))
                    if vmin is not None and val < vmin:
                        errors.append(f"{key}: 最小 {vmin}")
                        continue
                    if vmax is not None and val > vmax:
                        errors.append(f"{key}: 最大 {vmax}")
                        continue
                    cfg.set(key, val)
            except (ValueError, TypeError) as e:
                errors.append(f"{key}: 格式错误 ({e})")

        if errors:
            self._status_var.set(f"❌ {'; '.join(errors)}")
            return

        try:
# NOTE: 2026-05-04 17:58:01, self-evolved by tea_agent --- GUI 配置保存状态提示使用实际保存路径
# NOTE: 2026-05-20 gen by tea_agent, 保存到当前配置对应的文件，而非默认路径
            saved_path = save_config(cfg, config_path=self._config_path)
            self._status_var.set(f"✅ 已保存到 {saved_path}")
            if self.on_save:
                self.on_save(cfg)
            self.after(1500, self.destroy)
        except Exception as e:
            self._status_var.set(f"❌ 保存失败: {e}")

    def destroy(self):
        if hasattr(self, '_mw_binding'):
            try:
                self.unbind_all("<MouseWheel>")
            except Exception:
                pass
        super().destroy()


