## llm generated tool func, created Tue Jun  2 08:08:50 2026
# version: 1.0.0

import logging

logger = logging.getLogger("toolkit")

def toolkit_browser_tab(action: str, browser: str = "firefox", tab_title: str = None,
                        window_index: int = 0):
    """
    浏览器标签管理工具。

    action='activate_tab': 激活指定标签
        toolkit_browser_tab(action='activate_tab', browser='firefox', tab_title='智能研修平台')

    action='list_tabs': 列出所有标签
        toolkit_browser_tab(action='list_tabs', browser='firefox')

    action='get_active_tab': 获取当前标签
        toolkit_browser_tab(action='get_active_tab', browser='firefox')

    返回:
        {'ok': True, 'tabs': [...]} 或 {'ok': True, 'activated': '标签名'}
    """
    logger.info(f"toolkit_browser_tab called: action={action!r}, browser={browser!r}, tab_title={tab_title!r}")

    import sys

    # 平台检测
    is_windows = sys.platform == "win32"

    if is_windows:
        return _windows_browser_tab(action, browser, tab_title, window_index)
    else:
        return _linux_browser_tab(action, browser, tab_title, window_index)

def _windows_browser_tab(action, browser, tab_title, window_index):
    """Windows 平台实现"""
    import time
    import ctypes
    import ctypes.wintypes
    from ctypes import wintypes

    # Windows API 常量
    SW_RESTORE = 9
    SW_SHOW = 5
    GW_OWNER = 4

    # 获取前台窗口
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
        """枚举所有顶层窗口"""
        EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
        user32.EnumWindows(EnumWindowsProc(callback), 0)

    def find_browser_windows(browser_name):
        """查找浏览器窗口"""
        windows = []
        browser_name_lower = browser_name.lower()

        def callback(hwnd, lparam):
            title = get_window_text(hwnd)
            if not title:
                return True

            # 根据浏览器类型匹配
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
        # 返回所有窗口标题（标签页信息）
        tabs = []
        for i, win in enumerate(browser_windows):
            tabs.append({
                "index": i,
                "title": win["title"],
                "hwnd": win["hwnd"]
            })
        return {"ok": True, "browser": browser, "tabs": tabs, "count": len(tabs)}

    elif action == "get_active_tab":
        # 获取当前活动窗口
        hwnd = get_foreground_window()
        title = get_window_text(hwnd)
        return {"ok": True, "browser": browser, "active_tab": title, "hwnd": hwnd}

    elif action == "activate_tab":
        if not tab_title:
            return {"ok": False, "error": "activate_tab 需要 tab_title 参数"}

        # 查找匹配的标签
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

        # 激活窗口
        hwnd = matched_window["hwnd"]

        # 如果窗口最小化，先恢复
        if user32.IsIconic(hwnd):
            show_window(hwnd, SW_RESTORE)
            time.sleep(0.3)

        # 设置为前台窗口
        set_foreground_window(hwnd)
        time.sleep(0.2)

        # 验证是否成功激活
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

def _linux_browser_tab(action, browser, tab_title, window_index):
    """Linux 平台实现（使用 xdotool/wmctrl）"""
    import subprocess

    try:
        # 使用 wmctrl 列出窗口
        result = subprocess.run(["wmctrl", "-l"], capture_output=True, text=True, timeout=5)
        if result.returncode != 0:
            return {"ok": False, "error": "wmctrl 未安装，请运行: sudo apt install wmctrl"}

        windows = []
        for line in result.stdout.strip().split("\n"):
            if line:
                parts = line.split(None, 3)
                if len(parts) >= 4:
                    windows.append({
                        "id": parts[0],
                        "desktop": parts[1],
                        "title": parts[3]
                    })

        # 过滤浏览器窗口
        browser_windows = [w for w in windows if browser.lower() in w["title"].lower()]

        if action == "list_tabs":
            return {"ok": True, "browser": browser, "tabs": browser_windows, "count": len(browser_windows)}

        elif action == "activate_tab":
            if not tab_title:
                return {"ok": False, "error": "activate_tab 需要 tab_title 参数"}

            matched = None
            for w in browser_windows:
                if tab_title.lower() in w["title"].lower():
                    matched = w
                    break

            if not matched:
                return {"ok": False, "error": f"未找到包含 '{tab_title}' 的标签"}

            # 使用 wmctrl 激活窗口
            subprocess.run(["wmctrl", "-i", "-a", matched["id"]], timeout=5)
            return {"ok": True, "activated": matched["title"]}

    except FileNotFoundError:
        return {"ok": False, "error": "wmctrl 未安装，请运行: sudo apt install wmctrl"}

    return {"ok": False, "error": f"未知 action: {action}"}


def meta_toolkit_browser_tab() -> dict:
    return {"type": "function", "function": {"name": "toolkit_browser_tab", "description": "浏览器标签管理工具。可以激活指定浏览器窗口、切换到指定标签页、获取标签列表。支持 Firefox、Chrome 等主流浏览器。", "parameters": {"type": "object", "properties": {"action": {"type": "string", "enum": ["activate_tab", "list_tabs", "get_active_tab"], "description": "activate_tab=激活指定标签, list_tabs=列出所有标签, get_active_tab=获取当前标签"}, "browser": {"type": "string", "description": "浏览器名称，如 firefox, chrome, edge", "default": "firefox"}, "tab_title": {"type": "string", "description": "[activate_tab] 标签标题（支持部分匹配）"}, "window_index": {"type": "integer", "description": "窗口索引（0=第一个窗口）", "default": 0}}, "required": ["action"]}}}
