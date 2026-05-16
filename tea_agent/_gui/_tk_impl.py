"""
@2026-05-15 gen by tea_agent, _interfaces.py 的 tkinter 实现
生产环境中使用，将接口调用桥接至真实的 tkinter widget。
"""

import tkinter as tk
from tkinter import filedialog
from typing import Optional
from ._interfaces import HtmlDisplay, TextDisplay, StatusDisplay, ImagePicker


class HtmlFrameDisplay(HtmlDisplay):
    """基于 tkhtmlview 的 HtmlFrame 实现"""

    def __init__(self, html_frame):
        self._frame = html_frame

    def show_html(self, html: str) -> None:
        self._frame.load_html(html)

    def clear(self) -> None:
        self._frame.reset()


class ScrolledTextDisplay(TextDisplay):
    """基于 tkinter.scrolledtext 的实现"""

    def __init__(self, scrolled_text):
        self._text = scrolled_text

    def append(self, text: str, tag: str = "") -> None:
        self._text.configure(state=tk.NORMAL)
        if tag:
            self._text.insert(tk.END, text, tag)
        else:
            self._text.insert(tk.END, text)
        self._text.configure(state=tk.DISABLED)

    def append_tagged(self, text: str, tag: str) -> None:
        self.append(text, tag)

    def scroll_to_end(self) -> None:
        self._text.see(tk.END)

    def set_state(self, state: str) -> None:
        self._text.configure(state=state)

    def get_all_text(self) -> str:
        return self._text.get("1.0", tk.END)


class LabelStatusDisplay(StatusDisplay):
    """基于 ttk.Label 的状态栏实现"""

    def __init__(self, label):
        self._label = label
        self._after_id: Optional[str] = None

    def show(self, text: str) -> None:
        self._label.config(text=text)


class TkImagePicker(ImagePicker):
    """基于 tkinter.filedialog 的图片选择实现"""

    def pick_images(self) -> list:
        paths = filedialog.askopenfilenames(
            title="选择图片",
            filetypes=[
                ("图片文件", "*.png *.jpg *.jpeg *.gif *.bmp *.webp"),
                ("所有文件", "*.*"),
            ],
        )
        return list(paths) if paths else []

    def show_popup(self, image_data: bytes) -> None:
        """显示图片放大弹窗 — 在 TkGUI._show_image_popup 中完整实现"""
        raise NotImplementedError("use TkGUI._show_image_popup for full impl")
