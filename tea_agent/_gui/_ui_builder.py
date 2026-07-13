"""
从 gui.py L892-1030 提取：TkGUI._create_ui() 界面构建逻辑
"""

import logging
import tkinter as tk
from tkinter import Frame, scrolledtext, ttk
from tkinter import font as tkFont

if __import__('typing').TYPE_CHECKING:
    pass

from ._fonts import SYSTEM_FONT, _fs

try:
    from tkinterweb import HtmlFrame
    HAS_TKINTERWEB = True
except ImportError:
    HAS_TKINTERWEB = False

logger = logging.getLogger(__name__)

class UIBuilder:
    """界面构建器：创建所有 Tk widgets、布局、样式、快捷键"""

    def __init__(self, gui):
        """绑定 TkGUI 实例，接管界面构建。"""
        self.gui = gui

    def build(self):
        """创建界面 — 从 gui.py _create_ui 提取"""
        gui = self.gui
        
        # 配置 PanedWindow sash 样式：增加宽度和视觉反馈
        style = ttk.Style()
        # 配置 sash 宽度为 8 像素，背景色为浅灰色，悬停时变深，鼠标光标为左右箭头
        style.configure("TPanedwindow", 
                       sashthickness=8, 
                       sashrelief="raised", 
                       sashcursor="sb_h_double_arrow",
                       sashwidth=8)
        style.map("TPanedwindow", 
                  background=[("active", "#909090"), ("!active", "#d0d0d0")])
        
        main_split = ttk.PanedWindow(gui.root, orient=tk.HORIZONTAL)
        main_split.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

        # ===== 左侧面板 (占 1/5) =====
        left = Frame(main_split, width=280)
        left.pack_propagate(False)  # 固定宽度
        main_split.add(left, weight=0)

        ttk.Label(left, text="聊天主题", font=(SYSTEM_FONT, _fs(14), "bold")).pack(pady=5)
        _topic_font = tkFont.Font(family=SYSTEM_FONT, size=_fs(11))
        _topic_style = ttk.Style()
        _topic_style.configure("Topic.Treeview", rowheight=_fs(26))
        gui.topic_list = ttk.Treeview(left, show="tree", style="Topic.Treeview",
                                       selectmode="browse", height=12)
        gui.topic_list.tag_configure("topic_item", font=_topic_font)
        gui.topic_list.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        gui.topic_list.bind("<<TreeviewSelect>>", gui.on_topic_select)
        gui.topic_list.bind("<Motion>", gui._on_topic_hover, add="+")
        gui.topic_list.bind("<Leave>", gui._on_topic_leave, add="+")
        gui._topic_cache = []           # 缓存 list_topics 原始数据
        gui._topic_tooltip = None       # tooltip Toplevel
        gui._topic_hover_after = None   # debounce after_id
        ttk.Button(left, text="➕ 新建主题", command=gui.new_topic).pack(
            fill=tk.X, padx=4, pady=2)
        ttk.Separator(left, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=4, pady=6)
        ttk.Button(left, text="📁 主题管理", command=gui.open_topic_dialog).pack(
            fill=tk.X, padx=4, pady=2)
        ttk.Button(left, text="🧠 记忆管理", command=gui.open_memory_dialog).pack(
            fill=tk.X, padx=4, pady=2)



        ttk.Button(left, text="⏰ 定时任务", command=gui.open_scheduler_dialog).pack(
            fill=tk.X, padx=4, pady=2)
        ttk.Button(left, text="🔍 搜索对话", command=gui.open_search_dialog).pack(
            fill=tk.X, padx=4, pady=2)
        ttk.Button(left, text="📄 导出 PDF", command=gui.export_topic_pdf).pack(
            fill=tk.X, padx=4, pady=(2,6))

        # ===== 右侧面板 =====
        right = Frame(main_split)
        main_split.add(right, weight=5)

        # 状态栏
        gui.status_var = tk.StringVar(value="就绪")
        status_frame = ttk.Frame(right)
        status_frame.pack(anchor=tk.E, padx=6, fill=tk.X)
        ttk.Label(status_frame, textvariable=gui.status_var,
                  foreground="#666").pack(side=tk.LEFT, padx=(0, 20))
        gui.todo_btn = ttk.Button(status_frame, text="📋 任务",
                                  command=gui.show_todo_dialog,
                                  state="disabled")
        gui.todo_btn.pack(side=tk.RIGHT)

        # 聊天区域
        gui.chat_split = ttk.PanedWindow(right, orient=tk.VERTICAL)
        gui.chat_split.pack(fill=tk.BOTH, expand=True)

        # ── 顶部合并容器：chat + config（无 sash，整体拖动）──
        top_frame = Frame(gui.chat_split)
        gui.chat_split.add(top_frame, weight=3)

        chat_frame = Frame(top_frame)
        chat_frame.pack(fill=tk.BOTH, expand=True)

        gui.console = scrolledtext.ScrolledText(
            chat_frame, font=(SYSTEM_FONT, _fs(15)), bg="white", fg="black", wrap=tk.WORD
        )
        gui.console.config(state=tk.DISABLED)

        if HAS_TKINTERWEB:
            gui.chat_view = HtmlFrame(chat_frame, messages_enabled=False, on_link_click=gui._on_history_link_click, fontscale=1.5)
        else:
            gui.chat_view = scrolledtext.ScrolledText(
                chat_frame, font=(SYSTEM_FONT, _fs(15)), bg="#fafafa", fg="black", wrap=tk.WORD
            )
            gui.chat_view.config(state=tk.DISABLED)

        gui._show_mode = "console"
        gui._switch_display("console")

        # ── 配置切换栏（固定在 chat 区域底部）──
        cfg_bar_frame = Frame(top_frame)
        cfg_bar_frame.pack(fill=tk.X)  # 固定高度，不扩展

        cfg_row = ttk.Frame(cfg_bar_frame)
        cfg_row.pack(fill=tk.X, padx=4, pady=2)

        gui._config_var = tk.StringVar(value="(加载中...)")
        gui.config_combo = ttk.Combobox(
            cfg_row, textvariable=gui._config_var, state="readonly",
            font=(SYSTEM_FONT, _fs(10)), values=["(加载中...)"])
        gui.config_combo.pack(side=tk.LEFT, fill=tk.X, expand=True)
        gui.config_combo.bind("<<ComboboxSelected>>", gui._on_config_selected)

        ttk.Button(cfg_row, text="↻",
                   command=gui._refresh_config_list, width=3).pack(side=tk.LEFT, padx=(4, 2))
        ttk.Button(cfg_row, text="⚙️ 配置编辑",
                   command=gui.open_config_dialog).pack(side=tk.LEFT)

        # 输入区域（与 top_frame 之间只有一条 sash）
        input_frame = Frame(gui.chat_split)
        gui.chat_split.add(input_frame, weight=1)
        gui.input_box = scrolledtext.ScrolledText(
            input_frame, font=(SYSTEM_FONT, _fs(11)), height=4, bg="#f8f8f8"
        )
        gui.input_box.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        toolbar = ttk.Frame(input_frame)
        toolbar.pack(fill=tk.X, padx=4, pady=(0, 2))

        # 左侧：图片附件
        gui._img_btn = ttk.Button(toolbar, text="📎 图片", command=gui.images.attach)
        gui._img_btn.pack(side=tk.LEFT)
        gui._img_label = ttk.Label(toolbar, text="", foreground="#888")
        gui._img_label.pack(side=tk.LEFT, padx=(4, 2))
        gui._clear_img_btn = ttk.Button(toolbar, text="✕ 清除", command=gui.images.clear)

        # 检查模型是否支持图像输入，不支持则禁用图片按钮
        if hasattr(gui, '_cfg') and hasattr(gui._cfg, 'main_model') and not gui._cfg.main_model.supports_vision:
            gui._img_btn.config(state=tk.DISABLED)
            gui._img_label.config(text="(当前模型不支持图片)", foreground="#aaa")

        # 中间：视图切换
        gui._raw_check_btn = ttk.Checkbutton(
            toolbar, text="📋 纯文本视图", variable=gui._raw_view,
            command=gui._toggle_raw_view
        )

        # 右侧：提示文字
        ttk.Label(toolbar, text="Enter 发送  •  Shift+Enter 换行  •  ESC 打断  •  Ctrl+P 导出PDF",
                  foreground="#888", font=(SYSTEM_FONT, _fs(10)))\
            .pack(side=tk.RIGHT, padx=6)
        # 样式配置
        gui.console.tag_configure("user", foreground="#0055cc")
        gui.console.tag_configure("ai", foreground="black")
        gui.console.tag_configure("tool", foreground="#d68000")
        gui.console.tag_configure(
            "title", foreground="#0066cc", font=(SYSTEM_FONT, _fs(14), "bold"))
        gui.console.tag_configure("notice", foreground="#008800")
        gui.console.tag_configure("error", foreground="#cc0000")
        gui.console.tag_configure("think", foreground="#888888", font=(SYSTEM_FONT, _fs(13), "italic"))

        # 快捷键绑定
        gui.input_box.bind("<Return>", gui.send)
        gui.input_box.bind("<Shift-Return>", gui.newline)
        gui.input_box.bind("<Control-v>", gui.on_paste)
        gui.root.bind("<Escape>", gui.interrupt)

        # HtmlFrame 缩放快捷键
        if HAS_TKINTERWEB:
            gui.root.bind("<Control-equal>", gui.zoom_in)
            gui.root.bind("<Control-plus>", gui.zoom_in)
            gui.root.bind("<Control-minus>", gui.zoom_out)
            gui.root.bind("<Control-underscore>", gui.zoom_out)

        # HtmlFrame 历史轮次快捷键
        if HAS_TKINTERWEB:
            gui.root.bind("<Alt-Up>", gui._history_prev_round)
            gui.root.bind("<Alt-Down>", gui._history_next_round)

        # Ctrl+P: 导出当前主题最后一轮为 PDF
        gui.root.bind("<Control-p>", gui.export_last_pdf)

        # 左侧面板占 1/5，右侧占 4/5
        # ttk.PanedWindow 用 sashpos(index, newpos)
        def _set_sash_position(attempt=0):
            try:
                gui.root.update_idletasks()
                w = gui.root.winfo_width()
                if w > 100:
                    sash_x = max(200, w // 5)
                    main_split.sashpos(0, sash_x)
                elif attempt < 10:
                    gui.root.after(100, _set_sash_position, attempt + 1)
            except Exception:
                if attempt < 10:
                    gui.root.after(100, _set_sash_position, attempt + 1)
        gui.root.after(200, _set_sash_position)

        # ── 约束顶部面板（chat+config）不被 sash 压缩到 config 不可见 ──
        def _constrain_top_pane(event=None):
            """防止向上拖拽 sash 时 config 区域被隐藏。"""
            try:
                gui.root.update_idletasks()
                cfg_height = cfg_bar_frame.winfo_reqheight()
                if cfg_height <= 0:
                    return
                # 至少保留一行聊天文本高度 + 上下 padding
                min_chat_height = _fs(15) + 10
                min_top_height = cfg_height + min_chat_height
                # 只有一条 sash（index=0），检查 top_frame 的当前高度
                cur_sash_pos = gui.chat_split.sashpos(0)
                if 0 < cur_sash_pos < min_top_height:
                    gui.chat_split.sashpos(0, min_top_height)
            except Exception:
                logger.exception("operation failed")


        # UI 就绪后首次计算并约束
        gui.root.after(500, _constrain_top_pane)
        # 每次鼠标释放时重新约束（防止在可拖拽区域外也能触发约束）
        gui.chat_split.bind("<ButtonRelease-1>", _constrain_top_pane)
        # 窗口大小变化时也重新检查
        gui.root.bind("<Configure>", lambda e: gui.root.after_idle(_constrain_top_pane))
