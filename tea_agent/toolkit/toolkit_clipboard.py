"""
Clipboard Processor — 剪贴板内容感知与智能路由

核心思想：
  感受（监听）是免费的，选择（处理）才是价值。
  
架构：
  ClipboardMonitor (后台线程监听)
       │
       ▼
  ContentDetector (类型嗅探)
       │
       ├── TextRouter ──┬── CodeDetector → LSP review
       │                 ├── ErrorDetector → diagnose
       │                 ├── URLDetector   → fetch
       │                 ├── JSONDetector  → analyze
       │                 └── PlainText     → summarize
       │
       ├── ImageRouter ──┬── Screenshot    → OCR
       │                 └── Photo/Diagram → describe
       │
       └── FileRouter  ──┬── Python       → LSP
                         ├── Data (CSV)   → analyze
                         └── Image file   → process
"""

import os, re, time, json, logging, threading, hashlib
from pathlib import Path
from typing import Dict, List, Optional, Any, Callable
from datetime import datetime

logger = logging.getLogger("clipboard")

_prev_hash = ""
_last_clip = ""
_monitor_thread = None
_running = False
_callback = None

SAMPLE_SIZE = 50000  # 处理时截断长度


class ClipContent:
    """剪贴板内容统一封装"""
    def __init__(self, type="text", subtype="", text="", size=0,
                 confidence=0.0, meta=None, detected_at=""):
        self.type = type
        self.subtype = subtype
        self.text = text
        self.size = size
        self.confidence = confidence
        self.meta = meta or {}
        self.detected_at = detected_at or datetime.now().isoformat()


# ────────────────────────────────────────
# 类型嗅探
# ────────────────────────────────────────

ERROR_PATTERNS = [
    (r"Traceback.*most recent call last", "python_traceback"),
    (r"\bError\b.*:", "generic_error"),
    (r"\bException\b.*:", "exception"),
    (r"SyntaxError|NameError|TypeError|ValueError|KeyError|IndexError|AttributeError", "python_error"),
    (r"FileNotFoundError|PermissionError|ModuleNotFoundError|ImportError", "io_error"),
    (r"failed with error|fatal:|panic:", "fatal_error"),
]

CODE_SIGNATURES = {
    "python": [r"^import\s+\w+", r"^from\s+\w+\s+import", r"^def\s+\w+\s*\(", r"^class\s+\w+",
               r"^if\s+__name__\s*==", r"^#.*coding"],
    "javascript": [r"^import\s+.*from\s+['\"]", r"^const\s+\w+\s*=", r"^function\s+\w+\s*\("],
    "typescript": [r"^interface\s+\w+", r"^type\s+\w+\s*=", r":\s*(string|number)\s*[=;)]"],
    "go": [r"^package\s+\w+", r"^func\s+\w+\s*\("],
    "rust": [r"^use\s+\w+", r"^fn\s+\w+\s*\("],
    "sql": [r"^(SELECT|INSERT|UPDATE|DELETE|CREATE|ALTER|DROP)\s"],
    "bash": [r"^#!/(bin/)?(bash|sh)", r"^export\s+\w+="],
    "yaml": [r"^\w+:\s+\S+"],
}

URL_RE = re.compile(r'^https?://[^\s/$.?#].[^\s]*$', re.I)
LOG_RE = re.compile(r'^\d{4}[-/]\d{2}[-/]\d{2}[\sT]\d{2}:\d{2}')


