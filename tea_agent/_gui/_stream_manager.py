"""
Handles streaming output, logging, status updates, buffer flushing.

  - stream(): 恢复 [THINK] 前缀识别 + _pending_console_text 写入
  - stream_flush_tick(): 恢复 ScrolledText 批量刷新 + 自调度 + chat_messages 同步

  - log(): 恢复 chat_messages 追加（user/ai/tool/notice 角色），支持 _render_loaded_topic 正常渲染
  - log_tool(): 统一使用 "tool" 标签，确保工具日志也写入 chat_messages
"""

import tkinter as tk
from tkinter import messagebox
from typing import Optional, List

class StreamManager:
    """流式输出管理组件"""
    
    def __init__(self, gui):
        """Initialize  .
        
        Args:
            gui: Description.
        """
        self.gui = gui
    
    def safe_stream(self, text):
        """线程安全的流式输出"""
        self.gui.root.after(0, self.gui.stream, text)

    def safe_log(self, msg, tag="ai"):
        """Safe log.
        
        Args:
            msg: Description.
            tag: Description.
        """
        self.gui.root.after(0, self.gui.log, msg, tag)

    def safe_log_tool(self, msg: str):
        """Safe log tool.
        
        Args:
            msg: Description.
        """
        self.gui.root.after(0, self.gui.log_tool, msg)

    def safe_update_status(self, msg: str):
        """Safe update status.
        
        Args:
            msg: Description.
        """
        if msg.startswith("!MAX_ITER:"):
            self.gui.root.after(0, self.handle_max_iter, msg)
        else:
            self.gui.root.after(0, self.update_status, msg)

    def update_status(self, msg: str):
        """更新状态栏"""
        self.gui.status_var.set(msg)

    def handle_max_iter(self, msg: str):
        """处理最大迭代次数 - 弹框询问是否续命，设置 _max_iter_wait 信号"""
        display = msg.replace("!MAX_ITER:", "")
        extra = getattr(self.gui.sess, "extra_iterations_on_continue", 5) if hasattr(self.gui, "sess") and self.gui.sess else 5
        result = messagebox.askyesno(
            "达到工具调用上限",
            display + "\n\n选择「是」续命 " + str(extra) + " 轮\n选择「否」终止当前回答",
            parent=self.gui.root,
        )
        if hasattr(self.gui, "sess") and self.gui.sess:
            sess = self.gui.sess
            sess._continue_after_max = result
            sess._max_iter_wait.set()
            if result:
                self.update_status("续命成功，继续生成... (ESC 打断)")
            else:
                self.update_status("用户终止工具调用")
        self.gui.log(msg, tag="system")

    def log(self, msg, tag="ai", images=None):
        """输出日志到控制台区域，并追加到 chat_messages"""
        self.gui.console.config(state=tk.NORMAL)

        # 添加时间戳
        from datetime import datetime
        ts = datetime.now().strftime("%H:%M:%S")
        if tag == "user":
            self.gui.console.insert(tk.END, f"\n[{ts}]\n", "timestamp")
        elif tag == "ai":
            self.gui.console.insert(tk.END, f"[{ts}] ", "timestamp")
        elif tag == "tool" or tag == "tool_raw":
            self.gui.console.insert(tk.END, f"[{ts}] ", "timestamp")
        elif tag == "system":
            self.gui.console.insert(tk.END, f"[{ts}] ", "timestamp")
        elif tag == "notice":
            self.gui.console.insert(tk.END, f"[{ts}] ", "timestamp")

        self.gui.console.insert(tk.END, msg, tag)
        self.gui.console.see(tk.END)
        self.gui.console.config(state=tk.DISABLED)
        self.gui.console.update_idletasks()

        if tag in ("user", "ai", "tool", "notice"):
            entry = {"role": tag, "content": msg, "timestamp": self.gui._now_ts()}
            if images:
                entry["images"] = images
            self.gui.chat_messages.append(entry)

    def log_tool(self, msg: str):
        """记录工具调用日志 — 统一用 'tool' 标签确保写入 chat_messages"""
        self.gui.log(msg, "tool")

    # ── 流式输出核心方法 ─────────────────────────────────────

    def stream(self, text):
        """流式输出 — 识别 [THINK] 前缀，写入缓冲供 500ms 定时器批量刷新"""
        # [THINK_DONE] 信号 → 刷新 thinking buffer 为独立消息
        if text == "[THINK_DONE]":
            self.gui._flush_think_buffer_to_messages()
            return

        # 检测 [THINK] 前缀：7字符标记
        is_think = text.startswith("[THINK]")
        display_text = text[7:] if is_think else text

        # 分别缓冲 + 入队到 ScrolledText 刷新队列
        if is_think:
            self.gui._think_buffer += display_text
            self.gui._pending_console_text.append((display_text, "think"))
        else:
            self.gui._stream_buffer += display_text
            self.gui._pending_console_text.append((display_text, None))

    def stream_flush_tick(self):
        """500ms 定时器回调 — 批量刷新 ScrolledText + 同步 chat_messages"""
        # 1. 批量刷新 ScrolledText
        if self.gui._pending_console_text:
            self.gui.console.config(state=tk.NORMAL)
            for text, tag in self.gui._pending_console_text:
                if tag == "think":
                    self.gui.console.insert(tk.END, text, "think")
                else:
                    self.gui.console.insert(tk.END, text)
            self.gui.console.see(tk.END)
            self.gui.console.config(state=tk.DISABLED)
            self.gui.console.update_idletasks()
            self.gui._pending_console_text.clear()

        # 2. 不再同步到 chat_messages（流式期间不渲染 HtmlFrame，避免产生多个不完整 AI 块）
        # _stream_buffer 保持累积，最终一次性 flush 为完整 AI 消息

        # 3. 自调度：如果仍在生成中，继续 500ms 后刷新
        if self.gui.generating:
            self.gui.root.after(500, self.gui._stream_flush_tick)

    def flush_stream_to_messages(self):
        """刷新流式缓冲到消息列表"""
        if self.gui._stream_buffer:
            self.gui.chat_messages.append({"role": "ai", "content": self.gui._stream_buffer})
            self.gui._stream_buffer = ""
