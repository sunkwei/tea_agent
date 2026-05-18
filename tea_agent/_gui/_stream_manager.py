"""
@2026-07-05 gen by tea_agent, Stream Manager Component (组合模式)
Handles streaming output, logging, status updates, buffer flushing.
"""

import tkinter as tk
from typing import Optional, List

class StreamManager:
    """流式输出管理组件"""
    
    def __init__(self, gui):
        self.gui = gui
    
    def safe_stream(self, text):
        """线程安全的流式输出"""
        self.gui.root.after(0, self.gui.stream, text)

    def safe_log(self, msg, tag="ai"):
        self.gui.root.after(0, self.gui.log, msg, tag)

    def safe_log_tool(self, msg: str):
        self.gui.root.after(0, self.gui.log_tool, msg)

    def safe_update_status(self, msg: str):
        self.gui.root.after(0, self.update_status, msg)

    def update_status(self, msg: str):
        """更新状态栏"""
        self.gui.status_var.set(msg)

    def handle_max_iter(self, msg: str):
        """处理最大迭代次数提示"""
        self.gui.log(msg, tag="system")
        self.update_status("⚠️ 达到最大迭代次数")

    def log(self, msg, tag="ai", images=None):
        """输出日志到控制台，同时追加到 chat_messages"""
        self.gui.console.config(state=tk.NORMAL)
        prefix = {"ai": "🤖 ", "user": "👤 ", "tool": "🔧 ", "system": "⚙️ "}.get(tag, "")
        self.gui.console.insert(tk.END, f"{prefix}{msg}\n", tag)
        self.gui.console.see(tk.END)
        self.gui.console.config(state=tk.DISABLED)
        # 追加到 chat_messages，用于 HtmlFrame 渲染
        if tag in ("user", "ai", "tool", "notice", "error", "title"):
            entry = {"role": tag, "content": msg, "timestamp": self.gui._now_ts()}
            if images:
                entry["images"] = images
            self.gui.chat_messages.append(entry)

    def stream(self, text):
        """流式输出到聊天区"""
        self.gui._stream_buffer += text
        if not self._stream_flush_scheduled:
            self._stream_flush_scheduled = True
            self.gui.root.after(50, self.stream_flush_tick)

    def log_tool(self, msg: str):
        self.gui.log(msg, tag="tool")

    def stream_flush_tick(self):
        """定时刷新流式缓冲"""
        if self.gui._stream_buffer:
            self.gui.chat_messages.append({"role": "assistant", "content": self.gui._stream_buffer, "streaming": True})
            self.gui._stream_buffer = ""
            self.gui.renderer._render_and_show_chat()
        self._stream_flush_scheduled = False

    def flush_stream_to_messages(self):
        """刷新流式缓冲到消息列表"""
        if self.gui._stream_buffer:
            self.gui.chat_messages.append({"role": "assistant", "content": self.gui._stream_buffer})
            self.gui._stream_buffer = ""

    def flush_think_buffer_to_messages(self):
        """刷新思考缓冲"""
        if self.gui._think_buffer:
            self.gui.chat_messages.append({"role": "assistant", "content": self.gui._think_buffer, "type": "think"})
            self.gui._think_buffer = ""
