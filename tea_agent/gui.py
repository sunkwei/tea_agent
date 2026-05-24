import tkinter as tk
from tkinter import font as tkFont
from tkinter import ttk, scrolledtext, Listbox, Frame
import threading
import os
import os.path as osp
import sys
import re
import string
import html as html_mod
import traceback
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, cast, Callable, Optional, List, Tuple
import logging
import webbrowser

try:
    from tkinterweb import HtmlFrame
    import markdown
    HAS_TKINTERWEB = True
except ImportError:
    HAS_TKINTERWEB = False

try:
    import dbus
    import dbus.service
    import dbus.mainloop.glib
    from gi.repository import GLib
    HAS_SNI = True
except ImportError:
    HAS_SNI = False
from PIL import Image, ImageDraw

logger = logging.getLogger("main_db_gui")

if __name__ == "__main__":
    parent_dir = str(Path(__file__).resolve().parent.parent)
    if parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)
    from tea_agent.onlinesession import OnlineToolSession
    from tea_agent.store import Storage
    from tea_agent import tlk
    from tea_agent.agent_core import AgentCore

    from tea_agent._gui._tray import TrayManager
    from tea_agent._gui._images import ImageHandler
    from tea_agent._gui._renderer import ChatRenderer
    from tea_agent.config import load_config, get_config, save_config, ModelConfig
else:
    from .onlinesession import OnlineToolSession
    from .store import Storage
    from . import tlk
    from .agent_core import AgentCore
    from tea_agent._gui._tray import TrayManager
    from tea_agent._gui._images import ImageHandler
    from tea_agent._gui._renderer import ChatRenderer
    from .config import load_config, get_config, save_config, ModelConfig

_cfg = load_config()

if not _cfg.main_model.is_configured:
    print("错误: 请配置主模型 (main_model)")
    print("  编辑 $HOME/.tea_agent/config.yaml 或 tea_agent/config.yaml")
    sys.exit(1)

API_KEY = _cfg.main_model.api_key
API_URL = _cfg.main_model.api_url
MODEL = _cfg.main_model.model_name
CHEAP_MODEL = _cfg.cheap_model

_storage_ = None
_toolkit_ = None

from tea_agent._gui._fonts import (
    _fs, _init_fonts, SYSTEM_FONT, MONO_FONT,
    _DEFAULT_FONT_SIZE, _SCALE_FACTOR, _FONTS_DETECTED,
)
_IS_WINDOWS = __import__('platform').system() == "Windows"

from tea_agent._gui._markdown import (
    _render_markdown, _build_tool_blocks, _render_tool_group,
    _chat_to_markdown, _sanitize_html_control_chars,
    _validate_html_structure, _MD_CSS_TEMPLATE, _KNOWN_HTML_TAGS,
    HAS_TKINTERWEB,
)
from tea_agent._gui._topic_summary import _generate_topic_summary

from tea_agent._gui._stream_manager import StreamManager
from tea_agent._gui._topic_manager import TopicManager
from tea_agent._gui._ui_builder import UIBuilder
from tea_agent._gui._tray import TrayManager
from tea_agent._gui._images import ImageHandler
from tea_agent._gui._renderer import ChatRenderer

from tea_agent.gui_dialogs import MemoryDialog, TopicDialog, ConfigDialog

import os as _os

try:
    import dbus
    import dbus.service
    import dbus.mainloop.glib
    from gi.repository import GLib
    HAS_SNI = True
except ImportError:
    HAS_SNI = False

if HAS_SNI:
    class StatusNotifierItemDBus(dbus.service.Object):
        """StatusNotifierItem D-Bus 服务，替代 pystray，原生兼容 KDE Plasma 6"""

        def __init__(self, app_id, title, icon_pixmap_ar32, on_activate, on_context_menu):
            """Initialize  .
            
            Args:
                app_id: Description.
                title: Description.
                icon_pixmap_ar32: Description.
                on_activate: Description.
                on_context_menu: Description.
            """
            self._app_id = app_id
            self._title = title
            self._icon_data = icon_pixmap_ar32
            self._on_activate = on_activate
            self._on_context_menu = on_context_menu
            self._loop = None
            self._thread = None

            dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
            self._bus = dbus.SessionBus()
            bus_name = dbus.service.BusName(
                f'org.kde.StatusNotifierItem-{app_id.replace(".", "_")}-{os.getpid()}',
                self._bus,
            )
            super().__init__(bus_name, '/StatusNotifierItem')

        @dbus.service.method('org.kde.StatusNotifierItem', in_signature='', out_signature='s')
        def Title(self):
            """Title"""
            return self._title

        @dbus.service.method('org.kde.StatusNotifierItem', in_signature='', out_signature='s')
        def Id(self):
            """Id"""
            return self._app_id

        @dbus.service.method('org.kde.StatusNotifierItem', in_signature='', out_signature='s')
        def Status(self):
            """Status"""
            return 'Active'

        @dbus.service.method('org.kde.StatusNotifierItem', in_signature='', out_signature='s')
        def Category(self):
            """Category"""
            return 'ApplicationStatus'

        @dbus.service.method('org.kde.StatusNotifierItem', in_signature='', out_signature='ay')
        def IconPixmap(self):
            """IconPixmap"""
            import struct
            width = 32
            height = 32
            return struct.pack('<ii', width, height) + self._icon_data

        @dbus.service.method('org.kde.StatusNotifierItem', in_signature='', out_signature='')
        def Activate(self, x, y):
            """Activate.
            
            Args:
                x: Description.
                y: Description.
            """
            if callable(self._on_activate):
                self._on_activate()

        @dbus.service.method('org.kde.StatusNotifierItem', in_signature='', out_signature='')
        def ContextMenu(self, x, y):
            """ContextMenu.
            
            Args:
                x: Description.
                y: Description.
            """
            if callable(self._on_context_menu):
                self._on_context_menu(x, y)

        def start(self):
            """在后台线程启动 GLib main loop"""
            import threading
            self._loop = GLib.MainLoop()

            def run():
                """Run"""
                self._loop.run()

            self._thread = threading.Thread(target=run, daemon=True)
            self._thread.start()

        def stop(self):
            """Stop"""
            if self._loop:
                self._loop.quit()

