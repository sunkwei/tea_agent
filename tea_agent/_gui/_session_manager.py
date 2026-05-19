"""
@2026-07-05 gen by tea_agent, Session Manager Component (组合模式)
Handles session initialization, topic management, reasoning toggle.
"""

import tkinter as tk
import threading
from typing import Optional

class SessionManager:
    """会话管理组件"""
    
    def __init__(self, gui):
        self.gui = gui
    
    def init_session(self):
        """初始化会话"""
        self.gui.sess = self.gui._init_session()
        self.refresh_topics()

    def toggle_reasoning(self, enable: Optional[bool] = None) -> dict:
        """切换推理模式"""
        if enable is None:
            enable = not getattr(self.gui, '_reasoning_enabled', False)
        self.gui._reasoning_enabled = enable
        btn_text = "🧠 推理:开" if enable else "🧠 推理"
        self.gui._reasoning_btn.config(text=btn_text)
        if self.gui.sess:
            self.gui.sess.reasoning = enable
        return {"reasoning": enable}

    def clear_chat(self):
        """清空聊天"""
        self.gui.console.config(state=tk.NORMAL)
        self.gui.console.delete("1.0", tk.END)
        self.gui.console.config(state=tk.DISABLED)
        self.gui.chat_messages.clear()
        self.gui._stream_buffer = ""
        self.gui._think_buffer = ""
        self.gui._pending_console_text.clear()
        self.gui._pending_images.clear()
        self.gui._img_label.config(text="")
        self.gui._clear_img_btn.config(state=tk.DISABLED)
        self.gui._current_round_view = None
        self.gui._chat_rounds.clear()
        self.gui.renderer._render_and_show_chat()

    def new_topic(self):
        """新建主题"""
        if self.gui.sess:
            self.gui.sess.new_topic()
            self.refresh_topics()

    def refresh_topics(self):
        """刷新主题列表 — @2026-05-19 gen by claude, 仅显示活跃主题"""
        if not self.gui.sess:
            return
        self.gui._topic_tree.delete(*self.gui._topic_tree.get_children())
        all_topics = self.gui.db.list_topics()
        for t in all_topics:
            if not t.get("is_active", 1):
                continue  # 跳过停用主题
            title = t.get("title", "无标题") or "无标题"
            ts = t.get("updated_at", "")
            self.gui._topic_tree.insert("", "end", text=title, values=(title, ts, t.get("id", "")))
            self.gui._topic_tree.item(self.gui._topic_tree.get_children()[-1], tags=(t.get("id", ""),))
    def switch_topic(self, topic_id):
        """切换主题"""
        if not self.gui.sess:
            return
        self.gui.session_manager.clear_chat()
        self.gui.sess.switch_topic(topic_id)
        self.refresh_topics()
        # topic loading handled by switch_topic in gui.py

    def auto_new_topic(self):
        """自动新建主题"""
        if self.gui.sess:
            pass  # auto_new_topic simplified

    def suggest_new_topic_if_needed(self, topic_id: str):
        """建议新主题"""
        pass  # 简化实现

    def on_summary_updated(self, topic_id: str, summary: str):
        """摘要更新回调"""
        self.refresh_topics()

    def refresh_topics_preserve_selection(self):
        """刷新主题列表并保留选中项"""
        self.refresh_topics()
