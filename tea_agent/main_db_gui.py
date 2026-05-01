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
from typing import Optional, Dict, cast, Callable, Optional, List, Tuple
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
# NOTE: 2026-04-30 20:02:57, self-evolved by tea_agent --- 添加 Wayland/X11 显示缩放检测：全局 _SCALE_FACTOR + _fs() 辅助函数，_init_fonts() 中自动检测 tk scaling 并更新 _DEFAULT_FONT_SIZE
_FONTS_DETECTED = False
_SCALE_FACTOR = 1.0


def _fs(size):
    """返回按显示缩放因子调整后的字体大小（适配 Wayland/X11 高分屏）。"""
    return max(1, int(size * _SCALE_FACTOR))


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
# NOTE: 2026-04-30 20:03:08, self-evolved by tea_agent --- _init_fonts() 中检测 Tk 缩放因子并更新全局 _SCALE_FACTOR 和 _DEFAULT_FONT_SIZE
    except Exception:
        pass

    global _SCALE_FACTOR, _DEFAULT_FONT_SIZE
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
# NOTE: 2026-04-30 09:26:49, self-evolved by tea_agent --- _chat_to_markdown中notice角色直接输出内容(支持Markdown表格)，不再用*斜体*包裹
        elif role == "notice":
            parts.append(f"\n---\n{content.strip()}\n---\n")
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
            
# NOTE: 2026-05-01 08:10:00, self-evolved by tea_agent --- _generate_topic_summary 增加最小长度≥2的校验，防止LLM返回如"为"的单字摘要
        raw = content.strip()
        # 去掉各种引号包裹（中英文全角半角）
        raw = re.sub(r'^[\'"\u201c\u201d\u2018\u2019\u300c\u300d\uff02\uff07]+', '', raw)
        raw = re.sub(r'[\'"\u201c\u201d\u2018\u2019\u300c\u300d\uff02\uff07]+$', '', raw)
        raw = raw.strip()
        
        if not raw:
            return None
        
        # 拒绝过短的摘要（<2个字符，如 LLM 返回的"为"）
        if len(raw) < 2:
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

    def __init__(self, parent, storage, on_switch=None):
        super().__init__(parent)
        self.db = storage
        self.on_switch = on_switch  # callback(topic_id) when user switches
        self.title("📁 主题管理")
        self.geometry("900x600")
        self.minsize(700, 400)
        self.transient(parent)
        self.grab_set()

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

        ttk.Button(toolbar, text="📋 导出选中", command=self._export_selected).pack(side=tk.RIGHT, padx=2)
        ttk.Button(toolbar, text="📦 导出全部", command=self._export_all).pack(side=tk.RIGHT, padx=2)

        # 主题列表
        list_frame = ttk.Frame(self)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=4)

        columns = ("id", "title", "created", "tokens", "convs", "active")
        self.tree = ttk.Treeview(list_frame, columns=columns, show="headings", height=12)

        self.tree.heading("id", text="ID", command=lambda: self._sort("id"))
        self.tree.heading("title", text="标题", command=lambda: self._sort("title"))
        self.tree.heading("created", text="创建时间", command=lambda: self._sort("created"))
        self.tree.heading("tokens", text="Token消耗", command=lambda: self._sort("tokens"))
        self.tree.heading("convs", text="对话数", command=lambda: self._sort("convs"))
        self.tree.heading("active", text="状态")

        self.tree.column("id", width=50, anchor=tk.CENTER)
        self.tree.column("title", width=280)
        self.tree.column("created", width=140)
        self.tree.column("tokens", width=100, anchor=tk.E)
        self.tree.column("convs", width=70, anchor=tk.CENTER)
        self.tree.column("active", width=60, anchor=tk.CENTER)

        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # 操作按钮
        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill=tk.X, padx=10, pady=6)

        ttk.Button(btn_frame, text="💤 停用主题", command=self._deactivate).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="✅ 启用主题", command=self._activate).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="🗑️ 硬删除", command=self._hard_delete).pack(side=tk.LEFT, padx=2)

        # 绑定
        self.tree.bind("<Double-1>", lambda e: self._switch_to())
        self.bind("<Escape>", lambda e: self.destroy())
        self.bind("<Delete>", lambda e: self._deactivate())

    def _refresh(self):
        for item in self.tree.get_children():
            self.tree.delete(item)

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

                self.tree.insert("", tk.END,
                                 values=(tid, title, created, display_tokens, convs, status),
                                 iid=str(tid))

            self.stats_var.set(
                f"共 {len(topics)} 个主题 (活跃: {active_count}) | "
                f"总 Token: {total_tokens:,} | 总对话: {total_conv}"
            )
        except Exception as e:
            self.stats_var.set(f"加载失败: {e}")

    def _sort(self, col):
        items = [(self.tree.set(i, col), i) for i in self.tree.get_children("")]
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
            items.sort()
        for idx, (_, iid) in enumerate(items):
            self.tree.move(iid, "", idx)

    def _selected_id(self):
        sel = self.tree.selection()
        return int(sel[0]) if sel else None

    def _switch_to(self):
        tid = self._selected_id()
        if tid and self.on_switch:
            self.on_switch(tid)
            self.destroy()

    def _new_topic(self):
        title = f"主题 {datetime.now().strftime('%m-%d %H:%M:%S')}"
        self.db.create_topic(title)
        self._refresh()

    def _rename_dialog(self):
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

    def _deactivate(self):
        tid = self._selected_id()
        if tid:
            self.db.update_topic_active(tid, 0)
            self._refresh()

    def _activate(self):
        tid = self._selected_id()
        if tid:
            self.db.update_topic_active(tid, 1)
            self._refresh()

    def _hard_delete(self):
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

    def _export_selected(self):
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

    def _write_topic_md(self, f, topic_id: int, mode: str):
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
        f.write(f"- **Token消耗:** {ts.get('total_tokens', 0):,} "
                f"(P:{ts.get('total_prompt_tokens', 0):,} "
                f"C:{ts.get('total_completion_tokens', 0):,})\n")
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

    def _create_ui(self):
        """创建界面"""
        main_split = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        main_split.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

        # ===== 左侧面板 =====
        left = Frame(main_split, width=220)
        main_split.add(left, weight=1)

