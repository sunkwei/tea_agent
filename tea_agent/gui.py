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

# NOTE: 2026-06-23 gen by tea_agent, 托盘图标支持（StatusNotifierItem/KDE Plasma 6 + 通用 Linux）
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

# ====================== 包导入兼容处理 ======================
if __name__ == "__main__":
    parent_dir = str(Path(__file__).resolve().parent.parent)
    if parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)
# NOTE: 2026-05-04 18:47:48, self-evolved by tea_agent --- 添加 AgentCore 导入
    from tea_agent.onlinesession import OnlineToolSession
    from tea_agent.store import Storage
    from tea_agent import tlk
    from tea_agent.agent_core import AgentCore

# @2026-05-15 gen by tea_agent, Composition: GUI 组件
    from tea_agent._gui._tray import TrayManager
    from tea_agent._gui._images import ImageHandler
    from tea_agent._gui._renderer import ChatRenderer  # @2026-05-15 gen by tea_agent, Composition: 渲染组件
# NOTE: 2026-05-01 15:30:42, self-evolved by tea_agent --- 为 GUI 添加 ConfigDialog 配置编辑弹窗 + 左侧"⚙️ 配置"按钮
    from tea_agent.config import load_config, get_config, save_config, ModelConfig
else:
    from .onlinesession import OnlineToolSession
    from .store import Storage
    from . import tlk
    from .agent_core import AgentCore
    # @2026-05-15 gen by tea_agent, Composition: GUI 组件
    from tea_agent._gui._tray import TrayManager
    from tea_agent._gui._images import ImageHandler
    from tea_agent._gui._renderer import ChatRenderer  # @2026-05-15 gen by tea_agent, Composition: 渲染组件
# NOTE: 2026-05-01 15:30:48, self-evolved by tea_agent --- 给 GUI 加 ConfigDialog 弹窗：import save_config（第二处）
    from .config import load_config, get_config, save_config, ModelConfig

# ====================== 配置加载 ======================
# 优先使用 $HOME/.tea_agent/config.yaml，不存在时使用 tea_agent/config.yaml
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

# ====================== 从 _gui 子包导入（组合模式） ======================
# NOTE: 2026-05-20 gen by tea_agent, 字体/渲染/摘要从 _gui 子包导入，替代内联定义
from tea_agent._gui._fonts import (
    _fs, _init_fonts, SYSTEM_FONT, MONO_FONT,
    _DEFAULT_FONT_SIZE, _SCALE_FACTOR, _FONTS_DETECTED,
)
# 平台检测（从 _fonts 重导出，保持兼容）
_IS_WINDOWS = __import__('platform').system() == "Windows"

from tea_agent._gui._markdown import (
    _render_markdown, _build_tool_blocks, _render_tool_group,
    _chat_to_markdown, _sanitize_html_control_chars,
    _validate_html_structure, _MD_CSS_TEMPLATE, _KNOWN_HTML_TAGS,
    HAS_TKINTERWEB,
)
from tea_agent._gui._topic_summary import _generate_topic_summary

# 组件委托（composition）
from tea_agent._gui._stream_manager import StreamManager
from tea_agent._gui._topic_manager import TopicManager
from tea_agent._gui._ui_builder import UIBuilder
from tea_agent._gui._tray import TrayManager
from tea_agent._gui._images import ImageHandler
from tea_agent._gui._renderer import ChatRenderer

# Dialogs
from tea_agent.gui_dialogs import MemoryDialog, TopicDialog, ConfigDialog

# NOTE: 2026-06-23 gen by tea_agent, StatusNotifierItem D-Bus 实现（兼容 KDE Plasma 6）
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
            self._app_id = app_id
            self._title = title
            self._icon_data = icon_pixmap_ar32  # ARGB32 bytes
            self._on_activate = on_activate
            self._on_context_menu = on_context_menu
            self._loop = None
            self._thread = None

            # 初始化 D-Bus
            dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
            self._bus = dbus.SessionBus()
            bus_name = dbus.service.BusName(
                f'org.kde.StatusNotifierItem-{app_id.replace(".", "_")}-{os.getpid()}',
                self._bus,
            )
            super().__init__(bus_name, '/StatusNotifierItem')

        @dbus.service.method('org.kde.StatusNotifierItem', in_signature='', out_signature='s')
        def Title(self):
            return self._title

        @dbus.service.method('org.kde.StatusNotifierItem', in_signature='', out_signature='s')
        def Id(self):
            return self._app_id

        @dbus.service.method('org.kde.StatusNotifierItem', in_signature='', out_signature='s')
        def Status(self):
            return 'Active'

        @dbus.service.method('org.kde.StatusNotifierItem', in_signature='', out_signature='s')
        def Category(self):
            return 'ApplicationStatus'

        @dbus.service.method('org.kde.StatusNotifierItem', in_signature='', out_signature='ay')
        def IconPixmap(self):
            # 返回 ARGB32 像素数组
            import struct
            width = 32
            height = 32
            return struct.pack('<ii', width, height) + self._icon_data

        @dbus.service.method('org.kde.StatusNotifierItem', in_signature='', out_signature='')
        def Activate(self, x, y):
            if callable(self._on_activate):
                self._on_activate()

        @dbus.service.method('org.kde.StatusNotifierItem', in_signature='', out_signature='')
        def ContextMenu(self, x, y):
            if callable(self._on_context_menu):
                self._on_context_menu(x, y)

        def start(self):
            """在后台线程启动 GLib main loop"""
            import threading
            self._loop = GLib.MainLoop()

            def run():
                self._loop.run()

            self._thread = threading.Thread(target=run, daemon=True)
            self._thread.start()

        def stop(self):
            if self._loop:
                self._loop.quit()

