# ── Windows DPI 感知：必须在 tkinter 导入前设置 ──
# mss 库会在截图时调用 SetProcessDpiAwareness(2)，如果 GUI 未提前设置，
# 会导致 Windows 停止位图缩放，GUI 字体突然变小。
# 这里抢先设置为 Per-Monitor DPI Aware，避免中途被 mss 改变。
import sys as _sys
if _sys.platform == "win32":
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass

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
from typing import Optional, Dict, cast, Callable, List, Tuple
import logging
import webbrowser

try:
    from tkinterweb import HtmlFrame
    import markdown
    HAS_TKINTERWEB = True
except ImportError:
    HAS_TKINTERWEB = False


logger = logging.getLogger(__name__)

# ====================== 包导入兼容处理 ======================
if __name__ == "__main__":
    parent_dir = str(Path(__file__).resolve().parent.parent)
    if parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)
    from tea_agent.onlinesession import OnlineToolSession
    from tea_agent.store import Storage
    from tea_agent import tlk
    from tea_agent.agent import Agent

    from tea_agent._gui._tray import TrayManager
    from tea_agent._gui._images import ImageHandler
    from tea_agent._gui._renderer import ChatRenderer
    from tea_agent.config import load_config, get_config, save_config, ModelConfig, set_active_config_path
else:
    from .onlinesession import OnlineToolSession
    from .store import Storage
    from . import tlk
    from .agent import Agent
    from tea_agent._gui._tray import TrayManager
    from tea_agent._gui._images import ImageHandler
    from tea_agent._gui._renderer import ChatRenderer
    from .config import load_config, get_config, save_config, ModelConfig

