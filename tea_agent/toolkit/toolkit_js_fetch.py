# @2026-05-19 gen by claude, v1.2.1: 修复 engine._name 不存在；用 label 标识浏览器
# version: 1.2.1

import asyncio, sys
from playwright.async_api import async_playwright


async def _launch_browser(playwright):
    """跨平台自动选择最佳浏览器：
    Windows → msedge (系统预装)
    Linux   → chromium → firefox (fallback)
    macOS   → msedge → chromium → firefox
    返回 (browser, label)，label 如 'chromium:msedge'。
    """
    is_linux = sys.platform == "linux"
    is_windows = sys.platform == "win32"

    # 候选列表：(引擎, kwargs, label)，按优先级
    candidates = []
    if is_windows:
        candidates = [
            (playwright.chromium, {"channel": "msedge", "headless": True}, "chromium:msedge"),
        ]
    elif is_linux:
        candidates = [
            (playwright.chromium, {"headless": True}, "chromium"),          # playwright install chromium
            (playwright.firefox,  {"headless": True}, "firefox"),           # fallback
        ]
    else:  # darwin / others
        candidates = [
            (playwright.chromium, {"channel": "msedge", "headless": True}, "chromium:msedge"),
            (playwright.chromium, {"headless": True}, "chromium"),
            (playwright.firefox,  {"headless": True}, "firefox"),
        ]

    errors = []
    for engine, kwargs, label in candidates:
        try:
            browser = await engine.launch(**kwargs)
            return browser, label
        except Exception as e:
            errors.append(f"{label}: {e}")

    raise RuntimeError(
        f"无法启动任何浏览器，已尝试: {'; '.join(errors)}。"
        f"请执行 playwright install chromium 或 playwright install firefox"
    )


async def _js_fetch(url: str, wait_selector: str = "body", timeout: int = 15, return_html: bool = False):
    """内部异步函数：用无头浏览器打开页面，等 JS 渲染后返回内容"""
    async with async_playwright() as p:
        browser, engine_label = await _launch_browser(p)
        context = await browser.new_context(viewport={"width": 1280, "height": 800})
        page = await context.new_page()

        try:
            await page.goto(url, timeout=timeout * 1000, wait_until="domcontentloaded")
            await page.wait_for_selector(wait_selector, timeout=timeout * 1000)
            await asyncio.sleep(1)

            if return_html:
                result = await page.content()
            else:
                result = await page.evaluate("""() => {
                    document.querySelectorAll('script, style, noscript').forEach(e => e.remove());
                    return document.body ? document.body.innerText : document.documentElement.innerText;
                }""")

            await browser.close()
            return {"success": True, "engine": engine_label, "content": result[:10000], "url": url}
        except Exception as e:
            await browser.close()
            return {"success": False, "engine": engine_label, "error": str(e), "url": url}


def toolkit_js_fetch(url: str, wait_selector: str = "body", timeout: int = 15, return_html: bool = False):
    """同步包装器：用 Playwright 无头浏览器抓取 JS 动态渲染的页面内容。
    跨平台自动选最优浏览器：Windows→Edge, Linux→Chromium→Firefox。
    """
    return asyncio.run(_js_fetch(url, wait_selector, timeout, return_html))


def meta_toolkit_js_fetch() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "toolkit_js_fetch",
            "description": "用 Playwright 无头浏览器抓取 JS 动态渲染的页面内容。跨平台自动选浏览器(Windows→Edge/Linux→Chromium→Firefox)。解决 mcp-server-fetch 无法执行 JS 的问题。",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "目标 URL"
                    },
                    "wait_selector": {
                        "type": "string",
                        "description": "等待某 CSS 选择器出现后再抓取，默认 body",
                        "default": "body"
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "超时秒数，默认 15",
                        "default": 15
                    },
                    "return_html": {
                        "type": "boolean",
                        "description": "返回原始 HTML(true) 还是提取的文本(false)，默认 false",
                        "default": False
                    }
                },
                "required": ["url"]
            }
        }
    }
