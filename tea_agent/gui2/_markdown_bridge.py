"""
Markdown Bridge — 复用 tea_agent._gui._markdown 渲染管线，封装 QObject 供 QML 调用。

用法:
    bridge = MarkdownBridge()
    html = bridge.render_messages(messages)
    # messages: [{"role": "user"|"ai"|"think"|"tool", "content": str, "timestamp": str}, ...]
"""

import logging
import sys
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import QObject, Signal, Slot

logger = logging.getLogger(__name__)

# ── 导入现有渲染引擎 ──────────────────────────────────────
# 确保项目路径可导入
_project_root = str(Path(__file__).resolve().parent.parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from tea_agent._gui._markdown import (
    _MD_CSS_TEMPLATE,
    _chat_to_markdown,
    _render_markdown,
)


class MarkdownBridge(QObject):
    """将聊天消息列表渲染为完整 HTML，供 QML 的 WebEngineView 加载。

    复用 tea_agent._gui._markdown 的完整流程：
      1. _chat_to_markdown(messages) → Markdown 文本
      2. _render_markdown(md)        → 完整 HTML 页面
    """

    html_ready = Signal(str)  # 渲染完成时发射

    def __init__(self, parent=None):
        super().__init__(parent)
        self._font_size = 15          # 默认字号 (CSS px)
        self._zoom_level = 100        # 缩放百分比

    # ── 供 QML 调用的方法 ──────────────────────────────────

    @Slot(list, result=str)
    def render_messages(self, messages: list) -> str:
        """将消息列表渲染为完整 HTML 字符串。

        Args:
            messages: 消息列表，格式 [{"role":"user","content":"...","timestamp":"..."}, ...]
        Returns:
            完整 HTML 页面（含 CSS 样式）
        """
        try:
            md = _chat_to_markdown(messages)
            font_size = int(self._font_size * self._zoom_level / 100)
            html = _render_markdown(md, font_size=font_size)
            logger.debug(f"Rendered {len(messages)} messages → {len(html)} bytes HTML")
            self.html_ready.emit(html)
            return html
        except Exception as e:
            logger.error(f"Markdown render error: {e}")
            fallback = (
                f"<html><body style='font-family:sans-serif;padding:20px;color:#c00;'>"
                f"<h3>⚠️ 渲染错误</h3><pre>{e}</pre></body></html>"
            )
            self.html_ready.emit(fallback)
            return fallback

    @Slot(str, list, result=str)
    def render_messages_with_think(self, think_text: str, messages: list) -> str:
        """渲染消息列表 + 追加一条 thinking 消息。流式输出时使用。

        Args:
            think_text: 当前思考过程中的文本（可为空）
            messages: 已有的消息列表
        Returns:
            完整 HTML
        """
        if think_text and think_text.strip():
            msgs = list(messages) + [
                {"role": "think", "content": think_text.strip(), "timestamp": ""}
            ]
        else:
            msgs = messages
        return self.render_messages(msgs)

    # ── 字体 / 缩放 ───────────────────────────────────────

    @Slot(int)
    def set_font_size(self, size: int):
        """设置基础字号（CSS px）"""
        self._font_size = max(10, min(32, size))

    @Slot(int)
    def set_zoom(self, percent: int):
        """设置缩放百分比（50~200）"""
        self._zoom_level = max(50, min(200, percent))

    @Slot(result=int)
    def font_size(self) -> int:
        return self._font_size

    @Slot(result=int)
    def zoom(self) -> int:
        return self._zoom_level

    # ── 工具方法 ──────────────────────────────────────────

    @Slot(str, result=str)
    def render_single(self, markdown_text: str) -> str:
        """将单条 Markdown 文本渲染为 HTML 片段（不含页面壳）。"""
        try:
            import markdown as _md
            html = _md.markdown(
                markdown_text,
                extensions=["fenced_code", "tables", "codehilite", "md_in_html"]
            )
            return html
        except Exception as e:
            return f"<p style='color:red'>{e}</p>"

    @Slot(result=str)
    def get_default_css(self) -> str:
        """返回默认 CSS 定义，供 QML 直接注入 WebEngineView。"""
        return _MD_CSS_TEMPLATE.safe_substitute(font_size=self._font_size)
