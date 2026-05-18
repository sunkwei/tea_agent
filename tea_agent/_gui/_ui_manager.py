"""
@2026-07-05 gen by tea_agent, UI Manager Component (组合模式)
Handles UI creation, layout, zoom, tooltips, title updates.
"""

import tkinter as tk
from tkinter import ttk, Listbox, Frame
from tkinter import font as tkFont
from typing import Optional

SYSTEM_FONT = "TkDefaultFont"
MONO_FONT = "TkFixedFont"

# 全局字体缩放
_font_scale = 1.0
def _fs(size: int) -> int:
    return int(size * _font_scale)

class UIManager:
    """UI 管理组件，通过组合方式注入 TkGUI"""
    
    def __init__(self, gui):
        self.gui = gui
    
    def create_ui(self):
        """创建界面"""
        main_split = ttk.PanedWindow(self.gui.root, orient=tk.HORIZONTAL)
        main_split.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

        # ===== 左侧面板 =====
        left = Frame(main_split, width=220)
        main_split.add(left, weight=1)

        ttk.Label(left, text="聊天主题", font=(SYSTEM_FONT, _fs(14), "bold")).pack(pady=5)
        _topic_font = tkFont.Font(family=SYSTEM_FONT, size=_fs(12))
        _topic_style = ttk.Style()
        _topic_style.configure("Topic.Treeview", rowheight=_fs(30))
        
        self.gui._topic_tree = ttk.Treeview(left, show="tree", style="Topic.Treeview")
        self.gui._topic_tree.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        self.gui._topic_tree.bind("<<TreeviewSelect>>", self.gui.event_manager.on_topic_select)
        self.gui._topic_tree.bind("<Enter>", self.gui._on_topic_hover)
        self.gui._topic_tree.bind("<Leave>", self.gui._on_topic_leave)

        # 底部按钮区
        btn_frame = Frame(left)
        btn_frame.pack(fill=tk.X, padx=4, pady=4)
        self.gui._new_topic_btn = ttk.Button(btn_frame, text="➕ 新主题", command=self.gui.session_manager.new_topic)
        self.gui._new_topic_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2)
        self.gui._refresh_btn = ttk.Button(btn_frame, text="🔄", command=self.gui.session_manager.refresh_topics)
        self.gui._refresh_btn.pack(side=tk.LEFT, padx=2)

        # ===== 右侧面板 =====
        right = Frame(main_split)
        main_split.add(right, weight=4)

        # 顶部状态栏
        top_bar = Frame(right)
        top_bar.pack(fill=tk.X, padx=6, pady=2)
        self.gui._status_label = ttk.Label(top_bar, text="就绪", foreground="gray")
        self.gui._status_label.pack(side=tk.LEFT)
        
        self.gui._reasoning_btn = ttk.Button(top_bar, text="🧠 推理", command=self.gui.session_manager.toggle_reasoning)
        self.gui._reasoning_btn.pack(side=tk.RIGHT, padx=2)
        self.gui._interrupt_btn = ttk.Button(top_bar, text="⏹ 中断", command=self.gui.event_manager.interrupt, state=tk.DISABLED)
        self.gui._interrupt_btn.pack(side=tk.RIGHT, padx=2)
        self.gui._clear_btn = ttk.Button(top_bar, text="🗑 清空", command=self.gui.session_manager.clear_chat)
        self.gui._clear_btn.pack(side=tk.RIGHT, padx=2)

        # 聊天显示区（PanedWindow 分上下）
        chat_split = ttk.PanedWindow(right, orient=tk.VERTICAL)
        chat_split.pack(fill=tk.BOTH, expand=True, padx=6, pady=4)

        # 上方：聊天消息
        chat_frame = Frame(chat_split)
        chat_split.add(chat_frame, weight=8)
        
        self.gui._chat_canvas = tk.Canvas(chat_frame, bg="#f8f9fa")
        self.gui._chat_scrollbar = ttk.Scrollbar(chat_frame, orient=tk.VERTICAL, command=self.gui._chat_canvas.yview)
        self.gui._chat_frame_inner = Frame(self.gui._chat_canvas, bg="#f8f9fa")
        
        self.gui._chat_frame_inner.bind("<Configure>", lambda e: self.gui._chat_canvas.configure(scrollregion=self.gui._chat_canvas.bbox("all")))
        self.gui._chat_canvas.create_window((0, 0), window=self.gui._chat_frame_inner, anchor="nw")
        self.gui._chat_canvas.configure(yscrollcommand=self.gui._chat_scrollbar.set)
        
        self.gui._chat_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.gui._chat_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # 下方：控制台输出
        self.gui.console = tk.Text(chat_split, height=6, font=("Consolas", _fs(9)), bg="#1e1e1e", fg="#d4d4d4", state=tk.DISABLED)
        console_scroll = ttk.Scrollbar(chat_split, orient=tk.VERTICAL, command=self.gui.console.yview)
        self.gui.console.configure(yscrollcommand=console_scroll.set)
        chat_split.add(self.gui.console, weight=2)

        # 底部输入区
        input_frame = Frame(right)
        input_frame.pack(fill=tk.X, padx=6, pady=4)

        self.gui._img_label = ttk.Label(input_frame, text="")
        self.gui._img_label.pack(side=tk.LEFT, padx=4)
        self.gui._clear_img_btn = ttk.Button(input_frame, text="✕", command=self.gui.event_manager.clear_images, state=tk.DISABLED)
        self.gui._clear_img_btn.pack(side=tk.LEFT)

        self.gui._input = tk.Text(input_frame, height=3, font=(SYSTEM_FONT, _fs(11)))
        self.gui._input.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=4)
        self.gui._input.bind("<Return>", self.gui.event_manager.newline)
        self.gui._input.bind("<Control-Return>", self.gui.event_manager.send)

        send_btn = ttk.Button(input_frame, text="📤 发送", command=self.gui.event_manager.send)
        send_btn.pack(side=tk.RIGHT, padx=4)
        attach_btn = ttk.Button(input_frame, text="📎 图片", command=self.gui.event_manager.attach_image)
        attach_btn.pack(side=tk.RIGHT, padx=4)

        # 缩放控制
        self.gui._zoom_label = ttk.Label(top_bar, text=f"🔍 {_fs(100)}%")
        self.gui._zoom_label.pack(side=tk.RIGHT, padx=4)
        self.gui._zoom_label.bind("<Button-1>", lambda e: self.zoom_in())
        self.gui._zoom_label.bind("<Button-3>", lambda e: self.zoom_out())

        # Tooltip
        self.gui._tooltip = None
        self.gui._tooltip_text = ""

    def adjust_chat_sash(self):
        """调整聊天区域分割条"""
        self.gui.root.after(100, lambda: self.gui._chat_canvas.configure(scrollregion=self.gui._chat_canvas.bbox("all")))

    def zoom_in(self, e=None):
        global _font_scale
        _font_scale = min(1.5, _font_scale + 0.1)
        self._apply_zoom()

    def zoom_out(self, e=None):
        global _font_scale
        _font_scale = max(0.6, _font_scale - 0.1)
        self._apply_zoom()

    def _apply_zoom(self):
        self.gui._zoom_label.config(text=f"🔍 {int(_font_scale*100)}%")
        self.gui._input.config(font=(SYSTEM_FONT, _fs(11)))
        self.gui.console.config(font=("Consolas", _fs(9)))
        self.gui._chat_canvas.update_idletasks()

    def history_prev_round(self, e=None):
        if self.gui._current_round_view is None:
            self.gui._current_round_view = len(self.gui._chat_rounds) - 2
        elif self.gui._current_round_view > 0:
            self.gui._current_round_view -= 1
        if self.gui._current_round_view is not None and self.gui._current_round_view >= 0:
            self.gui.render_manager.render_round_view(self.gui._current_round_view)

    def history_next_round(self, e=None):
        if self.gui._current_round_view is None:
            self.gui._current_round_view = 0
        elif self.gui._current_round_view < len(self.gui._chat_rounds) - 1:
            self.gui._current_round_view += 1
        if self.gui._current_round_view is not None:
            if self.gui._current_round_view == len(self.gui._chat_rounds) - 1:
                self.gui._current_round_view = None
            self.gui.render_manager.render_round_view(self.gui._current_round_view)

    def show_tooltip(self, event, idx):
        item = self.gui._topic_tree.identify_row(event.y)
        if item:
            vals = self.gui._topic_tree.item(item, "values")
            if vals:
                self.gui._tooltip_text = str(vals[0])
                self.gui._tooltip = tk.Toplevel(self.gui.root)
                self.gui._tooltip.wm_overrideredirect(True)
                self.gui._tooltip.wm_geometry(f"+{event.x_root+10}+{event.y_root+10}")
                ttk.Label(self.gui._tooltip, text=self.gui._tooltip_text, background="#ffffcc", relief="solid", borderwidth=1).pack()

    def hide_tooltip(self):
        if self.gui._tooltip:
            self.gui._tooltip.destroy()
            self.gui._tooltip = None

    def update_title(self, topic_title=""):
        """更新窗口标题"""
        import os
        cwd = os.path.basename(self.gui._initial_cwd)
        title = f"TeaAgent - {cwd}"
        if topic_title:
            title += f" - {topic_title}"
        self.gui.root.title(title)

    def notify_completion(self, ai_msg: Optional[str] = None, user_msg: Optional[str] = None):
        """任务完成通知"""
        notification_msg = "TeaAgent: AI 任务已完成"
        if user_msg and ai_msg:
            u, a = user_msg.strip(), ai_msg.strip()
            if len(u) > 20: u = u[:20] + "..."
            if len(a) > 40: a = a[:40] + "..."
            notification_msg = f"TeaAgent: {u} + {a}"
        elif ai_msg:
            notification_msg = ai_msg.strip()[:60]
            notification_msg = f"TeaAgent: {notification_msg}"
        try:
            from tea_agent.toolkit.toolkit_notify import toolkit_notify
            toolkit_notify("TeaAgent", notification_msg, urgency="normal", duration=5000)
        except Exception:
            pass
