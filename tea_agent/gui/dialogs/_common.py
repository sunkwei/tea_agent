# -*- coding: utf-8 -*-
# @2026-05-17 gen by tea_agent, GUI 对话框共享工具模块
"""GUI 对话框公共组件：字体检测、跨平台适配"""
import platform as _platform
import tkinter as tk

_IS_WINDOWS = _platform.system() == "Windows"
SYSTEM_FONT = "TkDefaultFont"
MONO_FONT = "TkFixedFont"
_FONTS_DETECTED = False
_SCALE_FACTOR = 1.0
_DEFAULT_FONT_SIZE = 16


def _fs(size):
    """返回按显示缩放因子调整后的字体大小。"""
    return max(1, int(size * _SCALE_FACTOR))


def _init_fonts():
    """延迟检测系统可用字体（需 Tk root 创建后调用）。"""
    global SYSTEM_FONT, MONO_FONT, _FONTS_DETECTED, _SCALE_FACTOR, _DEFAULT_FONT_SIZE
    if _FONTS_DETECTED:
        return
    try:
        from tkinter import font as _tkfont
        available = set(_tkfont.families())

        def _detect(candidates):
            for f in candidates:
                if f in available:
                    return f
            return "TkDefaultFont"

        if _IS_WINDOWS:
            SYSTEM_FONT = _detect(["Microsoft YaHei", "Microsoft YaHei UI", "DengXian", "SimHei", "SimSun", "Noto Sans SC", "Microsoft JhengHei"])
            MONO_FONT = _detect(["Cascadia Code", "Cascadia Mono", "Consolas", "Courier New", "Lucida Console"])
        else:
            SYSTEM_FONT = _detect(["Noto Sans CJK SC", "Noto Sans SC", "WenQuanYi Micro Hei", "Source Han Sans SC", "DejaVu Sans"])
            MONO_FONT = _detect(["Noto Sans Mono CJK SC", "DejaVu Sans Mono", "Source Han Mono SC", "Courier New"])
    except Exception:
        pass

    try:
        root = tk._default_root
        if root:
            sf = float(root.tk.call("tk", "scaling"))
            if 1.0 < sf <= 4.0:
                _SCALE_FACTOR = sf
    except Exception:
        pass

    _DEFAULT_FONT_SIZE = max(12, int(16 * _SCALE_FACTOR))
    _FONTS_DETECTED = True
