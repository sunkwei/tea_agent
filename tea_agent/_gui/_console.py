"""
@2026-07-07 gen by tea_agent, 控制台 I/O 模块
从 gui.py L1131-1251 提取：log/stream/console 输出 + 状态更新 + max_iter 处理
"""

import tkinter as tk
from tkinter import messagebox
from datetime import datetime
import logging

from typing import Optional, TYPE_CHECKING
if TYPE_CHECKING:
    from tea_agent.gui import TkGUI

logger = logging.getLogger("main_db_gui")


class ConsoleIO:
    """控制台 I/O 管理器：log、stream、状态更新、max_iter 弹框"""

    def __init__(self, gui):
        self.gui = gui

    def _now_ts(self) -> str:
        return datetime.now().strftime("%H:%M:%S")

    # NOTE: 2026-05-04 18:48:10, _init_session 继承 AgentCore
    def _init_session(self):
        """GUI 的会话初始化 — 继承 AgentCore 创建 sess。"""
        self.gui.super()._init_session()

    def toggle_reasoning(self, enable: Optional[bool] = None) -> dict:
        """切换或查询 reasoning/thinking 状态。供 toolkit 工具调用。"""
        if self.gui.sess is None:
            return {"error": "无活跃会话"}
        if enable is None:
            return {"enable_thinking": self.gui.sess.enable_thinking}
        self.gui.sess.enable_thinking = bool(enable)
        state = "开启" if enable else "关闭"
        self.gui._update_status(f"🧠 Reasoning 已{state}")
        return {"enable_thinking": self.gui.sess.enable_thinking, "changed": True}

    def _update_status(self, msg: str):
        self.gui.status_var.set(msg)

    def safe_stream(self, text):
        self.gui.root.after(0, self.gui.stream, text)

    def safe_log(self, msg, tag="ai"):
        self.gui.root.after(0, self.gui.log, msg, tag)

    def safe_log_tool(self, msg: str):
        self.gui.root.after(0, self.gui.log_tool, msg)

    def safe_update_status(self, msg: str):
        if msg.startswith("!MAX_ITER:"):
            self.gui.root.after(0, self._handle_max_iter, msg)
        else:
            self.gui.root.after(0, self._update_status, msg)

    # NOTE: 2026-04-29 gen by deepseek-v4-pro, 工具调用达上限时弹框询问继续/终止
    def _handle_max_iter(self, msg: str):
        """弹出对话框询问用户是否继续工具调用。"""
        display = msg.replace("!MAX_ITER:", "")
        result = messagebox.askyesno(
            "达到工具调用上限",
            display + "\n\n选择「是」续命 " + str(getattr(self.gui.sess, "extra_iterations_on_continue", 5) if hasattr(self.gui, "sess") and self.gui.sess else 5) + " 轮\n选择「否」终止当前回答",
            parent=self.gui.root,
        )
        if hasattr(self.gui, 'sess') and self.gui.sess:
            self.gui.sess._continue_after_max = result
            self.gui.sess._max_iter_wait.set()
            if result:
                self._update_status("⏳ 已续命，继续生成... (ESC 打断)")
            else:
                self._update_status("🛑 用户终止工具调用")

    def log(self, msg, tag="ai", images=None):
        self.gui.console.config(state=tk.NORMAL)
        self.gui.console.insert(tk.END, msg + "\n", tag)
        self.gui.console.see(tk.END)
        self.gui.console.config(state=tk.DISABLED)

        if tag in ("user", "ai", "tool", "notice"):
            entry = {"role": tag, "content": msg, "timestamp": self._now_ts()}
            if images:
                entry["images"] = images
            self.gui.chat_messages.append(entry)

    # NOTE: 2026-05-07 17:32:01, stream() 识别 [THINK] 前缀
    def stream(self, text):
        # 检测 [THINK_DONE] 信号
        if text == "[THINK_DONE]":
            self.gui._flush_think_buffer_to_messages()
            return

        is_think = text.startswith("[THINK]")
        display_text = text[7:] if is_think else text

        if is_think:
            self.gui._think_buffer += display_text
            self.gui._pending_console_text.append((display_text, "think"))
        else:
            self.gui._stream_buffer += display_text
            self.gui._pending_console_text.append((display_text, None))

    def log_tool(self, msg: str):
        self.gui.log(msg, "tool")

    # NOTE: 2026-05-08 08:46:00, 500ms 定时器批量刷新
    def _stream_flush_tick(self):
        """500ms 定时器：批量将累积文本刷新到 ScrolledText 控制台。"""
        if self.gui._pending_console_text:
            self.gui.console.config(state=tk.NORMAL)
            for text, tag in self.gui._pending_console_text:
                if tag == "think":
                    self.gui.console.insert(tk.END, text, "think")
                else:
                    self.gui.console.insert(tk.END, text)
            self.gui.console.see(tk.END)
            self.gui.console.config(state=tk.DISABLED)
            self.gui._pending_console_text.clear()
        if self.gui.generating:
            self.gui.root.after(500, self._stream_flush_tick)