"""
"""

# 活跃模块由 gui.py 直接 import，此处仅标记包

from . import _fonts as _fonts_mod  # gui.py 使用 from tea_agent._gui import _fonts_mod

_fonts_mod  # 显式引用，抑制 ruff F401
