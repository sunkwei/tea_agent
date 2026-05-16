"""
@2026-05-16 gen by tea_agent, GUI 主入口 — python -m tea_agent.gui

此文件是 GUI 的活跃开发目标，未来修改优先在此进行。
如遇严重问题，可使用 python -m tea_agent.main_db_gui 回退到备份版本。
"""

# 从 main_db_gui 导入核心功能（保持 main_db_gui.py 为备份）
from .main_db_gui import main, TkGUI

__all__ = ["main", "TkGUI"]

if __name__ == "__main__":
    main()
