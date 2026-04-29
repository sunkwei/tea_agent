import tkinter as tk
from tkinter import ttk, scrolledtext, Listbox, Frame
import threading
import os
import os.path as osp
import sys
import re
import string
import html as html_mod
import traceback
from pathlib import Path
from datetime import datetime
from typing import Dict, cast, Callable, Optional, List, Tuple
import logging

try:
    from tkinterweb import HtmlFrame
    import markdown
    HAS_TKINTERWEB = True
except ImportError:
    HAS_TKINTERWEB = False

logger = logging.getLogger("main_db_gui")

# ====================== 包导入兼容处理 ======================
if __name__ == "__main__":
    parent_dir = str(Path(__file__).resolve().parent.parent)
    if parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)
    from tea_agent.onlinesession import OnlineToolSession
    from tea_agent.store import Storage
    from tea_agent import tlk
    from tea_agent.config import load_config, get_config, ModelConfig
else:
    from .onlinesession import OnlineToolSession
    from .store import Storage
    from . import tlk
    from .config import load_config, get_config, ModelConfig

# ====================== 配置加载 ======================
# 优先使用 $HOME/.tea_agent/config.yaml，不存在时使用 tea_agent/config.yaml
_cfg = load_config()

if not _cfg.main_model.is_configured:
    print("错误: 请配置主模型 (main_model)")
    print("  编辑 $HOME/.tea_agent/config.yaml 或 tea_agent/config.yaml")
    sys.exit(1)

API_KEY = _cfg.main_model.api_key
API_URL = _cfg.main_model.api_url
MODEL = _cfg.main_model.model_name
CHEAP_MODEL = _cfg.cheap_model

_storage_ = None
_toolkit_ = None


# ====================== 跨平台字体检测 ======================
# @2026-04-29 gen by deepseek-v4-pro, 跨平台字体自动检测(Windows/Linux)
import platform as _platform

_IS_WINDOWS = _platform.system() == "Windows"

SYSTEM_FONT = "TkDefaultFont"
MONO_FONT = "TkFixedFont"
_FONTS_DETECTED = False


def _init_fonts():
    """延迟检测系统可用字体（需 Tk root 创建后调用）。"""
    global SYSTEM_FONT, MONO_FONT, _FONTS_DETECTED
    if _FONTS_DETECTED:
        return
    try:
        from tkinter import font as _tkfont
        available = set(_tkfont.families())

        def _detect(candidates):
            for f in candidates:
                if f in available:
                    return f
            return candidates[-1]

        if _IS_WINDOWS:
            SYSTEM_FONT = _detect([
                "Microsoft YaHei", "Microsoft YaHei UI",
                "DengXian", "SimHei", "SimSun",
                "Noto Sans SC", "Microsoft JhengHei", "Microsoft Sans Serif",
            ])
            MONO_FONT = _detect([
                "Cascadia Code", "Cascadia Mono",
                "Consolas", "Courier New", "Lucida Console",
            ])
        else:
            SYSTEM_FONT = _detect([
                "Noto Sans CJK SC", "Noto Sans SC",
                "WenQuanYi Micro Hei", "Source Han Sans SC",
                "DejaVu Sans", "sans-serif",
            ])
            MONO_FONT = _detect([
                "Noto Sans Mono CJK SC", "DejaVu Sans Mono",
                "Source Han Mono SC", "Courier New",
            ])
    except Exception:
        pass
    _FONTS_DETECTED = True

# ====================== Markdown → HTML 渲染 ======================

