"""Skill: 桌面自动化 — 截屏、OCR、键鼠操作、通知"""
SKILL_MANIFEST = {
    "name": "desktop_automation",
    "version": "1.0.0",
    "description": "桌面自动化：截屏查看屏幕、OCR识别文字位置、模拟键鼠操作、发送桌面通知",
    "tools": [
        "toolkit_screenshot",
        "toolkit_ocr",
        "toolkit_input",
        "toolkit_notify",
    ],
    "prompt_inject": """当需要操作桌面 GUI 时遵循流程：
1. 先用 screenshot 或 OCR 查看当前屏幕
2. 用 OCR 定位目标元素的精确坐标
3. 用 input 执行鼠标点击/键盘输入
4. 操作完成后用 notify 通知用户
注意：OCR 可识别中英文，截图默认保存到临时目录。""",
    "activation": "auto",
    "dependencies": ["easyocr", "pyautogui", "pillow"],
    "trigger_words": [
        "截图", "截屏", "screenshot", "屏幕", "识别",
        "点击", "鼠标", "键盘", "输入", "打字", "click",
        "ocr", "通知", "桌面", "窗口", "按钮",
        "打开软件", "关闭窗口", "拖拽", "滚动",
    ],
}