# NOTE: 2026-05-04 18:47:26, self-evolved by tea_agent --- TkGUI 继承 AgentCore，消除重复代码
class TkGUI(AgentCore):
    def __init__(self, root, debug:bool=False):
        self.root = root
        import os
        self._initial_cwd = os.path.abspath(os.getcwd())  # NOTE: 2026-05-16 gen by tea_agent, 启动时固化完整路径
        self._update_title()  # NOTE: 2026-05-15 gen by tea_agent, 标题含当前目录
        self.root.geometry("1100x850")
        self.root.minsize(900, 600)

        self.sess = None  # 预设，AgentCore._init_session 会创建它

        # ── AgentCore 初始化：配置、目录、Storage/Toolkit、会话 ──
        super().__init__(debug=debug)

        # NOTE: 2026-05-20 gen by tea_agent, 组件委托（composition）
        self.stream_mgr = StreamManager(self)
        self.topic_mgr = TopicManager(self)
        self.ui_builder = UIBuilder(self)

        # @2026-05-15 gen by tea_agent, Composition: 消息渲染器
        self.renderer = ChatRenderer(self)

        # @2026-05-15 gen by tea_agent, Composition: 图片管理器
        self.images = ImageHandler(self)

        # @2026-05-15 gen by tea_agent, Composition: 托盘管理器
        self.tray = TrayManager(self)
        self.tray.start()

        # 暴露给 toolkit 工具函数
        globals()["_storage_"] = self.db
        globals()["tlk"]._toolkit_ = self.toolkit

        # HtmlFrame 缩放级别
        self._zoom_level = 100

        # @2026-05-15 gen by tea_agent, 图片点击放大弹窗
        self._image_cache = []  # list of (base64_data, mime_type)
        # NOTE: 2026-05-20 gen by tea_agent, 原始/渲染视图切换
        self._raw_view = tk.BooleanVar(value=False)  # False=HtmlFrame, True=ScrolledText

        # 聊天消息列表
        self.chat_messages: List[Dict] = []
        # NOTE: 2026-05-15 gen by tea_agent, 待发送图片列表（用户附带的图片路径）
        self._pending_images: List[str] = []
        # NOTE: 2026-05-15 gen by tea_agent, 当前查看的历史轮次索引，None=最新轮
        self._current_round_view: Optional[int] = None
        self._chat_rounds: List[List[Dict]] = []

        # 当前 stream 累积 buffer
        self._stream_buffer = ""
        self._think_buffer = ""  # think/reasoning 内容缓冲区
        # NOTE: 2026-05-08 08:50:00, self-evolved by tea_agent --- 初始化 _pending_console_text 缓冲队列，供 500ms 定时器批量刷新
        self._pending_console_text = []  # (text, tag) 列表

        # 当前对话 ID
        self._current_conversation_id: Optional[int] = None

# NOTE: 2026-05-04 18:59:23, self-evolved by tea_agent --- 移除冗余 _init_session 调用，在 UI 创建后加 status 显示
        # 创建界面
        self._create_ui()
        # NOTE: 2026-07-05 gen by tea_agent, 微调聊天/输入分隔栏位置，确保底部工具栏完整显示
        # NOTE: 2026-07-05 gen by tea_agent, 权重比 3:1 确保底部工具栏完整显示，不再需要 after sash 调整
        if hasattr(self,"sess") and self.sess is not None:
            self.sess.tool_log = self.safe_log_tool

        # 会话已由 AgentCore.__init__ 初始化，这里补状态显示
        cheap_m = self._cfg.cheap_model
        cheap_info = f" | 摘要模型: {cheap_m.model_name}" if cheap_m.model_name else ""
        self._update_status(f"📡 已连接 | 模型: {self._cfg.main_model.model_name}{cheap_info}")

# NOTE: 2026-05-04 17:16:04, self-evolved by tea_agent --- GUI on_closing: 退出时调用 storage.close() 完成 WAL checkpoint + 关闭连接
        # 加载主题
        self.refresh_topics()
        self.auto_new_topic()