# NOTE: 2026-04-30 20:03:32, self-evolved by tea_agent --- 主题标签(12→_fs(12))和主题列表(10→_fs(10))字体适配缩放
        ttk.Label(left, text="聊天主题", font=(SYSTEM_FONT, _fs(12), "bold")).pack(pady=5)
        self.topic_list = Listbox(left, font=(SYSTEM_FONT, _fs(10)))
        self.topic_list.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        self.topic_list.bind("<<ListboxSelect>>", self.on_topic_select)
        ttk.Button(left, text="➕ 新建主题", command=self.new_topic).pack(
            fill=tk.X, padx=4, pady=2)
        ttk.Separator(left, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=4, pady=6)
        ttk.Button(left, text="📁 主题管理", command=self.open_topic_dialog).pack(
            fill=tk.X, padx=4, pady=2)
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

# NOTE: 2026-04-30 20:03:16, self-evolved by tea_agent --- 控制台字体使用 _fs(11) 适配缩放
        self.console = scrolledtext.ScrolledText(
            chat_frame, font=(SYSTEM_FONT, _fs(11)), bg="white", fg="black", wrap=tk.WORD
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
# NOTE: 2026-04-30 20:03:24, self-evolved by tea_agent --- 输入框字体使用 _fs(14)、输入提示使用 _fs(9) 适配缩放
        self.input_box = scrolledtext.ScrolledText(
            input_frame, font=(SYSTEM_FONT, _fs(14)), height=4, bg="#f8f8f8"
        )
        self.input_box.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)


        ttk.Label(input_frame, text="Enter 发送 | Shift+Enter 换行 | ESC 打断",
                  foreground="#666").pack(anchor=tk.E, padx=6)

        # 样式配置
        self.console.tag_configure("user", foreground="#0055cc")
        self.console.tag_configure("ai", foreground="black")
        self.console.tag_configure("tool", foreground="#d68000")
