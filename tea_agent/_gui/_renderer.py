"""
将对话消息渲染为 HTML，管理 HtmlFrame / ScrolledText 切换，
处理流式缓冲刷新、轮次视图、加载动画。
Usage: self.renderer = ChatRenderer(self)  # self = TkGUI instance
"""
import html as html_mod
import logging
import threading
import tkinter as tk
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tea_agent.gui import TkGUI

import contextlib

from . import _fonts as _fonts_mod  # 动态获取 _DEFAULT_FONT_SIZE
from ._markdown import (
    _MD_CSS_TEMPLATE,
    HAS_TKINTERWEB,
    _auto_close_unclosed_tags,
    _chat_to_markdown,
    _render_markdown,
    _sanitize_html_control_chars,
    _validate_html_structure,
)

logger = logging.getLogger(__name__)

class ChatRenderer:
    """消息渲染器：HtmlFrame 渲染、加载动画、轮次视图、显示模式切换"""

    def __init__(self, gui: 'TkGUI'):
        """Initialize  .

        Args:
            gui: Description.
        """
        self.gui = gui
        self._last_html_warn = None  # 用于去重相同的 WARN

    # ── 便捷属性 ────────────────────────
    @property
    def _show_mode(self):
        """消息显示模式：'console'=ScrolledText, 'chat_view'=HtmlFrame。"""
        return self.gui._show_mode
    @_show_mode.setter
    def _show_mode(self, v):
        self.gui._show_mode = v

    # ── _html_render ──
    def _html_render(self, html: str):
        """Internal: html render — 校验+自动修复+渲染。

        Args:
            html: 完整 HTML 字符串
        """
        if not html or not isinstance(html, str):
            print("[_html_render WARN] HTML 为空或非字符串，跳过渲染")
            return
        # 1. 清洗控制字符（保留 \n \t）
        cleaned = _sanitize_html_control_chars(html)
        if cleaned != html:
            logger.debug(f"[_html_render] 移除了 {len(html) - len(cleaned)} 个控制字符")
        # 2. 结构校验 + 自动修复
        ok, diag, unclosed = _validate_html_structure(cleaned)
        if not ok:
            # 自动补全未闭合标签
            fixed = _auto_close_unclosed_tags(cleaned.rstrip(), unclosed)
            # 二次校验
            ok2, diag2, unclosed2 = _validate_html_structure(fixed)
            if ok2:
                cleaned = fixed
            else:
                # 仍有问题但尝试继续渲染（HtmlFrame 有容错能力）
                cleaned = fixed
                warn_key = f"html_warn:{';'.join(sorted(unclosed2))}"
                if warn_key != self._last_html_warn:
                    self._last_html_warn = warn_key
                    logger.warning(f"[_html_render] 修复后仍有未闭合标签: {diag2}，尝试继续渲染")
        # 3. 渲染
        try:
            self.gui.chat_view.load_html(cleaned)
        except Exception as e:
            logger.error(f"[_html_render ERROR] {e}")
            import traceback
            traceback.print_exc()

    # ── _render_chat ──
    def _render_chat(self, streaming_think: str = "", streaming_text: str = ""):
        """渲染 HtmlFrame。可选 streaming_think/streaming_text 用于流式输出期间实时显示。"""
        msgs = self._filtered_messages()
        # 流式内容临时追加到最后一条 AI 消息
        streaming = streaming_think + streaming_text
        if streaming:
            if msgs and msgs[-1]["role"] == "ai":
                msgs[-1] = dict(msgs[-1])
                msgs[-1]["content"] = msgs[-1]["content"] + streaming
            else:
                msgs.append({"role": "ai", "content": streaming, "timestamp": self.gui._now_ts()})
        self.gui._image_cache.clear()
        md = _chat_to_markdown(msgs, image_cache=self.gui._image_cache)
        if HAS_TKINTERWEB:
            # HtmlFrame 使用 _HTML_FONT_SIZE（由 _init_fonts 从 config 读取）
            font_size = int(_fonts_mod._HTML_FONT_SIZE * self.gui._zoom_level / 100)
            html = _render_markdown(md, font_size=font_size)
            self._html_render(html)
        else:
            self.gui.chat_view.config(state=tk.NORMAL)
            self.gui.chat_view.delete("1.0", tk.END)
            self.gui.chat_view.insert("1.0", md)
            self.gui.chat_view.config(state=tk.DISABLED)
            self.gui.chat_view.see(tk.END)

    def _threaded_render(self, prepare_fn, on_done_fn):
        """后台线程执行 prepare_fn → 主线程执行 on_done_fn。

        消除多处的 _prepare/_on_done/_worker 三件套重复。
        """
        def _worker():
            try:
                result = prepare_fn()
                self.gui.root.after(0, lambda r=result: on_done_fn(r))
            except Exception:
                self.gui.root.after(0, lambda: on_done_fn("<p>渲染错误</p>"))
        threading.Thread(target=_worker, daemon=True).start()

    def _on_done_chat(self, html):
        """_render_and_show_chat 的完成回调：HtmlFrame/ScrolledText 渲染 + 加载标记清理"""
        if HAS_TKINTERWEB:
            # 主题加载模式下，先显示渲染提示避免 load_html 阻塞时用户以为卡死
            if getattr(self.gui, '_loading_topic', False):
                self._html_render(
                    '<html><body><div style="text-align:center;padding:60px 20px;color:#888;'
                    'font-family:sans-serif;"><p style="font-size:18px;">🔄 正在渲染视图...</p>'
                    '<p style="font-size:13px;">内容较多，请稍候</p></div></body></html>')
                self.gui.root.update_idletasks()
            self._html_render(html)
            self._switch_display("chat_view")
            self.gui.root.after(300, self.scroll_to_bottom)
            if getattr(self.gui, '_loading_topic', False):
                self.gui._loading_topic = False
                self.gui.generating = False
                self.gui._update_status("✅ 就绪")
                # 主题加载完成后检查 TODO 清单
                self.gui.root.after(400, self.gui._check_and_show_todo)
        else:
            self.gui.chat_view.config(state=tk.NORMAL)
            self.gui.chat_view.delete("1.0", tk.END)
            self.gui.chat_view.insert("1.0", html)
            self.gui.chat_view.config(state=tk.DISABLED)
            self.gui.chat_view.see(tk.END)
            self._switch_display("chat_view")

    def _on_done_round(self, html):
        """_render_round_view 的完成回调：HtmlFrame/ScrolledText 渲染"""
        if HAS_TKINTERWEB:
            self._html_render(html)
            self._switch_display("chat_view")
            self.gui.root.after(200, self.scroll_to_bottom)
        else:
            self.gui.chat_view.config(state=tk.NORMAL)
            self.gui.chat_view.delete("1.0", tk.END)
            self.gui.chat_view.insert("1.0", html)
            self.gui.chat_view.config(state=tk.DISABLED)
            self.gui.chat_view.see(tk.END)
            self._switch_display("chat_view")

    # ── _render_and_show_chat ──
    def _render_and_show_chat(self):
        """会话完成后渲染：历史轮次链接表 + 最新轮内容"""
        msgs = self._filtered_messages()

        # 分组为轮次
        rounds = self._group_into_rounds(msgs)
        self.gui._chat_rounds = rounds
        self.gui._current_round_view = None

        if not rounds:
            return

        active_idx = len(rounds) - 1  # 最新轮
        font_size = int(_fonts_mod._HTML_FONT_SIZE * self.gui._zoom_level / 100)

        self._threaded_render(
            prepare_fn=lambda: self._build_round_view_html(rounds, active_idx, font_size),
            on_done_fn=self._on_done_chat,
        )

    # ── _render_loaded_topic ──
    def _render_loaded_topic(self, render_items):
        """主线程：快速加载最近轮次到 chat_messages 并渲染。

        只加载 header（标题/Token/摘要）+ 最近 MAX_RECENT 轮对话到 chat_messages，
        完整历史已通过 load_history 存入 session，后续轮次导航/导出可从中获取。
        """
        self.gui.clear_chat()
        total_convs = getattr(self.gui, '_pending_total', 0)

        # ── 找到对话边界：每个 ("user", ...) 标志一轮的开始 ──
        conv_starts = []
        for i, item in enumerate(render_items):
            if item[0] == "user":
                conv_starts.append(i)

        MAX_RECENT = 20
        if conv_starts and len(conv_starts) > MAX_RECENT:
            cutoff = len(conv_starts) - MAX_RECENT
            recent_start = conv_starts[cutoff]
            # header = 第一个 "user" 之前的所有条目（标题、Token、摘要等）
            items_to_load = render_items[:conv_starts[0]] + render_items[recent_start:]
            displayed = MAX_RECENT
        else:
            items_to_load = render_items
            displayed = len(conv_starts) if conv_starts else 0

        # 批量构建 chat_messages entries（无 update_idletasks，纯内存操作 <1ms）
        entries = []
        for tag, text, *rest in items_to_load:
            if tag in ("user", "ai", "tool", "notice", "title"):
                entry = {"role": tag, "content": text, "timestamp": self.gui._now_ts()}
                if rest:
                    entry["images"] = rest[0]
                entries.append(entry)
        self.gui.chat_messages.extend(entries)

        # 状态提示
        if total_convs > displayed:
            self.gui._update_status(f"✅ 就绪（显示最近 {displayed}/{total_convs} 轮）")

        if HAS_TKINTERWEB and self.gui.chat_messages:
            self.gui._loading_topic = True  # 标记：_on_done 中负责 generating=False
            self._render_and_show_chat()
        else:
            self._switch_display("chat_view")
            self.gui.generating = False
            if total_convs <= displayed:
                self.gui._update_status("✅ 就绪")
            # 主题加载完成后检查 TODO 清单
            self.gui.root.after(400, self.gui._check_and_show_todo)

    # ── _render_round_view ──
    def _render_round_view(self, round_idx):
        """渲染指定轮次：后台线程生成 HTML，主线程加载"""
        rounds = self.gui._chat_rounds
        if not rounds or round_idx < 0 or round_idx >= len(rounds):
            return
        font_size = int(_fonts_mod._HTML_FONT_SIZE * self.gui._zoom_level / 100)

        self._threaded_render(
            prepare_fn=lambda: self._build_round_view_html(rounds, round_idx, font_size),
            on_done_fn=self._on_done_round,
        )
    # ── _render_topic_error ──
    def _render_topic_error(self, error_msg):
        """主线程：加载失败回调"""
        logger.error(f"❌ 主题加载失败详情: {error_msg}")
        self.gui.clear_chat()
        self.gui.log(f"❌ 加载历史失败: {error_msg}", "error")
        self.gui.generating = False
        self.gui._update_status(f"❌ 加载失败: {error_msg}")

    # ── _build_round_view_html ──
    def _build_round_view_html(self, rounds, active_idx, font_size):
        """构建包含历史轮次链接表 + 当前轮内容的完整 HTML。"""
        import markdown as _md_lib
        total = len(rounds)
        is_latest = (self.gui._current_round_view is None)

        # -- 状态指示行 --
        if is_latest:
            status_line = '<p style="margin:0 0 6px; color:#1a73e8; font-weight:bold;">\U0001f4cc 当前：最新轮（第' + str(total) + '轮 / 共' + str(total) + '轮）</p>'
        else:
            status_line = '<p style="margin:0 0 6px; color:#e67e22; font-weight:bold;">\U0001f4cc 当前查看：第' + str(active_idx + 1) + '轮 / 共' + str(total) + '轮 | <a href="tea://latest">\u2190 返回最新轮</a></p>'

        # -- 历史轮次表格 --
        max_rows = 12
        shown = []
        if total <= max_rows:
            shown = list(range(total))
        else:
            shown = list(range(3))
            if active_idx > 3:
                shown.append(-1)
            start = max(3, active_idx - 1)
            end = min(total - 3, active_idx + 2)
            for i in range(start, end):
                if i not in shown:
                    shown.append(i)
            if active_idx < total - 4:
                shown.append(-2)
            for i in range(total - 3, total):
                if i not in shown:
                    shown.append(i)

        rows_html = []
        for i in shown:
            if i < 0:
                rows_html.append('<tr><td colspan="2" style="text-align:center;color:#999;padding:4px;">\u00b7\u00b7\u00b7</td></tr>')
            elif i == active_idx:
                rows_html.append('<tr style="background:#e8f0fe;"><td style="padding:4px 10px;">第' + str(i+1) + '轮</td><td style="padding:4px 10px;"><strong>\u2190 当前</strong></td></tr>')
            else:
                rows_html.append('<tr><td style="padding:4px 10px;">第' + str(i+1) + '轮</td><td style="padding:4px 10px;"><a href="tea://round/' + str(i) + '">查看</a></td></tr>')

        table_html = '<div style="background:#eff6ff; border:2px solid #93c5fd; border-radius:6px; padding:8px 12px; margin-bottom:14px;">\n' + status_line + '\n<p style="margin:4px 0 8px; color:#666; font-size:0.9em;">\U0001f4cb 历史轮次（共' + str(total) + '轮）</p>\n<table style="margin:0; font-size:0.9em;">\n<thead><tr><th style="width:70px;">轮次</th><th>操作</th></tr></thead>\n<tbody>\n' + '\n'.join(rows_html) + '\n</tbody>\n</table></div>'

        # -- 当前轮内容 --
        round_msgs = rounds[active_idx]
        self.gui._image_cache.clear()
        round_md = _chat_to_markdown(round_msgs, image_cache=self.gui._image_cache)
        if HAS_TKINTERWEB:
            round_body = _md_lib.markdown(round_md, extensions=["fenced_code", "tables", "codehilite", "md_in_html"])
            from tea_agent._gui._markdown import _fix_double_escape_all, _fix_double_escape_in_code
            round_body = _fix_double_escape_all(round_body)
            round_body = _fix_double_escape_in_code(round_body)
            css = _MD_CSS_TEMPLATE.safe_substitute(font_size=font_size)
            full_html = "<html><head>" + css + "</head><body>" + table_html + round_body + "</body></html>"
        else:
            full_html = round_md
        return full_html

    # ── _switch_display ──
    def _switch_display(self, mode: str):
        """切换消息显示模式：'console'=ScrolledText, 'chat_view'=HtmlFrame。"""
        if mode == self.gui._show_mode:
            return
        self.gui._show_mode = mode
        if mode == "console":
            self.gui.chat_view.pack_forget()
            self.gui.console.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        else:
            self.gui.console.pack_forget()
            self.gui.chat_view.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
            self.gui.root.after(400, self.scroll_to_bottom)

    # ── _show_loading ──
    def _show_loading(self, text: str = "正在加载历史记录", progress: str = None):
        """在 HtmlFrame 中显示加载动画（spinner + 文字），用于异步加载期间的过渡。
        progress 非空时显示为进度文本（如 '第 5 / 20 条'），常用于后台线程实时更新。"""
        if not HAS_TKINTERWEB:
            self._switch_display("console")
            msg = f"⏳ {text}..."
            if progress:
                msg = f"⏳ {text}: {progress}"
            self.gui.log(msg, "notice")
            return

        display_text = text
        if progress:
            display_text = f"{text}（{progress}）"

        loading_html = f'''<html><head>
<style>
body {{ display:flex; align-items:center; justify-content:center; height:100vh;
       margin:0; background:#fafafa; font-family:"DengXian","Noto Sans SC","Noto Sans CJK SC","Microsoft YaHei",sans-serif; }}
.loader {{ text-align:center; }}
.spinner {{ width:48px; height:48px; border:4px solid #e0e0e0; border-top-color:#1a73e8;
           border-radius:50%; animation:spin 0.8s linear infinite; margin:0 auto 20px; }}
@keyframes spin {{ to {{ transform:rotate(360deg); }} }}
.text {{ color:#888; font-size:{_fonts_mod._HTML_FONT_SIZE}px; }}
.dots::after {{ content:''; animation:d 1.5s steps(4,end) infinite; }}
@keyframes d {{ 0% {{ content:'' }} 25% {{ content:'.' }} 50% {{ content:'..' }} 75% {{ content:'...' }} 100% {{ content:'' }} }}
</style></head>
<body><div class="loader">
<div class="spinner"></div>
<div class="text">{html_mod.escape(display_text)}<span class="dots"></span></div>
</div></body></html>'''

        # 切换到 chat_view 但不修改 chat_messages
        if self.gui._show_mode != "chat_view":
            self.gui.console.pack_forget()
            self.gui.chat_view.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
            self.gui._show_mode = "chat_view"
        self._html_render(loading_html)

    # ── _poll_loading_progress ──
    def _poll_loading_progress(self, _retries=0):
        """定时器（50ms）：从 _progress_queue 逐条出队更新 HtmlFrame 进度；
        队列排空后若后台线程已完成，触发最终渲染。
        熔断：最多轮询 600 次（≈30 秒），超时后强制结束。"""
        MAX_POLL = 600  # 30秒熔断上限
        if _retries > MAX_POLL:
            self.gui._update_status("⚠️ 主题加载超时，请重试")
            self.gui._loading_done = False
            self.gui.generating = False
            return
        if not HAS_TKINTERWEB:
            return
        if self.gui._progress_queue:
            # 用 pop(0) 是 O(n)，但进度队列通常很短（<100条），性能可接受
            progress = self.gui._progress_queue.pop(0)
            self._show_loading("正在加载历史记录", f"{progress[0]}/{progress[1]}")
            self.gui.root.after(50, lambda: self._poll_loading_progress(_retries + 1))
            return
        # 队列已空，检查后台线程是否完成
        if getattr(self.gui, '_loading_done', False):
            # 最终渲染
            if getattr(self.gui, '_pending_error', None) is not None:
                self._render_topic_error(self.gui._pending_error)
                self.gui._pending_error = None
            elif hasattr(self.gui, '_pending_render'):
                self._render_loaded_topic(self.gui._pending_render)
                with contextlib.suppress(AttributeError):
                    delattr(self.gui, '_pending_render')
                try:
                    if hasattr(self.gui, '_pending_total'):
                        delattr(self.gui, '_pending_total')
                except AttributeError:
                    pass
            self.gui._loading_done = False
            self.gui.generating = False  # loading完成，释放send()锁
            # 加载完成后检查任务面板（Plan + TODO），覆盖启动和切换场景
            self.gui.root.after(500, self.gui._check_and_show_todo)
            return
        # 线程还在跑，继续等待
        self.gui.root.after(50, lambda: self._poll_loading_progress(_retries + 1))

    # ── scroll_to_bottom ──
    def scroll_to_bottom(self):
        """滚动聊天视图到最底部。"""
        self.gui.chat_view.yview_moveto(1.0)

    # ── _filtered_messages ──
    def _filtered_messages(self):
        """返回用于 HtmlFrame 渲染的消息列表（始终包含工具轮）。"""
        return list(self.gui.chat_messages)

    # ── _group_into_rounds ──
    def _group_into_rounds(self, msgs):
        """将消息列表按 user 角色切分为轮次列表。每轮从 user 开始。"""
        rounds = []
        current = []
        for msg in msgs:
            if msg["role"] == "user":
                if current:
                    rounds.append(current)
                current = [msg]
            else:
                current.append(msg)
        if current:
            rounds.append(current)
        return rounds

    # ── _toggle_raw_view ──
    def _toggle_raw_view(self):
        """Check 按钮回调：选中→ScrolledText 原始视图，取消→HtmlFrame 渲染视图"""
        if self.gui._raw_view.get():
            self._switch_display("console")
        else:
            self._switch_display("chat_view")
            self.gui.root.after(100, self.scroll_to_bottom)

    # ── _show_raw_check_btn ──
    def _show_raw_check_btn(self):
        """显示纯文本视图切换按钮（仅会话完成后）"""
        self.gui._raw_check_btn.pack(side=tk.LEFT, padx=8)

    # ── _hide_raw_check_btn ──
    def _hide_raw_check_btn(self):
        """隐藏纯文本视图切换按钮（会话进行中）"""
        self.gui._raw_check_btn.pack_forget()

    # ── _flush_stream_to_messages ──
    def _flush_stream_to_messages(self):
        # 先刷新控制台剩余内容（确保最后一批 pending 文本显示完毕）
        """Internal: flush stream to messages."""
        if self.gui._pending_console_text:
            self.gui.console.config(state=tk.NORMAL)
            for text, tag in self.gui._pending_console_text:
                if tag == "think":
                    self.gui.console.insert(tk.END, text, "think")
                else:
                    self.gui.console.insert(tk.END, text)
            self.gui.console.see(tk.END)
            self.gui.console.config(state=tk.DISABLED)
            self.gui._pending_console_text.clear()

        if self.gui._think_buffer or self.gui._stream_buffer:
            self._flush_think_buffer_to_messages()
            if self.gui._stream_buffer:
                self.gui.chat_messages.append({"role": "ai", "content": self.gui._stream_buffer, "timestamp": self.gui._now_ts()})
            self.gui._stream_buffer = ""

    # ── _flush_think_buffer_to_messages ──
    def _flush_think_buffer_to_messages(self):
        """将当前 think 缓冲刷新为独立的思考消息。
        工具调用每轮结束后调用，确保思考过程与工具轮对应。"""
        think_text = self.gui._think_buffer.strip()
        if think_text:
            self.gui.chat_messages.append({
                "role": "think",
                "content": think_text,
                "timestamp": self.gui._now_ts()
            })
            self.gui._think_buffer = ""

