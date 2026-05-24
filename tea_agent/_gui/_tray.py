"""
Usage: self.tray = TrayManager(self)  # self = TkGUI instance
"""

import tkinter as tk
import threading
import logging
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from tea_agent.gui import TkGUI

logger = logging.getLogger(__name__)

try:
    from tea_agent.toolkit.toolkit_sni_tray import StatusNotifierItemDBus
    HAS_SNI = True
except ImportError:
    HAS_SNI = False

class TrayManager:
    """系统托盘图标管理器（委托给 TkGUI）"""

    def __init__(self, gui: 'TkGUI'):
        """Initialize  .
        
        Args:
            gui: Description.
        """
        self.gui = gui
        self._sni = None
        self._tray_thread: Optional[threading.Thread] = None


    def start(self):
        """启动托盘图标"""
        self._init_tray()

    def stop(self):
        """停止托盘图标"""
        if HAS_SNI and self._sni:
            try:
                self._sni.stop()
                logger.info("托盘图标已停止")
            except Exception as e:
                logger.warning(f"停止托盘图标失败: {e}")


    def _init_tray(self):
        """Internal: initialize tray"""
        if not HAS_SNI:
            return
        try:
            from PIL import Image, ImageDraw
            pil_icon = self._create_tray_icon()
            argb_data = self._pil_to_argb32(pil_icon)
            self._sni = StatusNotifierItemDBus(
                app_id="tea_agent",
                title="TeaAgent",
                icon_pixmap_ar32=argb_data,
                on_activate=lambda: self.gui.root.after(0, self._on_tray_activate),
                on_context_menu=lambda x, y: self.gui.root.after(0, self._on_tray_context_menu, x, y),
            )
            self._tray_thread = threading.Thread(
                target=self._sni.run, daemon=True, name="tray-icon"
            )
            self._tray_thread.start()
            logger.info("托盘图标已启动 (StatusNotifierItem)")
        except Exception as e:
            logger.warning(f"初始化托盘图标失败: {e}")

    def _create_tray_icon(self):
        """Internal: create tray icon"""
        from PIL import Image, ImageDraw
        size = 32
        img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.rounded_rectangle([2, 2, size - 2, size - 2], radius=6, fill=(59, 130, 246, 255))
        try:
            from PIL import ImageFont
            font = ImageFont.truetype("arial.ttf", 14)
        except Exception:
            font = ImageFont.load_default()
        draw.text((6, 6), "TA", fill=(255, 255, 255, 255), font=font)
        return img

    def _pil_to_argb32(self, img):
        """Internal: pil to argb32.
        
        Args:
            img: Description.
        """
        rgba = img.tobytes()
        argb = bytearray(len(rgba))
        for i in range(0, len(rgba), 4):
            r, g, b, a = rgba[i], rgba[i + 1], rgba[i + 2], rgba[i + 3]
            argb[i], argb[i + 1], argb[i + 2], argb[i + 3] = a, r, g, b
        return bytes(argb)


    def _on_tray_activate(self):
        """左键点击：显示/恢复主窗口"""
        self.gui.root.deiconify()
        self.gui.root.lift()
        self.gui.root.focus_force()

    def _on_tray_context_menu(self, x, y):
        """
        右键点击：弹出菜单

        Args:
            x: Description.
            y: Description.
        """
        menu = tk.Menu(self.gui.root, tearoff=0)
        menu.add_command(label="退出", command=self._on_closing)
        try:
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()

    def _on_closing(self):
        """窗口关闭：清理托盘 + DB + Dream，然后 destroy"""
        self.gui._update_status("⏳ 正在清理资源...")
        self.stop()
        try:
            from tea_agent.toolkit.toolkit_subconscious import toolkit_subconscious
            toolkit_subconscious("stop")
            logger.info("Dream 已停止")
        except Exception as e:
            logger.warning(f"停止 Dream 失败: {e}")
        try:
            self.gui.db.close()
            self.gui._update_status("✅ 数据库已正常关闭")
        except Exception as e:
            logger.warning(f"关闭数据库失败: {e}")
        self.gui.root.destroy()