def detect_content(text: str) -> ClipContent:
    """检测剪贴板内容类型，返回结构化结果"""
    content = ClipContent(text=text[:SAMPLE_SIZE], size=len(text.encode("utf-8")),
                           detected_at=datetime.now().isoformat())

    if not text or not text.strip():
        content.subtype = "empty"; content.confidence = 1.0; return content

    t = text.strip()
    lines = text.splitlines()
    lines[0].strip() if lines else ""

    # 1. 错误信息
    for pat, sub in ERROR_PATTERNS:
        if re.search(pat, text[:2000], re.I):
            content.subtype = sub; content.confidence = 0.95; content.meta["error_type"] = sub; return content

    # 2. URL
    if len(lines) == 1 and URL_RE.match(t):
        content.subtype = "url"; content.confidence = 0.98; content.meta["url"] = t; return content

    # 3. JSON
    if t.startswith("{") or t.startswith("["):
        try:
            parsed = json.loads(t)
            content.subtype = "json"; content.confidence = 0.99
            content.meta["json_type"] = "dict" if isinstance(parsed, dict) else "array"
            if isinstance(parsed, dict): content.meta["json_keys"] = list(parsed.keys())[:15]
            return content
        except: pass

    # 4. 代码（多行且有特征关键字）
    if len(lines) >= 3:
        best_lang, best_score = "unknown", 0
        for lang, patterns in CODE_SIGNATURES.items():
            score = sum(1 for p in patterns if re.search(p, text[:3000], re.M))
            if score > best_score: best_lang, best_score = lang, score
        if best_score >= 2:
            content.subtype = "code"; content.confidence = min(0.95, 0.5 + best_score * 0.12)
            content.meta["language"] = best_lang; content.meta["line_count"] = len(lines); return content

    # 5. 日志
    log_lines = sum(1 for l in lines[:20] if LOG_RE.match(l))
    if len(lines) >= 3 and log_lines >= 2:
        content.subtype = "log"; content.confidence = 0.85; return content

    # 6. 长文本
    wc = len(text.split())
    if wc > 50:
        content.subtype = "article"; content.confidence = 0.6; content.meta["word_count"] = wc; return content

    # 7. 纯文本
    content.subtype = "plain"; content.confidence = 0.5
    content.meta["word_count"] = wc; content.meta["line_count"] = len(lines)
    return content


# ────────────────────────────────────────
# 路由决策
# ────────────────────────────────────────

def route_content(content: ClipContent) -> Dict:
    """根据内容类型路由到合适的处理方案"""
    sub = content.subtype
    sug = []

    if sub in ("python_traceback", "generic_error", "exception", "python_error", "io_error", "fatal_error"):
        sug = [
            {"tool": "toolkit_search", "prompt": f"分析这个错误并给出解决方案：{content.text[:500]}",
             "label": "🔍 搜索错误原因"},
        ]

    elif sub == "url":
        sug = [
            {"tool": "toolkit_js_fetch", "prompt": content.meta.get("url", content.text),
             "label": "🌐 抓取页面内容"},
        ]

    elif sub == "json":
        keys = content.meta.get("json_keys", [])
        sug = [
            {"tool": None, "label": f"📊 分析 JSON（{len(keys)}个字段）"},
        ]

    elif sub == "code":
        lang = content.meta.get("language", "unknown")
        sug = [
            {"tool": "toolkit_lsp", "prompt": f"审查这段{lang}代码：\n{content.text[:3000]}",
             "label": f"🔍 {lang} 代码审查"},
            {"tool": None, "prompt": f"解释这段{lang}代码的功能", "label": "📖 解释代码"},
        ]

    elif sub == "log":
        sug = [{"label": "🔍 日志分析"}]

    elif sub == "article":
        sug = [
            {"label": "📝 总结要点"},
            {"label": "🌍 翻译成中文"},
        ]

    else:  # plain
        if len(content.text.strip()) < 100:
            sug = [{"label": "💬 直接回复"}]
        else:
            sug = [{"label": "💬 回复"}, {"label": "📝 总结"}]

    return {
        "type": content.type, "subtype": sub, "confidence": content.confidence,
        "summary": content.text[:200].replace('\n', ' ').strip() + ("..." if len(content.text) > 200 else ""),
        "size": content.size, "suggestions": sug,
    }


# ────────────────────────────────────────
# 剪贴板读取（跨平台）
# ────────────────────────────────────────