# NOTE: 2026-04-30 20:03:47, self-evolved by tea_agent --- title 标签字体使用 _fs(12) 适配缩放
        self.console.tag_configure(
            "title", foreground="#0066cc", font=(SYSTEM_FONT, _fs(12), "bold"))
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
            keep_turns=cfg.keep_turns,
            max_tool_output=cfg.max_tool_output,
            max_assistant_content=cfg.max_assistant_content,
            extra_iterations_on_continue=cfg.extra_iterations_on_continue,
            memory_extraction_threshold=cfg.memory_extraction_threshold,
            storage=self.db,
            cheap_api_key=cast(str, CHEAP_MODEL.api_key),
            cheap_api_url=cast(str, CHEAP_MODEL.api_url),
            cheap_model=cast(str, CHEAP_MODEL.model_name),
            enable_thinking=cfg.enable_thinking,
        )

        self._cfg = cfg
        self.sess.tool_log = self.safe_log_tool
        import tea_agent.session_ref as _sref; _sref.set_session(self.sess)  # 供 toolkit 工具访问
        cheap_info = f" | 摘要模型: {CHEAP_MODEL.model_name}" if CHEAP_MODEL.model_name else ""
        self._update_status(f"📡 已连接 | 模型: {MODEL}{cheap_info}")

    def toggle_reasoning(self, enable: Optional[bool] = None) -> dict:
        """切换或查询 reasoning/thinking 状态。供 toolkit 工具调用。"""
        if self.sess is None:
            return {"error": "无活跃会话"}
        if enable is None:
            return {"enable_thinking": self.sess.enable_thinking}
        self.sess.enable_thinking = bool(enable)
        state = "开启" if enable else "关闭"
        self._update_status(f"🧠 Reasoning 已{state}")
        return {"enable_thinking": self.sess.enable_thinking, "changed": True}

    def _update_status(self, msg: str):
        self.status_var.set(msg)

    def safe_stream(self, text):
        self.root.after(0, self.stream, text)

    def safe_log(self, msg, tag="ai"):
        self.root.after(0, self.log, msg, tag)

    def safe_log_tool(self, msg: str):
        self.root.after(0, self.log_tool, msg)

    def safe_update_status(self, msg: str):
        if msg.startswith("!MAX_ITER:"):
            self.root.after(0, self._handle_max_iter, msg)
        else:
            self.root.after(0, self._update_status, msg)

    # @2026-04-29 gen by deepseek-v4-pro, 工具调用达上限时弹框询问继续/终止
    def _handle_max_iter(self, msg: str):
        """弹出对话框询问用户是否继续工具调用。"""
        from tkinter import messagebox
        display = msg.replace("!MAX_ITER:", "")
        result = messagebox.askyesno(
            "达到工具调用上限",
            f"{display}\n\n选择「是」再执行 5 轮\n选择「否」终止当前回答",
            parent=self.root,
        )
        if hasattr(self, 'sess') and self.sess:
            self.sess._continue_after_max = result
            self.sess._max_iter_wait.set()
            if result:
                self._update_status("⏳ 已续命 5 轮，继续生成... (ESC 打断)")
            else:
                self._update_status("🛑 用户终止工具调用")

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

# NOTE: 2026-04-30 09:37:55, self-evolved by tea_agent --- 左侧主题列表移除token前缀，直接显示摘要标题（不超过20字）
    def refresh_topics(self):
        self.topic_list.delete(0, tk.END)
        for tp in self.db.list_topics():
            title = tp.get("title", "")
            # 直接显示摘要标题，不超过20字
            display = title[:20] if len(title) > 20 else title
            self.topic_list.insert(tk.END, display)

