# @2026-04-30 gen by deepseek-v4-pro, toolkit_ocr: "眼睛" — 截屏 + OCR 文字识别，让 Agent 能"看到"屏幕
"""toolkit_ocr — 屏幕视觉能力：截屏 + OCR 文字识别"""


# NOTE: 2026-04-30 16:56:08, self-evolved by tea_agent --- 新增monitor参数支持多显示器截图（mss按索引截屏）
def toolkit_ocr(
    action: str = "ocr_screen",
    region: str = "",
    monitor: int = -1,
    image_path: str = "",
    lang: str = "ch_sim,en",
    detail: str = "full",
    timeout: int = 30,
) -> str:
    """
    屏幕文字识别（OCR）— Agent 的'眼睛'。

    Args:
        action: 操作类型
            - 'screenshot': 只截图，保存并返回路径
            - 'ocr_screen': 截屏并 OCR 识别（默认）
            - 'ocr_file': 识别指定图片文件
        region: 截取区域 'x,y,w,h'（如 '100,200,800,600'），空=全屏
        monitor: 显示器索引（0=全部桌面, 1=主屏, 2=第二屏...），默认 -1 表示用 region
        image_path: [ocr_file] 图片文件路径
        lang: OCR 语言，逗号分隔（如 'ch_sim,en', 'en', 'ja'）
        detail: 'full'=完整位置信息, 'simple'=仅文字列表
        timeout: OCR 超时秒数（easyocr 首次加载模型可能较慢）

    Returns:
        结构化识别结果
    """
    import json
    import os
    import time
    from pathlib import Path

    # --- 内部：懒加载 easyocr ---
    def _get_reader(langs):
        # 使用闭包缓存
        if not hasattr(_get_reader, '_reader'):
            import easyocr
            _get_reader._reader = easyocr.Reader(list(langs), gpu=False)
            _get_reader._langs = langs
        elif _get_reader._langs != langs:
            import easyocr
            _get_reader._reader = easyocr.Reader(list(langs), gpu=False)
            _get_reader._langs = langs
        return _get_reader._reader

# NOTE: 2026-04-30 16:56:31, self-evolved by tea_agent --- _screenshot支持monitor_idx参数，优先用mss按显示器索引截图
    # --- 内部：截屏（支持 region / monitor 两种模式）---
    def _screenshot(reg, mon_idx=-1):
        import time
        from pathlib import Path

# NOTE: 2026-05-04 17:56:50, self-evolved by tea_agent --- toolkit_ocr screenshots 路径从 config.paths 读取
        try:
            from tea_agent.config import get_config
            tmp_dir = Path(get_config().paths.data_dir_abs) / "screenshots"
        except Exception:
            tmp_dir = Path.home() / ".tea_agent" / "screenshots"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S")
        fpath = str(tmp_dir / f"screenshot_{ts}.png")

        # 优先 mss 按显示器索引截图（更可靠，支持多屏）
        if mon_idx >= 0:
            import mss as mss_lib
            with mss_lib.MSS() as sct:
                if mon_idx < len(sct.monitors):
                    sct.shot(mon=mon_idx, output=fpath)
                    return fpath
                # 索引无效，回退到 region/pyautogui
        elif reg and len(reg) == 4:
            import pyautogui
            from PIL import Image
            x, y, w, h = reg
            img = pyautogui.screenshot(region=(x, y, w, h))
            img.save(fpath)
            return fpath

        # 全屏截图（pyautogui fallback）
        import pyautogui
        img = pyautogui.screenshot()
        img.save(fpath)
        return fpath

    langs = tuple(l.strip() for l in lang.split(",") if l.strip())

    # --- screenshot action ---
    if action == "screenshot":
        reg = None
        if region:
            try:
                parts = [int(x.strip()) for x in region.split(",")]
                if len(parts) == 4:
                    reg = tuple(parts)
            except ValueError:
                return "❌ region 格式错误，应为 'x,y,w,h'（如 '100,200,800,600'）"