_MD_CSS_TEMPLATE = string.Template("""
<style>
body { font-family: "Microsoft YaHei", "Microsoft YaHei UI", "DengXian", "SimHei", "SimSun", "Noto Sans SC", "Noto Sans CJK SC", "Source Han Sans SC", "WenQuanYi Micro Hei", "DejaVu Sans", sans-serif; font-size: ${font_size}px; line-height: 1.6; color: #333; padding: 8px; }
h1, h2, h3, h4, h5, h6 { margin: 0.8em 0 0.4em; color: #1a73e8; }
h1 { font-size: 1.5em; border-bottom: 2px solid #eee; padding-bottom: 0.3em; }
h2 { font-size: 1.3em; border-bottom: 1px solid #eee; padding-bottom: 0.3em; }
p { margin: 0.5em 0; }
code { background: #f4f4f4; padding: 2px 5px; border-radius: 3px; font-family: "Cascadia Code", "Consolas", "Courier New", "Noto Sans Mono CJK SC", "DejaVu Sans Mono", "Source Han Mono SC", monospace; font-size: 0.9em; }
pre { background: #f6f8fa; border: 1px solid #ddd; border-radius: 5px; padding: 12px; overflow-x: auto; }
pre code { background: none; padding: 0; }
ul, ol { padding-left: 1.5em; }
li { margin: 0.3em 0; }
blockquote { border-left: 4px solid #ddd; margin: 0.5em 0; padding: 0.5em 1em; color: #666; background: #f9f9f9; }
table { border-collapse: collapse; width: 100%; margin: 0.8em 0; }
th, td { border: 1px solid #ddd; padding: 8px; text-align: left; }
th { background: #f2f2f2; font-weight: bold; }
a { color: #1a73e8; text-decoration: none; }
a:hover { text-decoration: underline; }
hr { border: none; border-top: 1px solid #ddd; margin: 1em 0; }
strong { font-weight: bold; color: #222; }
em { font-style: italic; }
.msg-timestamp { font-size: 0.8em; color: #999; margin-bottom: 0.3em; }
.msg-divider { border: none; border-top: 2px solid #e8e8e8; margin: 1.2em 0; }
</style>
""")

_DEFAULT_FONT_SIZE = 16


def _render_markdown(text: str, font_size: int = _DEFAULT_FONT_SIZE) -> str:
    """将 markdown 文本转换为带样式的 HTML 片段"""
    if not HAS_TKINTERWEB:
        return text
    html_body = markdown.markdown(text, extensions=["fenced_code", "tables", "codehilite"])
    css = _MD_CSS_TEMPLATE.safe_substitute(font_size=font_size)
    return f"<html><head>{css}</head><body>{html_body}</body></html>"


def _chat_to_markdown(messages: List[Dict]) -> str:
    """将聊天消息列表转换为 markdown 格式，包含时间戳和分割线"""
    parts = []
    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")
        ts = msg.get("timestamp", "")
        ts_display = f'<span class="msg-timestamp">{ts}</span>' if ts else ""
        if role == "user":
            parts.append(f"{ts_display}\n\n### 👤 你\n\n{content.strip()}\n")
        elif role == "ai":
            parts.append(f"{ts_display}\n\n### 🤖 AI\n\n{content.strip()}\n\n---\n")
        elif role == "tool":
            parts.append(f"{ts_display}\n> 🔧 **工具**: {content.strip()}\n")
        elif role == "notice":
            parts.append(f"\n---\n*{content.strip()}*\n---\n")
    return "\n".join(parts)


# ====================== Topic 摘要 Prompt ======================

_TOPIC_SUMMARY_SYSTEM = (
    "你是一个极简摘要生成器。根据对话内容，生成不超过20字的摘要标题。"
    "要求：精准概括对话核心主题，不使用书名号，不加引号，不加多余修饰。"
    "直接输出摘要文本，不要任何额外说明。"
)

_TOPIC_SUMMARY_USER_TEMPLATE = (
    "以下是最近3轮对话的用户消息：\n\n{user_msgs}\n\n"
    "请生成不超过20字的摘要标题："
)


def _generate_topic_summary(client, model: str, conversations: List[Dict]) -> Optional[str]:
    """
    根据最近3轮对话通过 LLM 生成不超过20字的摘要。

    Args:
        client: OpenAI 客户端实例
        model: 模型名称
        conversations: 最近的对话列表（按时间正序），包含 user_msg 和 ai_msg

    Returns:
        不超过20字的摘要字符串；若生成失败则返回 None
    """
    if not conversations:
        return None
        
    user_msgs = []
    for conv in conversations:
        um = conv.get("user_msg", "").strip()
        ai = conv.get("ai_msg", "").strip()
        
        if um:
            if len(um) > 200:
                um = um[:200] + "..."
            user_msgs.append(f"用户：{um}")
        
        # 同时提取 AI 回复，提供更完整的上下文
        if ai:
            if len(ai) > 200:
                ai = ai[:200] + "..."
            user_msgs.append(f"AI：{ai}")

    if not user_msgs:
        return None

    user_content = _TOPIC_SUMMARY_USER_TEMPLATE.format(
        user_msgs="\n".join(user_msgs)
    )

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _TOPIC_SUMMARY_SYSTEM},
                {"role": "user", "content": user_content},
            ],
            temperature=0.3,
            max_tokens=50,
        )
        
        # 安全检查返回值
        if not response.choices or len(response.choices) == 0:
            return None
            
        content = response.choices[0].message.content
        if not content or not isinstance(content, str):
            return None
            
        raw = content.strip()
        raw = re.sub(r'^["""\'""\']+|["""\'""\']+$', '', raw).strip()
        
        if not raw:
            return None
            
        if len(raw) > 20:
            raw = raw[:20]
            
        return raw if raw else None
    except Exception:
        return None