# NOTE: 2026-04-30 10:03:19, self-evolved by tea_agent --- switch_topic加载全部历史，旧轮次仅显示问答，最近10轮显示完整工具链
# NOTE: 2026-04-30 10:26:10, self-evolved by tea_agent --- switch_topic两阶段加载：旧轮次轻量查询(无rounds_json)，最近10轮完整查询
# NOTE: 2026-04-30 10:31:53, self-evolved by tea_agent --- switch_topic改为后台线程加载DB+解析，主线程仅渲染；新增_render_loaded_topic和_render_topic_error
    def switch_topic(self, topic_id):
        self.current_topic_id = topic_id
        self.clear_chat()
        self.generating = True  # 加载期间阻塞输入
        self.log("⏳ 正在加载历史记录...", "notice")
        self._update_status("⏳ 加载中...")

        recent_turns = 10

        def load_worker():
            """后台线程：DB 查询 + JSON 解析 + 构建渲染列表（不阻塞 GUI）"""
            try:
                # === 第一阶段：DB 查询（后台线程） ===
                topic = cast(dict, self.db.get_topic(topic_id))
                ts = self.db.get_topic_tokens(topic_id)

                # 轻量查询所有对话（不含 rounds_json）
                all_light = self.db.get_conversations(topic_id, limit=-1, include_rounds=False)
                total_convs = len(all_light)
                old_count = max(0, total_convs - recent_turns)

                # 最近 N 轮完整查询（含工具调用链）
                if total_convs > 0:
                    recent_full = self.db.get_conversations(topic_id, limit=recent_turns, include_rounds=True)
                    offset = total_convs - min(total_convs, recent_turns)
                    for i in range(offset, total_convs):
                        j = i - offset
                        if j < len(recent_full):
                            all_light[i] = recent_full[j]

                summary = self.db.get_topic_summary(topic_id) or ""

                # 更新 session 消息列表
                self.sess.load_history(all_light, summary, recent_turns=recent_turns)

                # === 第二阶段：构建渲染列表（纯数据，无 GUI 操作） ===
                render_items = []  # list of (tag, text)

                render_items.append(("title", f"📌 当前主题：{topic['title']}"))
                render_items.append(("notice", "-" * 50))

                total_tokens = ts.get("total_tokens", 0)
                if total_tokens > 0:
                    render_items.append(("notice",
                        f"📊 Token 消耗: {total_tokens:,} "
                        f"(prompt: {ts.get('total_prompt_tokens', 0):,}, "
                        f"completion: {ts.get('total_completion_tokens', 0):,})"))
                    render_items.append(("notice", ""))

                if summary:
                    render_items.append(("notice", f"📖 历史摘要：{summary}"))
                    render_items.append(("notice", "-" * 50))

                if old_count > 0:
                    render_items.append(("notice",
                        f"📖 最近 {recent_turns} 轮显示完整对话，更早的 {old_count} 轮仅显示问答"))
                    render_items.append(("notice", ""))

                # 遍历对话，构建渲染项
                for i, c in enumerate(all_light):
                    is_old = i < old_count
                    render_items.append(("user", f"你：{c['user_msg']}"))

                    if is_old:
                        # 旧轮次：仅显示最终 ai_msg
                        render_items.append(("ai", f"AI：{c['ai_msg']}"))
                    else:
                        # 最近N轮：显示完整工具调用链
                        rounds = c.get("rounds_json_parsed")
                        tool_names = []
                        if rounds and c.get("is_func_calling"):
                            for rd in rounds:
                                rd_role = rd.get("role", "")
                                if rd_role == "assistant" and rd.get("tool_calls"):
                                    for tc in rd["tool_calls"]:
                                        fn_name = tc.get("function", {}).get("name", "unknown")
                                        fn_args = tc.get("function", {}).get("arguments", "")
                                        if fn_name not in tool_names:
                                            tool_names.append(fn_name)
                                        render_items.append(("tool", f"🔧 调用工具：{fn_name}({fn_args})"))
                                    if rd.get("content"):
                                        render_items.append(("ai", f"AI：{rd['content']}"))
                                elif rd_role == "tool":
                                    result_preview = rd.get("content", "")
                                    if len(result_preview) > 200:
                                        result_preview = result_preview[:200] + "..."
                                    render_items.append(("tool", f"📋 结果：{result_preview}"))
                                elif rd_role == "assistant" and rd.get("content"):
                                    render_items.append(("ai", f"AI：{rd['content']}"))
                        else:
                            render_items.append(("ai", f"AI：{c['ai_msg']}"))

                        if c["is_func_calling"]:
                            if tool_names:
                                render_items.append(("tool", f"ℹ️ 工具：{', '.join(tool_names)}"))
                            else:
                                render_items.append(("tool", "ℹ️ 本条使用了工具调用"))
                    render_items.append(("notice", ""))

                # === 第三阶段：回到主线程渲染 ===
                self.root.after(0, self._render_loaded_topic, render_items)
            except Exception as e:
                self.root.after(0, self._render_topic_error, str(e))

        threading.Thread(target=load_worker, daemon=True).start()

    def _render_loaded_topic(self, render_items):
        """主线程：清屏 + 逐条渲染准备好的数据"""
        self.clear_chat()
        for tag, text in render_items:
            self.log(text, tag)

        if HAS_TKINTERWEB and self.chat_messages:
            self._render_chat()
            self._switch_display("chat_view")
            self.root.after(400, self.scroll_to_bottom)

        self.generating = False
        self._update_status("✅ 就绪")

    def _render_topic_error(self, error_msg):
        """主线程：加载失败回调"""
        self.clear_chat()
        self.log(f"❌ 加载历史失败: {error_msg}", "error")
        self.generating = False
        self._update_status("❌ 加载失败")

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

# NOTE: 2026-04-30 09:25:58, self-evolved by tea_agent --- send()中保存便宜模型token到DB，并传递给_add_token_notice_and_render
                # @2026-04-23 generated by unknown_model, 保存 token 统计到数据库
                usage = self.sess._last_usage
                cheap_usage = self.sess._last_cheap_usage
                if usage and usage.get("total_tokens", 0) > 0:
                    self.db.add_topic_tokens(
                        self.current_topic_id,
                        total_tokens=usage["total_tokens"],
                        prompt_tokens=usage["prompt_tokens"],
                        completion_tokens=usage["completion_tokens"],
                        cheap_tokens=cheap_usage.get("total_tokens", 0),
                        cheap_prompt_tokens=cheap_usage.get("prompt_tokens", 0),
                        cheap_completion_tokens=cheap_usage.get("completion_tokens", 0),
                    )