# NOTE: 2026-05-15 13:06:43, self-evolved by tea_agent --- 补充托盘初始化代码到 __init__ 结尾
        # 注册窗口关闭回调：退出时正常关闭数据库（WAL checkpoint + close）
        self.root.protocol("WM_DELETE_WINDOW", self.tray._on_closing)

    # NOTE: 2026-05-18 gen by tea_agent, 托盘图标支持（仅显示状态+退出入口，不改变关闭按钮行为）
    def _create_tray_icon(self):
        """动态生成托盘图标图像（32x32 蓝色圆角方块 + TA 字母），返回 PIL Image"""
        size = 32
        img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        # 绘制蓝色圆角背景
        draw.rounded_rectangle([2, 2, size-2, size-2], radius=6, fill=(59, 130, 246, 255))
        # 绘制 "TA" 字母
        try:
            from PIL import ImageFont
            font = ImageFont.truetype("arial.ttf", 14)
        except:
            font = ImageFont.load_default()
        draw.text((6, 6), "TA", fill=(255, 255, 255, 255), font=font)
        return img

    # NOTE: 2026-06-23 gen by tea_agent, 将 RGBA PIL Image 转换为 ARGB32 字节
    def _pil_to_argb32(self, img):
        """PIL RGBA Image -> ARGB32 bytes (用于 StatusNotifierItem IconPixmap)"""
        rgba = img.tobytes()  # R,G,B,A, R,G,B,A, ...
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
            # 在后台线程启动 GLib 事件循环
            self._tray_thread = threading.Thread(
                target=self._sni.run, daemon=True, name="tray-icon"
            )
            self._tray_thread.start()
            logger.info("托盘图标已启动 (StatusNotifierItem)")
        except Exception as e:
            logger.warning(f"初始化托盘图标失败: {e}")

    # NOTE: 2026-06-23 gen by tea_agent, 托盘左键激活：显示/恢复窗口
    def _on_tray_activate(self):
        """托盘图标左键点击：显示/恢复主窗口"""
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    # NOTE: 2026-06-23 gen by tea_agent, 托盘右键弹出菜单
    def _on_tray_context_menu(self, x, y):
        """托盘图标右键：弹出菜单（含退出选项）"""
        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label="退出", command=self._on_closing)
        try:
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()

# NOTE: 2026-05-15 13:07:16, self-evolved by tea_agent --- _on_closing 添加托盘图标清理逻辑
    # NOTE: 2026-05-05, self-evolved by tea_agent --- 退出时正常关闭数据库：WAL checkpoint
    def _on_closing(self):
        """窗口关闭时的清理流程"""
        self._update_status("⏳ 正在清理资源...")
        # NOTE: 2026-05-18 gen by tea_agent, 退出时停止托盘图标
        if HAS_SNI and self._sni:
            try:
                self._sni.stop()
                logger.info("托盘图标已停止")
            except Exception as e:
                logger.warning(f"停止托盘图标失败: {e}")
        # NOTE: 2026-06-19 gen by tea_agent, 退出时停止Dream线程
        try:
            from tea_agent.toolkit.toolkit_subconscious import toolkit_subconscious
            toolkit_subconscious("stop")
            logger.info("Dream 已停止")
        except Exception as e:
            logger.warning(f"停止 Dream 失败: {e}")
        # NOTE: 2026-05-16 gen by tea_agent, 退出时停止定时任务调度器
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

    # NOTE: 2026-06-19 gen by tea_agent, App启动自动启动Dream潜意识引擎
    def _start_dream(self):
        """启动Dream潜意识引擎后台线程，每小时循环一次"""
        # 确保 cwd 为项目根目录，使 _is_tea_agent_cwd() 检查通过
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

    # NOTE: 2026-05-16 gen by tea_agent, App启动自动启动定时任务调度器
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
        if not HAS_TKINTERWEB or self._show_mode != "chat_view":
            return "break"
        self._zoom_level = min(self._zoom_level + 10, 200)
        self._apply_zoom()
        self._update_status(f"🔍 缩放: {self._zoom_level}%")
        return "break"

    def zoom_out(self, e=None):
        if not HAS_TKINTERWEB or self._show_mode != "chat_view":
            return "break"
        self._zoom_level = max(self._zoom_level - 10, 50)
        self._apply_zoom()
        self._update_status(f"🔍 缩放: {self._zoom_level}%")
        return "break"

    def _apply_zoom(self):
        if not HAS_TKINTERWEB or not self._filtered_messages():
            return
        self._image_cache.clear()
        md = _chat_to_markdown(self._filtered_messages(), image_cache=self._image_cache)
        font_size = int(_DEFAULT_FONT_SIZE * self._zoom_level / 100)
        html = _render_markdown(md, font_size=font_size)
        self._html_render(html)
        self.root.after(200, self.scroll_to_bottom)