# ====================== GUI 主界面 ======================

# ====================== 记忆管理对话框 ======================

# @2026-04-29 gen by deepseek-v4-pro, MemoryDialog记忆管理弹窗+on_status状态回调
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
        ttk.Label(top, textvariable=self.stats_var, font=(SYSTEM_FONT, 10)).pack(side=tk.LEFT)

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
        content_text = tk.Text(dlg, height=3, width=55, font=(SYSTEM_FONT, 10))
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
                  font=("", 8), foreground="#666").place(x=150, y=133)

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
                  font=("", 8), foreground="#666").place(x=130, y=252)

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

        text = tk.Text(dlg, font=(SYSTEM_FONT, 11), wrap=tk.WORD)
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


class TkGUI:
    def __init__(self, root, debug:bool=False):
        self.debug = debug
        self.root = root
        self.root.title("AI 工具调用助手")
        self.root.geometry("1100x750")
        self.root.minsize(900, 600)

        root_path = Path.home() / ".tea_agent"
        if not root_path.exists():
            logger.info(f"create user path: '{root_path}'")
            os.makedirs(root_path, exist_ok=True)

        db_path = root_path / "chat_history.db"
        tool_dir = root_path / "toolkit"
        if not tool_dir.exists():
            logger.info(f"create user toolkit path: '{tool_dir}'")
            os.makedirs(tool_dir, exist_ok=True)

        self.db = Storage(db_path=str(db_path))
        self.toolkit = tlk.Toolkit(str(tool_dir))

        globals()["_storage_"] = self.db
        globals()["tlk"]._toolkit_ = self.toolkit

        tlk.toolkit_reload()

        # 会话相关
        self.current_topic_id = -1
        self.generating = False

        # Thinking 开关状态
        self.enable_thinking_var = tk.BooleanVar(value=True)

        # HtmlFrame 缩放级别
        self._zoom_level = 100

        # 聊天消息列表
        self.chat_messages: List[Dict] = []

        # 当前 stream 累积 buffer
        self._stream_buffer = ""

        # 当前对话 ID
        self._current_conversation_id: Optional[int] = None

        # 创建界面
        self._create_ui()

        # 初始化会话
        self._init_session()

        # 加载主题
        self.refresh_topics()
        self.auto_new_topic()
        self.show_tool_list()

    def _create_ui(self):
        """创建界面"""
        main_split = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        main_split.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

        # ===== 左侧面板 =====
        left = Frame(main_split, width=220)
        main_split.add(left, weight=1)

        ttk.Label(left, text="聊天主题", font=(SYSTEM_FONT, 12, "bold")).pack(pady=5)
        self.topic_list = Listbox(left, font=(SYSTEM_FONT, 10))
        self.topic_list.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        self.topic_list.bind("<<ListboxSelect>>", self.on_topic_select)
        ttk.Button(left, text="➕ 新建主题", command=self.new_topic).pack(
            fill=tk.X, padx=4, pady=2)
        ttk.Separator(left, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=4, pady=6)
        ttk.Button(left, text="🧠 记忆管理", command=self.open_memory_dialog).pack(
            fill=tk.X, padx=4, pady=2)

        # ===== 右侧面板 =====
        right = Frame(main_split)
        main_split.add(right, weight=5)

        # 状态栏
        self.status_var = tk.StringVar(value="就绪")
        ttk.Label(right, textvariable=self.status_var,
                  foreground="#666").pack(anchor=tk.E, padx=6)

        # 聊天区域
        chat_split = ttk.PanedWindow(right, orient=tk.VERTICAL)
        chat_split.pack(fill=tk.BOTH, expand=True)

        chat_frame = Frame(chat_split)
        chat_split.add(chat_frame, weight=4)

        self.console = scrolledtext.ScrolledText(
            chat_frame, font=(SYSTEM_FONT, 11), bg="white", fg="black", wrap=tk.WORD
        )
        self.console.config(state=tk.DISABLED)

        if HAS_TKINTERWEB:
            self.chat_view = HtmlFrame(chat_frame, messages_enabled=False)
        else:
            self.chat_view = scrolledtext.ScrolledText(
                chat_frame, font=(SYSTEM_FONT, 11), bg="#fafafa", fg="black", wrap=tk.WORD
            )
            self.chat_view.config(state=tk.DISABLED)

        self._show_mode = "console"
        self._switch_display("console")

        # 输入区域
        input_frame = Frame(chat_split)
        chat_split.add(input_frame, weight=1)
        self.input_box = scrolledtext.ScrolledText(
            input_frame, font=(SYSTEM_FONT, 14), height=4, bg="#f8f8f8"
        )
        self.input_box.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        self.thinking_check = ttk.Checkbutton(
            input_frame,
            text="🧠 启用 Thinking",
            variable=self.enable_thinking_var,
            command=self.on_thinking_toggle
        )
        self.thinking_check.pack(anchor=tk.W, padx=6, pady=2)

        ttk.Label(input_frame, text="Enter 发送 | Shift+Enter 换行 | ESC 打断",
                  foreground="#666").pack(anchor=tk.E, padx=6)

        # 样式配置
        self.console.tag_configure("user", foreground="#0055cc")
        self.console.tag_configure("ai", foreground="black")
        self.console.tag_configure("tool", foreground="#d68000")
        self.console.tag_configure(
            "title", foreground="#0066cc", font=(SYSTEM_FONT, 12, "bold"))
        self.console.tag_configure("notice", foreground="#008800")
        self.console.tag_configure("error", foreground="#cc0000")

        # 快捷键绑定
        self.input_box.bind("<Return>", self.send)
        self.input_box.bind("<Shift-Return>", self.newline)
        self.root.bind("<Escape>", self.interrupt)

        # HtmlFrame 缩放快捷键
        if HAS_TKINTERWEB:
            self.root.bind("<Control-equal>", self.zoom_in)
            self.root.bind("<Control-plus>", self.zoom_in)
            self.root.bind("<Control-minus>", self.zoom_out)
            self.root.bind("<Control-underscore>", self.zoom_out)

    def zoom_in(self, e=None):
        if not HAS_TKINTERWEB or self._show_mode != "chat_view":
            return "break"
        self._zoom_level = min(self._zoom_level + 10, 200)
        self._apply_zoom()
        self._update_status(f"🔍 缩放: {self._zoom_level}%")
        return "break"

    def zoom_out(self, e=None):
        if not HAS_TKINTERWEB or self._show_mode != "chat_view":
            return "break"
        self._zoom_level = max(self._zoom_level - 10, 50)
        self._apply_zoom()
        self._update_status(f"🔍 缩放: {self._zoom_level}%")
        return "break"

    def _apply_zoom(self):
        if not HAS_TKINTERWEB or not self.chat_messages:
            return
        md = _chat_to_markdown(self.chat_messages)
        font_size = int(_DEFAULT_FONT_SIZE * self._zoom_level / 100)
        html = _render_markdown(md, font_size=font_size)
        self.chat_view.load_html(html)
        self.root.after(200, self.scroll_to_bottom)

    def _switch_display(self, mode: str):
        if mode == self._show_mode:
            return
        self._show_mode = mode
        if mode == "console":
            self.chat_view.pack_forget()
            self.console.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        else:
            self.console.pack_forget()
            self.chat_view.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
            self.root.after(400, self.scroll_to_bottom)

    def scroll_to_bottom(self):
        self.chat_view.yview_moveto(1.0)

    def _render_chat(self):
        md = _chat_to_markdown(self.chat_messages)
        if HAS_TKINTERWEB:
            font_size = int(_DEFAULT_FONT_SIZE * self._zoom_level / 100)
            html = _render_markdown(md, font_size=font_size)
            self.chat_view.load_html(html)
        else:
            self.chat_view.config(state=tk.NORMAL)
            self.chat_view.delete("1.0", tk.END)
            self.chat_view.insert("1.0", md)
            self.chat_view.config(state=tk.DISABLED)
            self.chat_view.see(tk.END)

    def _now_ts(self) -> str:
        return datetime.now().strftime("%H:%M:%S")

    def _init_session(self):
        """初始化会话"""
        # 从配置中获取参数
        cfg = get_config()
        
        self.sess = OnlineToolSession(
            toolkit=self.toolkit,
            api_key=cast(str, API_KEY),
            api_url=cast(str, API_URL),
            model=cast(str, MODEL),
            max_history=cfg.max_history,
            max_iterations=cfg.max_iterations,
            enable_thinking=cfg.enable_thinking,
            keep_turns=cfg.keep_turns,
            max_tool_output=cfg.max_tool_output,
            max_assistant_content=cfg.max_assistant_content,
            storage=self.db,
            cheap_api_key=cast(str, CHEAP_MODEL.api_key),
            cheap_api_url=cast(str, CHEAP_MODEL.api_url),
            cheap_model=cast(str, CHEAP_MODEL.model_name),
        )
        self.sess.enable_thinking = self.enable_thinking_var.get()

        self.sess.tool_log = self.safe_log_tool
        cheap_info = f" | 摘要模型: {CHEAP_MODEL.model_name}" if CHEAP_MODEL.model_name else ""
        self._update_status(f"📡 已连接 | 模型: {MODEL}{cheap_info}")

    def _update_status(self, msg: str):
        self.status_var.set(msg)

    def safe_stream(self, text):
        self.root.after(0, self.stream, text)

    def safe_log(self, msg, tag="ai"):
        self.root.after(0, self.log, msg, tag)

    def safe_log_tool(self, msg: str):
        self.root.after(0, self.log_tool, msg)

    def safe_update_status(self, msg: str):
        self.root.after(0, self._update_status, msg)

    def on_thinking_toggle(self):
        if hasattr(self, 'sess') and self.sess:
            self.sess.enable_thinking = self.enable_thinking_var.get()
            state = "已开启" if self.enable_thinking_var.get() else "已关闭"
            self._update_status(f"🧠 Thinking {state}")

    def show_tool_list(self):
        self.log("=" * 50, "title")
        self.log(f"📦 已加载工具函数（共 {len(self.toolkit.func_map)} 个）", "title")
        for name in self.toolkit.func_map.keys():
            self.log(f"✅ {name}", "notice")
        self.log("=" * 50, "title")
        self.log("")

    def log(self, msg, tag="ai"):
        self.console.config(state=tk.NORMAL)
        self.console.insert(tk.END, msg + "\n", tag)
        self.console.see(tk.END)
        self.console.config(state=tk.DISABLED)

        if tag in ("user", "ai", "tool", "notice"):
            self.chat_messages.append({"role": tag, "content": msg, "timestamp": self._now_ts()})

    def stream(self, text):
        self.console.config(state=tk.NORMAL)
        self.console.insert(tk.END, text)
        self.console.see(tk.END)
        self.console.config(state=tk.DISABLED)

        self._stream_buffer += text

    def log_tool(self, msg: str):
        self.log(msg, "tool")

    def _flush_stream_to_messages(self):
        if self._stream_buffer:
            if self.chat_messages and self.chat_messages[-1]["role"] == "ai":
                self.chat_messages[-1]["content"] += self._stream_buffer
            else:
                self.chat_messages.append({"role": "ai", "content": self._stream_buffer, "timestamp": self._now_ts()})
            self._stream_buffer = ""

    def clear_chat(self):
        self.console.config(state=tk.NORMAL)
        self.console.delete("1.0", tk.END)
        self.console.config(state=tk.DISABLED)
        self.chat_messages.clear()
        self._stream_buffer = ""

    def auto_new_topic(self):
        topics = self.db.list_topics()
        if topics:
            self.topic_list.select_set(0)
            self.on_topic_select(None)
        else:
            self.new_topic()

    def new_topic(self):
        title = f"主题 {datetime.now().strftime('%m-%d %H:%M:%S')}"
        tid = self.db.create_topic(title)
        self.refresh_topics()
        self.switch_topic(tid)

    def refresh_topics(self):
        self.topic_list.delete(0, tk.END)
        for tp in self.db.list_topics():
            title = tp.get("title", "")
            tokens = tp.get("total_tokens", 0)
            # @2026-04-23 generated by unknown_model, topic 列表显示 token 统计
            if tokens > 0:
                display = f"📊 {tokens:,} tokens  {title}"
            else:
                display = f"    {title}"
            self.topic_list.insert(tk.END, display)

    def switch_topic(self, topic_id):
        self.current_topic_id = topic_id
        self.clear_chat()
        topic = cast(dict, self.db.get_topic(topic_id))
        self.log(f"📌 当前主题：{topic['title']}", "title")
        self.log("-" * 50, "notice")

        # @2026-04-23 generated by unknown_model, 显示 token 统计
        ts = self.db.get_topic_tokens(topic_id)
        total = ts.get("total_tokens", 0)
        if total > 0:
            self.log(f"📊 Token 消耗: {total:,} (prompt: {ts.get('total_prompt_tokens', 0):,}, completion: {ts.get('total_completion_tokens', 0):,})", "notice")
            self.log("")

        # @2026-04-28 generated by Gemini, 改为加载所有未摘要的对话
        conversations = self.db.get_unsummarized_conversations(topic_id)
        summary = self.db.get_topic_summary(topic_id) or ""
        self.sess.load_history(conversations, summary)

        if summary:
            self.log(f"📖 历史摘要：{summary}", "notice")
            self.log("-" * 50, "notice")

        for c in conversations:
            self.log(f"你：{c['user_msg']}", "user")

            rounds = c.get("rounds_json_parsed")
            if rounds and c.get("is_func_calling"):
                for rd in rounds:
                    rd_role = rd.get("role", "")
                    if rd_role == "assistant" and rd.get("tool_calls"):
                        for tc in rd["tool_calls"]:
                            fn_name = tc.get("function", {}).get("name", "unknown")
                            fn_args = tc.get("function", {}).get("arguments", "")
                            self.log(f"🔧 调用工具：{fn_name}({fn_args})", "tool")
                        if rd.get("content"):
                            self.log(f"AI：{rd['content']}", "ai")
                    elif rd_role == "tool":
                        result_preview = rd.get("content", "")
                        if len(result_preview) > 200:
                            result_preview = result_preview[:200] + "..."
                        self.log(f"📋 结果：{result_preview}", "tool")
                    elif rd_role == "assistant" and rd.get("content"):
                        self.log(f"AI：{rd['content']}", "ai")
            else:
                self.log(f"AI：{c['ai_msg']}", "ai")

            if c["is_func_calling"]:
                self.log("ℹ️ 本条使用了工具调用", "tool")
            self.log("")

        if HAS_TKINTERWEB and self.chat_messages:
            self._render_chat()
            self._switch_display("chat_view")
            self.root.after(400, self.scroll_to_bottom)

    def on_topic_select(self, e):
        idx = self.topic_list.curselection()
        if not idx:
            return
        tp = self.db.list_topics()[idx[0]]
        self.switch_topic(tp["topic_id"])

    def newline(self, e=None):
        self.input_box.insert(tk.INSERT, "\n")
        return "break"

    def _update_topic_summary(self):
        """使用 cheap_model 生成 topic 摘要标题"""
        if not self.current_topic_id or self.current_topic_id < 0:
            return

        recent = self.db.get_recent_conversations(self.current_topic_id, limit=3)
        if not recent:
            return

        try:
            # 优先使用 cheap_model 降低成本
            cli, mdl = self.sess._get_summarize_client()
            summary = _generate_topic_summary(
                client=cli,
                model=mdl,
                conversations=recent,
            )
            if summary:
                try:
                    self.db.update_topic_title(self.current_topic_id, summary)
                    self.root.after(0, self._refresh_topics_preserve_selection)
                    if self.sess.tool_log:
                        self.sess.tool_log(f"📝 Topic摘要已更新: {summary}")
                except Exception as db_e:
                    if self.sess and self.sess.tool_log:
                        self.sess.tool_log(f"⚠️ Topic摘要数据库更新失败: {db_e}")
                        self.sess.tool_log(traceback.format_exc())
        except Exception as e:
            if self.sess and self.sess.tool_log:
                self.sess.tool_log(f"⚠️ Topic摘要生成失败: {e}")
                self.sess.tool_log(traceback.format_exc())

    def _refresh_topics_preserve_selection(self):
        current_idx = self.topic_list.curselection()
        self.refresh_topics()
        if current_idx:
            try:
                self.topic_list.select_set(current_idx[0])
            except Exception:
                pass

    def send(self, e=None):
        if self.generating or not self.current_topic_id:
            return "break"
        msg = self.input_box.get("1.0", tk.END).strip()
        if not msg:
            return "break"
        self.input_box.delete("1.0", tk.END)

        self._switch_display("console")

        self.log(f"你：{msg}", "user")
        self.generating = True
        self.log("AI：", "ai")

        mem_count = len(self.db.get_active_memories(50))
        self._update_status(f"⏳ 生成中... (ESC 打断) | 🧠 {mem_count}")

        def work():
            try:
                ai_msg, is_func = self.sess.chat_stream(
                    msg, 
                    callback=self.safe_stream,
                    topic_id=self.current_topic_id,
                    on_status=self.safe_update_status,
                )
                self.root.after(0, self._flush_stream_to_messages)

                ## 如果 chat_stream 成功，再存储到数据库
                conv_id = self.db.save_msg(
                    self.current_topic_id, msg, "", False)
                self._current_conversation_id = conv_id

                rounds = self.sess._rounds_collector
                self.db.update_msg_rounds(
                    conversation_id=conv_id,
                    ai_msg=ai_msg,
                    is_func_calling=is_func,
                    rounds=rounds if rounds else None,
                )

                # @2026-04-23 generated by unknown_model, 保存 token 统计到数据库
                usage = self.sess._last_usage
                if usage and usage.get("total_tokens", 0) > 0:
                    self.db.add_topic_tokens(
                        self.current_topic_id,
                        total_tokens=usage["total_tokens"],
                        prompt_tokens=usage["prompt_tokens"],
                        completion_tokens=usage["completion_tokens"],
                    )
                    self.root.after(0, self._render_and_show_chat)
                    # 刷新界面显示 token 统计
                    status_msg = (f"✅ 完成 | Tokens: {usage['total_tokens']:,} "
                                  f"(P:{usage['prompt_tokens']:,} C:{usage['completion_tokens']:,})")
                    self.root.after(0, lambda m=status_msg: self._update_status(m))
                    self.root.after(0, self._refresh_topics_preserve_selection)
                else:
                    self.root.after(0, self._render_and_show_chat)
                    self.root.after(0, lambda: self._update_status("✅ 完成"))

                self._update_topic_summary()
            except Exception as ex:
                ai_msg = f"异常：{ex}"
                self.safe_stream(ai_msg)
                self.root.after(0, self._flush_stream_to_messages)
                # 异常时也尽量保存 rounds 数据
                if self._current_conversation_id is not None:
                    rounds = self.sess._rounds_collector
                    try:
                        self.db.update_msg_rounds(
                            conversation_id=self._current_conversation_id,
                            ai_msg=ai_msg,
                            is_func_calling=False,
                            rounds=rounds if rounds else None,
                        )
                    except Exception:
                        pass
                self.root.after(0, self._render_and_show_chat)
                self.root.after(0, lambda: self._update_status(f"❌ 错误: {ai_msg}"))
            finally:
                self.generating = False
                self.safe_log("")

        threading.Thread(target=work, daemon=True).start()
        return "break"

    def _render_and_show_chat(self):
        self._render_chat()
        self._switch_display("chat_view")

    def open_memory_dialog(self):
        """打开记忆管理对话框"""
        MemoryDialog(self.root, self.db)

    def interrupt(self, e=None):
        if self.generating:
            self.sess.interrupt()
            self.safe_log("\n🛑 已打断", "tool")
            self.generating = False
            self.root.after(0, self._flush_stream_to_messages)
            self.root.after(0, self._render_and_show_chat)
            self._update_status("🛑 已打断")


def main(debug:bool=False, no_gui:bool=False):
    if no_gui:
        raise NotImplementedError("No GUI mode is not implemented yet.")
    
    root = tk.Tk()
    app = TkGUI(root, debug=debug)
    root.mainloop()
