"""
@2026-07-07 gen by tea_agent, Tooltip 模块
从 gui.py L1527-1600 提取：主题列表鼠标悬停 tooltip
"""

import tkinter as tk
import logging

if __import__('typing').TYPE_CHECKING:
    from tea_agent.gui import TkGUI

from ._fonts import SYSTEM_FONT, _fs

logger = logging.getLogger("main_db_gui")


class TooltipManager:
    """主题列表 Tooltip：鼠标悬停显示创建日期和最后使用日期"""

    def __init__(self, gui):
        self.gui = gui

    def _on_topic_hover(self, event):
        """鼠标在主题列表上移动时，延迟显示 tooltip"""
        gui = self.gui
        item_id = gui.topic_list.identify_row(event.y)
        idx = gui.topic_list.index(item_id) if item_id else -1
        if idx < 0 or idx >= len(gui._topic_cache):
            self._hide_tooltip()
            return

        if gui._topic_hover_after:
            gui.root.after_cancel(gui._topic_hover_after)
            gui._topic_hover_after = None

        gui._topic_hover_after = gui.root.after(
            300, lambda: self._show_tooltip(event, idx)
        )

    def _on_topic_leave(self, event):
        """鼠标离开列表时隐藏 tooltip"""
        gui = self.gui
        if gui._topic_hover_after:
            gui.root.after_cancel(gui._topic_hover_after)
            gui._topic_hover_after = None
        self._hide_tooltip()

    def _show_tooltip(self, event, idx):
        """在鼠标位置显示主题日期 tooltip"""
        gui = self.gui
        if idx < 0 or idx >= len(gui._topic_cache):
            return
        tp = gui._topic_cache[idx]
        create_ts = tp.get("create_stamp", "")
        update_ts = tp.get("last_update_stamp", "")

        def fmt(ts):
            if not ts:
                return "未知"
            s = str(ts)
            return s[:16] if len(s) >= 16 else s

        self._hide_tooltip()

        tip = tk.Toplevel(gui.root)
        tip.overrideredirect(True)
        tip.attributes("-topmost", True)
        tip.configure(bg="#ffffcc")

        lines = [f"📅 创建: {fmt(create_ts)}", f"🕐 最后使用: {fmt(update_ts)}"]
        tip_text = "\n".join(lines)
        label = tk.Label(
            tip, text=tip_text,
            bg="#ffffcc", fg="#333333",
            font=(SYSTEM_FONT, _fs(10)),
            padx=8, pady=4,
            relief=tk.SOLID, borderwidth=1,
        )
        label.pack()

        x = gui.root.winfo_pointerx() + 12
        y = gui.root.winfo_pointery() + 8
        tip.geometry(f"+{x}+{y}")

        gui._topic_tooltip = tip

    def _hide_tooltip(self):
        """隐藏 tooltip"""
        gui = self.gui
        if gui._topic_tooltip:
            try:
                gui._topic_tooltip.destroy()
            except Exception:
                pass
            gui._topic_tooltip = None