# NOTE: 2026-05-01 10:38:17, self-evolved by tea_agent --- 在 _switch_display 之后添加 _show_loading 方法（简单 spinner + 三点动画）
    # NOTE: 2026-05-17 gen by tea_agent, Alt+Up/Down 切换历史轮次
    def _history_prev_round(self, e=None):
        """Alt+Up: 切换到上一条历史轮次，若无则忽略"""
        if not HAS_TKINTERWEB or self._show_mode != "chat_view":
            return "break"
        rounds = self._chat_rounds
        if not rounds:
            return "break"
        curr = self._current_round_view
        if curr is None:
            # 当前在最新轮，跳到最后一轮
            self._current_round_view = len(rounds) - 1
        elif curr <= 0:
            # 已在第一轮，忽略
            return "break"
        else:
            self._current_round_view = curr - 1
        self._render_round_view(self._current_round_view)
        return "break"

    def _history_next_round(self, e=None):
        """Alt+Down: 切换到下一条历史轮次，若无则忽略"""
        if not HAS_TKINTERWEB or self._show_mode != "chat_view":
            return "break"
        rounds = self._chat_rounds
        if not rounds:
            return "break"
        curr = self._current_round_view
        if curr is None:
            # 当前在最新轮，忽略（已是最新，无"下一条"）
            return "break"
        if curr >= len(rounds) - 1:
            # 已在最后一轮，回到最新轮
            self._current_round_view = None
            self._render_and_show_chat()
        else:
            self._current_round_view = curr + 1
            self._render_round_view(self._current_round_view)
        return "break"

# @2026-05-15 gen by tea_agent, Composition: moved to ChatRenderer → def _switch_display(self, mode: str):

# NOTE: 2026-05-07 14:25:13, self-evolved by tea_agent --- _show_loading 支持动态进度文本 + switch_topic 中后台线程上报加载进度，GUI 不卡死
    # NOTE: 2026-05-01, self-evolved by tea_agent --- _show_loading: HtmlFrame spinner动画，异步加载历史时不再长时间空白
    # NOTE: 2026-05-07 gen by tea_agent, _show_loading 支持 progress 参数动态更新进度文本
# @2026-05-15 gen by tea_agent, Composition: moved to ChatRenderer → def _show_loading(self, text: str = "正在加载历史记录", progress: str = None):
# NOTE: 2026-05-07 14:45:26, self-evolved by tea_agent --- 新增 _poll_loading_progress 方法：50ms 轮询共享变量，仅变化时 load_html
        # 不调用 root.update()：让 CSS animation 自己跑，GUI 主循环保持响应

# NOTE: 2026-05-07 14:48:15, self-evolved by tea_agent --- _poll_loading_progress 改为从队列逐条出队，确保每个进度都被渲染
# NOTE: 2026-05-07 14:49:37, self-evolved by tea_agent --- 轮询器：队列排空且 _loading_done 时触发 _render_loaded_topic 或 _render_topic_error
# @2026-05-15 gen by tea_agent, Composition: moved to ChatRenderer → def _poll_loading_progress(self):

# @2026-05-15 gen by tea_agent, Composition: moved to ChatRenderer → def scroll_to_bottom(self):

    # 2026-05-11 gen by tea_agent, 将 render 到 HtmlFrame 的 HTML 同时 print 到终端
# NOTE: 2026-05-14 16:00:34, self-evolved by tea_agent --- _html_render 增加渲染前校验：控制字符清洗 + 结构检查 + 自动修复缺失闭合标签
    # NOTE: 2026-05-15 gen by tea_agent, 注释掉终端打印避免刷屏，调试时可取消注释
    # NOTE: 2026-05-16 gen by tea_agent, 渲染前增加 HTML 校验与清洗：控制字符过滤 + 标签配对检查 + 自动修复
# @2026-05-15 gen by tea_agent, Composition: moved to ChatRenderer → def _html_render(self, html: str):

# NOTE: 2026-05-07 17:33:05, self-evolved by tea_agent --- _render_chat 支持可选的流式缓冲区参数，_stream_render_tick 传递当前 think/stream 内容
# @2026-05-15 gen by tea_agent, Composition: moved to ChatRenderer → def _render_chat(self, streaming_think: str = "", streaming_text: str = ""):

    def _now_ts(self) -> str:
        return datetime.now().strftime("%H:%M:%S")

