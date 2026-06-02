import logging

logger = logging.getLogger("toolkit")

def toolkit_browser_tab(action: str, browser: str = "firefox", tab_title: str = None,
                        window_index: int = 0):
    """
    浏览器标签管理工具。

    action='activate_tab': 激活指定标签
    action='list_tabs': 列出所有标签
    action='get_active_tab': 获取当前标签
    """
    logger.info(f"toolkit_browser_tab called: action={action!r}, browser={browser!r}, tab_title={tab_title!r}")

    import os
    import sys
    import json
    import time
    import subprocess
    import ctypes
    import ctypes.wintypes
    from ctypes import wintypes

    # Windows API 常量
    SW_RESTORE = 9
    SW_SHOW = 5

    user32 = ctypes.windll.user32

    def get_foreground_window():
        return user32.GetForegroundWindow()

    def set_foreground_window(hwnd):
        user32.SetForegroundWindow(hwnd)

    def show_window(hwnd, cmd_show):
        user32.ShowWindow(hwnd, cmd_show)

    def get_window_text(hwnd):
        length = user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return ""
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        return buffer.value

    def enum_windows(callback):
        EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
        user32.EnumWindows(EnumWindowsProc(callback), 0)

    def find_browser_windows(browser_name):
        windows = []
        browser_name_lower = browser_name.lower()

        def callback(hwnd, lparam):
            title = get_window_text(hwnd)
            if not title:
                return True

            if browser_name_lower == "firefox" and "firefox" in title.lower():
                windows.append({"hwnd": hwnd, "title": title})
            elif browser_name_lower == "chrome" and "chrome" in title.lower():
                windows.append({"hwnd": hwnd, "title": title})
            elif browser_name_lower == "edge" and ("edge" in title.lower() or "microsoft" in title.lower()):
                windows.append({"hwnd": hwnd, "title": title})
            return True

        enum_windows(callback)
        return windows

    # 查找浏览器窗口
    browser_windows = find_browser_windows(browser)

    if not browser_windows:
        return {"ok": False, "error": f"未找到 {browser} 窗口"}

    if action == "list_tabs":
        tabs = []
        for i, win in enumerate(browser_windows):
            tabs.append({
                "index": i,
                "title": win["title"],
                "hwnd": win["hwnd"]
            })
        return {"ok": True, "browser": browser, "tabs": tabs, "count": len(tabs)}

    elif action == "get_active_tab":
        hwnd = get_foreground_window()
        title = get_window_text(hwnd)
        return {"ok": True, "browser": browser, "active_tab": title, "hwnd": hwnd}

    elif action == "activate_tab":
        if not tab_title:
            return {"ok": False, "error": "activate_tab 需要 tab_title 参数"}

        tab_title_lower = tab_title.lower()
        matched_window = None

        for win in browser_windows:
            if tab_title_lower in win["title"].lower():
                matched_window = win
                break

        if not matched_window:
            return {
                "ok": False,
                "error": f"未找到包含 '{tab_title}' 的标签",
                "available_tabs": [w["title"] for w in browser_windows]
            }

        hwnd = matched_window["hwnd"]

        if user32.IsIconic(hwnd):
            show_window(hwnd, SW_RESTORE)
            time.sleep(0.3)

        set_foreground_window(hwnd)
        time.sleep(0.2)

        current_fg = get_foreground_window()
        success = current_fg == hwnd

        return {
            "ok": success,
            "activated": matched_window["title"],
            "hwnd": hwnd,
            "success": success
        }

    else:
        return {"ok": False, "error": f"未知 action: {action}"}
