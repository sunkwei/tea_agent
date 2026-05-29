"""
从 gui.py L84-160 提取：跨平台字体自动检测 + Wayland/X11 显示缩放
"""

import platform as _platform
import logging

logger = logging.getLogger("tea_agent")

_IS_WINDOWS = _platform.system() == "Windows"

SYSTEM_FONT = "TkDefaultFont"
MONO_FONT = "TkFixedFont"

_FONTS_DETECTED = False
_SCALE_FACTOR = 1.0
_DEFAULT_FONT_SIZE = 16  # 模块级默认（_init_fonts 后会更新）

def _fs(size):
    """返回按显示缩放因子调整后的字体大小（适配 Wayland/X11 高分屏）。"""
    return max(1, int(size * _SCALE_FACTOR))

# NOTE: 2026-05-29 07:52:57, self-evolved by tea_agent --- 修复 _init_fonts 中缺少的 global 声明
def _init_fonts():
    """延迟检测系统可用字体（需 Tk root 创建后调用）。"""
    global SYSTEM_FONT, MONO_FONT, _FONTS_DETECTED, _SCALE_FACTOR, _DEFAULT_FONT_SIZE

    if _FONTS_DETECTED:
        return
    try:
        from tkinter import font as _tkfont
        available = set(_tkfont.families())

        def _detect(candidates):
            """Internal: detect.
            
            Args:
                candidates: Description.
            """
            for f in candidates:
                if f in available:
                    return f
            return "TkDefaultFont"  # 最终回退：系统默认字体

        if _IS_WINDOWS:
            SYSTEM_FONT = _detect([
                "Microsoft YaHei", "Microsoft YaHei UI",
                "DengXian", "SimHei", "SimSun",
                "Noto Sans SC", "Microsoft JhengHei",
            ])
            MONO_FONT = _detect([
                "Cascadia Code", "Cascadia Mono",
                "Consolas", "Courier New", "Lucida Console",
            ])
        else:
            SYSTEM_FONT = _detect([
                "Noto Sans CJK SC", "Noto Sans SC",
                "WenQuanYi Micro Hei", "Source Han Sans SC",
                "DejaVu Sans",
            ])
            MONO_FONT = _detect([
                "Noto Sans Mono CJK SC", "DejaVu Sans Mono",
                "Source Han Mono SC", "Courier New",
            ])
        # DEBUG: 打印检测结果，方便排查字体问题
        logging.getLogger("tea_agent").debug(
            f"字体检测: SYSTEM={SYSTEM_FONT}, MONO={MONO_FONT}"
        )
    except Exception as e:
# NOTE: 2026-05-29 07:53:07, self-evolved by tea_agent --- 合并重复的 global 声明
        logging.getLogger("tea_agent").warning(
            f"字体检测失败: {e}，使用默认字体"
        )

    try:
        import tkinter as _tk2
        root = _tk2._default_root
        if root:
            sf = float(root.tk.call("tk", "scaling"))
            if 1.0 < sf <= 4.0:
                _SCALE_FACTOR = sf
    except Exception:
        pass
    _DEFAULT_FONT_SIZE = max(12, int(16 * _SCALE_FACTOR))

    _FONTS_DETECTED = True
