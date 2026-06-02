import logging

logger = logging.getLogger("toolkit")

def toolkit_screen_read(action: str, browser: str = "firefox", tab_title: str = None,
                        region: str = None, lang: str = "zh-CN", output: str = None):
    """
    屏幕内容读取工具 - 组合截图、OCR、浏览器标签管理。

    action='read_tab': 读取浏览器标签内容
    action='read_region': 读取屏幕指定区域
    action='read_window': 读取当前活动窗口
    """
    logger.info(f"toolkit_screen_read called: action={action!r}, browser={browser!r}, tab_title={tab_title!r}")

    import os
    import sys
    import json
    import time
    import tempfile

    # 延迟导入工具函数（避免循环依赖）
    def get_toolkit_func(name):
        import importlib
        module = importlib.import_module(f"tea_agent.toolkit.{name}")
        return getattr(module, name)

    if action == "read_tab":
        if not tab_title:
            return {"ok": False, "error": "read_tab 需要 tab_title 参数"}

        # 1. 激活浏览器标签
        try:
            browser_tab = get_toolkit_func("toolkit_browser_tab")
            result = browser_tab(
                action="activate_tab",
                browser=browser,
                tab_title=tab_title
            )
            if not result.get("ok"):
                return result
        except Exception as e:
            return {"ok": False, "error": f"激活标签失败: {str(e)}"}

        # 2. 等待窗口激活完成
        time.sleep(0.5)

        # 3. 截图
        try:
            screenshot = get_toolkit_func("toolkit_screenshot")
            screenshot_path = tempfile.mktemp(suffix=".png")
            screenshot_result = screenshot(action="full", output=screenshot_path)
            if not screenshot_result.get("success"):
                return {"ok": False, "error": f"截图失败: {screenshot_result.get('error', '未知错误')}"}
        except Exception as e:
            return {"ok": False, "error": f"截图失败: {str(e)}"}

        # 4. OCR 识别
        try:
            ocr = get_toolkit_func("toolkit_ocr")
            ocr_result = ocr(action="recognize", image_path=screenshot_path, lang=lang)
            if not ocr_result.get("ok"):
                return {"ok": False, "error": f"OCR 失败: {ocr_result.get('error', '未知错误')}"}

            text = ocr_result.get("text", "")
        except Exception as e:
            return {"ok": False, "error": f"OCR 失败: {str(e)}"}

        # 5. 清理临时文件
        try:
            if os.path.exists(screenshot_path):
                os.remove(screenshot_path)
        except:
            pass

        # 6. 保存结果（可选）
        if output:
            try:
                with open(output, "w", encoding="utf-8") as f:
                    f.write(text)
            except Exception as e:
                logger.warning(f"保存 OCR 结果失败: {e}")

        return {
            "ok": True,
            "text": text,
            "title": result.get("activated", tab_title),
            "browser": browser,
            "lang": lang
        }

    elif action == "read_region":
        if not region:
            return {"ok": False, "error": "read_region 需要 region 参数 (格式: 'x,y,w,h')"}

        # 1. 截取指定区域
        try:
            screenshot = get_toolkit_func("toolkit_screenshot")
            screenshot_path = tempfile.mktemp(suffix=".png")
            screenshot_result = screenshot(action="region", region=region, output=screenshot_path)
            if not screenshot_result.get("success"):
                return {"ok": False, "error": f"截图失败: {screenshot_result.get('error', '未知错误')}"}
        except Exception as e:
            return {"ok": False, "error": f"截图失败: {str(e)}"}

        # 2. OCR 识别
        try:
            ocr = get_toolkit_func("toolkit_ocr")
            ocr_result = ocr(action="recognize", image_path=screenshot_path, lang=lang)
            if not ocr_result.get("ok"):
                return {"ok": False, "error": f"OCR 失败: {ocr_result.get('error', '未知错误')}"}

            text = ocr_result.get("text", "")
        except Exception as e:
            return {"ok": False, "error": f"OCR 失败: {str(e)}"}

        # 3. 清理临时文件
        try:
            if os.path.exists(screenshot_path):
                os.remove(screenshot_path)
        except:
            pass

        # 4. 保存结果（可选）
        if output:
            try:
                with open(output, "w", encoding="utf-8") as f:
                    f.write(text)
            except Exception as e:
                logger.warning(f"保存 OCR 结果失败: {e}")

        return {
            "ok": True,
            "text": text,
            "region": region,
            "lang": lang
        }

    elif action == "read_window":
        # 1. 获取当前活动窗口标题
        try:
            browser_tab = get_toolkit_func("toolkit_browser_tab")
            result = browser_tab(action="get_active_tab", browser=browser)
            title = result.get("active_tab", "未知窗口")
        except:
            title = "未知窗口"

        # 2. 截图
        try:
            screenshot = get_toolkit_func("toolkit_screenshot")
            screenshot_path = tempfile.mktemp(suffix=".png")
            screenshot_result = screenshot(action="full", output=screenshot_path)
            if not screenshot_result.get("success"):
                return {"ok": False, "error": f"截图失败: {screenshot_result.get('error', '未知错误')}"}
        except Exception as e:
            return {"ok": False, "error": f"截图失败: {str(e)}"}

        # 3. OCR 识别
        try:
            ocr = get_toolkit_func("toolkit_ocr")
            ocr_result = ocr(action="recognize", image_path=screenshot_path, lang=lang)
            if not ocr_result.get("ok"):
                return {"ok": False, "error": f"OCR 失败: {ocr_result.get('error', '未知错误')}"}

            text = ocr_result.get("text", "")
        except Exception as e:
            return {"ok": False, "error": f"OCR 失败: {str(e)}"}

        # 4. 清理临时文件
        try:
            if os.path.exists(screenshot_path):
                os.remove(screenshot_path)
        except:
            pass

        # 5. 保存结果（可选）
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
            "lang": lang
        }

    else:
        return {"ok": False, "error": f"未知 action: {action}，支持: read_tab/read_region/read_window"}
