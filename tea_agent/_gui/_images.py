"""
Usage: self.images = ImageHandler(self)  # self = TkGUI instance
"""

import tkinter as tk
import os
import shutil
import base64
import io
import logging
from typing import List, TYPE_CHECKING

if TYPE_CHECKING:
    from tea_agent.gui import TkGUI

logger = logging.getLogger(__name__)

class ImageHandler:
    """图片附件选择、清除、放大查看（委托给 TkGUI）"""

    def __init__(self, gui: 'TkGUI'):
        self.gui = gui

    @property
    def _pending_images(self) -> list:
        return self.gui._pending_images

    @property
    def _image_cache(self) -> list:
        return self.gui._image_cache

    # ── 选择图片 ────────────────────────

    def attach(self):
        """打开文件对话框选择图片，复制到 tmp/images/，存入 _pending_images"""
        from tkinter import filedialog

        files = filedialog.askopenfilenames(
            title="选择图片",
            filetypes=[
                ("图片文件", "*.png *.jpg *.jpeg *.gif *.bmp *.webp"),
                ("所有文件", "*.*"),
            ],
        )
        if not files:
            return

        img_dir = os.path.join(self.gui._initial_cwd, "tmp", "images")
        os.makedirs(img_dir, exist_ok=True)

        for f in files:
            basename = os.path.basename(f)
            dest = os.path.join(img_dir, basename)
            if os.path.exists(dest):
                name, ext = os.path.splitext(basename)
                counter = 1
                while os.path.exists(os.path.join(img_dir, f"{name}_{counter}{ext}")):
                    counter += 1
                dest = os.path.join(img_dir, f"{name}_{counter}{ext}")
            shutil.copy2(f, dest)
            self._pending_images.append(dest)

        count = len(self._pending_images)
        self.gui._img_label.config(text=f"已选 {count} 张图片")
        self.gui._clear_img_btn.pack(side=tk.LEFT, padx=4)

    def clear(self):
        """清空待发送图片列表"""
        self._pending_images.clear()
        self.gui._img_label.config(text="")

    # ── 放大查看 ────────────────────────

    def show_popup(self, idx: int):
        """点击聊天图片时弹出放大查看窗口"""
        if idx < 0 or idx >= len(self._image_cache):
            return
        b64_data, mime = self._image_cache[idx]

        try:
            from PIL import Image, ImageTk
        except ImportError:
            self.gui._update_status("需要安装 Pillow 库: pip install Pillow")
            return

        try:
            img_bytes = base64.b64decode(b64_data)
            img = Image.open(io.BytesIO(img_bytes))
        except Exception as exc:
            self.gui._update_status("图片解码失败: " + str(exc))
            return

        popup = tk.Toplevel(self.gui.root)
        popup.title("图片查看 - 点击图片或按 Esc 关闭")
        popup.configure(bg="#1a1a1a")

        screen_w = self.gui.root.winfo_screenwidth()
        screen_h = self.gui.root.winfo_screenheight()
        max_w = int(screen_w * 0.9)
        max_h = int(screen_h * 0.85)

        img_w, img_h = img.size
        if img_w > max_w or img_h > max_h:
            ratio = min(max_w / img_w, max_h / img_h)
            new_w, new_h = int(img_w * ratio), int(img_h * ratio)
            img = img.resize((new_w, new_h), Image.LANCZOS)

        photo = ImageTk.PhotoImage(img)
        label = tk.Label(popup, image=photo, bg="#1a1a1a", cursor="hand2")
        label.image = photo
        label.pack(padx=4, pady=4)

        label.bind("<Button-1>", lambda e: popup.destroy())
        popup.bind("<Escape>", lambda e: popup.destroy())

        popup.update_idletasks()
        pw = popup.winfo_reqwidth()
        ph = popup.winfo_reqheight()
        x = (screen_w - pw) // 2
        y = (screen_h - ph) // 2
        popup.geometry("+{}+{}".format(x, y))

        popup.focus_set()
