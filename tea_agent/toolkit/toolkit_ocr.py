import logging

logger = logging.getLogger("toolkit")

def toolkit_ocr(action: str, image_path: str = None, image_base64: str = None,
                region: str = None, lang: str = "zh-CN", output: str = None):
    """
    OCR 文字识别工具。

    action='recognize': 识别图片中的文字
    action='screenshot_ocr': 截图并识别文字

    返回:
        {'ok': True, 'text': '识别的文字'}
    """
    logger.info(f"toolkit_ocr called: action={action!r}, image_path={image_path!r}")

    import os, sys, json, base64, tempfile

    if action == "recognize":
        return _ocr_recognize(image_path, image_base64, lang, output)
    elif action == "screenshot_ocr":
        return _ocr_screenshot(region, lang, output)
    else:
        return {"ok": False, "error": f"未知 action: {action}"}


def _ocr_recognize(image_path, image_base64, lang, output):
    """识别图片中的文字"""
    import os, tempfile, base64

    if image_path:
        if not os.path.exists(image_path):
            return {"ok": False, "error": f"图片文件不存在: {image_path}"}
        img_path = image_path
    elif image_base64:
        try:
            img_data = base64.b64decode(image_base64)
            tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
            tmp.write(img_data)
            tmp.close()
            img_path = tmp.name
        except Exception as e:
            return {"ok": False, "error": f"base64 解码失败: {e}"}
    else:
        return {"ok": False, "error": "需要提供 image_path 或 image_base64"}

    import sys
    if sys.platform == "win32":
        result = _ocr_windows(img_path, lang)
    else:
        result = _ocr_tesseract(img_path, lang)

    if image_base64 and img_path:
        try: os.unlink(img_path)
        except: pass

    if output and result.get("ok"):
        try:
            with open(output, "w", encoding="utf-8") as f:
                f.write(result.get("text", ""))
            result["output"] = output
        except Exception as e:
            result["output_error"] = str(e)

    return result


def _ocr_windows(image_path, lang):
    """使用 Windows 内置 OCR API（通过 winocr 库）"""
    import sys, os

    # 将 winocr 所在目录添加到 sys.path
    winocr_dir = r"C:\Users\Hetin\venv_work\Lib\site-packages"
    if winocr_dir not in sys.path:
        sys.path.insert(0, winocr_dir)

    try:
        from PIL import Image
        import winocr

        img = Image.open(image_path)

        lang_map = {
            "zh-CN": "zh-Hans-CN", "zh-TW": "zh-Hant-TW",
            "en": "en-US", "ja": "ja-JP", "ko": "ko-KR",
        }
        ocr_lang = lang_map.get(lang, lang)

        result = winocr.recognize_pil_sync(img, ocr_lang)

        text = ""
        if isinstance(result, dict):
            lines = result.get("lines", [])
            for line in lines:
                text += line.get("text", "") + "\n"
        elif isinstance(result, str):
            text = result

        return {"ok": True, "text": text.strip(), "lang": ocr_lang}
    except ImportError:
        return _ocr_tesseract(image_path, lang)
    except Exception as e:
        return {"ok": False, "error": f"Windows OCR 失败: {e}"}


def _ocr_tesseract(image_path, lang):
    """使用 Tesseract OCR"""
    import subprocess, shutil

    tesseract = shutil.which("tesseract")
    if not tesseract:
        return {"ok": False, "error": "未找到 tesseract，请安装: apt install tesseract-ocr 或 brew install tesseract"}

    lang_map = {"zh-CN": "chi_sim", "zh-TW": "chi_tra", "en": "eng", "ja": "jpn", "ko": "kor"}
    tess_lang = lang_map.get(lang, lang)

    try:
        result = subprocess.run(
            [tesseract, image_path, "stdout", "-l", tess_lang],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            return {"ok": True, "text": result.stdout.strip(), "lang": tess_lang}
        else:
            return {"ok": False, "error": f"tesseract 错误: {result.stderr}"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "OCR 超时"}
    except Exception as e:
        return {"ok": False, "error": f"执行异常: {e}"}


def _ocr_screenshot(region, lang, output):
    """截图并识别文字"""
    import tempfile, os

    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    tmp_path = tmp.name
    tmp.close()

    try:
        from tea_agent.toolkit.toolkit_screenshot import toolkit_screenshot
        if region:
            toolkit_screenshot(action="region", region=region, output=tmp_path)
        else:
            toolkit_screenshot(action="full", output=tmp_path)

        if not os.path.exists(tmp_path) or os.path.getsize(tmp_path) < 100:
            return {"ok": False, "error": "截图失败"}
    except Exception as e:
        return {"ok": False, "error": f"截图异常: {e}"}

    ocr_result = _ocr_recognize(tmp_path, None, lang, output)

    try: os.unlink(tmp_path)
    except: pass

    if ocr_result.get("ok"):
        ocr_result["screenshot"] = True
        if region:
            ocr_result["region"] = region

    return ocr_result


def meta_toolkit_ocr():
    """Meta for toolkit_ocr."""
    return {
        "type": "function",
        "function": {
            "name": "toolkit_ocr",
            "description": "OCR 文字识别工具。支持图片文件、截图、base64 图片作为输入，返回识别的文字。Windows 使用内置 OCR API，Linux/macOS 使用 Tesseract。",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["recognize", "screenshot_ocr"], "description": "recognize=识别图片文字, screenshot_ocr=截图并识别"},
                    "image_path": {"type": "string", "description": "[recognize] 图片文件路径"},
                    "image_base64": {"type": "string", "description": "[recognize] base64 编码的图片数据"},
                    "region": {"type": "string", "description": "[screenshot_ocr] 截图区域 'x,y,w,h'"},
                    "lang": {"type": "string", "description": "语言，默认 zh-CN"},
                    "output": {"type": "string", "description": "输出文件路径（可选）"}
                },
                "required": ["action"]
            }
        }
    }
