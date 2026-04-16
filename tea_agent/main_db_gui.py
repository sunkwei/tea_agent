import tkinter as tk
from tkinter import ttk, scrolledtext, Listbox, Frame
import threading
import os
import os.path as osp
import sys
import re
import html as html_mod
from pathlib import Path
from datetime import datetime
from typing import Dict, cast, Callable, Optional, List, Tuple

try:
    from tkinterweb import HtmlFrame
    import markdown
    HAS_TKINTERWEB = True
except ImportError:
    HAS_TKINTERWEB = False

# ====================== 包导入兼容处理 ======================
if __name__ == "__main__":
    parent_dir = str(Path(__file__).resolve().parent.parent)
    if parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)
    from tea_agent.onlinesession import OnlineToolSession
    from tea_agent.store import Storage
    from tea_agent.memory import Memory, get_memory
    from tea_agent import tlk
else:
    from .onlinesession import OnlineToolSession
    from .store import Storage
    from .memory import Memory, get_memory
    from . import tlk

# ====================== 配置区 ======================
API_KEY = os.environ.get("TEA_AGENT_KEY")
API_URL = os.environ.get("TEA_AGENT_URL")
MODEL = os.environ.get("TEA_AGENT_MODEL")

if not API_KEY or not API_URL or not MODEL:
    print("错误: 请设置以下环境变量：")
    print("  TEA_AGENT_KEY   : API 密钥")
    print("  TEA_AGENT_URL   : API 地址")
    print("  TEA_AGENT_MODEL : 模型名称")
    sys.exit(1)

_storage_ = None
_toolkit_ = None
_memory_ = None

# ====================== Markdown → HTML 渲染 ======================

_MD_CSS = """
<style>
body { font-family: "Noto Sans CJK SC", "Source Han Sans SC", "WenQuanYi Micro Hei", "WenQuanYi Zen Hei", sans-serif; font-size: 16px; line-height: 1.6; color: #333; padding: 8px; }
h1, h2, h3, h4, h5, h6 { margin: 0.8em 0 0.4em; color: #1a73e8; }
h1 { font-size: 1.5em; border-bottom: 2px solid #eee; padding-bottom: 0.3em; }
h2 { font-size: 1.3em; border-bottom: 1px solid #eee; padding-bottom: 0.3em; }
p { margin: 0.5em 0; }
code { background: #f4f4f4; padding: 2px 5px; border-radius: 3px; font-family: "Noto Sans Mono CJK SC", "Source Han Mono SC", "WenQuanYi Micro Hei Mono", "Consolas", "Courier New", monospace; font-size: 0.9em; }
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
"""


def _render_markdown(text: str) -> str:
    """将 markdown 文本转换为带样式的 HTML 片段"""
    if not HAS_TKINTERWEB:
        return text
    html_body = markdown.markdown(text, extensions=["fenced_code", "tables", "codehilite"])
    return f"<html><head>{_MD_CSS}</head><body>{html_body}</body></html>"


def _chat_to_markdown(messages: List[Dict]) -> str:
    """将聊天消息列表转换为 markdown 格式，包含时间戳和分割线"""
    parts = []
    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")
        ts = msg.get("timestamp", "")
        ts_display = f"<span class=\"msg-timestamp\">{ts}</span>" if ts else ""
        if role == "user":
            parts.append(f"{ts_display}\n\n### 👤 你\n\n{content.strip()}\n")
        elif role == "ai":
            parts.append(f"{ts_display}\n\n### 🤖 AI\n\n{content.strip()}\n\n---\n")
        elif role == "tool":
            parts.append(f"{ts_display}\n> 🔧 **工具**: {content.strip()}\n")
        elif role == "notice":
            parts.append(f"\n---\n*{content.strip()}*\n---\n")
    return "\n".join(parts)