# NOTE: 2026-04-30 09:12:34, self-evolved by tea_agent --- send()完成后调用_add_token_notice_and_render，在HtmlFrame显示本轮token消耗
                    # 在聊天区域显示本轮 + 主题累积 token 消耗（含主模型+便宜模型），然后渲染
                    self.root.after(0, lambda u=usage, cu=cheap_usage: self._add_token_notice_and_render(u, cu))
                    # 刷新状态栏显示 token 统计
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

# NOTE: 2026-04-30 09:12:24, self-evolved by tea_agent --- 新增 _add_token_notice_and_render 方法，在聊天区域显示本轮token消耗
# NOTE: 2026-04-30 09:13:24, self-evolved by tea_agent --- 简化token显示格式，修复括号配对问题
# NOTE: 2026-04-30 09:15:53, self-evolved by tea_agent --- token通知增加当前主题累积消耗显示
# NOTE: 2026-04-30 09:26:32, self-evolved by tea_agent --- _add_token_notice_and_render改为Markdown表格(主模型+便宜模型，本轮+主题累积)
    def _add_token_notice_and_render(self, usage: dict, cheap_usage: dict = None):
        """在聊天消息中追加 Markdown 表格：本轮/主题累积 × 主模型/便宜模型 token 消耗"""
        if cheap_usage is None:
            cheap_usage = {}
        # 本轮：主模型
        m_total = usage.get("total_tokens", 0)
        m_p = usage.get("prompt_tokens", 0)
        m_c = usage.get("completion_tokens", 0)
        # 本轮：便宜模型
        c_total = cheap_usage.get("total_tokens", 0)
        c_p = cheap_usage.get("prompt_tokens", 0)
        c_c = cheap_usage.get("completion_tokens", 0)
        # 主题累积
        try:
            ts = self.db.get_topic_tokens(self.current_topic_id)
            tm_total = ts.get("total_tokens", 0)
            tm_p = ts.get("total_prompt_tokens", 0)
            tm_c = ts.get("total_completion_tokens", 0)
            tc_total = ts.get("total_cheap_tokens", 0)
            tc_p = ts.get("total_cheap_prompt_tokens", 0)
            tc_c = ts.get("total_cheap_completion_tokens", 0)
        except Exception:
            tm_total = tm_p = tm_c = tc_total = tc_p = tc_c = 0

# NOTE: 2026-04-30 09:27:37, self-evolved by tea_agent --- _cell()中去掉<br>改用空格，保证Markdown表格兼容性
        def _cell(val, detail_p=None, detail_c=None):
            """格式化为 'total (P:x C:y)' 或 '—'"""
            if val <= 0:
                return "—"
            if detail_p is not None and detail_c is not None:
                return f"{val:,} (P:{detail_p:,} C:{detail_c:,})"
            return f"{val:,}"

        lines = [
            "| | 主模型 | 便宜模型 |",
            "|-------|--------|----------|",
            f"| 本轮 | {_cell(m_total, m_p, m_c)} | {_cell(c_total, c_p, c_c)} |",
            f"| 主题 | {_cell(tm_total, tm_p, tm_c)} | {_cell(tc_total, tc_p, tc_c)} |",
        ]
        token_msg = "\n".join(lines)
        self.chat_messages.append({"role": "notice", "content": token_msg, "timestamp": self._now_ts()})
        self._render_and_show_chat()

    def _render_and_show_chat(self):
        self._render_chat()
        self._switch_display("chat_view")

    # @2026-04-29 gen by deepseek-v4-pro, 打开主题管理弹窗
    def open_topic_dialog(self):
        """打开主题管理弹窗"""
        TopicDialog(self.root, self.db,
                    on_switch=lambda tid: self.root.after(0, self.switch_topic, tid))

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


# NOTE: 2026-04-30 19:36:28, self-evolved by tea_agent --- 补回缺失的 __main__ 入口，使 python -m tea_agent.main_db_gui 可正常启动 GUI
def main(debug:bool=False, no_gui:bool=False):
    if no_gui:
        raise NotImplementedError("No GUI mode is not implemented yet.")
    
    root = tk.Tk()
    app = TkGUI(root, debug=debug)
    root.mainloop()


if __name__ == "__main__":
    main()