# NOTE: 2026-05-04 18:48:10, self-evolved by tea_agent --- _init_session 继承 AgentCore，仅补 UI 回调
# NOTE: 2026-05-04 18:58:17, self-evolved by tea_agent --- GUI _init_session 调用 super() 确保 sess 被创建
# NOTE: 2026-05-04 18:58:47, self-evolved by tea_agent --- _init_session 只设 tool_log，status 移到 UI 创建后
    def _init_session(self):
        """GUI 的会话初始化 — 继承 AgentCore 创建 sess。"""
        super()._init_session()

    def toggle_reasoning(self, enable: Optional[bool] = None) -> dict:
        """切换或查询 reasoning/thinking 状态。供 toolkit 工具调用。"""
        if self.sess is None:
            return {"error": "无活跃会话"}
        if enable is None:
            return {"enable_thinking": self.sess.enable_thinking}
        self.sess.enable_thinking = bool(enable)
        state = "开启" if enable else "关闭"
        self._update_status(f"🧠 Reasoning 已{state}")
        return {"enable_thinking": self.sess.enable_thinking, "changed": True}

    def _update_status(self, msg: str):
        """更新状态栏"""
        if hasattr(self, 'status_var'):
            self.status_var.set(msg)

    def safe_stream(self, text):
        """线程安全的流式输出 — 委托 StreamManager"""
        self.stream_mgr.safe_stream(text)

    def safe_log(self, msg, tag="ai"):
        """线程安全的日志输出 — 委托 StreamManager"""
        self.stream_mgr.safe_log(msg, tag)

    def safe_log_tool(self, msg: str):
        """线程安全的工具日志 — 委托 StreamManager"""
        self.stream_mgr.safe_log_tool(msg)

    def safe_update_status(self, msg: str):
        """线程安全的状态更新 — 委托 StreamManager"""
        self.stream_mgr.safe_update_status(msg)

    def _handle_max_iter(self, msg: str):
        """处理最大迭代次数 — 委托 StreamManager"""
        self.stream_mgr.handle_max_iter(msg)

    def log(self, msg, tag="ai", images=None):
        """输出日志到控制台 — 委托 StreamManager"""
        self.stream_mgr.log(msg, tag, images)

    def stream(self, text):
        """流式输出 — 委托 StreamManager"""
        self.stream_mgr.stream(text)

    def log_tool(self, msg: str):
        """工具日志 — 委托 StreamManager"""
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
        """更新窗口标题"""
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
        """切换主题 — 委托 TopicManager"""
        self.topic_mgr.switch_topic(topic_id)

    def on_topic_select(self, e):
        """主题选择回调 — 委托 TopicManager"""
        self.topic_mgr.on_topic_select(e)

    def newline(self, e=None):
        """插入换行 — 委托 TopicManager"""
        return self.topic_mgr.newline(e)

    def _suggest_new_topic_if_needed(self, topic_id: str):
        """建议新建主题 — 委托 TopicManager"""
        self.topic_mgr._suggest_new_topic_if_needed(topic_id)

    def _on_summary_updated(self, topic_id: str, summary: str):
        """摘要更新回调 — 委托 TopicManager"""
        self.topic_mgr._on_summary_updated(topic_id, summary)

    def _refresh_topics_preserve_selection(self):
        """刷新主题列表保持选择 — 委托 TopicManager"""
        self.topic_mgr._refresh_topics_preserve_selection()

    def _on_topic_hover(self, event):
        """主题悬停 — 委托 TopicManager"""
        self.topic_mgr._on_topic_hover(event)

    def _on_topic_leave(self, event):
        """主题离开 — 委托 TopicManager"""
        self.topic_mgr._on_topic_leave(event)

    def _show_tooltip(self, event, idx):
        """显示工具提示 — 委托 TopicManager"""
        self.topic_mgr._show_tooltip(event, idx)

    def _hide_tooltip(self):
        """隐藏工具提示 — 委托 TopicManager"""
        self.topic_mgr._hide_tooltip()

    def _notify_completion(self, ai_msg: Optional[str] = None, user_msg: Optional[str] = None):
        """LLM 任务完成后发送桌面通知。通知内容: TeaAgent: {user_msg} + {ai_msg}。
        委托给 toolkit_notify（跨平台兼容：Windows/macOS/Linux）。"""
        # 构建通知消息：TeaAgent: {user_msg} + {ai_msg}
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
            # 直接导入 toolkit_notify 以复用其跨平台实现
            from tea_agent.toolkit.toolkit_notify import toolkit_notify
            toolkit_notify("TeaAgent", notification_msg, urgency="normal", duration=5000)
        except Exception:
            pass  # 通知失败不影响主流程

# NOTE: 2026-05-04 19:35:31, self-evolved by tea_agent --- GUI send() 入口加 _shutting_down 闸门 — 重启中拒绝新消息
    # NOTE: 2026-05-15 gen by tea_agent, 图片附件支持：选择图片文件并暂存
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
        # 确保 tmp/images 目录存在
        img_dir = os.path.join(self._initial_cwd, "tmp", "images")
        os.makedirs(img_dir, exist_ok=True)
        for f in files:
            # 复制到 tmp/images 目录（避免原始文件被移动/删除）
            basename = os.path.basename(f)
            dest = os.path.join(img_dir, basename)
            # 如果同名文件存在，添加序号
            if os.path.exists(dest):
                name, ext = os.path.splitext(basename)
                counter = 1
                while os.path.exists(os.path.join(img_dir, f"{name}_{counter}{ext}")):
                    counter += 1
                dest = os.path.join(img_dir, f"{name}_{counter}{ext}")
            shutil.copy2(f, dest)
            self._pending_images.append(dest)
        # 更新标签显示
        count = len(self._pending_images)
        self._img_label.config(text=f"已选 {count} 张图片")
        self._clear_img_btn.pack(side=tk.LEFT, padx=4)

    # NOTE: 2026-05-15 gen by tea_agent, 清除已选图片
    def _clear_images(self):
        """清空待发送图片列表"""
        self._pending_images.clear()
        self._img_label.config(text="")

    # NOTE: 2026-05-20 gen by tea_agent, 切换 HtmlFrame / ScrolledText 视图
# @2026-05-15 gen by tea_agent, Composition: moved to ChatRenderer → def _toggle_raw_view(self):

# @2026-05-15 gen by tea_agent, Composition: moved to ChatRenderer → def _show_raw_check_btn(self):

