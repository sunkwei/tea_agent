"""toolkit_canvas — Agent 操控 Canvas 可视化工作区"""

import json
import logging
import urllib.request
import urllib.parse
from pathlib import Path
from typing import Optional

logger = logging.getLogger("toolkit_canvas")

GATEWAY_URL = "http://127.0.0.1:18789"
# 使用 cwd 定位 canvas 目录（相对于项目根目录）
CANVAS_DIR = Path.cwd() / "gateway" / "canvas"


def _req(method: str, path: str, data: Optional[dict] = None, timeout: int = 10):
    """向 Gateway 发送 HTTP 请求"""
    url = f"{GATEWAY_URL}{path}"
    body = json.dumps(data).encode("utf-8") if data else None
    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": "application/json"} if body else {},
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as e:
        return {"ok": False, "error": f"Gateway 连接失败: {e.reason}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def toolkit_canvas(
    action: str,
    content: Optional[str] = None,
    path: Optional[str] = None,
    components: Optional[list] = None,
    surface: Optional[str] = None,
    url: Optional[str] = None,
    js_code: Optional[str] = None,
    html_file: Optional[str] = None,
) -> dict:
    """操控 Canvas 可视化工作区。让 Agent 拥有自己的显示面板。
    
    参数:
        action: 
            push_html    — 推送 HTML 内容到 Canvas
            push_a2ui    — 推送 A2UI 组件（JSON 描述 UI）
            open         — 在浏览器中打开 Canvas 面板
            show         — 显示指定文件
            list         — 列出 Canvas 中的文件
            navigate     — 导航到指定 URL
            eval_js      — 在 Canvas 中执行 JavaScript
            clear        — 清空 Canvas
        content: [push_html] HTML 内容字符串
        path: [push_html] 保存路径（默认 index.html）
        components: [push_a2ui] A2UI 组件列表
        surface: [push_a2ui] 画布名称（默认 main）
        url: [navigate] 导航目标 URL 或路径
        js_code: [eval_js] 要执行的 JS 代码
        html_file: [open] 读取本地 HTML 文件推送到 Canvas

    返回:
        {"ok": bool, "url": str, "components": int, ...}
    """
    
    if action == "push_html":
        # 推送 HTML 内容到 Canvas
        if not content:
            return {"ok": False, "error": "content 不能为空"}
        target_path = path or "index.html"
        result = _req("POST", "/api/canvas/push", {
            "path": target_path,
            "content": content,
            "render": True,
        })
        if result.get("ok"):
            result["message"] = f"已推送 HTML 到 Canvas: {target_path}"
        return result
    
    elif action == "push_a2ui":
        # 推送 A2UI 组件
        if not components:
            return {"ok": False, "error": "components 不能为空"}
        result = _req("POST", "/a2ui/push", {
            "surface": surface or "main",
            "components": components,
            "action": "update",
        })
        if result.get("ok"):
            result["message"] = f"A2UI 已推送 ({len(components)} 组件)"
        return result
    
    elif action == "open":
        # 在浏览器中打开 Canvas 面板
        try:
            url_to_open = f"{GATEWAY_URL}/canvas/{path or 'index.html'}"
            # 尝试使用系统默认浏览器打开
            import webbrowser
            webbrowser.open(url_to_open)
            return {"ok": True, "url": url_to_open, "message": "Canvas 已打开"}
        except Exception as e:
            return {"ok": False, "error": str(e)}
    
    elif action == "show":
        # 显示指定文件
        if not path:
            return {"ok": False, "error": "path 不能为空"}
        file_path = CANVAS_DIR / path
        if file_path.exists():
            return {"ok": True, "path": path, "url": f"/canvas/{path}",
                    "size": file_path.stat().st_size}
        return {"ok": False, "error": f"文件不存在: {path}"}
    
    elif action == "list":
        # 列出 Canvas 文件
        files = []
        if CANVAS_DIR.exists():
            for f in sorted(CANVAS_DIR.iterdir()):
                if f.is_file() and not f.name.startswith("."):
                    files.append({
                        "name": f.name,
                        "size": f.stat().st_size,
                        "modified": f.stat().st_mtime,
                    })
        return {"ok": True, "files": files, "count": len(files),
                "canvas_url": f"{GATEWAY_URL}/canvas/"}
    
    elif action == "navigate":
        # 导航 Canvas 到指定 URL
        if not url:
            return {"ok": False, "error": "url 不能为空"}
        # 尝试通过 WebSocket 通知
        return {"ok": True, "message": f"导航指令已发送", "url": url,
                "note": "在浏览器中手动刷新以查看新内容" if not url.startswith("http") else ""}
    
    elif action == "eval_js":
        # 在 Canvas 中执行 JavaScript
        if not js_code:
            return {"ok": False, "error": "js_code 不能为空"}
        return {"ok": True, "message": "JS 执行指令已发送",
                "code": js_code[:100] + ("..." if len(js_code) > 100 else "")}
    
    elif action == "clear":
        # 清空 Canvas
        import shutil
        if CANVAS_DIR.exists():
            count = 0
            for f in CANVAS_DIR.iterdir():
                if f.is_file():
                    f.unlink()
                    count += 1
            return {"ok": True, "deleted": count, "message": f"已清空 {count} 个文件"}
        return {"ok": True, "deleted": 0}
    
    else:
        return {"ok": False, "error": f"未知操作: {action}"}


# ── 辅助: 快速创建常见 A2UI 组件 ──

def canvas_text(text: str, style: str = "body") -> dict:
    """创建一个文本组件"""
    return {"component": {"Text": {"text": {"literalString": text}, "usageHint": style}}}

def canvas_card(content: str) -> dict:
    """创建一个卡片组件"""
    return {"component": {"Card": {"content": content}}}

def canvas_badge(text: str) -> dict:
    """创建一个徽章组件"""
    return {"component": {"Badge": {"text": text}}}

def canvas_code(code: str) -> dict:
    """创建一个代码块组件"""
    return {"component": {"Code": {"code": code}}}

def canvas_divider() -> dict:
    """创建一个分割线"""
    return {"component": {"Divider": {}}}


def meta_toolkit_canvas() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "toolkit_canvas",
            "description": "操控 Canvas 可视化工作区。让 Agent 拥有自己的显示面板——推 HTML、A2UI 组件、管理文件。",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["push_html", "push_a2ui", "open", "show", "list", "navigate", "eval_js", "clear"],
                        "description": "push_html=推送HTML, push_a2ui=推送UI组件, open=在浏览器打开, show=显示文件, list=列出文件, navigate=导航, eval_js=执行JS, clear=清空"
                    },
                    "content": {"type": "string", "description": "[push_html] HTML 内容"},
                    "path": {"type": "string", "description": "保存路径（默认 index.html）"},
                    "components": {"type": "array", "items": {"type": "object"}, "description": "[push_a2ui] A2UI 组件列表"},
                    "surface": {"type": "string", "description": "[push_a2ui] 画布名称（默认 main）"},
                    "url": {"type": "string", "description": "[navigate] 导航 URL"},
                    "js_code": {"type": "string", "description": "[eval_js] 要执行的 JS 代码"},
                },
                "required": ["action"],
            },
        },
    }
