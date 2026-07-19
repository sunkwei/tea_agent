"""
Usage: self.tray = TrayManager(self)  # self = TkGUI instance
"""

import logging
import threading
import tkinter as tk
from typing import TYPE_CHECKING

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
        self._tray_thread: threading.Thread | None = None

    # ── 初始化 ──────────────────────────

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

    # ── 内部方法 ────────────────────────

    def _init_tray(self):
        """Internal: initialize tray."""
        if not HAS_SNI:
            return
        try:
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
        """加载或生成托盘图标（32x32 齿轮图标）。"""
        import os as _os

        from PIL import Image
        size = 32
        # 先尝试加载生成的图标，fallback 到代码绘制
        icon_path = _os.path.join(_os.path.dirname(__file__), "icon.png")
        if _os.path.exists(icon_path):
            img = Image.open(icon_path).convert("RGBA")
            img = img.resize((size, size), Image.LANCZOS)
            return img
        # Fallback: 简单齿轮图案
        from PIL import ImageDraw
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

    # ── 事件处理 ────────────────────────

    def _on_tray_activate(self):
        """左键点击：显示/恢复主窗口"""
        self.gui.root.deiconify()
        self.gui.root.lift()
        self.gui.root.focus_force()

    def _on_tray_context_menu(self, x, y):
        """右键点击：弹出菜单"""
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
        # 停止定时任务调度器
        try:
            from tea_agent.toolkit.toolkit_scheduler import toolkit_scheduler
            toolkit_scheduler("stop")
            logger.info("定时任务调度器已停止")
        except Exception as e:
            logger.warning(f"停止定时任务调度器失败: {e}")
        # 关闭会话资源
        try:
            if hasattr(self.gui, 'sess') and self.gui.sess:
                self.gui.sess.close()
                logger.info("会话资源已释放")
        except Exception as e:
            logger.warning(f"关闭会话资源失败: {e}")
        # 关闭数据库
        try:
            self.gui.db.close()
            self.gui._update_status("✅ 数据库已正常关闭")
        except Exception as e:
            logger.warning(f"关闭数据库失败: {e}")
        self.gui.root.destroy()