# @2026-05-15 gen by tea_agent, Composition: moved to ChatRenderer → def _hide_raw_check_btn(self):

    def send(self, e=None):
        if self._shutting_down:
            self._update_status("🔄 代码已变更，等待重启...")
            return "break"
        if self.generating or not self.current_topic_id:
            return "break"
        msg = self.input_box.get("1.0", tk.END).strip()
        # 允许仅有图片无文本的情况
        images = list(self._pending_images)
        self.images.clear()  # 发送后清空
        if not msg and not images:
            return "break"
        self.input_box.delete("1.0", tk.END)

        self._switch_display("console")

        # NOTE: 2026-05-15 gen by tea_agent, 支持图片附件
        display_msg = f"你：{msg}" if msg else "你：[图片]"
        self.log(display_msg, "user", images=images if images else None)
        self._hide_raw_check_btn()  # 会话中隐藏切换按钮
        self.generating = True
        # 启动 500ms 定时器，批量刷新流式内容到 ScrolledText（不渲染 HtmlFrame）
        # NOTE: 2026-05-08 08:46:00, self-evolved by tea_agent --- 流式输出启动 _stream_flush_tick 500ms 定时器
        self.root.after(500, self._stream_flush_tick)
        self.log("AI：", "ai")

        mem_count = len(self.db.get_active_memories(50))
        self._update_status(f"⏳ 生成中... (ESC 打断) | 🧠 {mem_count}")

        # NOTE: 2026-05-15 gen by tea_agent, 构建含图片的消息传给 chat_stream
        chat_input = {"text": msg} if not images else {"text": msg, "images": images}

        def work():
            try:
                ai_msg, is_func = self.sess.chat_stream(
                    chat_input, 
                    callback=self.safe_stream,
                    topic_id=self.current_topic_id,
                    on_status=self.safe_update_status,
                )
# NOTE: 2026-05-18 14:05:48, self-evolved by tea_agent --- 修复HTML渲染延迟15s+：将_render_and_show_chat提前到_post_chat_pipeline之前
                self.root.after(0, self._flush_stream_to_messages)

                # NOTE: 2026-05-18 gen by tea_agent, 修复渲染延迟15s+：提前调度 HTML 渲染
                # 原逻辑在 _post_chat_pipeline 之后才渲染，_auto_summary 等 API 调用阻塞渲染调度
                self.root.after(0, self._render_and_show_chat)
                self.root.after(0, self._show_raw_check_btn)

                # ── 标准后处理流水线（入库 → Token → 摘要）──
                # NOTE: 2026-05-15 gen by tea_agent, 传入图片信息用于入库
                user_msg_for_db = msg if not images else {"text": msg, "images": images}
                self._post_chat_pipeline(ai_msg, is_func, user_msg_for_db, self.current_topic_id)

                # GUI 特定：token 渲染 + 通知
                usage = self.sess._last_usage
                cheap_usage = self.sess._last_cheap_usage
# NOTE: 2026-05-07 13:14:48, self-evolved by tea_agent --- 完成状态栏消息增加嵌入模型 token (Emb:xxx)
                if usage and usage.get("total_tokens", 0) > 0:
                    self.root.after(0, lambda u=usage, cu=cheap_usage: self._add_token_notice_and_render(u, cu))
                    # 读取嵌入模型用量
                    emb_str = ""
                    try:
                        from tea_agent.embedding_util import get_embedding_engine
                        euse = get_embedding_engine().get_embedding_usage(reset=False)
                        if euse.get("total_tokens", 0) > 0:
                            emb_str = f" | Emb:{euse['total_tokens']:,}"
                    except Exception:
                        pass
                    status_msg = (f"✅ 完成 | Tokens: {usage['total_tokens']:,} "
                                  f"(P:{usage['prompt_tokens']:,} C:{usage['completion_tokens']:,}){emb_str}")
                    self.root.after(0, lambda m=status_msg: self._update_status(m))
                    self.root.after(0, self._refresh_topics_preserve_selection)
# NOTE: 2026-05-06 09:31, self-evolved by tea_agent --- 通知传入 user_msg，显示用户消息+AI回复
                    self.root.after(600, lambda am=ai_msg, um=msg: self._notify_completion(am, um))
# NOTE: 2026-05-18 14:06:01, self-evolved by tea_agent --- 移除else分支中重复的_render_and_show_chat调用（已提前调度）
                else:
                    # NOTE: 2026-05-18 gen by tea_agent, 渲染已提前调度，此处仅更新状态
                    self.root.after(0, lambda: self._update_status("✅ 完成"))
# NOTE: 2026-05-06 09:31, self-evolved by tea_agent --- 通知传入 user_msg，显示用户消息+AI回复
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
# NOTE: 2026-05-06 09:31, self-evolved by tea_agent --- 异常时通知也传入 user_msg
                self.root.after(600, lambda am=ai_msg, um=msg: self._notify_completion(am, um))
            finally:
                self.generating = False
                self.safe_log("")

        threading.Thread(target=work, daemon=True).start()
        return "break"

