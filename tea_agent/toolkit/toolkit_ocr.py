## llm generated tool func, created Tue Jun  2 08:03:14 2026
# version: 1.0.2

import logging

logger = logging.getLogger("toolkit")

def toolkit_ocr(action: str, image_path: str = None, image_base64: str = None,
                region: str = None, lang: str = "zh-CN", output: str = None):
    """
    OCR 文字识别工具。
    
    action='recognize': 识别图片中的文字
        toolkit_ocr(action='recognize', image_path='/path/to/image.png')
        toolkit_ocr(action='recognize', image_base64='base64data...')
    
    action='screenshot_ocr': 截图并识别文字
        toolkit_ocr(action='screenshot_ocr')
        toolkit_ocr(action='screenshot_ocr', region='100,200,800,600')
    
    返回:
        {'ok': True, 'text': '识别的文字', 'confidence': 0.95}
    """
    logger.info(f"toolkit_ocr called: action={action!r}, image_path={image_path!r}")
    
    import os
    import sys
    import json
    import base64
    import tempfile
    
    if action == "recognize":
        return _ocr_recognize(image_path, image_base64, lang, output)
    elif action == "screenshot_ocr":
        return _ocr_screenshot(region, lang, output)
    else:
        return {"ok": False, "error": f"未知 action: {action}"}


def _ocr_recognize(image_path: str, image_base64: str, lang: str, output: str):
    """识别图片中的文字"""
    import os
    import tempfile
    import base64
    
    # 获取图片路径
    if image_path:
        if not os.path.exists(image_path):
            return {"ok": False, "error": f"图片文件不存在: {image_path}"}
        img_path = image_path
    elif image_base64:
        # 保存 base64 到临时文件
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
    
    # 根据平台选择 OCR 方法
    import sys
    if sys.platform == "win32":
        result = _ocr_windows(img_path, lang)
    else:
        result = _ocr_tesseract(img_path, lang)
    
    # 清理临时文件
    if image_base64 and img_path:
        try:
            os.unlink(img_path)
        except:
            pass
    
    # 保存结果
    if output and result.get("ok"):
        try:
            with open(output, "w", encoding="utf-8") as f:
                f.write(result.get("text", ""))
            result["output"] = output
        except Exception as e:
            result["output_error"] = str(e)
    
    return result


def _ocr_windows(image_path: str, lang: str):
    """使用 Windows 内置 OCR API（通过 winocr 库）"""
    import sys
    import os
    
    # 将 winocr 所在目录添加到 sys.path
    winocr_dir = r"C:\Users\Hetin\venv_work\Lib\site-packages"
    if winocr_dir not in sys.path:
        sys.path.insert(0, winocr_dir)
    
    try:
        from PIL import Image
        import winocr
        
        # 读取图片
        img = Image.open(image_path)
        
        # 语言映射
        lang_map = {
            "zh-CN": "zh-Hans-CN",
            "zh-TW": "zh-Hant-TW",
            "en": "en-US",
            "ja": "ja-JP",
            "ko": "ko-KR",
        }
        ocr_lang = lang_map.get(lang, lang)
        
        # 执行 OCR
        result = winocr.recognize_pil_sync(img, ocr_lang)
        
        # 提取文本
        text = ""
        if isinstance(result, dict):
            lines = result.get("lines", [])
            for line in lines:
                text += line.get("text", "") + "\n"
        elif isinstance(result, str):
            text = result
        
        return {
            "ok": True,
            "text": text.strip(),
            "lang": ocr_lang
        }
    except ImportError as e:
        # 如果 winocr 不可用，尝试 tesseract
        return _ocr_tesseract(image_path, lang)
    except Exception as e:
        return {"ok": False, "error": f"Windows OCR 失败: {e}"}


def _ocr_tesseract(image_path: str, lang: str):
    """使用 Tesseract OCR（Linux/macOS/Windows）"""
    import subprocess
    import shutil
    
    # 检查 tesseract 是否安装
    tesseract = shutil.which("tesseract")
    if not tesseract:
        return {"ok": False, "error": "未找到 tesseract，请安装: apt install tesseract-ocr 或 brew install tesseract"}
    
    # 语言映射
    lang_map = {
        "zh-CN": "chi_sim",
        "zh-TW": "chi_tra",
        "en": "eng",
        "ja": "jpn",
        "ko": "kor",
    }
    tess_lang = lang_map.get(lang, lang)
    
    try:
        result = subprocess.run(
            [tesseract, image_path, "stdout", "-l", tess_lang],
            capture_output=True, text=True, timeout=30
        )
        
        if result.returncode == 0:
            return {
                "ok": True,
                "text": result.stdout.strip(),
                "lang": tess_lang
            }
        else:
            return {"ok": False, "error": f"tesseract 错误: {result.stderr}"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "OCR 超时"}
    except Exception as e:
        return {"ok": False, "error": f"执行异常: {e}"}


def _ocr_screenshot(region: str, lang: str, output: str):
    """截图并识别文字"""
    import tempfile
    import os
    
    # 截图
    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    tmp_path = tmp.name
    tmp.close()
    
    try:
        from tea_agent.toolkit.toolkit_screenshot import toolkit_screenshot
        if region:
            result = toolkit_screenshot(action="region", region=region, output=tmp_path)
        else:
            result = toolkit_screenshot(action="full", output=tmp_path)
        
        if not os.path.exists(tmp_path) or os.path.getsize(tmp_path) < 100:
            return {"ok": False, "error": f"截图失败: {result}"}
    except Exception as e:
        return {"ok": False, "error": f"截图异常: {e}"}
    
    # OCR
    ocr_result = _ocr_recognize(tmp_path, None, lang, output)
    
    # 清理临时文件
    try:
        os.unlink(tmp_path)
    except:
        pass
    
    # 添加截图信息
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


def meta_toolkit_ocr() -> dict:
    return {"type": "function", "function": {"name": "toolkit_ocr", "description": "OCR 文字识别工具。支持图片文件、截图、base64 图片作为输入，返回识别的文字。Windows 使用内置 OCR API，Linux/macOS 使用 Tesseract。", "parameters": {"type": "object", "properties": {"action": {"type": "string", "enum": ["recognize", "screenshot_ocr"], "description": "recognize=识别图片文字, screenshot_ocr=截图并识别"}, "image_path": {"type": "string", "description": "[recognize] 图片文件路径"}, "image_base64": {"type": "string", "description": "[recognize] base64 编码的图片数据"}, "region": {"type": "string", "description": "[screenshot_ocr] 截图区域 'x,y,w,h'"}, "lang": {"type": "string", "description": "语言，默认 zh-CN"}, "output": {"type": "string", "description": "输出文件路径（可选）"}}, "required": ["action"]}}}
