"""
@2026-05-15 gen by tea_agent, GUI 组件包 — Composition 模式拆分 TkGUI
"""

from ._interfaces import HtmlDisplay, TextDisplay, StatusDisplay, ImagePicker
from ._tk_impl import (
    HtmlFrameDisplay,
    ScrolledTextDisplay,
    LabelStatusDisplay,
    TkImagePicker,
)
from ._tray import TrayManager
from ._images import ImageHandler

__all__ = [
    "HtmlDisplay",
    "TextDisplay",
    "StatusDisplay",
    "ImagePicker",
    "HtmlFrameDisplay",
    "ScrolledTextDisplay",
    "LabelStatusDisplay",
    "TkImagePicker",
    "TrayManager",
    "ImageHandler",
]