# NOTE: 2026-04-30 09:12:24, self-evolved by tea_agent --- 新增 _add_token_notice_and_render 方法，在聊天区域显示本轮token消耗
# NOTE: 2026-04-30 09:13:24, self-evolved by tea_agent --- 简化token显示格式，修复括号配对问题
# NOTE: 2026-04-30 09:15:53, self-evolved by tea_agent --- token通知增加当前主题累积消耗显示
# NOTE: 2026-04-30 09:26:32, self-evolved by tea_agent --- _add_token_notice_and_render改为Markdown表格(主模型+便宜模型，本轮+主题累积)
# NOTE: 2026-05-07 13:14:07, self-evolved by tea_agent --- _add_token_notice_and_render 表格新增嵌入模型列：本轮 reading + 主题累积 te_total/te_p
    def _add_token_notice_and_render(self, usage: dict, cheap_usage: dict = None):
        """在聊天消息中追加 Markdown 表格：本轮/主题累积 × 主模型/便宜模型/嵌入模型 token 消耗"""
        if cheap_usage is None:
            cheap_usage = {}
        # 本轮：主模型
        m_total = usage.get("total_tokens", 0)
        m_p = usage.get("prompt_tokens", 0)
        m_c = usage.get("completion_tokens", 0)
        # 本轮：便宜模型
        c_total = cheap_usage.get("total_tokens", 0)
        c_p = cheap_usage.get("prompt_tokens", 0)
        c_c = cheap_usage.get("completion_tokens", 0)
        # 嵌入模型 token 用量（从 EmbeddingEngine 读取本轮）
        e_total = 0
        e_p = 0
        try:
            from tea_agent.embedding_util import get_embedding_engine
            emb_engine = get_embedding_engine()
            emb_usage = emb_engine.get_embedding_usage(reset=False)  # 已在 _post_chat_pipeline reset
            e_total = emb_usage.get("total_tokens", 0)
            e_p = emb_usage.get("prompt_tokens", 0)
        except Exception:
            pass
        # 主题累积
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

# NOTE: 2026-04-30 09:27:37, self-evolved by tea_agent --- _cell()中去掉<br>改用空格，保证Markdown表格兼容性
# NOTE: 2026-05-07 13:18:26, self-evolved by tea_agent --- _cell 支持只有 P 无 C 的场景（嵌入模型），显示 total (P:xxx)
        def _cell(val, detail_p=None, detail_c=None):
            """格式化为 'total (P:x C:y)' 或 'total (P:x)' 或 '—'"""
            if val <= 0:
                return "—"
            if detail_p is not None and detail_c is not None:
                return f"{val:,} (P:{detail_p:,} C:{detail_c:,})"
            if detail_p is not None:
                return f"{val:,} (P:{detail_p:,})"
            return f"{val:,}"

# NOTE: 2026-05-07 13:14:18, self-evolved by tea_agent --- Token 表格新增嵌入模型列
        lines = [
            "| | 主模型 | 便宜模型 | 嵌入模型 |",
            "|-------|--------|----------|----------|",
            f"| 本轮 | {_cell(m_total, m_p, m_c)} | {_cell(c_total, c_p, c_c)} | {_cell(e_total, e_p)} |",
            f"| 主题 | {_cell(tm_total, tm_p, tm_c)} | {_cell(tc_total, tc_p, tc_c)} | {_cell(te_total, te_p)} |",
        ]
        token_msg = "\n".join(lines)
        self.chat_messages.append({"role": "notice", "content": token_msg, "timestamp": self._now_ts()})
        self._render_and_show_chat()
        self._show_raw_check_btn()

    # NOTE: 2026-05-16 gen by tea_agent, 工具轮始终显示：移除过滤逻辑，每次render显示全部消息
# @2026-05-15 gen by tea_agent, Composition: moved to ChatRenderer → def _filtered_messages(self):

    # NOTE: 2026-05-15 gen by tea_agent, 历史轮次分组：按 user 消息切分轮次
# @2026-05-15 gen by tea_agent, Composition: moved to ChatRenderer → def _group_into_rounds(self, msgs):

    # NOTE: 2026-05-15 gen by tea_agent, HtmlFrame 历史链接 + 图片点击回调
    def _on_history_link_click(self, url):
        """处理 tea://round/N 或 tea://latest 或 tea://image/N 链接点击，外部链接用系统浏览器打开"""
        try:
            # NOTE: 2026-05-18 gen by tea_agent, 外部链接用系统默认浏览器打开
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

    # @2026-05-15 gen by tea_agent, 图片点击放大弹窗
    def _show_image_popup(self, idx):
        """点击聊天图片时弹出放大查看窗口。点击图片或按 Esc 关闭。"""
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

    # NOTE: 2026-05-15 gen by tea_agent, 构建轮次视图完整 HTML
# @2026-05-15 gen by tea_agent, Composition: moved to ChatRenderer → def _build_round_view_html(self, rounds, active_idx, font_size):

    # NOTE: 2026-05-15 gen by tea_agent, 渲染指定历史轮次（用户点击链接时调用）
# @2026-05-15 gen by tea_agent, Composition: moved to ChatRenderer → def _render_round_view(self, round_idx):

    # NOTE: 2026-05-15 gen by tea_agent, 重构：渲染最新轮 + 历史轮次链接表
