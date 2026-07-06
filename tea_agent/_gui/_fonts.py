"""
从 gui.py L84-160 提取：跨平台字体自动检测 + Wayland/X11 显示缩放
"""

import logging
import platform as _platform

logger = logging.getLogger("tea_agent")

_IS_WINDOWS = _platform.system() == "Windows"

SYSTEM_FONT = "TkDefaultFont"
MONO_FONT = "TkFixedFont"

_FONTS_DETECTED = False
_SCALE_FACTOR = 1.0
_DEFAULT_APP_FONT_SIZE = 12  # App GUI 默认基础字体大小
_FONT_SIZE_MULTIPLIER = 1.0   # 字体缩放倍率（_APP_FONT_SIZE / _DEFAULT_APP_FONT_SIZE）
_DEFAULT_FONT_SIZE = _DEFAULT_APP_FONT_SIZE  # 模块级默认（_init_fonts 后会更新）
_HTML_FONT_SIZE = 16          # HtmlFrame 基础字体大小（px）
_APP_FONT_SIZE = _DEFAULT_APP_FONT_SIZE  # App GUI 基础字体大小（pt）

def _fs(size):
    """返回按显示缩放因子和字体倍率调整后的字体大小（受 app_font_size 控制）。"""
    return max(1, int(size * _SCALE_FACTOR * _FONT_SIZE_MULTIPLIER))

def _get_font_size_from_config():
    """从配置文件读取 HtmlFrame 字体大小，失败时返回默认值16"""
    try:
        from tea_agent.config import get_config
        cfg = get_config()
        return cfg.font_size if hasattr(cfg, 'font_size') else 16
    except Exception:
        return 16

def _get_app_font_size_from_config():
    """从配置文件读取 App GUI 字体大小，失败时返回默认值12"""
    try:
        from tea_agent.config import get_config
        cfg = get_config()
        return cfg.app_font_size if hasattr(cfg, 'app_font_size') else _DEFAULT_APP_FONT_SIZE
    except Exception:
        return _DEFAULT_APP_FONT_SIZE
def _init_fonts():
    """延迟检测系统可用字体（需 Tk root 创建后调用）。"""
    global SYSTEM_FONT, MONO_FONT, _FONTS_DETECTED, _SCALE_FACTOR, _DEFAULT_FONT_SIZE, _HTML_FONT_SIZE, _APP_FONT_SIZE, _FONT_SIZE_MULTIPLIER

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
        logging.getLogger("tea_agent").warning(
            f"字体检测失败: {e}，使用默认字体"
        )

    try:
        import tkinter as _tk2
        root = _tk2._default_root
        if root:
            if _IS_WINDOWS:
                # DPI-aware 模式下 tk scaling 报物理 DPI（可能 2.0），
                # 但用户 Windows 缩放设置可能是 150%（1.5x）。
                # 用系统缩放因子更准确，避免 Tk 控件字体过大。
                try:
                    import ctypes
                    scale_pct = ctypes.windll.shcore.GetScaleFactorForDevice(0)
                    sf = scale_pct / 100.0
                except Exception:
                    sf = float(root.tk.call("tk", "scaling"))
            else:
                sf = float(root.tk.call("tk", "scaling"))
            if 1.0 < sf <= 4.0:
                _SCALE_FACTOR = sf
    except Exception:
        logger.exception("operation failed")

    _DEFAULT_FONT_SIZE = max(10, int(16 * _SCALE_FACTOR * _FONT_SIZE_MULTIPLIER))
    # 从配置文件读取用户字体大小
    _HTML_FONT_SIZE = _get_font_size_from_config()
    _APP_FONT_SIZE = _get_app_font_size_from_config()
    # 重算字体缩放倍率，使 _fs() 全线受 app_font_size 控制
    _FONT_SIZE_MULTIPLIER = _APP_FONT_SIZE / _DEFAULT_APP_FONT_SIZE

    # 将 Tk 默认字体大小也乘以缩放因子，保持控件字体与 _fs() 一致
    try:
        from tkinter import font as _tkfont
        for _fname in ["TkDefaultFont", "TkTextFont", "TkMenuFont",
                        "TkHeadingFont", "TkCaptionFont", "TkSmallCaptionFont",
                        "TkIconFont", "TkTooltipFont"]:
            try:
                _f = _tkfont.nametofont(_fname)
                _orig = _f.cget("size")
                if _orig > 0:
                    _f.configure(size=max(1, int(_orig * _SCALE_FACTOR * _FONT_SIZE_MULTIPLIER)))
            except Exception:
                logger.exception("operation failed")

    except Exception:
        logger.exception("operation failed")


    # 配置 Treeview 行高，避免字体重叠
    _configure_treeview_rowheight()

    _FONTS_DETECTED = True


def _configure_treeview_rowheight():
    """配置 Treeview 行高，确保与缩放后的字体匹配。"""
    try:
        import tkinter.ttk as _ttk
        from tkinter import font as _tkfont

        style = _ttk.Style()

        # 获取 Treeview 实际使用的字体大小
        # Treeview 默认使用 TkDefaultFont
        try:
            default_font = _tkfont.nametofont("TkDefaultFont")
            font_size = default_font.cget("size")
            if font_size <= 0:
                font_size = _fs(10)
        except Exception:
            font_size = _fs(10)

        # 计算合适的行高：字体大小 * 2.8 + 4（上下边距）
        # 对于 13 号字体：13 * 2.8 + 4 ≈ 40，中文字符更高需要更大行高
        row_height = max(28, int(font_size * 2.8 + 4))

        style.configure("Treeview", rowheight=row_height)
        # 也配置 Topic.Treeview 样式（主界面使用）
        style.configure("Topic.Treeview", rowheight=row_height)

        logger.debug(f"Treeview 行高配置: font_size={font_size}, rowheight={row_height}")
    except Exception as e:
        logger.debug(f"配置 Treeview 行高失败: {e}")