# ====================== GUI 主界面 ======================
class TkGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("AI 工具调用助手")
        self.root.geometry("1100x750")
        self.root.minsize(900, 600)

        root_path = Path.home() / ".tea_agent"
        if not root_path.exists():
            os.makedirs(root_path, exist_ok=True)

        db_path = root_path / "chat_history.db"
        tool_dir = root_path / "toolkit"
        if not tool_dir.exists():
            os.makedirs(tool_dir, exist_ok=True)

        self.db = Storage(db_path=str(db_path))
        self.toolkit = tlk.Toolkit(str(tool_dir))

        # 初始化 Memory
        self.memory = get_memory()

        globals()["_storage_"] = self.db
        globals()["_memory_"] = self.memory
        globals()["tlk"]._toolkit_ = self.toolkit

        tlk.toolkit_reload()

        # 会话相关
        self.current_topic_id = -1
        self.generating = False

        # Thinking 开关状态
        self.enable_thinking_var = tk.BooleanVar(value=True)

        # 聊天消息列表 — 用于最终渲染
        # 格式: [{"role": "user"|"ai"|"tool"|"notice", "content": "...", "timestamp": "..."}, ...]
        self.chat_messages: List[Dict] = []

        # 当前 stream 累积 buffer
        self._stream_buffer = ""

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

        ttk.Label(left, text="聊天主题", font=("Noto Sans CJK SC", 12, "bold")).pack(pady=5)
        self.topic_list = Listbox(left, font=("Noto Sans CJK SC", 10))
        self.topic_list.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        self.topic_list.bind("<<ListboxSelect>>", self.on_topic_select)
        ttk.Button(left, text="➕ 新建主题", command=self.new_topic).pack(
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

        # --- 组件 1: console (ScrolledText) — 用于显示中间结果 ---
        self.console = scrolledtext.ScrolledText(
            chat_frame, font=("Noto Sans CJK SC", 11), bg="white", fg="black", wrap=tk.WORD
        )
        self.console.config(state=tk.DISABLED)

        # --- 组件 2: chat_view (HtmlFrame) — 用于显示最终聊天信息 ---
        if HAS_TKINTERWEB:
            self.chat_view = HtmlFrame(chat_frame, messages_enabled=False)
        else:
            self.chat_view = scrolledtext.ScrolledText(
                chat_frame, font=("Noto Sans CJK SC", 11), bg="#fafafa", fg="black", wrap=tk.WORD
            )
            self.chat_view.config(state=tk.DISABLED)

        # 默认显示 console
        self._show_mode = "console"
        self._switch_display("console")

        # 输入区域
        input_frame = Frame(chat_split)
        chat_split.add(input_frame, weight=1)
        self.input_box = scrolledtext.ScrolledText(
            input_frame, font=("Noto Sans CJK SC", 14), height=4, bg="#f8f8f8"
        )
        self.input_box.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        self.thinking_check = ttk.Checkbutton(
            input_frame,
            text="🧠 启用 Thinking",
            variable=self.enable_thinking_var,
            command=self.on_thinking_toggle
        )
        self.thinking_check.pack(anchor=tk.W, padx=6, pady=2)

        ttk.Label(input_frame, text="Enter 发送 | Shift+Enter 换行 | Ctrl+C 打断",
                  foreground="#666").pack(anchor=tk.E, padx=6)

        # 样式配置
        self.console.tag_configure("user", foreground="#0055cc")
        self.console.tag_configure("ai", foreground="black")
        self.console.tag_configure("tool", foreground="#d68000")
        self.console.tag_configure(
            "title", foreground="#0066cc", font=("Noto Sans CJK SC", 12, "bold"))
        self.console.tag_configure("notice", foreground="#008800")
        self.console.tag_configure("error", foreground="#cc0000")

        # 快捷键绑定
        self.input_box.bind("<Return>", self.send)
        self.input_box.bind("<Shift-Return>", self.newline)
        self.root.bind("<Control-c>", self.interrupt)

    def _switch_display(self, mode: str):
        """切换显示模式: 'console' 或 'chat_view'"""
        if mode == self._show_mode:
            return
        self._show_mode = mode
        if mode == "console":
            self.chat_view.pack_forget()
            self.console.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        else:
            self.console.pack_forget()
            self.chat_view.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
            self.root.after(400, self.scroll_to_bottom)   # 延迟一点，等渲染完成

    def scroll_to_bottom(self):
        # HtmlFrame 内部通常有一个 canvas 或 text，可以通过属性访问并滚动
        self.chat_view.yview_moveto(1.0)

    def _render_chat(self):
        """将 self.chat_messages 渲染到 chat_view"""
        md = _chat_to_markdown(self.chat_messages)
        if HAS_TKINTERWEB:
            html = _render_markdown(md)
            self.chat_view.load_html(html)
        else:
            self.chat_view.config(state=tk.NORMAL)
            self.chat_view.delete("1.0", tk.END)
            self.chat_view.insert("1.0", md)
            self.chat_view.config(state=tk.DISABLED)
            self.chat_view.see(tk.END)

    def _now_ts(self) -> str:
        """获取当前时间戳字符串"""
        return datetime.now().strftime("%H:%M:%S")

    def _init_session(self):
        """初始化会话"""
        self.sess = OnlineToolSession(
            toolkit=self.toolkit,
            api_key=API_KEY,
            api_url=API_URL,
            model=MODEL,
            max_history=10,
            memory=self.memory,
            storage=self.db,
        )
        self.sess.enable_thinking = self.enable_thinking_var.get()

        self.sess.tool_log = self.safe_log_tool
        self._update_status(f"📡 已连接 | 模型: {MODEL} | 💾 Memory 已启用")

    def _update_status(self, msg: str):
        """更新状态栏"""
        self.status_var.set(msg)

    # ====================== 安全 UI 更新 ======================
    def safe_stream(self, text):
        self.root.after(0, self.stream, text)

    def safe_log(self, msg, tag="ai"):
        self.root.after(0, self.log, msg, tag)

    def safe_log_tool(self, msg: str):
        self.root.after(0, self.log_tool, msg)

    def on_thinking_toggle(self):
        """Thinking 开关切换回调"""
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

        stats = self.memory.get_stats()
        self.log(f"💾 Memory: {stats['total']} 条记忆", "notice")
        self.log("")

    def log(self, msg, tag="ai"):
        """向 console 追加一行文本，同时记录到 chat_messages"""
        self.console.config(state=tk.NORMAL)
        self.console.insert(tk.END, msg + "\n", tag)
        self.console.see(tk.END)
        self.console.config(state=tk.DISABLED)

        if tag in ("user", "ai", "tool", "notice"):
            self.chat_messages.append({"role": tag, "content": msg, "timestamp": self._now_ts()})

    def stream(self, text):
        """流式输出到 console，同时累积到 _stream_buffer"""
        self.console.config(state=tk.NORMAL)
        self.console.insert(tk.END, text)
        self.console.see(tk.END)
        self.console.config(state=tk.DISABLED)

        self._stream_buffer += text

    def log_tool(self, msg: str):
        self.log(msg, "tool")

    def _flush_stream_to_messages(self):
        """将当前 stream buffer 追加到 chat_messages 的 AI 消息中"""
        if self._stream_buffer:
            if self.chat_messages and self.chat_messages[-1]["role"] == "ai":
                self.chat_messages[-1]["content"] += self._stream_buffer
            else:
                self.chat_messages.append({"role": "ai", "content": self._stream_buffer, "timestamp": self._now_ts()})
            self._stream_buffer = ""

    def clear_chat(self):
        """清空 console 和 chat_messages"""
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
            self.topic_list.insert(tk.END, tp["title"])

    def switch_topic(self, topic_id):
        self.current_topic_id = topic_id
        self.clear_chat()
        topic = cast(dict, self.db.get_topic(topic_id))
        self.log(f"📌 当前主题：{topic['title']}", "title")
        self.log("-" * 50, "notice")

        conversations = self.db.get_conversations(topic_id)
        self.sess.load_history(conversations)
        for c in conversations:
            self.log(f"你：{c['user_msg']}", "user")
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

        self._update_status("⏳ 生成中... (Ctrl+C 打断)")

        def work():
            try:
                conv_id = self.db.save_msg(
                    self.current_topic_id, msg, "", False)
                self.sess.set_conversation_id(conv_id)

                ai_msg, is_func = self.sess.chat_stream(msg, self.safe_stream)

                self.root.after(0, self._flush_stream_to_messages)

                self.db.save_msg(self.current_topic_id, msg, ai_msg, is_func)

                self.root.after(0, self._render_and_show_chat)
                self.root.after(0, lambda: self._update_status("✅ 完成"))
            except Exception as ex:
                ai_msg = f"异常：{ex}"
                self.safe_stream(ai_msg)
                self.root.after(0, self._flush_stream_to_messages)
                self.root.after(0, self._render_and_show_chat)
                self.root.after(0, lambda: self._update_status(f"❌ 错误: {ex}"))
            finally:
                self.generating = False
                self.safe_log("")

        threading.Thread(target=work, daemon=True).start()
        return "break"

    def _render_and_show_chat(self):
        """渲染最终聊天信息并切换到 web 视图"""
        self._render_chat()
        self._switch_display("chat_view")

    def interrupt(self, e=None):
        if self.generating:
            self.sess.interrupt()
            self.safe_log("\n🛑 已打断", "tool")
            self.generating = False
            self.root.after(0, self._flush_stream_to_messages)
            self.root.after(0, self._render_and_show_chat)
            self._update_status("🛑 已打断")


def main():
    root = tk.Tk()
    app = TkGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()