# ====================== 模块级引用（供 toolkit 通过 globals() 访问） ======================
_storage_ = None
_toolkit_ = None
# ====================== 从 _gui 子包导入（组合模式） ======================
from tea_agent._gui._fonts import (
    _fs, _init_fonts, SYSTEM_FONT, MONO_FONT,
    _SCALE_FACTOR, _FONTS_DETECTED,
)
import tea_agent._gui._fonts as _fonts_mod  # 模块引用，动态获取 _DEFAULT_FONT_SIZE
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
class TkGUI(Agent):
    """TkGUI class."""
    # 窗口大小常量
    WINDOW_DEFAULT_SIZE = "1440x960"
    WINDOW_MIN_SIZE = (960, 720)
    
    # 延迟常量（毫秒）
    STREAM_FLUSH_INTERVAL_MS = 500  # 流式刷新间隔
    RENDER_DELAY_MS = 200           # 渲染延迟
    NOTIFY_DELAY_MS = 600           # 通知延迟
    
    def __init__(self, root, debug:bool=False, config_fname:str="", disable_summary:bool=False, no_stream_chunk:bool=False):
        self.root = root
        import os
        self._initial_cwd = os.path.abspath(os.getcwd())
        self._update_title()
        self.root.geometry(self.WINDOW_DEFAULT_SIZE)
        self.root.minsize(*self.WINDOW_MIN_SIZE)
        
        # 线程安全的 generating 状态
        self._generating_lock = threading.Lock()
        self._generating = False

        self.sess = None  # 预设，Agent._init_session 会创建它

        # ── Agent 初始化：配置、目录、Storage/Toolkit、会话 ──
        super().__init__(mode="full", debug=debug, config_path=config_fname,
                         enable_thinking=True, disable_summary=disable_summary,
                         no_stream_chunk=no_stream_chunk)

        self.stream_mgr = StreamManager(self)
        self.topic_mgr = TopicManager(self)
        self.ui_builder = UIBuilder(self)

        self.renderer = ChatRenderer(self)

        self.images = ImageHandler(self)

        self.tray = TrayManager(self)
        self.tray.start()

        # 初始化字体缩放（必须在 UI 构建前调用）
        _init_fonts()

        # 暴露给 toolkit 工具函数
        globals()["_storage_"] = self.db
        globals()["tlk"]._toolkit_ = self.toolkit

        # HtmlFrame 缩放级别
        self._zoom_level = 100

        self._image_cache = []  # list of (base64_data, mime_type)
        self._raw_view = tk.BooleanVar(value=False)  # False=HtmlFrame, True=ScrolledText

        # 聊天消息列表
        self.chat_messages: List[Dict] = []
        self._pending_images: List[str] = []
        self._current_round_view: Optional[int] = None
        self._chat_rounds: List[List[Dict]] = []

        # 当前 stream 累积 buffer
        self._stream_buffer = ""
        self._think_buffer = ""  # think/reasoning 内容缓冲区
        self._pending_console_text = []  # (text, tag) 列表
        # 当前对话 ID
        self._current_conversation_id: Optional[int] = None
        
        # 显示模式："console" 或 "chat_view"
        self._show_mode = "console"
        
        # 主题列表相关状态
        self._topic_cache: List[Dict] = []
        self._topic_hover_after = None
        self._topic_tooltip = None
        
        # 加载状态
        self._progress_queue: List[tuple] = []
        self._loading_done = False
        self._pending_render: Optional[List] = None
        self._pending_error: Optional[str] = None

        # 创建界面
        self._create_ui()
        if hasattr(self,"sess") and self.sess is not None:
            self.sess.tool_log = self.safe_log_tool

        # 会话已由 AgentCore.__init__ 初始化，这里补状态显示
        cheap_m = self._cfg.cheap_model
        cheap_info = f" | 摘要模型: {cheap_m.model_name}" if cheap_m.model_name else ""
        self._update_status(f"📡 已连接 | 模型: {self._cfg.main_model.model_name}{cheap_info}")

        # 加载主题
        self.refresh_topics()
        self.auto_new_topic()
        # 延迟加载配置列表（等 UI 完全构建后）
        self.root.after(500, self._refresh_config_list)
        # 注册窗口关闭回调：退出时正常关闭数据库（WAL checkpoint + close）
        self.root.protocol("WM_DELETE_WINDOW", self.tray._on_closing)
        # Ctrl+F 搜索快捷键
        self.root.bind("<Control-f>", lambda e: self.open_search_dialog())
        self.root.bind("<Control-F>", lambda e: self.open_search_dialog())

    @property
    def generating(self):
        """线程安全的 generating 状态访问"""
        with self._generating_lock:
            return self._generating

    @generating.setter
    def generating(self, value):
        """线程安全的 generating 状态设置"""
        with self._generating_lock:
            self._generating = value

    def _start_dream(self):
        """启动Dream潜意识引擎后台线程，每小时循环一次"""
        # 确保 cwd 为项目根目录，使 _is_tea_agent_cwd() 检查通过
        _proj_root = str(Path(__file__).resolve().parent.parent)
        try:
            os.chdir(_proj_root)
        except Exception:
            logger.exception("operation failed")

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

    def _create_ui(self):
        """创建界面 — 委托给 UIBuilder"""
        self.ui_builder.build()
    def zoom_in(self, e=None):
        """放大 HtmlFrame 渲染内容"""
        if not HAS_TKINTERWEB or self._show_mode != "chat_view":
            return "break"
        self._zoom_level = min(self._zoom_level + 10, 200)
        self._apply_zoom()
        self._update_status(f"🔍 缩放: {self._zoom_level}%")
        return "break"

    def zoom_out(self, e=None):
        """缩小 HtmlFrame 渲染内容"""
        if not HAS_TKINTERWEB or self._show_mode != "chat_view":
            return "break"
        self._zoom_level = max(self._zoom_level - 10, 50)
        self._apply_zoom()
        self._update_status(f"🔍 缩放: {self._zoom_level}%")
        return "break"
    def _apply_zoom(self):
        """应用缩放级别到 HtmlFrame"""
        if not HAS_TKINTERWEB or not self._filtered_messages():
            return
        self._image_cache.clear()
        md = _chat_to_markdown(self._filtered_messages(), image_cache=self._image_cache)
        # HtmlFrame使用独立的字体大小，不受配置影响
        font_size = int(_fonts_mod._HTML_FONT_SIZE * self._zoom_level / 100)
        html = _render_markdown(md, font_size=font_size)
        self._html_render(html)
        self.root.after(self.RENDER_DELAY_MS, self.scroll_to_bottom)

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


    def _now_ts(self) -> str:
        """Internal: now ts."""
        return datetime.now().strftime("%H:%M:%S")

    def _init_session(self):
        """GUI 的会话初始化 — 继承 AgentCore 创建 sess。"""
        super()._init_session()

    def toggle_reasoning(self, enable: Optional[bool] = None) -> dict:
        """切换或查询 reasoning/thinking 状态。供 toolkit 工具调用。线程安全版。"""
        # 捕获 sess 到本地变量
        sess = self.sess
        if sess is None:
            return {"error": "无活跃会话"}
        if enable is None:
            return {"enable_thinking": sess.enable_thinking}
        sess.enable_thinking = bool(enable)
        state = "开启" if enable else "关闭"
        self._update_status(f"🧠 Reasoning 已{state}")
        return {"enable_thinking": sess.enable_thinking, "changed": True}

    def export_last_pdf(self, e=None):
        """Ctrl+P: 导出当前 HtmlFrame 中渲染的轮次为 last.pdf（支持 Alt+Up/Down 切换轮次）"""
        import json, tempfile, subprocess
        
        # 捕获必要的状态到本地变量，避免 worker 线程与主线程竞争
        chat_rounds = list(self._chat_rounds)  # 复制列表
        current_round_view = self._current_round_view
        zoom_level = self._zoom_level
        
        def _do():
            try:
                # ── 优先使用内存中当前渲染的轮次（与 HtmlFrame 一致）──
                rounds = chat_rounds
                if not rounds:
                    self._update_status("⚠️ 无对话记录")
                    return

                cur_view = current_round_view
                if cur_view is None:
                    # 最新轮
                    active_idx = len(rounds) - 1
                else:
                    active_idx = max(0, min(cur_view, len(rounds) - 1))

                msgs = rounds[active_idx]

                # ── 渲染为 HTML ──
                from tea_agent._gui._markdown import _chat_to_markdown, _render_markdown
                self._image_cache.clear()
                md = _chat_to_markdown(msgs, image_cache=self._image_cache)
                font_size = int(_fonts_mod._HTML_FONT_SIZE * zoom_level / 100)
                html = _render_markdown(md, font_size=font_size)

                # ── 写临时 HTML ──
                tmp = tempfile.NamedTemporaryFile(suffix=".html", delete=False, mode="w", encoding="utf-8")
                tmp.write(html)
                tmp.close()

                # ── Playwright 无头转 PDF（跨平台，Windows/Linux/macOS）──
                output = os.path.join(self._initial_cwd, "last.pdf")
                tmp_url = "file:///" + tmp.name.replace("\\", "/")

                pdf_ok = False
                try:
                    from playwright.sync_api import sync_playwright
                    with sync_playwright() as p:
                        browser = p.chromium.launch(headless=True)
                        page = browser.new_page()
                        page.goto(tmp_url, wait_until="networkidle", timeout=15000)
                        page.pdf(path=output, format="A4", print_background=True,
                                  margin={"top": "15mm", "bottom": "15mm", "left": "12mm", "right": "12mm"})
                        browser.close()
                    pdf_ok = True
                    self._update_status(f"✅ 已导出: last.pdf")
                except Exception:
                    # 回退：Windows 下尝试 Edge 无头
                    edge_paths = [
                        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
                    ]
                    edge = None
                    for p in edge_paths:
                        if os.path.exists(p):
                            edge = p
                            break
                    if edge:
                        subprocess.run(
                            [edge, "--headless=new", f"--print-to-pdf={output}",
                             "--no-pdf-header-footer", tmp_url],
                            capture_output=True, text=True, timeout=30,
                        )
                        pdf_ok = True
                        self._update_status(f"✅ 已导出: last.pdf")
                    else:
                        import shutil
                        html_output = os.path.join(self._initial_cwd, "last.html")
                        shutil.copy(tmp.name, html_output)
                        self._update_status(f"⚠️ 无可用浏览器，已保存 HTML: last.html")

                os.unlink(tmp.name)
                
                # 导出成功后打开文件管理器并定位到文件
                if pdf_ok and os.path.exists(output):
                    self._open_file_manager(output)

            except Exception as ex:
                self._update_status(f"❌ 导出失败: {ex}")
                import traceback
                traceback.print_exc()

        threading.Thread(target=_do, daemon=True).start()

    def export_topic_pdf(self, topic_id: str = None, e=None):
        """导出完整主题为 PDF（当前主题或指定主题）"""
        import json, tempfile, subprocess, threading, shutil

        tid = topic_id or self.current_topic_id
        if not tid:
            self._update_status("⚠️ 无主题可导出")
            return

        chat_messages = list(self.chat_messages)
        topic_title = "导出主题"

        # 获取主题标题
        for tp in self._topic_cache:
            if tp.get("topic_id") == tid:
                topic_title = tp.get("title", "导出主题")
                break

        def _do():
            try:
                # ── 用 chat_messages 构建 Markdown ──
                md_parts = [f"# {topic_title}\n\n"]
                md_parts.append(f"> 导出时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                md_parts.append("---\n\n")

                for msg in chat_messages:
                    role = msg.get("role", "")
                    content = msg.get("content", "")
                    if isinstance(content, list):
                        text_parts = []
                        for p in content:
                            if isinstance(p, dict) and p.get("type") == "text":
                                text_parts.append(p.get("text", ""))
                        content = "\n".join(text_parts) if text_parts else str(content)

                    if not isinstance(content, str):
                        content = str(content)

                    if role == "user":
                        md_parts.append(f"## 🧑 用户\n\n{content}\n\n---\n\n")
                    elif role == "assistant":
                        rc = msg.get("reasoning_content", "")
                        if rc:
                            md_parts.append(f"## 🤖 AI (思考过程)\n\n> {rc}\n\n")
                        md_parts.append(f"### 🤖 AI 回复\n\n{content}\n\n---\n\n")
                    elif role == "tool":
                        name = msg.get("name", "?")
                        call_id = msg.get("tool_call_id", "")
                        n_chars = len(content)
                        if n_chars > 200:
                            content = content[:200] + f"\n\n... [结果过长，仅显示前 200/ {n_chars} 字符]"
                        md_parts.append(f"### 🔧 工具: {name} ({call_id})\n\n```\n{content}\n```\n\n---\n\n")

                md = "".join(md_parts)

                # ── 渲染为 HTML ──
                from tea_agent._gui._markdown import _render_markdown
                from tea_agent._gui import _fonts_mod
                html = _render_markdown(md, font_size=int(_fonts_mod._HTML_FONT_SIZE * self._zoom_level / 100))

                # ── 写临时 HTML ──
                tmp = tempfile.NamedTemporaryFile(suffix=".html", delete=False, mode="w", encoding="utf-8")
                tmp.write(html)
                tmp.close()

                # ── Playwright 无头转 PDF ──
                safe_title = "".join(c if c.isalnum() or c in " _-" else "_" for c in topic_title)
                output = os.path.join(self._initial_cwd, f"{safe_title}.pdf")
                tmp_url = "file:///" + tmp.name.replace("\\", "/")

                pdf_ok = False
                try:
                    from playwright.sync_api import sync_playwright
                    with sync_playwright() as p:
                        browser = p.chromium.launch(headless=True)
                        page = browser.new_page()
                        page.goto(tmp_url, wait_until="networkidle", timeout=15000)
                        page.pdf(path=output, format="A4", print_background=True,
                                  margin={"top": "15mm", "bottom": "15mm", "left": "12mm", "right": "12mm"})
                        browser.close()
                    pdf_ok = True
                    self._update_status(f"✅ 已导出: {safe_title}.pdf")
                except Exception:
                    # 回退：Edge 无头
                    edge_paths = [
                        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
                    ]
                    edge = None
                    for p in edge_paths:
                        if os.path.exists(p):
                            edge = p
                            break
                    if edge:
                        subprocess.run(
                            [edge, "--headless=new", f"--print-to-pdf={output}",
                             "--no-pdf-header-footer", tmp_url],
                            capture_output=True, text=True, timeout=30,
                        )
                        pdf_ok = True
                        self._update_status(f"✅ 已导出: {safe_title}.pdf")
                    else:
                        html_output = os.path.join(self._initial_cwd, f"{safe_title}.html")
                        shutil.copy(tmp.name, html_output)
                        self._update_status(f"⚠️ 已保存 HTML: {safe_title}.html")

                os.unlink(tmp.name)
                if pdf_ok and os.path.exists(output):
                    self._open_file_manager(output)

            except Exception as ex:
                self._update_status(f"❌ 导出失败: {ex}")
                import traceback
                traceback.print_exc()

        threading.Thread(target=_do, daemon=True).start()


    def _update_status(self, msg: str):
        """更新状态栏"""
        if hasattr(self, 'status_var'):
            self.status_var.set(msg)
    
    def _open_file_manager(self, file_path: str):
        """打开文件管理器并定位到指定文件"""
        import subprocess
        import platform
        
        try:
            system = platform.system()
            if system == "Windows":
                # Windows: explorer /select,<file_path>
                subprocess.Popen(["explorer", "/select,", os.path.normpath(file_path)])
            elif system == "Darwin":
                # macOS: open -R <file_path>
                subprocess.Popen(["open", "-R", file_path])
            else:
                # Linux: 尝试多种文件管理器
                dir_path = os.path.dirname(file_path)
                # 优先尝试 nautilus --select (GNOME)
                try:
                    subprocess.Popen(["nautilus", "--select", file_path])
                except FileNotFoundError:
                    # 尝试 xdg-open 打开目录
                    subprocess.Popen(["xdg-open", dir_path])
        except Exception:
            # 静默失败，不影响主流程
            pass

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
            logger.exception("operation failed")

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

    def on_paste(self, e=None):
        """Ctrl+V 粘贴：若模型支持视觉且剪贴板含图像，则缓冲到临时目录并加入待发送列表。

        Returns:
            "break" 表示已处理（阻止默认文本粘贴），None 表示未处理（允许默认粘贴）。
        """
        # 1. 检查模型是否支持视觉
        vision_ok = False
        try:
            vision_ok = (hasattr(self, '_cfg')
                         and hasattr(self._cfg, 'main_model')
                         and self._cfg.main_model.supports_vision)
        except Exception:
            logger.exception("operation failed")

        if not vision_ok:
            return None

        # 2. 尝试从剪贴板获取图像
        img = None
        try:
            from PIL import ImageGrab, Image
            img = ImageGrab.grabclipboard()
        except Exception:
            return None

        if img is None:
            return None

        # 3. 保存到 tmp/images/ 目录
        img_dir = os.path.join(self._initial_cwd, "tmp", "images")
        os.makedirs(img_dir, exist_ok=True)

        from datetime import datetime as _dt
        ts = _dt.now().strftime("%Y%m%d_%H%M%S")
        dest = os.path.join(img_dir, f"paste_{ts}.jpg")
        # 转换为 RGB 模式以支持 JPEG 保存
        if img.mode in ("RGBA", "LA", "P"):
            # 创建白色背景
            background = Image.new("RGB", img.size, (255, 255, 255))
            if img.mode == "P":
                img = img.convert("RGBA")
            background.paste(img, mask=img.split()[-1] if img.mode == "RGBA" else None)
            img = background
        elif img.mode != "RGB":
            img = img.convert("RGB")
        img.save(dest, "JPEG", quality=95)
        self._pending_images.append(dest)

        # 4. 更新 UI 反馈（与 images.attach 一致）
        count = len(self._pending_images)
        self._img_label.config(text=f"已选 {count} 张图片")
        self._clear_img_btn.pack(side=tk.LEFT, padx=4)
        self._update_status(f"📸 已粘贴图像 ({img.size[0]}×{img.size[1]})")

        return "break"

    def send(self, e=None):
        """发送用户消息 — 线程安全版（原子 check-and-set generating）"""
        # 原子操作：检查并设置 generating，避免竞态条件
        with self._generating_lock:
            if self._generating or not self.current_topic_id:
                return "break"
            self._generating = True
        
        msg = self.input_box.get("1.0", tk.END).strip()
        # 允许仅有图片无文本的情况
        images = list(self._pending_images)
        self.images.clear()  # 发送后清空
        if not msg and not images:
            self.generating = False  # 回退状态
            return "break"
        self.input_box.delete("1.0", tk.END)

        self._switch_display("console")

        display_msg = f"你：{msg}" if msg else "你：[图片]"
        self.log(display_msg, "user", images=images if images else None)
        self._hide_raw_check_btn()  # 会话中隐藏切换按钮
        # 启动定时器，批量刷新流式内容到 ScrolledText（不渲染 HtmlFrame）
        self.root.after(self.STREAM_FLUSH_INTERVAL_MS, self._stream_flush_tick)
        self.log("AI：", "title")

        mem_count = len(self.db.get_active_memories(50))
        self._update_status(f"⏳ 生成中... (ESC 打断) | 🧠 {mem_count}")

        chat_input = {"text": msg} if not images else {"text": msg, "images": images}

        def work():
            """Work — 线程安全版：捕获 sess 到本地变量，避免跨线程竞争"""
            # 捕获 sess 到本地变量，避免 worker 线程与主线程竞争
            sess = self.sess
            if sess is None:
                self.safe_stream("❌ 错误：会话未初始化")
                self.root.after(0, self._on_generation_done)
                return
            
            try:
                ai_msg, is_func = sess.chat_stream(
                    chat_input, 
                    callback=self.safe_stream,
                    topic_id=self.current_topic_id,
                    on_status=self.safe_update_status,
                )
                self.root.after(0, self._flush_stream_to_messages)

                # 原逻辑在 _post_chat_pipeline 之后才渲染，_auto_summary 等 API 调用阻塞渲染调度
                self.root.after(0, self._render_and_show_chat)
                self.root.after(0, self._show_raw_check_btn)

                # ── 标准后处理流水线（入库 → Token → 摘要）──
                user_msg_for_db = msg if not images else {"text": msg, "images": images}
                self._post_chat_pipeline(ai_msg, is_func, user_msg_for_db, self.current_topic_id)

                # GUI 特定：token 渲染 + 通知（使用本地变量）
                usage = sess._last_usage
                cheap_usage = sess._last_cheap_usage
                # 嵌入模型 token：读取本轮用量→写DB→重置
                emb_total = 0
                emb_p = 0
                try:
                    from tea_agent.embedding_util import get_embedding_engine
                    euse = get_embedding_engine().get_embedding_usage(reset=True)
                    emb_total = euse.get("total_tokens", 0)
                    emb_p = euse.get("prompt_tokens", 0)
                    if emb_total > 0:
                        self._db.add_topic_tokens(
                            self.current_topic_id,
                            embedding_tokens=emb_total,
                            embedding_prompt_tokens=emb_p,
                        )
                except Exception:
                    logger.exception("operation failed")

                if usage and usage.get("total_tokens", 0) > 0:
                    self.root.after(0, lambda u=usage, cu=cheap_usage, et=emb_total, ep=emb_p:
                                    self._add_token_notice_and_render(u, cu, et, ep))
                    emb_str = f" | Emb:{emb_total:,}" if emb_total > 0 else ""
                    status_msg = (f"✅ 完成 | Tokens: {usage['total_tokens']:,} "
                                  f"(P:{usage['prompt_tokens']:,} C:{usage['completion_tokens']:,}){emb_str}")
                    # 追加缓存命中率（如有）
                    hit = usage.get('prompt_cache_hit_tokens', 0)
                    miss = usage.get('prompt_cache_miss_tokens', 0)
                    if hit + miss > 0:
                        rate = hit / (hit + miss) * 100
                        status_msg += f" | 缓存:{rate:.0f}%({hit:,}/{miss:,})"
                    self.root.after(0, lambda m=status_msg: self._update_status(m))
                    self.root.after(0, self._refresh_topics_preserve_selection)
                    self.root.after(self.NOTIFY_DELAY_MS, lambda am=ai_msg, um=msg: self._notify_completion(am, um))
                else:
                    self.root.after(0, lambda: self._update_status("✅ 完成"))
                    self.root.after(self.NOTIFY_DELAY_MS, lambda am=ai_msg, um=msg: self._notify_completion(am, um))
            except Exception as ex:
                import traceback
                tb = traceback.format_exc()
                ai_msg = f"异常：{type(ex).__name__}: {ex}\n\n```\n{tb[-2000:]}\n```"
                self.safe_stream(ai_msg)
                self.root.after(0, self._flush_stream_to_messages)
                if self._current_conversation_id is not None:
                    # 使用本地变量访问 _rounds_collector
                    rounds = sess._rounds_collector if sess else []
                    try:
                        self.db.update_msg_rounds(
                            conversation_id=self._current_conversation_id,
                            ai_msg=ai_msg,
                            is_func_calling=False,
                            rounds=rounds if rounds else None,
                        )
                    except Exception:
                        logger.exception("operation failed")

                self.root.after(0, self._render_and_show_chat)
                self.root.after(0, self._show_raw_check_btn)
                self.root.after(0, lambda: self._update_status(f"❌ 错误: {ai_msg}"))
                self.root.after(self.NOTIFY_DELAY_MS, lambda am=ai_msg, um=msg: self._notify_completion(am, um))
            finally:
                # 回到主线程设置 generating=False，避免跨线程竞争
                self.root.after(0, self._on_generation_done)
                self.safe_log("")
        threading.Thread(target=work, daemon=True).start()
        return "break"

    def _add_token_notice_and_render(self, usage: dict, cheap_usage: dict = None,
                                     emb_total: int = 0, emb_prompt: int = 0):
        """在聊天消息中追加 Markdown 表格：本轮/主题累积 × 主模型/便宜模型/嵌入模型 token 消耗"""
        if cheap_usage is None:
            cheap_usage = {}
        # 本轮：主模型
        m_total = usage.get("total_tokens", 0)
        m_p = usage.get("prompt_tokens", 0)
        m_c = usage.get("completion_tokens", 0)
        m_cache_hit = usage.get("prompt_cache_hit_tokens", 0)
        m_cache_miss = usage.get("prompt_cache_miss_tokens", 0)
        # 本轮：便宜模型
        c_total = cheap_usage.get("total_tokens", 0)
        c_p = cheap_usage.get("prompt_tokens", 0)
        c_c = cheap_usage.get("completion_tokens", 0)
        c_cache_hit = cheap_usage.get("prompt_cache_hit_tokens", 0)
        c_cache_miss = cheap_usage.get("prompt_cache_miss_tokens", 0)
        # 合并上轮异步摘要产生的 pending cheap tokens（如有）
        pending = getattr(self, '_pending_cheap_tokens', {})
        if pending and pending.get("total_tokens", 0) > 0:
            c_total += pending.get("total_tokens", 0)
            c_p += pending.get("prompt_tokens", 0)
            c_c += pending.get("completion_tokens", 0)
        self._pending_cheap_tokens = {}  # 清零
        # 嵌入模型 token（由 work() 在 _post_chat_pipeline 后 capture+reset 后传入）
        e_total = emb_total
        e_p = emb_prompt
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

        def _cell(val, detail_p=None, detail_c=None):
            """格式化为 'total (P:x C:y)' 或 'total (P:x)' 或 '—'"""
            if val <= 0:
                return "—"
            if detail_p is not None and detail_c is not None:
                return f"{val:,} (P:{detail_p:,} C:{detail_c:,})"
            if detail_p is not None:
                return f"{val:,} (P:{detail_p:,})"
            return f"{val:,}"

        def _cache_cell(hit, miss):
            """格式化为 'hit/miss (rate%)' 或 '—'"""
            total = hit + miss
            if total <= 0:
                return "—"
            rate = hit / total * 100
            return f"{hit:,}/{miss:,} ({rate:.0f}%)"

        lines = [
            "| | 主模型 | 便宜模型 | 嵌入模型 |",
            "|-------|--------|----------|----------|",
            f"| 本轮 | {_cell(m_total, m_p, m_c)} | {_cell(c_total, c_p, c_c)} | {_cell(e_total, e_p)} |",
            f"| 主题 | {_cell(tm_total, tm_p, tm_c)} | {_cell(tc_total, tc_p, tc_c)} | {_cell(te_total, te_p)} |",
            f"| 缓存 | {_cache_cell(m_cache_hit, m_cache_miss)} | {_cache_cell(c_cache_hit, c_cache_miss)} | — |",
        ]
        token_msg = "\n".join(lines)
        self.chat_messages.append({"role": "notice", "content": token_msg, "timestamp": self._now_ts()})
        self._render_and_show_chat()
        self._show_raw_check_btn()

    def _on_history_link_click(self, url):
        """处理 tea://round/N 或 tea://latest 或 tea://image/N 链接点击，外部链接用系统浏览器打开"""
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
            logger.exception("operation failed")


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

    def open_topic_dialog(self):
        """打开主题管理弹窗，关闭后自动刷新主界面主题列表"""
        old_topic_id = self.current_topic_id
        dlg = TopicDialog(self.root, self.db,
                          on_switch=lambda tid: self.root.after(0, self.switch_topic, tid))

        def _on_dialog_destroy(e):
            """对话框关闭后刷新主界面主题列表。
            如果当前主题被停用，自动切换到下一条活跃主题；
            如果当前主题未被停用，仅刷新列表，不重新加载。"""
            if e.widget == dlg:
                self.root.after(50, self._after_topic_dialog_close, old_topic_id)

        dlg.bind("<Destroy>", _on_dialog_destroy)

    def _after_topic_dialog_close(self, old_topic_id):
        """主题管理对话框关闭后：刷新列表 + 条件切换"""
        self.refresh_topics()
        if self.current_topic_id != old_topic_id:
            self.switch_topic(self.current_topic_id)
        # 如果 current_topic_id 未变，仅刷新列表，不重新加载

    def open_memory_dialog(self):
        """打开记忆管理对话框"""
        MemoryDialog(self.root, self.db)

    def open_config_dialog(self):
        """打开配置编辑对话框"""

        def on_save(cfg):
            # 同步到当前 session
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
                            logger.exception("operation failed")

                # max_context_tokens 从 main_model 读取（非全局配置）
                try:
                    self.sess.max_context_tokens = cfg.main_model.max_context_tokens
                except Exception:
                    logger.exception("operation failed")

            self._update_status("⚙️ 配置已更新")

        ConfigDialog(self.root, on_save=on_save, config_path=self._config_path)

    # ── 配置快捷切换 ──

    def get_config_list(self) -> list:
        """扫描 ~/.tea_agent/*.yaml，返回配置摘要列表。
        
        每个元素: {"filename": str, "path": str, "main_model": str, "cheap_model": str}
        """
        configs_dir = Path.home() / ".tea_agent"
        if not configs_dir.exists():
            return []
        results = []
        for fpath in sorted(configs_dir.glob("*.yaml")):
            try:
                cfg = load_config(str(fpath))
                main_name = cfg.main_model.model_name or ""
                cheap_name = cfg.cheap_model.model_name or ""
                results.append({
                    "filename": fpath.name,
                    "path": str(fpath),
                    "main_model": main_name,
                    "cheap_model": cheap_name,
                })
            except Exception as e:
                results.append({
                    "filename": fpath.name,
                    "path": str(fpath),
                    "main_model": f"❌ {e}",
                    "cheap_model": "",
                })
        return results

    def switch_config_file(self, config_path: str) -> bool:
        """切换配置文件，重新初始化会话。
        
        Args:
            config_path: 配置文件的完整路径
        
        Returns:
            True 表示切换成功，False 表示失败
        """
        try:
            new_cfg = load_config(config_path)
            if not new_cfg.main_model.is_configured:
                logger.warning(f"配置文件 {config_path} 主模型不完整，跳过")
                return False

            topic_id = getattr(self, 'current_topic_id', None)

            # 关闭旧会话
            if hasattr(self, 'sess') and self.sess:
                try:
                    self.sess.close()
                except Exception:
                    logger.exception("operation failed")

                self.sess = None

            # 更新配置
            self._cfg = new_cfg
            self._config_path = config_path  # 同步更新，确保 GUI 下拉框标记正确
            set_active_config_path(config_path)  # 更新全局活跃配置路径

            # 重新初始化会话
            self._init_session()
            if hasattr(self, 'sess') and self.sess is not None:
                self.sess.tool_log = self.safe_log_tool

            # 重新加载当前主题
            if topic_id:
                self.current_topic_id = topic_id
                try:
                    self.load_topic_history(topic_id)
                except Exception:
                    logger.exception("operation failed")


            # 更新状态栏
            cheap_m = self._cfg.cheap_model
            cheap_info = f" | 摘要模型: {cheap_m.model_name}" if cheap_m and cheap_m.model_name else ""
            self._update_status(
                f"📡 已切换 | {Path(config_path).name} | "
                f"模型: {self._cfg.main_model.model_name}{cheap_info}"
            )

            # 通知前端刷新
            self.root.after(100, lambda: self._update_title())
            return True

        except Exception as e:
            logger.exception(f"切换配置文件失败: {config_path}")
            self._update_status(f"❌ 切换失败: {e}")
            return False

    def _refresh_config_list(self):
        """刷新左侧面板的配置选择下拉框（显示主模型/便宜模型名称）"""
        configs = self.get_config_list()
        if not hasattr(self, 'config_combo') or not self.config_combo:
            return
        # 构建显示文本 → 路径映射（主模型 / 便宜模型，相同时只显示一个）
        self._config_display_map = {}
        values = []
        # 第一遍：检测 display 文本重复
        seen = {}
        for cfg in configs:
            m = cfg["main_model"] or "?"
            c = cfg["cheap_model"] or ""
            base_display = f"{m} / {c}" if (c and c != m) else m
            if base_display in seen:
                seen[base_display] += 1
            else:
                seen[base_display] = 1
        # 第二遍：生成最终 display（重复时追加文件名）
        for cfg in configs:
            m = cfg["main_model"] or "?"
            c = cfg["cheap_model"] or ""
            base_display = f"{m} / {c}" if (c and c != m) else m
            if seen.get(base_display, 0) > 1:
                display = f"{base_display} ({cfg['filename']})"
            else:
                display = base_display
            self._config_display_map[display] = cfg["path"]
            values.append(display)
        self.config_combo["values"] = values
        # 标记当前配置（规范化路径比较，避免 \ vs / 差异）
        current_path = getattr(self, '_config_path', None)
        if current_path:
            norm_current = str(Path(current_path)).lower()
            for cfg in configs:
                if str(Path(cfg["path"])).lower() == norm_current:
                    # 找到对应的 display 文本
                    m = cfg["main_model"] or "?"
                    c = cfg["cheap_model"] or ""
                    base_display = f"{m} / {c}" if (c and c != m) else m
                    display = f"{base_display} ({cfg['filename']})" if seen.get(base_display, 0) > 1 else base_display
                    self._config_var.set(display)
                    break
            else:
                self._config_var.set("")
        else:
            self._config_var.set("")
        # 如果没有配置，提示
        if not values:
            self.config_combo["values"] = ["(暂无配置文件)"]
            self._config_var.set("(暂无配置文件)")

    def _on_config_selected(self, event=None):
        """左侧面板配置选择下拉框回调"""
        selected = self._config_var.get()
        if not selected or "(暂无" in selected or "(加载中" in selected:
            return
        # 通过 display_text → path 映射查找配置文件路径
        display_map = getattr(self, '_config_display_map', {})
        fpath = display_map.get(selected)
        if not fpath:
            # 兼容旧逻辑：直接作为文件名
            configs_dir = Path.home() / ".tea_agent"
            fpath = str(configs_dir / selected)
        if not Path(fpath).exists():
            self._update_status(f"❌ 配置文件不存在: {fpath}")
            return
        # 检查是否已经是当前配置
        if getattr(self, '_config_path', None) == str(fpath):
            self._update_status(f"✓ 已是当前配置: {selected}")
            return
        filename = Path(fpath).name
        self._update_status(f"⏳ 正在切换到: {filename}...")
        ok = self.switch_config_file(str(fpath))
        if ok:
            self._config_path = str(fpath)
            self._update_status(f"✅ 已切换到: {filename}")
            # 刷新列表以更新"当前配置"标记
            self.root.after(500, self._refresh_config_list)
        else:
            self._update_status(f"❌ 切换失败: {filename}")

    def open_scheduler_dialog(self):
        """打开定时任务管理对话框"""
        from tea_agent.gui_dialogs import ScheduledTaskDialog
        ScheduledTaskDialog(self.root)

    def open_search_dialog(self):
        """打开对话搜索对话框"""
        from tea_agent._gui._search import SearchDialog
        SearchDialog(self.root, self.db,
                     on_switch_topic=lambda tid: self.root.after(0, self.switch_topic, tid))

    def _on_generation_done(self):
        """主线程回调：标记生成完成（避免跨线程写 generating）"""
        self.generating = False

    def interrupt(self, e=None):
        """打断当前 AI 生成 — 线程安全版"""
        # 原子检查并重置 generating
        with self._generating_lock:
            if not self._generating:
                return
            self._generating = False
        
        # 安全访问 sess（可能为 None）
        sess = self.sess
        if sess is not None:
            sess.interrupt()
        
        self.safe_log("\n🛑 已打断", "tool")
        # 先刷新控制台剩余内容，再 flush 到 messages
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
        """显示加载动画"""
        return self.renderer._show_loading(text, progress)

    def _poll_loading_progress(self):
        """轮询加载进度"""
        return self.renderer._poll_loading_progress()

    def scroll_to_bottom(self):
        """滚动到底部"""
        return self.renderer.scroll_to_bottom()

    def _html_render(self, html: str):
        """渲染 HTML 到 chat_view"""
        return self.renderer._html_render(html)

    def _render_chat(self, streaming_think: str = "", streaming_text: str = ""):
        """渲染聊天消息"""
        return self.renderer._render_chat(streaming_think, streaming_text)

    def _render_and_show_chat(self):
        """渲染并显示聊天"""
        return self.renderer._render_and_show_chat()

    def _render_loaded_topic(self, render_items):
        """渲染加载的主题历史"""
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
        """Internal: filtered messages."""
        return self.renderer._filtered_messages()

    def _group_into_rounds(self, msgs):
        """Internal: group into rounds.
        
        Args:
            msgs: Description.
        """
        return self.renderer._group_into_rounds(msgs)

    def _flush_stream_to_messages(self):
        """Internal: flush stream to messages."""
        return self.renderer._flush_stream_to_messages()

    def _flush_think_buffer_to_messages(self):
        """Internal: flush think buffer to messages."""
        return self.renderer._flush_think_buffer_to_messages()

    def _toggle_raw_view(self):
        """Internal: toggle raw view."""
        return self.renderer._toggle_raw_view()

    def _show_raw_check_btn(self):
        """Internal: show raw check btn."""
        return self.renderer._show_raw_check_btn()

    def _hide_raw_check_btn(self):
        """Internal: hide raw check btn."""
        return self.renderer._hide_raw_check_btn()

def main(debug:bool=False, no_gui:bool=False, timeout:int=0, config_fname:str="", disable_summary:bool=False, no_stream_chunk:bool=False):
    """启动 GUI 主界面。

    Args:
        debug: 调试模式
        timeout: 超时秒数，超时后自动关闭窗口（0=不超时，用于自动化测试）
        disable_summary: 禁用历史压缩和摘要
        no_stream_chunk: 非流式模式，方便单步调试
    """
    root = tk.Tk()
    _set_app_icon(root)  # 设置窗口图标（齿轮图标）
    app = TkGUI(root, debug=debug, config_fname=config_fname, disable_summary=disable_summary, no_stream_chunk=no_stream_chunk)
    
    if timeout > 0:
        logger.info(f"GUI debug timeout set: {timeout}s, will auto-close")
        root.after(timeout * 1000, lambda: _safe_destroy(root))
    
    root.mainloop()

def _set_app_icon(root):
    """给窗口+任务栏设置 Tea Agent 齿轮图标（跨平台）。"""
    gui_dir = os.path.join(os.path.dirname(__file__), "_gui")
    ico_path = os.path.join(gui_dir, "icon.ico")
    png_path = os.path.join(gui_dir, "icon.png")

    # Windows: 用 iconbitmap(.ico) 设置任务栏图标
    if sys.platform == "win32" and os.path.exists(ico_path):
        try:
            # 设置 AppUserModelID，让 Windows 识别为独立应用
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "tea_agent.gui"
            )
            root.iconbitmap(default=ico_path)
        except Exception:
            logger.exception("operation failed")


    # 跨平台：用 iconphoto(.png) 设置标题栏图标
    if os.path.exists(png_path):
        try:
            from PIL import Image, ImageTk
            img = Image.open(png_path)
            photo = ImageTk.PhotoImage(img)
            root.iconphoto(True, photo)
            root._icon_ref = photo  # 防止被 GC
        except Exception:
            logger.exception("operation failed")



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
    ap.add_argument(
        "--timeout", type=int, default=0,
        help="超时秒数，超时后自动关闭（用于自动化测试）"
    )
    ap.add_argument("--config", type=str, help="配置文件路径")
    ap.add_argument("--disable_summary", action="store_true", default=False,
                    help="禁用历史压缩和摘要，超过30轮直接丢弃")
    ap.add_argument("--no_stream_chunk", action="store_true", default=False,
                    help="非流式模式，方便单步调试")
    args = ap.parse_args()
    main(debug=args.debug, timeout=args.timeout, config_fname=args.config, disable_summary=args.disable_summary, no_stream_chunk=args.no_stream_chunk)
