"""

@2026-07-05 gen by tea_agent, Render Manager Component (组合模式)
Handles chat rendering, message filtering, round grouping, HTML generation.
"""

import tkinter as tk
from typing import Optional, List, Dict
from datetime import datetime

class RenderManager:
    """渲染管理组件"""
    
    def __init__(self, gui):
        self.gui = gui
    
    def now_ts(self) -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def render_chat(self, streaming_think: str = "", streaming_text: str = ""):
        """渲染聊天消息"""
        for w in self.gui._chat_frame_inner.winfo_children():
            w.destroy()
        
        msgs = self.filtered_messages()
        if self.gui._current_round_view is not None:
            msgs = self.gui._chat_rounds[self.gui._current_round_view]
            
        for msg in msgs:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role == "user":
                self.gui._chat_frame_inner.pack_forget()
                lbl = tk.Label(self.gui._chat_frame_inner, text=content, bg="#dcf8c6", anchor="e", wraplength=600, justify="right")
                lbl.pack(fill=tk.X, padx=20, pady=2, anchor="e")
            elif role == "assistant":
                if msg.get("type") == "think":
                    lbl = tk.Label(self.gui._chat_frame_inner, text=f"💭 {content}", fg="gray", anchor="w", wraplength=600, justify="left")
                    lbl.pack(fill=tk.X, padx=20, pady=2, anchor="w")
                else:
                    self.html_render(content)

        if streaming_think:
            lbl = tk.Label(self.gui._chat_frame_inner, text=f"💭 {streaming_think}", fg="gray", anchor="w", wraplength=600)
            lbl.pack(fill=tk.X, padx=20, pady=2, anchor="w")
        if streaming_text:
            self.html_render(streaming_text)

        self.gui._chat_canvas.configure(scrollregion=self.gui._chat_canvas.bbox("all"))
        self.gui._chat_canvas.yview_moveto(1.0)

    def render_and_show_chat(self):
        self.gui.render_manager.render_chat()
        self.gui.scroll_to_bottom()

    def render_loaded_topic(self, render_items):
        self.gui.chat_messages = render_items
        self.gui._chat_rounds = self.group_into_rounds(render_items)
        self.gui._current_round_view = None
        self.gui.render_manager.render_chat()

    def render_round_view(self, round_idx: int):
        if 0 <= round_idx < len(self.gui._chat_rounds):
            msgs = self.gui._chat_rounds[round_idx]
            self.gui.chat_messages = msgs
            self.gui.render_manager.render_chat()

    def render_topic_error(self, error_msg: str):
        for w in self.gui._chat_frame_inner.winfo_children():
            w.destroy()
        lbl = tk.Label(self.gui._chat_frame_inner, text=f"❌ {error_msg}", fg="red")
        lbl.pack(pady=20)

    def build_round_view_html(self, rounds, active_idx, font_size):
        html = "<html><body style='font-size:{}px'>".format(font_size)
        for i, r in enumerate(rounds):
            color = "#e3f2fd" if i == active_idx else "#f5f5f5"
            html += f"<div style='background:{color};padding:8px;margin:4px;border-radius:4px'>"
            for m in r:
                role = "👤" if m.get("role") == "user" else "🤖"
                html += f"<p>{role} {m.get('content','')[:100]}</p>"
            html += "</div>"
        html += "</body></html>"
        return html

    def filtered_messages(self):
        return [m for m in self.gui.chat_messages if m.get("content", "").strip()]

    def group_into_rounds(self, msgs):
        rounds = []
        current = []
        for m in msgs:
            if m.get("role") == "user" and current:
                rounds.append(current)
                current = []
            current.append(m)
        if current:
            rounds.append(current)
        return rounds

    def add_token_notice_and_render(self, usage: dict, cheap_usage: dict = None):
        notice = f"\n\n---\n💰 Tokens: {usage.get('total', 0)}"
        self.gui.chat_messages.append({"role": "system", "content": notice})
        self.gui.render_manager.render_chat()

    def cell(self, val, detail_p=None, detail_c=None):
        return val

    def on_history_link_click(self, url):
        import webbrowser
        webbrowser.open(url)

    def show_image_popup(self, idx):
        if 0 <= idx < len(self.gui._image_cache):
            b64, mime = self.gui._image_cache[idx]
            popup = tk.Toplevel(self.gui.root)
            popup.title("图片查看")
            import base64, io
            from PIL import Image, ImageTk
            img_data = base64.b64decode(b64)
            img = Image.open(io.BytesIO(img_data))
            img.thumbnail((800, 600))
            photo = ImageTk.PhotoImage(img)
            lbl = tk.Label(popup, image=photo)
            lbl.image = photo
            lbl.pack()

    def scroll_to_bottom(self):
        self.gui._chat_canvas.yview_moveto(1.0)

    def html_render(self, html: str):
        try:
            from tkinterweb import HtmlFrame
            frame = HtmlFrame(self.gui._chat_frame_inner, messages_enabled=False)
            frame.load_html(html)
            frame.pack(fill=tk.X, padx=10, pady=4)
        except ImportError:
            lbl = tk.Label(self.gui._chat_frame_inner, text=html, wraplength=600, justify="left", anchor="w")
            lbl.pack(fill=tk.X, padx=10, pady=4, anchor="w")

    def toggle_raw_view(self):
        self.gui._raw_view.set(not self.gui._raw_view.get())
        self.gui.render_manager.render_chat()

    def show_raw_check_btn(self):
        pass

    def hide_raw_check_btn(self):
        pass

    def switch_display(self, mode: str):
        pass

    def show_loading(self, text: str = "正在加载历史记录", progress: str = None):
        pass

    def poll_loading_progress(self):
        """定时器（50ms）：从 _progress_queue 逐条出队更新 HtmlFrame 进度；
        队列排空后若后台线程已完成，触发最终渲染。"""
        if not HAS_TKINTERWEB:
            return
        if self.gui._progress_queue:
            progress = self.gui._progress_queue.pop(0)  # FIFO
            self.show_loading("正在加载历史记录", f"{progress[0]}/{progress[1]}")
            self.gui.root.after(50, self.poll_loading_progress)
            return
        # 队列已空，检查后台线程是否完成
        if getattr(self.gui, '_loading_done', False):
            # 最终渲染
            if hasattr(self.gui, '_pending_error'):
                self.render_topic_error(self.gui._pending_error)
                delattr(self.gui, '_pending_error')
            elif hasattr(self.gui, '_pending_render'):
                self.render_loaded_topic(self.gui._pending_render)
                delattr(self.gui, '_pending_render')
            self.gui._loading_done = False
            self.gui.generating = False  # loading完成，释放send()锁
            return
        # 线程还在跑，继续等待
        self.gui.root.after(50, self.poll_loading_progress)
