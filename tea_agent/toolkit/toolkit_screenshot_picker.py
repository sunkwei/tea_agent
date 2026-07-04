"""
toolkit_screenshot_picker — 系统级交互式截图选区工具

使用 tkinter 全屏窗口显示截图，让用户在桌面级直接拖拽选择区域。
完全绕过浏览器坐标限制（浏览器窗口位置/DPI缩放/视口偏移等）。

支持：Windows / Linux X11 / macOS
不支持：Wayland（需 XWayland 兼容层）

用法:
  result = toolkit_screenshot_picker(output="/tmp/sel.png")
  # 返回: {"success": true, "path": "...", "width": ..., "height": ...,
  #         "x": ..., "y": ..., "w": ..., "h": ...}
"""

import tkinter as tk
from PIL import Image, ImageTk, ImageGrab
import os, sys, tempfile, logging

logger = logging.getLogger("toolkit")


def toolkit_screenshot_picker(output: str = None):
    """
    交互式截图选区 — 全屏显示截图，用户拖拽选择区域后返回裁剪图片。

    Args:
        output: 输出文件路径，默认临时文件

    Returns:
        dict: {
            "success": bool,
            "path": str,          # 裁剪后的图片文件路径
            "width": int,         # 裁剪图片宽度(物理像素)
            "height": int,        # 裁剪图片高度(物理像素)
            "x": int, "y": int,   # 选区左上角(物理像素)
            "w": int, "h": int,   # 选区宽高(物理像素)
            "error": str          # 失败时
        }
    """
    if output is None:
        output = os.path.join(tempfile.gettempdir(), "screenshot_picker_result.png")

    try:
        return _run_picker(output)
    except Exception as e:
        logger.exception("Screenshot picker failed")
        return {"success": False, "error": str(e)}


def _run_picker(output_path: str) -> dict:
    """内部：运行 tkinter 全屏选区窗口"""
    # 全屏截图（物理像素）
    full_img = ImageGrab.grab()
    phys_w, phys_h = full_img.size

    # 创建 tkinter 全屏窗口
    root = tk.Tk()
    root.attributes("-fullscreen", True)
    root.attributes("-topmost", True)
    root.configure(bg="black")

    logical_w = root.winfo_screenwidth()
    logical_h = root.winfo_screenheight()

    # 缩放比例（物理→逻辑）
    scale_x = phys_w / logical_w
    scale_y = phys_h / logical_h

    # 缩放图片以适应窗口
    display_img = full_img.resize((logical_w, logical_h), Image.LANCZOS)
    tk_img = ImageTk.PhotoImage(display_img)

    # Canvas 显示截图
    canvas = tk.Canvas(
        root,
        width=logical_w,
        height=logical_h,
        highlightthickness=0,
        cursor="crosshair",
    )
    canvas.pack(fill="both", expand=True)
    canvas.create_image(0, 0, anchor="nw", image=tk_img)

    # 半透明遮罩
    mask = canvas.create_rectangle(
        0, 0, logical_w, logical_h,
        fill="black", stipple="gray25", outline="",
    )

    # 状态
    start = {"x": 0, "y": 0}
    rect_id = [None]
    result = [None]  # 存储结果

    def on_press(e):
        start["x"], start["y"] = e.x, e.y
        if rect_id[0]:
            canvas.delete(rect_id[0])
        rect_id[0] = canvas.create_rectangle(
            e.x, e.y, e.x, e.y,
            outline="#00ff88", width=3, dash=(8, 4),
        )
        # 移除遮罩
        canvas.delete(mask)

    def on_drag(e):
        if rect_id[0]:
            canvas.coords(rect_id[0], start["x"], start["y"], e.x, e.y)
            # 显示尺寸信息
            _w, _h = abs(e.x - start["x"]), abs(e.y - start["y"])
            canvas.itemconfig(rect_id[0], width=3)

    def on_release(e):
        x1, y1 = min(start["x"], e.x), min(start["y"], e.y)
        x2, y2 = max(start["x"], e.x), max(start["y"], e.y)
        w, h = x2 - x1, y2 - y1

        if w < 10 or h < 10:
            return  # 选区太小，忽略

        # 转换到物理像素
        px1, py1 = int(x1 * scale_x), int(y1 * scale_y)
        px2, py2 = int(x2 * scale_x), int(y2 * scale_y)
        pw, ph = px2 - px1, py2 - py1

        # 裁剪
        cropped = full_img.crop((px1, py1, px2, py2))
        cropped.save(output_path, quality=95)

        result[0] = {
            "success": True,
            "path": os.path.abspath(output_path),
            "width": pw,
            "height": ph,
            "x": px1,
            "y": py1,
            "w": pw,
            "h": ph,
        }
        root.quit()
        root.destroy()

    canvas.bind("<ButtonPress-1>", on_press)
    canvas.bind("<B1-Motion>", on_drag)
    canvas.bind("<ButtonRelease-1>", on_release)
    root.bind("<Escape>", lambda e: setattr(result, "cancelled", True) or (root.quit(), root.destroy()))

    # 进入主循环
    root.mainloop()

    # 检查是否取消了
    if result[0] is None:
        # 清理临时文件
        if os.path.exists(output_path):
            os.remove(output_path)
        return {"success": False, "error": "用户取消"}

    return result[0]
