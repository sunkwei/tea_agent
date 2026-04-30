# NOTE: 2026-04-30 16:39:52, self-evolved by tea_agent --- json/time导入移到函数体内，解决exec沙箱环境模块不可见问题
# @2026-04-30 gen by deepseek-v4-pro, toolkit_input: "手" — 模拟鼠标/键盘操作，让 Agent 能操作电脑
"""toolkit_input — 操作能力：鼠标移动/点击/拖拽 + 键盘输入/快捷键"""


def toolkit_input(
    action: str,
    x: int = 0,
    y: int = 0,
    text: str = "",
    button: str = "left",
    duration: float = 0.3,
    dx: int = 0,
    dy: int = 0,
    keys: str = "",
    amount: int = 3,
) -> str:
    """
    模拟鼠标和键盘操作 — Agent 的'手'。

    Args:
        action: 操作类型
            鼠标: 'move', 'click', 'double_click', 'right_click', 'drag', 'position', 'scroll'
            键盘: 'type', 'press', 'hotkey'
            信息: 'screen_size'
        x: 目标 X 坐标（或拖拽起始X）
        y: 目标 Y 坐标（或拖拽起始Y）
        text: [type] 要输入的文本
        button: [click/scroll] 鼠标按键 'left'/'right'/'middle'
        duration: [move/drag] 移动耗时秒数（慢一点更安全）
        dx: [drag] 拖拽目标 X 偏移
        dy: [drag] 拖拽目标 Y 偏移
        keys: [press/hotkey] 按键或组合键（如 'enter', 'ctrl+c'）
        amount: [scroll] 滚动量，正=上滚，负=下滚

    Returns:
        操作结果描述
# NOTE: 2026-04-30 16:40:00, self-evolved by tea_agent --- 函数体内添加import json，解决exec沙箱问题
    """
    import json
    import pyautogui as pg
    pg.FAILSAFE = True
    pg.PAUSE = 0.05

    try:
        # ── 鼠标操作 ──
        if action == "move":
            pg.moveTo(x, y, duration=duration)
            return json.dumps({"action": "move", "to": [x, y], "ok": True}, ensure_ascii=False)

        elif action == "click":
            pg.moveTo(x, y, duration=duration * 0.5)
            pg.click(x, y, button=button)
            return json.dumps({"action": "click", "at": [x, y], "button": button, "ok": True}, ensure_ascii=False)

        elif action == "double_click":
            pg.moveTo(x, y, duration=duration * 0.5)
            pg.doubleClick(x, y, button=button)
            return json.dumps({"action": "double_click", "at": [x, y], "ok": True}, ensure_ascii=False)

        elif action == "right_click":
            pg.moveTo(x, y, duration=duration * 0.5)
            pg.rightClick(x, y)
            return json.dumps({"action": "right_click", "at": [x, y], "ok": True}, ensure_ascii=False)

        elif action == "drag":
            pg.moveTo(x, y, duration=duration * 0.5)
            pg.drag(dx, dy, duration=duration, button=button)
            end_x, end_y = x + dx, y + dy
            return json.dumps({
                "action": "drag",
                "from": [x, y],
                "to": [end_x, end_y],
                "ok": True
            }, ensure_ascii=False)

        elif action == "position":
            pos = pg.position()
            screen = pg.size()
            return json.dumps({
                "action": "position",
                "x": pos.x,
                "y": pos.y,
                "screen": f"{screen.width}x{screen.height}",
            }, ensure_ascii=False)

        elif action == "scroll":
            pg.scroll(amount, x=x if x else None, y=y if y else None)
            return json.dumps({"action": "scroll", "amount": amount, "ok": True}, ensure_ascii=False)

        # ── 键盘操作 ──
        elif action == "type":
            if not text:
                return "❌ type 需要提供 text 参数"
            pg.typewrite(text, interval=0.02)
            return json.dumps({
                "action": "type",
                "text": text[:80] + ("..." if len(text) > 80 else ""),
                "length": len(text),
                "ok": True,
            }, ensure_ascii=False)

        elif action == "press":
            if not keys:
                return "❌ press 需要提供 keys 参数"
            pg.press(keys)
            return json.dumps({"action": "press", "key": keys, "ok": True}, ensure_ascii=False)

        elif action == "hotkey":
            if not keys:
                return "❌ hotkey 需要提供 keys 参数（如 'ctrl+c'）"
            key_list = [k.strip() for k in keys.split("+")]
            pg.hotkey(*key_list)
            return json.dumps({"action": "hotkey", "keys": keys, "ok": True}, ensure_ascii=False)

        # ── 信息 ──
        elif action == "screen_size":
            s = pg.size()
            return json.dumps({"action": "screen_size", "width": s.width, "height": s.height}, ensure_ascii=False)

        else:
            return f"❌ 未知操作: {action}。支持: move, click, double_click, right_click, drag, position, scroll, type, press, hotkey, screen_size"

    except pg.FailSafeException:
        return "⚠️ 触发 FailSafe：鼠标移到了左上角 (0,0)，操作已取消。"
    except Exception as e:
        return f"❌ 操作失败: {e}"


def meta_toolkit_input() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "toolkit_input",
            "description": "模拟鼠标和键盘操作 — Agent 的'手'。可移动鼠标、点击、拖拽、滚动、输入文本、按快捷键。配合 toolkit_ocr 可实现「看→分析→操作」闭环。",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": [
                            "move", "click", "double_click", "right_click", "drag",
                            "position", "scroll",
                            "type", "press", "hotkey",
                            "screen_size"
                        ],
                        "description": "操作类型。鼠标: move/click/double_click/right_click/drag/position/scroll。键盘: type/press/hotkey。信息: screen_size"
                    },
                    "x": {
                        "type": "integer",
                        "description": "目标 X 坐标（move/click/drag 时使用）"
                    },
                    "y": {
                        "type": "integer",
                        "description": "目标 Y 坐标（move/click/drag 时使用）"
                    },
                    "text": {
                        "type": "string",
                        "description": "[type] 要输入的文本"
                    },
                    "button": {
                        "type": "string",
                        "enum": ["left", "right", "middle"],
                        "description": "鼠标按键，默认 left"
                    },
                    "duration": {
                        "type": "number",
                        "description": "移动耗时秒数，默认 0.3"
                    },
                    "dx": {
                        "type": "integer",
                        "description": "[drag] X 偏移量"
                    },
                    "dy": {
                        "type": "integer",
                        "description": "[drag] Y 偏移量"
                    },
                    "keys": {
                        "type": "string",
                        "description": "[press/hotkey] 按键或组合键（如 'enter'、'ctrl+c'）"
                    },
                    "amount": {
                        "type": "integer",
                        "description": "[scroll] 滚动量，正=上滚 负=下滚"
                    }
                },
                "required": ["action"]
            }
        }
    }