# NOTE: 2026-04-30 16:56:39, self-evolved by tea_agent --- _screenshot调用点传入monitor参数
        fpath = _screenshot(reg, monitor)
        try:
            from PIL import Image
            img = Image.open(fpath)
            w, h = img.size
            return json.dumps({
                "action": "screenshot",
                "path": fpath,
                "size": f"{w}x{h}",
                "region": list(reg) if reg else "fullscreen",
            }, ensure_ascii=False, indent=2)
        except Exception:
            return f"✅ 截图已保存: {fpath}"

    # --- determine image ---
    if action == "ocr_file":
        if not image_path:
            return "❌ ocr_file 需要提供 image_path 参数"
        if not os.path.exists(image_path):
            return f"❌ 文件不存在: {image_path}"
        img_source = image_path
        reg = None
    else:  # ocr_screen
        reg = None
        if region:
            try:
                parts = [int(x.strip()) for x in region.split(",")]
                if len(parts) == 4:
                    reg = tuple(parts)
            except ValueError:
                return "❌ region 格式错误，应为 'x,y,w,h'"
# NOTE: 2026-04-30 16:56:51, self-evolved by tea_agent --- ocr_screen分支的_screenshot调用也传入monitor
        img_source = _screenshot(reg, monitor)

    # --- OCR ---
    try:
        reader = _get_reader(langs)
        results = reader.readtext(img_source, detail=1)

        if not results:
            return json.dumps({
                "action": action,
                "source": img_source,
                "region": list(reg) if reg else "fullscreen",
                "text_count": 0,
                "texts": [],
            }, ensure_ascii=False, indent=2)

        texts = []
        all_text_lines = []
        for bbox, text, confidence in results:
            x_coords = [p[0] for p in bbox]
            y_coords = [p[1] for p in bbox]
            x = int(min(x_coords))
            y = int(min(y_coords))
            w = int(max(x_coords) - x)
            h = int(max(y_coords) - y)
            cx = int(x + w / 2)
            cy = int(y + h / 2)

            texts.append({
                "text": text,
                "confidence": round(confidence, 3),
                "bbox": {"x": x, "y": y, "w": w, "h": h},
                "center": {"x": cx, "y": cy},
            })
            all_text_lines.append(text)

        full_text = "\n".join(all_text_lines)

        if detail == "simple":
            return full_text

        return json.dumps({
            "action": action,
            "source": img_source,
            "region": list(reg) if reg else "fullscreen",
            "text_count": len(texts),
            "full_text": full_text,
            "texts": texts,
        }, ensure_ascii=False, indent=2)

    except Exception as e:
        return f"❌ OCR 失败: {e}"


def meta_toolkit_ocr() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "toolkit_ocr",
# NOTE: 2026-04-30 16:57:08, self-evolved by tea_agent --- 描述增加monitor多屏说明
            "description": "屏幕文字识别（OCR）— Agent 的'眼睛'。可截屏并识别屏幕上的文字，返回文字内容和位置坐标。支持全屏、区域、多显示器（monitor参数）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["screenshot", "ocr_screen", "ocr_file"],
                        "description": "screenshot=仅截图, ocr_screen=截图+OCR, ocr_file=识别文件"
                    },
# NOTE: 2026-04-30 16:57:00, self-evolved by tea_agent --- meta_toolkit_ocr增加monitor参数定义
                    "region": {
                        "type": "string",
                        "description": "截取区域 'x,y,w,h'（如 '100,200,800,600'），空=全屏"
                    },
                    "monitor": {
                        "type": "integer",
                        "description": "显示器索引（0=全部桌面, 1=主屏, 2=第二屏...），默认 -1 不用。优先级高于 region"
                    },
                    "image_path": {
                        "type": "string",
                        "description": "[ocr_file] 图片文件路径"
                    },
                    "lang": {
                        "type": "string",
                        "description": "OCR 语言，逗号分隔。默认 'ch_sim,en'。支持: ch_sim, en, ja, ko 等"
                    },
                    "detail": {
                        "type": "string",
                        "enum": ["full", "simple"],
                        "description": "full=含位置坐标, simple=仅文字列表"
                    }
                },
                "required": ["action"]
            }
        }
    }