class TkGUI(AgentCore):
    """TkGUI class."""
    def __init__(self, root, debug:bool=False, config_fname:str="", disable_summary:bool=False):
        """Initialize  .
        
        Args:
            root: Description.
            debug: Description.
            config_fname: Description.
            disable_summary: Description.
        """
        self.root = root
        import os
        self._initial_cwd = os.path.abspath(os.getcwd())
        self._update_title()
        self.root.geometry("1100x850")
        self.root.minsize(900, 600)

        self.sess = None

        super().__init__(debug=debug, config_path=config_fname, disable_summary=disable_summary)

        self.stream_mgr = StreamManager(self)
        self.topic_mgr = TopicManager(self)
        self.ui_builder = UIBuilder(self)

        self.renderer = ChatRenderer(self)

        self.images = ImageHandler(self)

        self.tray = TrayManager(self)
        self.tray.start()

        globals()["_storage_"] = self.db
        globals()["tlk"]._toolkit_ = self.toolkit

        self._zoom_level = 100

        self._image_cache = []
        self._raw_view = tk.BooleanVar(value=False)

        self.chat_messages: List[Dict] = []
        self._pending_images: List[str] = []
        self._current_round_view: Optional[int] = None
        self._chat_rounds: List[List[Dict]] = []

        self._stream_buffer = ""
        self._think_buffer = ""
        self._pending_console_text = []

        self._current_conversation_id: Optional[int] = None

        self._create_ui()
        if hasattr(self,"sess") and self.sess is not None:
            self.sess.tool_log = self.safe_log_tool

        cheap_m = self._cfg.cheap_model
        cheap_info = f" | 摘要模型: {cheap_m.model_name}" if cheap_m.model_name else ""
        self._update_status(f"📡 已连接 | 模型: {self._cfg.main_model.model_name}{cheap_info}")

        self.refresh_topics()
        self.auto_new_topic()
        # try:
        #     from tea_agent.toolkit.toolkit_subconscious import toolkit_subconscious
        #     result = toolkit_subconscious("start")
        #     if result.get("status") == "started":
        #         logger.info(f"潜意识引擎已随GUI启动, PID={result.get('pid')}")
        #     else:
        #         logger.info(f"潜意识引擎: {result.get('status', result)}")
        # except Exception as e:
        #     logger.warning(f"潜意识引擎启动失败(非致命): {e}")
        self.root.protocol("WM_DELETE_WINDOW", self.tray._on_closing)
    def _create_tray_icon(self):
        """动态生成托盘图标图像（32x32 蓝色圆角方块 + TA 字母），返回 PIL Image"""
        size = 32
        img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.rounded_rectangle([2, 2, size-2, size-2], radius=6, fill=(59, 130, 246, 255))
        try:
            from PIL import ImageFont
            font = ImageFont.truetype("arial.ttf", 14)
        except:
            font = ImageFont.load_default()
        draw.text((6, 6), "TA", fill=(255, 255, 255, 255), font=font)
        return img

    def _pil_to_argb32(self, img):
        """
        PIL RGBA Image -> ARGB32 bytes (用于 StatusNotifierItem IconPixmap)

        Args:
            img: Description.
        """
        rgba = img.tobytes()
        argb = bytearray(len(rgba))
        for i in range(0, len(rgba), 4):
            r, g, b, a = rgba[i], rgba[i+1], rgba[i+2], rgba[i+3]
            argb[i], argb[i+1], argb[i+2], argb[i+3] = a, r, g, b
        return bytes(argb)

    def _init_tray(self):
        """初始化系统托盘图标（StatusNotifierItem / KDE Plasma 6 原生支持）"""
        if not HAS_SNI:
            return
        try:
            pil_icon = self._create_tray_icon()
            argb_data = self._pil_to_argb32(pil_icon)
            self._sni = StatusNotifierItemDBus(
                app_id="tea_agent",
                title="TeaAgent",
                icon_pixmap_ar32=argb_data,
                on_activate=lambda: self.root.after(0, self._on_tray_activate),
                on_context_menu=lambda x, y: self.root.after(0, self._on_tray_context_menu, x, y),
            )
            self._tray_thread = threading.Thread(
                target=self._sni.run, daemon=True, name="tray-icon"
            )
            self._tray_thread.start()
            logger.info("托盘图标已启动 (StatusNotifierItem)")
        except Exception as e:
            logger.warning(f"初始化托盘图标失败: {e}")

    def _on_tray_activate(self):
        """托盘图标左键点击：显示/恢复主窗口"""
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def _on_tray_context_menu(self, x, y):
        """
        托盘图标右键：弹出菜单（含退出选项）

        Args:
            x: Description.
            y: Description.
        """
        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label="退出", command=self._on_closing)
        try:
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()

    def _on_closing(self):
        """窗口关闭时的清理流程"""
        self._update_status("⏳ 正在清理资源...")
        if HAS_SNI and self._sni:
            try:
                self._sni.stop()
                logger.info("托盘图标已停止")
            except Exception as e:
                logger.warning(f"停止托盘图标失败: {e}")
        try:
            from tea_agent.toolkit.toolkit_subconscious import toolkit_subconscious
            toolkit_subconscious("stop")
            logger.info("Dream 已停止")
        except Exception as e:
            logger.warning(f"停止 Dream 失败: {e}")
        try:
            from tea_agent.toolkit.toolkit_scheduler import toolkit_scheduler
            toolkit_scheduler("stop")
            logger.info("定时任务调度器已停止")
        except Exception as e:
            logger.warning(f"停止定时任务调度器失败: {e}")
        try:
            self.db.close()
            self._update_status("✅ 数据库已正常关闭")
        except Exception as e:
            logger.warning(f"关闭数据库失败: {e}")
        self.root.destroy()

    def _start_dream(self):
        """启动Dream潜意识引擎后台线程，每小时循环一次"""
        _proj_root = str(Path(__file__).resolve().parent.parent)
        try:
            os.chdir(_proj_root)
        except Exception:
            pass
        try:
            from tea_agent.toolkit.toolkit_subconscious import toolkit_subconscious
            result = toolkit_subconscious("start")
            status = result.get("status", "unknown")
            if status == "rejected":
                logger.warning(f"Dream 未自动启动: {result.get('reason')}, cwd={os.getcwd()}")
            elif status == "already_running":
                logger.info(f"Dream 已在运行中 (pid={result.get('pid')})")
            else:
                logger.info(f"Dream 自动启动成功: {status}")
        except Exception as e:
            logger.warning(f"Dream 自动启动失败: {e}")

    def _start_scheduler(self):
        """启动定时任务调度器后台线程，每分钟检查一次"""
        try:
            from tea_agent.toolkit.toolkit_scheduler import toolkit_scheduler
            result = toolkit_scheduler("start")
            status = result.get("status", "unknown")
            if status == "already_running":
                logger.info(f"定时任务调度器已在运行中 (pid={result.get('pid')})")
            else:
                logger.info(f"定时任务调度器自动启动成功: {status}")
        except Exception as e:
            logger.warning(f"定时任务调度器自动启动失败: {e}")

    def _create_ui(self):
        """创建界面 — 委托给 UIBuilder"""
        self.ui_builder.build()

    def _adjust_chat_sash(self):
        """权重比已调整，此方法保留作兼容"""
        pass

    def zoom_in(self, e=None):
        """Zoom in.
        
        Args:
            e: Description.
        """
        if not HAS_TKINTERWEB or self._show_mode != "chat_view":
            return "break"
        self._zoom_level = min(self._zoom_level + 10, 200)
        self._apply_zoom()
        self._update_status(f"🔍 缩放: {self._zoom_level}%")
        return "break"

    def zoom_out(self, e=None):
        """Zoom out.
        
        Args:
            e: Description.
        """
        if not HAS_TKINTERWEB or self._show_mode != "chat_view":
            return "break"
        self._zoom_level = max(self._zoom_level - 10, 50)
        self._apply_zoom()
        self._update_status(f"🔍 缩放: {self._zoom_level}%")
        return "break"

    def _apply_zoom(self):
        """Internal: apply zoom"""
        if not HAS_TKINTERWEB or not self._filtered_messages():
            return
        self._image_cache.clear()
        md = _chat_to_markdown(self._filtered_messages(), image_cache=self._image_cache)
        font_size = int(_DEFAULT_FONT_SIZE * self._zoom_level / 100)
        html = _render_markdown(md, font_size=font_size)
        self._html_render(html)
        self.root.after(200, self.scroll_to_bottom)

    def _history_prev_round(self, e=None):
        """
        Alt+Up: 切换到上一条历史轮次，若无则忽略

        Args:
            e: Description.
        """
        if not HAS_TKINTERWEB or self._show_mode != "chat_view":
            return "break"
        rounds = self._chat_rounds
        if not rounds:
            return "break"
        curr = self._current_round_view
        if curr is None:
            self._current_round_view = len(rounds) - 1
        elif curr <= 0:
            return "break"
        else:
            self._current_round_view = curr - 1
        self._render_round_view(self._current_round_view)
        return "break"

    def _history_next_round(self, e=None):
        """
        Alt+Down: 切换到下一条历史轮次，若无则忽略

        Args:
            e: Description.
        """
        if not HAS_TKINTERWEB or self._show_mode != "chat_view":
            return "break"
        rounds = self._chat_rounds
        if not rounds:
            return "break"
        curr = self._current_round_view
        if curr is None:
            return "break"
        if curr >= len(rounds) - 1:
            self._current_round_view = None
            self._render_and_show_chat()
        else:
            self._current_round_view = curr + 1
            self._render_round_view(self._current_round_view)
        return "break"


    def _now_ts(self) -> str:
        """
        Internal: now ts

        Returns:
            str: Description.
        """
        return datetime.now().strftime("%H:%M:%S")

    def _init_session(self):
        """GUI 的会话初始化 — 继承 AgentCore 创建 sess。"""
        super()._init_session()

    def toggle_reasoning(self, enable: Optional[bool] = None) -> dict:
        """
        切换或查询 reasoning/thinking 状态。供 toolkit 工具调用。

        Args:
            enable (Optional[bool]): Description.

        Returns:
            dict: Description.
        """
        if self.sess is None:
            return {"error": "无活跃会话"}
        if enable is None:
            return {"enable_thinking": self.sess.enable_thinking}
        self.sess.enable_thinking = bool(enable)
        state = "开启" if enable else "关闭"
        self._update_status(f"🧠 Reasoning 已{state}")
        return {"enable_thinking": self.sess.enable_thinking, "changed": True}

    def _update_status(self, msg: str):
        """
        更新状态栏

        Args:
            msg (str): Description.
        """
        if hasattr(self, 'status_var'):
            self.status_var.set(msg)

    def safe_stream(self, text):
        """
        线程安全的流式输出 — 委托 StreamManager

        Args:
            text: Description.
        """
        self.stream_mgr.safe_stream(text)

    def safe_log(self, msg, tag="ai"):
        """
        线程安全的日志输出 — 委托 StreamManager

        Args:
            msg: Description.
            tag: Description.
        """
        self.stream_mgr.safe_log(msg, tag)

    def safe_log_tool(self, msg: str):
        """
        线程安全的工具日志 — 委托 StreamManager

        Args:
            msg (str): Description.
        """
        self.stream_mgr.safe_log_tool(msg)

    def safe_update_status(self, msg: str):
        """
        线程安全的状态更新 — 委托 StreamManager

        Args:
            msg (str): Description.
        """
        self.stream_mgr.safe_update_status(msg)

    def _handle_max_iter(self, msg: str):
        """
        处理最大迭代次数 — 委托 StreamManager

        Args:
            msg (str): Description.
        """
        self.stream_mgr.handle_max_iter(msg)

    def log(self, msg, tag="ai", images=None):
        """
        输出日志到控制台 — 委托 StreamManager

        Args:
            msg: Description.
            tag: Description.
            images: Description.
        """
        self.stream_mgr.log(msg, tag, images)

    def stream(self, text):
        """
        流式输出 — 委托 StreamManager

        Args:
            text: Description.
        """
        self.stream_mgr.stream(text)

    def log_tool(self, msg: str):
        """
        工具日志 — 委托 StreamManager

        Args:
            msg (str): Description.
        """
        self.stream_mgr.log_tool(msg)

    def _stream_flush_tick(self):
        """流式刷新 — 委托 StreamManager"""
        self.stream_mgr.stream_flush_tick()

    def clear_chat(self):
        """清空聊天"""
        import tkinter as tk
        self.console.config(state=tk.NORMAL)
        self.console.delete("1.0", tk.END)
        self.console.config(state=tk.DISABLED)
        self.chat_messages.clear()
        self._stream_buffer = ""
        self._think_buffer = ""
        self._pending_console_text.clear()
        self._pending_images.clear()
        self._img_label.config(text="")
        self._clear_img_btn.pack_forget()

    def auto_new_topic(self):
        """自动创建主题 — 委托 TopicManager"""
        self.topic_mgr.auto_new_topic()

    def new_topic(self):
        """新建主题 — 委托 TopicManager"""
        self.topic_mgr.new_topic()

    def refresh_topics(self):
        """刷新主题列表 — 委托 TopicManager"""
        self.topic_mgr.refresh_topics()

    def _update_title(self, topic_title=""):
        """
        更新窗口标题

        Args:
            topic_title: Description.
        """
        title = "Tea Agent"
        if hasattr(self, 'current_topic_id') and self.current_topic_id and self.current_topic_id != -1:
            try:
                tp = self.db.get_topic(self.current_topic_id)
            except Exception:
                tp = None
            if tp and tp.get('summary'):
                title = f"{tp['summary']} - Tea Agent"
        if topic_title:
            title = f"{topic_title} - Tea Agent"
        try:
            dir_name = os.path.basename(self._initial_cwd or os.getcwd())
            title = f"{title}  [{dir_name}]"
        except Exception:
            pass
        self.root.title(title)

    def switch_topic(self, topic_id):
        """
        切换主题 — 委托 TopicManager

        Args:
            topic_id: Description.
        """
        self.topic_mgr.switch_topic(topic_id)

    def on_topic_select(self, e):
        """
        主题选择回调 — 委托 TopicManager

        Args:
            e: Description.
        """
        self.topic_mgr.on_topic_select(e)

    def newline(self, e=None):
        """
        插入换行 — 委托 TopicManager

        Args:
            e: Description.
        """
        return self.topic_mgr.newline(e)

    def _suggest_new_topic_if_needed(self, topic_id: str):
        """
        建议新建主题 — 委托 TopicManager

        Args:
            topic_id (str): Description.
        """
        self.topic_mgr._suggest_new_topic_if_needed(topic_id)

    def _on_summary_updated(self, topic_id: str, summary: str):
        """
        摘要更新回调 — 委托 TopicManager

        Args:
            topic_id (str): Description.
            summary (str): Description.
        """
        self.topic_mgr._on_summary_updated(topic_id, summary)

    def _refresh_topics_preserve_selection(self):
        """刷新主题列表保持选择 — 委托 TopicManager"""
        self.topic_mgr._refresh_topics_preserve_selection()

    def _on_topic_hover(self, event):
        """
        主题悬停 — 委托 TopicManager

        Args:
            event: Description.
        """
        self.topic_mgr._on_topic_hover(event)

    def _on_topic_leave(self, event):
        """
        主题离开 — 委托 TopicManager

        Args:
            event: Description.
        """
        self.topic_mgr._on_topic_leave(event)

    def _show_tooltip(self, event, idx):
        """
        显示工具提示 — 委托 TopicManager

        Args:
            event: Description.
            idx: Description.
        """
        self.topic_mgr._show_tooltip(event, idx)

    def _hide_tooltip(self):
        """隐藏工具提示 — 委托 TopicManager"""
        self.topic_mgr._hide_tooltip()

    def _notify_completion(self, ai_msg: Optional[str] = None, user_msg: Optional[str] = None):
        """
        LLM 任务完成后发送桌面通知。通知内容: TeaAgent: {user_msg} + {ai_msg}。

        Args:
            ai_msg (Optional[str]): Description.
            user_msg (Optional[str]): Description.
        """
        if user_msg and ai_msg:
            u = user_msg.strip()
            a = ai_msg.strip()
            if len(u) > 20:
                u = u[:20] + "..."
            if len(a) > 40:
                a = a[:40] + "..."
            notification_msg = f"TeaAgent: {u} + {a}"
        elif ai_msg:
            notification_msg = ai_msg.strip()
            if len(notification_msg) > 60:
                notification_msg = notification_msg[:60] + "..."
            notification_msg = f"TeaAgent: {notification_msg}"
        else:
            notification_msg = "TeaAgent: AI 任务已完成"

        try:
            from tea_agent.toolkit.toolkit_notify import toolkit_notify
            toolkit_notify("TeaAgent", notification_msg, urgency="normal", duration=5000)
        except Exception:
            pass

    def _attach_image(self):
        """打开文件对话框选择图片，存入 _pending_images"""
        from tkinter import filedialog
        import shutil, os
        files = filedialog.askopenfilenames(
            title="选择图片",
            filetypes=[
                ("图片文件", "*.png *.jpg *.jpeg *.gif *.bmp *.webp"),
                ("所有文件", "*.*"),
            ]
        )
        if not files:
            return
        img_dir = os.path.join(self._initial_cwd, "tmp", "images")
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
        self._img_label.config(text=f"已选 {count} 张图片")
        self._clear_img_btn.pack(side=tk.LEFT, padx=4)

    def _clear_images(self):
        """清空待发送图片列表"""
        self._pending_images.clear()
        self._img_label.config(text="")

    def send(self, e=None):
        """Send.
        
        Args:
            e: Description.
        """
        if self.generating or not self.current_topic_id:
            return "break"
        msg = self.input_box.get("1.0", tk.END).strip()
        images = list(self._pending_images)
        self.images.clear()
        if not msg and not images:
            return "break"
        self.input_box.delete("1.0", tk.END)

        self._switch_display("console")

        display_msg = f"你：{msg}" if msg else "你：[图片]"
        self.log(display_msg, "user", images=images if images else None)
        self._hide_raw_check_btn()
        self.generating = True
        self.root.after(500, self._stream_flush_tick)
        self.log("AI：", "title")

        mem_count = len(self.db.get_active_memories(50))
        self._update_status(f"⏳ 生成中... (ESC 打断) | 🧠 {mem_count}")

        chat_input = {"text": msg} if not images else {"text": msg, "images": images}

        def work():
            """Work"""
            try:
                ai_msg, is_func = self.sess.chat_stream(
                    chat_input, 
                    callback=self.safe_stream,
                    topic_id=self.current_topic_id,
                    on_status=self.safe_update_status,
                )
                self.root.after(0, self._flush_stream_to_messages)

                user_msg_for_db = msg if not images else {"text": msg, "images": images}
                self._post_chat_pipeline(ai_msg, is_func, user_msg_for_db, self.current_topic_id)

                usage = self.sess._last_usage
                cheap_usage = self.sess._last_cheap_usage
                if usage and usage.get("total_tokens", 0) > 0:
                    # 通过 after 调度 token 表格追加，确保排在 _flush_stream_to_messages 之后
                    # 避免工作线程直接 append 导致 token 表格跑到 AI 消息前面
                    def _append_token_and_render():
                        token_msg = self._build_token_table(cheap_usage, usage=usage)
                        self.chat_messages.append({"role": "notice", "content": token_msg, "timestamp": self._now_ts()})
                        self._render_and_show_chat()
                    self.root.after(0, _append_token_and_render)
                    self.root.after(0, self._show_raw_check_btn)
                    # self.root.after(3000, self._refresh_cheap_token_notice)
                    status_msg = (f"✅ 完成 | Tokens: {usage['total_tokens']:,} "
                                  f"(P:{usage['prompt_tokens']:,} C:{usage['completion_tokens']:,})")
                    self.root.after(0, lambda m=status_msg: self._update_status(m))
                    self.root.after(0, self._refresh_topics_preserve_selection)
                    self.root.after(600, lambda am=ai_msg, um=msg: self._notify_completion(am, um))
                else:
                    self.root.after(0, self._render_and_show_chat)
                    self.root.after(0, self._show_raw_check_btn)
                    self.root.after(0, lambda: self._update_status("✅ 完成"))
                    self.root.after(600, lambda am=ai_msg, um=msg: self._notify_completion(am, um))
            except Exception as ex:
                import traceback
                tb = traceback.format_exc()
                ai_msg = f"异常：{type(ex).__name__}: {ex}\n\n```\n{tb[-2000:]}\n```"
                self.safe_stream(ai_msg)
                self.root.after(0, self._flush_stream_to_messages)
                if self._current_conversation_id is not None:
                    rounds = self.sess._rounds_collector
                    try:
                        self.db.update_msg_rounds(
                            conversation_id=self._current_conversation_id,
                            ai_msg=ai_msg,
                            is_func_calling=False,
                            rounds=rounds if rounds else None,
                        )
                    except Exception:
                        pass
                self.root.after(0, self._render_and_show_chat)
                self.root.after(0, self._show_raw_check_btn)
                self.root.after(0, lambda: self._update_status(f"❌ 错误: {ai_msg}"))
                self.root.after(600, lambda am=ai_msg, um=msg: self._notify_completion(am, um))
            finally:
                self.generating = False
                self.safe_log("")

        threading.Thread(target=work, daemon=True).start()
        return "break"

    @staticmethod
    def _fmt_cell(val, detail_p=None, detail_c=None):
        """格式化为 'total (P:x C:y)' 或 'total (P:x)' 或 '—'"""
        if val <= 0:
            return "—"
        if detail_p is not None and detail_c is not None:
            return f"{val:,} (P:{detail_p:,} C:{detail_c:,})"
        if detail_p is not None:
            return f"{val:,} (P:{detail_p:,})"
        return f"{val:,}"

    def _build_token_table(self, cheap_usage: dict = None, usage: dict = None) -> str:
        """
        构建 token 统计 Markdown 表格：本轮/主题累积 × 主模型/便宜模型/嵌入模型。
        cheap_usage 为 None 时自动从 session 读取最新值。

        Args:
            cheap_usage (dict): 便宜模型本轮用量，None 则从 sess._last_cheap_usage 读取
            usage (dict): 主模型本轮用量，None 则从 sess._last_usage 读取
        Returns:
            str: Markdown 表格字符串
        """
        if usage is None:
            usage = self.sess._last_usage or {}
        if cheap_usage is None:
            cheap_usage = self.sess._last_cheap_usage or {}
        m_total = usage.get("total_tokens", 0)
        m_p = usage.get("prompt_tokens", 0)
        m_c = usage.get("completion_tokens", 0)
        c_total = cheap_usage.get("total_tokens", 0)
        c_p = cheap_usage.get("prompt_tokens", 0)
        c_c = cheap_usage.get("completion_tokens", 0)
        e_total = 0
        e_p = 0
        try:
            from tea_agent.embedding_util import get_embedding_engine
            emb_engine = get_embedding_engine()
            emb_usage = emb_engine.get_embedding_usage(reset=False)
            e_total = emb_usage.get("total_tokens", 0)
            e_p = emb_usage.get("prompt_tokens", 0)
        except Exception:
            pass
        try:
            ts = self.db.get_topic_tokens(self.current_topic_id)
            tm_total = ts.get("total_tokens", 0)
            tm_p = ts.get("total_prompt_tokens", 0)
            tm_c = ts.get("total_completion_tokens", 0)
            tc_total = ts.get("total_cheap_tokens", 0)
            tc_p = ts.get("total_cheap_prompt_tokens", 0)
            tc_c = ts.get("total_cheap_completion_tokens", 0)
            te_total = ts.get("total_embedding_tokens", 0)
            te_p = ts.get("total_embedding_prompt_tokens", 0)
        except Exception:
            tm_total = tm_p = tm_c = tc_total = tc_p = tc_c = te_total = te_p = 0

        _cell = self._fmt_cell
        lines = [
            "| | 主模型 | 便宜模型 | 嵌入模型 |",
            "|-------|--------|----------|----------|",
            f"| 本轮 | {_cell(m_total, m_p, m_c)} | {_cell(c_total, c_p, c_c)} | {_cell(e_total, e_p)} |",
            f"| 主题 | {_cell(tm_total, tm_p, tm_c)} | {_cell(tc_total, tc_p, tc_c)} | {_cell(te_total, te_p)} |",
        ]
        return "\n".join(lines)


    def _add_token_notice_and_render(self, usage: dict, cheap_usage: dict = None):
        """
        在聊天消息中追加 Markdown 表格：本轮/主题累积 × 主模型/便宜模型/嵌入模型 token 消耗。
        仅在 interrupt 等异常路径使用；正常流程由 work() 直接调用 _build_token_table 并一次性渲染。

        Args:
            usage (dict): 主模型本轮用量
            cheap_usage (dict): 便宜模型本轮用量
        """
        # token_msg = self._build_token_table(cheap_usage, usage=usage)
        # self.chat_messages.append({"role": "notice", "content": token_msg, "timestamp": self._now_ts()})
        # self._render_and_show_chat()
        pass

    def _on_history_link_click(self, url):
        """
        处理 tea://round/N 或 tea://latest 或 tea://image/N 链接点击，外部链接用系统浏览器打开

        Args:
            url: Description.
        """
        try:
            if url.startswith("http://") or url.startswith("https://"):
                webbrowser.open(url)
                return
            if url.startswith("tea://image/"):
                idx = int(url.rsplit("/", 1)[-1])
                self.images.show_popup(idx)
                return
            if url.startswith("tea://round/"):
                idx = int(url.rsplit("/", 1)[-1])
                self._current_round_view = idx
                self._render_round_view(idx)
            elif url == "tea://latest":
                self._current_round_view = None
                self._render_and_show_chat()
        except Exception:
            pass

    def _show_image_popup(self, idx):
        """
        点击聊天图片时弹出放大查看窗口。点击图片或按 Esc 关闭。

        Args:
            idx: Description.
        """
        if idx < 0 or idx >= len(self._image_cache):
            return
        b64_data, mime = self._image_cache[idx]

        import base64, io
        try:
            from PIL import Image, ImageTk
        except ImportError:
            self._update_status("需要安装 Pillow 库: pip install Pillow")
            return

        try:
            img_bytes = base64.b64decode(b64_data)
            img = Image.open(io.BytesIO(img_bytes))
        except Exception as exc:
            self._update_status("图片解码失败: " + str(exc))
            return

        popup = tk.Toplevel(self.root)
        popup.title("图片查看 - 点击图片或按 Esc 关闭")
        popup.configure(bg="#1a1a1a")

        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
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

    def open_topic_dialog(self):
        """打开主题管理弹窗"""
        TopicDialog(self.root, self.db,
                    on_switch=lambda tid: self.root.after(0, self.switch_topic, tid))

    def open_memory_dialog(self):
        """打开记忆管理对话框"""
        MemoryDialog(self.root, self.db)

    def open_config_dialog(self):
        """打开配置编辑对话框"""

        def on_save(cfg):
            """Handle save event.
            
            Args:
                cfg: Description.
            """
            if hasattr(self, 'sess') and self.sess:
                for key in cfg._RUNTIME_CONFIG_KEYS:
                    val = getattr(cfg, key, None)
                    if val is not None and hasattr(self.sess, key):
                        try:
                            setattr(self.sess, key, val)
                        except Exception:
                            pass
            self._update_status("⚙️ 配置已更新")

        ConfigDialog(self.root, on_save=on_save, config_path=self._config_path)

    def interrupt(self, e=None):
        """Interrupt.
        
        Args:
            e: Description.
        """
        if self.generating:
            self.sess.interrupt()
            self.safe_log("\n🛑 已打断", "tool")
            self.generating = False
            if self._pending_console_text:
                self.console.config(state=tk.NORMAL)
                for text, tag in self._pending_console_text:
                    if tag == "think":
                        self.console.insert(tk.END, text, "think")
                    else:
                        self.console.insert(tk.END, text)
                self.console.see(tk.END)
                self.console.config(state=tk.DISABLED)
                self._pending_console_text.clear()
            self.root.after(0, self._flush_stream_to_messages)
            self.root.after(0, self._render_and_show_chat)
            self.root.after(0, self._show_raw_check_btn)
            self._update_status("🛑 已打断")

    def _switch_display(self, mode: str):
        """Internal: switch display.
        
        Args:
            mode: Description.
        """
        return self.renderer._switch_display(mode)

    def _show_loading(self, text: str = "正在加载历史记录", progress: str = None):
        """Internal: show loading.
        
        Args:
            text: Description.
            progress: Description.
        """
        return self.renderer._show_loading(text, progress)

    def _poll_loading_progress(self):
        """Internal: poll loading progress"""
        return self.renderer._poll_loading_progress()

    def scroll_to_bottom(self):
        """Scroll to bottom"""
        return self.renderer.scroll_to_bottom()

    def _html_render(self, html: str):
        """Internal: html render.
        
        Args:
            html: Description.
        """
        return self.renderer._html_render(html)

    def _render_chat(self, streaming_think: str = "", streaming_text: str = ""):
        """Internal: render chat.
        
        Args:
            streaming_think: Description.
            streaming_text: Description.
        """
        return self.renderer._render_chat(streaming_think, streaming_text)

    def _render_and_show_chat(self):
        """Internal: render and show chat"""
        return self.renderer._render_and_show_chat()

    def _render_loaded_topic(self, render_items):
        """Internal: render loaded topic.
        
        Args:
            render_items: Description.
        """
        return self.renderer._render_loaded_topic(render_items)

    def _render_round_view(self, round_idx: int):
        """Internal: render round view.
        
        Args:
            round_idx: Description.
        """
        return self.renderer._render_round_view(round_idx)

    def _render_topic_error(self, error_msg: str):
        """Internal: render topic error.
        
        Args:
            error_msg: Description.
        """
        return self.renderer._render_topic_error(error_msg)

    def _build_round_view_html(self, rounds, active_idx, font_size):
        """Internal: build round view html.
        
        Args:
            rounds: Description.
            active_idx: Description.
            font_size: Description.
        """
        return self.renderer._build_round_view_html(rounds, active_idx, font_size)

    def _filtered_messages(self):
        """Internal: filtered messages"""
        return self.renderer._filtered_messages()

    def _group_into_rounds(self, msgs):
        """Internal: group into rounds.
        
        Args:
            msgs: Description.
        """
        return self.renderer._group_into_rounds(msgs)

    def _flush_stream_to_messages(self):
        """Internal: flush stream to messages"""
        return self.renderer._flush_stream_to_messages()

    def _flush_think_buffer_to_messages(self):
        """Internal: flush think buffer to messages"""
        return self.renderer._flush_think_buffer_to_messages()

    def _toggle_raw_view(self):
        """Internal: toggle raw view"""
        return self.renderer._toggle_raw_view()

    def _show_raw_check_btn(self):
        """Internal: show raw check btn"""
        return self.renderer._show_raw_check_btn()

    def _hide_raw_check_btn(self):
        """Internal: hide raw check btn"""
        return self.renderer._hide_raw_check_btn()

