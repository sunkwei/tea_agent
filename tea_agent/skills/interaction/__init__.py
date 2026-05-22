"""Skill: 交互 — 网络搜索、MCP"""
SKILL_MANIFEST = {
    "name": "interaction",
    "version": "1.1.0",
    "description": "外部交互：互联网搜索、MCP 外部工具连接、JS 动态页面抓取",
    "tools": [
        "toolkit_search",
        "toolkit_mcp",
        "toolkit_js_fetch",
    ],
    "prompt_inject": """交互准则：
1. 需要查互联网信息时用 search（DuckDuckGo/百度），支持 web/code/symbol 三种搜索类型
2. 需要抓取 JS 动态渲染页面时用 js_fetch（Playwright 无头浏览器）
3. 需要连接外部 MCP Server 时用 mcp（stdio/SSE）""",
    "activation": "auto",
    "dependencies": ["duckduckgo_search", "playwright"],
    "trigger_words": [
        "搜索", "查一下", "搜一下", "网上", "百度", "google",
        "网页", "fetch", "爬取", "抓取", "mcp",
    ],
}
