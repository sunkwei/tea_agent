"""
@2026-07-05 gen by tea_agent, Event Manager Component (组合模式)
Handles user interactions, dialogs, image attachments, send/interrupt.
"""

import tkinter as tk
from tkinter import ttk, filedialog
from typing import Optional, List
import base64
import os

class EventManager:
    """事件处理组件"""
    
    def __init__(self, gui):
        self.gui = gui
    
    def send(self, e=None):
        """发送消息"""
        text = self.gui._input.get("1.0", tk.END).strip()
        if not text:
            return
        self.gui._input.delete("1.0", tk.END)
        
        self.gui.chat_messages.append({"role": "user", "content": text})
        self.gui._current_round_view = None
        self.gui.renderer._render_and_show_chat()
        
        self.gui._interrupt_btn.config(state=tk.NORMAL)
        self.gui.stream_manager.update_status("正在思考...")
        
        # 启动工作线程
        import threading
        def work():
            try:
                if self.gui.sess:
                    self.gui.sess.send(text, stream_callback=self.gui.stream_manager.safe_stream)
            except Exception as ex:
                self.gui.stream_manager.safe_log(f"错误: {ex}", tag="system")
            finally:
                self.gui.root.after(0, lambda: self.gui._interrupt_btn.config(state=tk.DISABLED))
                self.gui.root.after(0, lambda: self.gui.stream_manager.update_status("就绪"))
                self.gui.ui_manager.notify_completion(ai_msg=text)
        
        threading.Thread(target=work, daemon=True).start()

    def interrupt(self, e=None):
        """中断当前任务"""
        if self.gui.sess:
            self.gui.sess.interrupt()
        self.gui._interrupt_btn.config(state=tk.DISABLED)
        self.gui.stream_manager.update_status("已中断")

    def newline(self, e=None):
        """换行"""
        self.gui._input.insert(tk.INSERT, "\n")
        return "break"

    def on_topic_select(self, e):
        """主题选择"""
        sel = self.gui._topic_tree.selection()
        if sel:
            item = sel[0]
            vals = self.gui._topic_tree.item(item, "values")
            if vals and len(vals) >= 3:
                topic_id = vals[2]
                self.gui.switch_topic(topic_id)

    def attach_image(self):
        """附加图片"""
        paths = filedialog.askopenfilenames(filetypes=[("图片", "*.png *.jpg *.jpeg *.gif *.webp")])
        if paths:
            self.gui._pending_images.extend(paths)
            self.gui._img_label.config(text=f"📎 {len(self.gui._pending_images)} 张图片")
            self.gui._clear_img_btn.config(state=tk.NORMAL)

    def clear_images(self):
        """清除附加图片"""
        self.gui._pending_images.clear()
        self.gui._img_label.config(text="")
        self.gui._clear_img_btn.config(state=tk.DISABLED)

    def open_topic_dialog(self):
        """打开主题管理对话框"""
        dlg = tk.Toplevel(self.gui.root)
        dlg.title("主题管理")
        dlg.geometry("400x300")
        ttk.Label(dlg, text="主题管理功能开发中...").pack(pady=20)

    def open_memory_dialog(self):
        """打开记忆管理对话框"""
        dlg = tk.Toplevel(self.gui.root)
        dlg.title("记忆管理")
        dlg.geometry("400x300")
        ttk.Label(dlg, text="记忆管理功能开发中...").pack(pady=20)

    def open_config_dialog(self):
        """打开配置对话框"""
        dlg = tk.Toplevel(self.gui.root)
        dlg.title("配置")
        dlg.geometry("500x400")
        ttk.Label(dlg, text="配置编辑功能开发中...").pack(pady=20)

    def on_save(self, cfg):
        """保存配置"""
        pass