def main(debug:bool=False, no_gui:bool=False, timeout:int=0, config_fname:str="", disable_summary:bool=False):
    """启动 GUI 主界面。

    Args:
        debug: 调试模式
        timeout: 超时秒数，超时后自动关闭窗口（0=不超时，用于自动化测试）
        disable_summary: 禁用历史压缩和摘要
    """
    root = tk.Tk()
    app = TkGUI(root, debug=debug, config_fname=config_fname, disable_summary=disable_summary)
    
    if timeout > 0:
        logger.info(f"GUI debug timeout set: {timeout}s, will auto-close")
        root.after(timeout * 1000, lambda: _safe_destroy(root))
    
    root.mainloop()

def _safe_destroy(root):
    """
    安全销毁 Tk 窗口，捕获可能的异常。

    Args:
        root: Description.
    """
    try:
        if root.winfo_exists():
            root.destroy()
            logger.info("GUI auto-closed by timeout")
    except Exception as e:
        logger.warning(f"GUI safe destroy failed: {e}")

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Tea Agent GUI")
    ap.add_argument("--debug", action="store_true", help="调试模式")
    ap.add_argument(
        "--timeout", type=int, default=0,
        help="超时秒数，超时后自动关闭（用于自动化测试）"
    )
    ap.add_argument("--config", type=str, help="配置文件路径")
    ap.add_argument("--disable_summary", action="store_true", default=False,
                    help="禁用历史压缩和摘要，超过30轮直接丢弃")
    args = ap.parse_args()
    main(debug=args.debug, timeout=args.timeout, config_fname=args.config, disable_summary=args.disable_summary)