def _read_clipboard() -> str:
    """读取剪贴板文本（跨平台）"""
    import subprocess
    try:
        if os.name == "nt":  # Windows
            r = subprocess.run(["powershell", "-NoProfile", "-Command",
                                "Add-Type -AssemblyName System.Windows.Forms; "
                                "[System.Windows.Forms.Clipboard]::GetText()"],
                               capture_output=True, text=True, timeout=3)
            return r.stdout.strip()
        elif sys.platform == "darwin":  # macOS
            r = subprocess.run(["pbpaste"], capture_output=True, text=True, timeout=3)
            return r.stdout.strip()
        else:  # Linux
            for cmd in [["xclip", "-o", "-selection", "clipboard"],
                        ["xsel", "-o", "-b"]]:
                try:
                    r = subprocess.run(cmd, capture_output=True, text=True, timeout=3)
                    if r.stdout.strip(): return r.stdout.strip()
                except: continue
            return ""
    except Exception as e:
        logger.debug(f"clipboard read failed: {e}")
        return ""


# ────────────────────────────────────────
# 监控线程
# ────────────────────────────────────────

def _monitor_loop():
    """后台监听循环"""
    global _prev_hash, _last_clip
    detector = detect_content
    router = route_content

    while _running:
        try:
            text = _read_clipboard()
            if not text:
                time.sleep(1.0)
                continue

            h = hashlib.md5(text.encode()).hexdigest()
            if h == _prev_hash:
                time.sleep(1.0)
                continue

            _prev_hash = h
            _last_clip = text[:500]

            # 类型检测 + 路由
            content = detector(text)
            routing = router(content)

            logger.info(f"📋 剪贴板: {content.subtype} (置信度={content.confidence:.0%})")

            # 回调
            if _callback:
                try:
                    _callback(routing)
                except Exception as e:
                    logger.warning(f"callback error: {e}")

        except Exception as e:
            logger.debug(f"monitor error: {e}")
            time.sleep(2.0)


def start_monitoring(callback: Optional[Callable] = None, interval: float = 1.0):
    """启动剪贴板监听"""
    global _monitor_thread, _running, _callback
    if _running:
        return {"status": "already_running"}
    _running = True
    _callback = callback
    _monitor_thread = threading.Thread(target=_monitor_loop, daemon=True, name="clip-monitor")
    _monitor_thread.start()
    return {"status": "started"}


def stop_monitoring():
    """停止剪贴板监听"""
    global _running, _monitor_thread
    _running = False
    if _monitor_thread:
        _monitor_thread.join(timeout=5)
        _monitor_thread = None
    return {"status": "stopped"}


# ────────────────────────────────────────
# 工具入口
# ────────────────────────────────────────

def toolkit_clipboard(action: str = "read", format: str = "text") -> Dict:
    """
    剪贴板处理工具 — 感知 + 智能路由

    读取当前剪贴板内容，自动检测类型（代码/错误/URL/JSON/日志/文本），
    返回类型判断 + 处理建议。

    Args:
        action: read=读取并分析, start=启动后台监听, stop=停止监听
        format: text/html（仅 read 时使用）

    Returns:
        内容类型 + 摘要 + 处理建议列表
    """
    if action == "read":
        text = _read_clipboard()
        if not text:
            return {"type": "empty", "text": "", "size": 0}
        content = detect_content(text)
        routing = route_content(content)
        routing["text"] = text[:5000]
        return routing

    elif action == "start":
        return start_monitoring()

    elif action == "stop":
        return stop_monitoring()

    elif action == "status":
        import sys
        return {
            "running": _running,
            "last_clip_subtype": "",
            "last_clip_preview": _last_clip[:100] if _last_clip else "",
        }

    return {"error": f"未知操作: {action}"}


import sys  # noqa: E402


def meta_toolkit_clipboard() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "toolkit_clipboard",
            "description": "剪贴板处理工具 — 感知 + 智能路由。读取当前剪贴板内容，自动检测类型（代码/错误/URL/JSON/日志/文本），返回类型判断 + 处理建议。支持后台监听模式。",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["read", "start", "stop", "status"],
                        "description": "read=读取并分析, start=启动后台监听, stop=停止监听, status=查看状态"
                    },
                    "format": {"type": "string", "description": "text/html", "default": "text"},
                },
                "required": ["action"],
            },
        },
    }