# @2026-05-15 gen by tea_agent, Composition: moved to ChatRenderer → def _render_and_show_chat(self):

    # @2026-04-29 gen by deepseek-v4-pro, 打开主题管理弹窗
    def open_topic_dialog(self):
        """打开主题管理弹窗"""
        TopicDialog(self.root, self.db,
                    on_switch=lambda tid: self.root.after(0, self.switch_topic, tid))

# NOTE: 2026-05-01 15:33:25, self-evolved by tea_agent --- 添加 TkGUI.open_config_dialog 方法（紧挨 open_memory_dialog）
    def open_memory_dialog(self):
        """打开记忆管理对话框"""
        MemoryDialog(self.root, self.db)

    def open_config_dialog(self):
        """打开配置编辑对话框"""

        def on_save(cfg):
            # 同步到当前 session
            if hasattr(self, 'sess') and self.sess:
                for key in cfg._RUNTIME_CONFIG_KEYS:
                    val = getattr(cfg, key, None)
                    if val is not None and hasattr(self.sess, key):
                        try:
                            setattr(self.sess, key, val)
                        except Exception:
                            pass
            self._update_status("⚙️ 配置已更新")

        ConfigDialog(self.root, on_save=on_save)

    def interrupt(self, e=None):
        if self.generating:
            self.sess.interrupt()
            self.safe_log("\n🛑 已打断", "tool")
            self.generating = False
            # 先刷新控制台剩余内容，再 flush 到 messages
            # NOTE: 2026-05-08 08:46:00, self-evolved by tea_agent --- interrupt 时也刷新 pending 控制台内容
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

# NOTE: 2026-04-30 19:36:28, self-evolved by tea_agent --- 补回缺失的 __main__ 入口，使 python -m tea_agent.main_db_gui 可正常启动 GUI
# NOTE: 2026-05-09 19:26:36, self-evolved by tea_agent --- 修复 main() no_gui 模式：用 CLI 回退替代 NotImplementedError 崩溃
    # ═══ @2026-05-15 gen by tea_agent, Composition 委派包装器 ═══

    def _switch_display(self, mode: str):
        return self.renderer._switch_display(mode)

    def _show_loading(self, text: str = "正在加载历史记录", progress: str = None):
        return self.renderer._show_loading(text, progress)

    def _poll_loading_progress(self):
        return self.renderer._poll_loading_progress()

    def scroll_to_bottom(self):
        return self.renderer.scroll_to_bottom()

    def _html_render(self, html: str):
        return self.renderer._html_render(html)

    def _render_chat(self, streaming_think: str = "", streaming_text: str = ""):
        return self.renderer._render_chat(streaming_think, streaming_text)

    def _render_and_show_chat(self):
        return self.renderer._render_and_show_chat()

    def _render_loaded_topic(self, render_items):
        return self.renderer._render_loaded_topic(render_items)

    def _render_round_view(self, round_idx: int):
        return self.renderer._render_round_view(round_idx)

    def _render_topic_error(self, error_msg: str):
        return self.renderer._render_topic_error(error_msg)

    def _build_round_view_html(self, rounds, active_idx, font_size):
        return self.renderer._build_round_view_html(rounds, active_idx, font_size)

    def _filtered_messages(self):
        return self.renderer._filtered_messages()

    def _group_into_rounds(self, msgs):
        return self.renderer._group_into_rounds(msgs)

    def _flush_stream_to_messages(self):
        return self.renderer._flush_stream_to_messages()

    def _flush_think_buffer_to_messages(self):
        return self.renderer._flush_think_buffer_to_messages()

    def _toggle_raw_view(self):
        return self.renderer._toggle_raw_view()

    def _show_raw_check_btn(self):
        return self.renderer._show_raw_check_btn()

    def _hide_raw_check_btn(self):
        return self.renderer._hide_raw_check_btn()

# NOTE: 2026-05-20 gen by tea_agent, 添加 timeout 参数支持 debug 模式超时自动退出
def main(debug:bool=False, no_gui:bool=False, timeout:int=0):
    """启动 GUI 主界面。
    
    Args:
        debug: 调试模式
        no_gui: 回退到 CLI 模式
        timeout: 超时秒数，超时后自动关闭窗口（0=不超时，用于自动化测试）
    """
    if no_gui:
        # 回退到 CLI 模式
        from tea_agent.tea_main_cli import main as cli_main
        cli_main()
        return
    
    root = tk.Tk()
    app = TkGUI(root, debug=debug)
    
    if timeout > 0:
        logger.info(f"GUI debug timeout set: {timeout}s, will auto-close")
        root.after(timeout * 1000, lambda: _safe_destroy(root))
    
    root.mainloop()

def _safe_destroy(root):
    """安全销毁 Tk 窗口，捕获可能的异常。"""
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
    ap.add_argument("--no-gui", action="store_true", help="回退到 CLI 模式")
    ap.add_argument("--timeout", type=int, default=0,
                    help="超时秒数，超时后自动关闭（用于自动化测试）")
    args = ap.parse_args()
    main(debug=args.debug, no_gui=args.no_gui, timeout=args.timeout)
