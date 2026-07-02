import logging
import os
import tempfile
import time

logger = logging.getLogger("toolkit")


def toolkit_screen_read(action: str, browser: str = "firefox", tab_title: str = None,
                        region: str = None, lang: str = "zh-CN", output: str = None):
    """
    屏幕内容读取工具 - 截图 + OCR 一体化。
    使用系统截图（非浏览器CDP），适合本地桌面场景。

    action='read_tab': 激活浏览器标签 → 截图 → OCR
        toolkit_screen_read(action='read_tab', browser='firefox', tab_title='智能研修平台')

    action='read_region': 截取屏幕区域 → OCR
        toolkit_screen_read(action='read_region', region='100,200,800,600')

    action='read_window': 截取当前活动窗口 → OCR
        toolkit_screen_read(action='read_window')

    返回:
        {'ok': True, 'text': 'OCR识别的文字', 'title': '窗口/标签标题'}
    """
    logger.info(f"toolkit_screen_read: action={action!r}, tab_title={tab_title!r}")

    # 延迟导入（避免循环依赖）
    def _import(name):
        import importlib
        mod = importlib.import_module(f"tea_agent.toolkit.{name}")
        return getattr(mod, name)

    # ── 系统截图 ──
    def _system_screenshot() -> str:
        """返回截图文件路径，失败抛异常"""
        path = tempfile.mktemp(suffix=".png")
        ss = _import("toolkit_screenshot")
        r = ss(action="full", output=path)
        if r.get("success") and os.path.getsize(path) > 100:
            return path
        raise RuntimeError(f"系统截图失败: {r.get('error', '未知')}")

    # ── OCR ──
    def _ocr_image(img_path: str) -> str:
        ocr = _import("toolkit_ocr")
        r = ocr(action="recognize", image_path=img_path, lang=lang)
        if not r.get("ok"):
            raise RuntimeError(f"OCR 失败: {r.get('error', '未知')}")
        return r.get("text", "")

    # ── 根据 action 分发 ──
    title = tab_title or ""

    if action == "read_tab":
        if not tab_title:
            return {"ok": False, "error": "read_tab 需要 tab_title 参数"}

        # 激活浏览器标签
        try:
            bt = _import("toolkit_browser_tab")
            r = bt(action="activate_tab", browser=browser, tab_title=tab_title)
            if not r.get("ok"):
                return r
            title = r.get("activated", tab_title)
        except Exception as e:
            return {"ok": False, "error": f"激活标签失败: {e}"}

        time.sleep(0.5)

        # 系统截图
        try:
            img_path = _system_screenshot()
        except RuntimeError as e:
            return {"ok": False, "error": str(e)}

    elif action == "read_region":
        if not region:
            return {"ok": False, "error": "read_region 需要 region 参数 (格式: 'x,y,w,h')"}
        try:
            img_path = tempfile.mktemp(suffix=".png")
            ss = _import("toolkit_screenshot")
            r = ss(action="region", region=region, output=img_path)
            if not r.get("success"):
                return {"ok": False, "error": f"截图失败: {r.get('error')}"}
        except Exception as e:
            return {"ok": False, "error": f"截图失败: {e}"}

    elif action == "read_window":
        try:
            bt = _import("toolkit_browser_tab")
            r = bt(action="get_active_tab", browser=browser)
            title = r.get("active_tab", "未知窗口")
        except Exception:
            title = "未知窗口"
        try:
            img_path = _system_screenshot()
        except RuntimeError as e:
            return {"ok": False, "error": str(e)}

    else:
        return {"ok": False, "error": f"未知 action: {action}，支持: read_tab/read_region/read_window"}

    # ── OCR ──
    try:
        text = _ocr_image(img_path)
    except RuntimeError as e:
        try:
            os.remove(img_path)
        except Exception:
            pass
        return {"ok": False, "error": str(e)}

    # ── 清理临时文件 ──
    try:
        os.remove(img_path)
    except Exception:
        pass

    # 保存结果（可选）
    if output:
        try:
            with open(output, "w", encoding="utf-8") as f:
                f.write(text)
        except Exception as e:
            logger.warning(f"保存 OCR 结果失败: {e}")

    return {
        "ok": True,
        "text": text,
        "title": title,
        "lang": lang,
    }


def meta_toolkit_screen_read() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "toolkit_screen_read",
            "description": "屏幕内容读取工具 - 截图 + OCR 一体化。支持浏览器标签内容读取、屏幕区域读取、当前窗口读取。通过系统截图方式（非浏览器CDP），适合本地桌面场景。",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["read_tab", "read_region", "read_window"],
                        "description": "read_tab=激活标签+截图+OCR, read_region=截取屏幕区域, read_window=截取当前窗口"
                    },
                    "browser": {
                        "type": "string",
                        "description": "[read_tab] 浏览器名称",
                        "default": "firefox"
                    },
                    "tab_title": {
                        "type": "string",
                        "description": "[read_tab] 标签标题（支持部分匹配）"
                    },
                    "region": {
                        "type": "string",
                        "description": "[read_region] 区域 'x,y,w,h'"
                    },
                    "lang": {
                        "type": "string",
                        "description": "OCR 语言",
                        "default": "zh-CN"
                    },
                    "output": {
                        "type": "string",
                        "description": "OCR 结果输出文件路径（可选）"
                    }
                },
                "required": ["action"]
            }
        }
    }
