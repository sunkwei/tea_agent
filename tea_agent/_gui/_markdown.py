"""
从 gui.py 提取，供 ChatRenderer 等组件使用。
"""

import re
import string

import markdown

try:
    from tkinterweb import HtmlFrame
    HAS_TKINTERWEB = True
except ImportError:
    HAS_TKINTERWEB = False

_DEFAULT_FONT_SIZE = 16  # 模块级默认
# ====================== Markdown → HTML 渲染 ======================

_MD_CSS_TEMPLATE = string.Template("""
<style>
body { font-family: "DengXian", "Noto Sans SC", "Noto Sans CJK SC", "Microsoft YaHei", "Microsoft YaHei UI", "Source Han Sans SC", "WenQuanYi Micro Hei", "SimHei", "SimSun", "DejaVu Sans", sans-serif; font-size: ${font_size}px; line-height: 1.7; color: #333; padding: 8px; }
h1, h2, h3, h4, h5, h6 { margin: 0.8em 0 0.4em; color: #1a73e8; }
h1 { font-size: 1.5em; border-bottom: 2px solid #eee; padding-bottom: 0.3em; }
h2 { font-size: 1.3em; border-bottom: 1px solid #eee; padding-bottom: 0.3em; }
p { margin: 0.5em 0; }
code { background: #f4f4f4; padding: 2px 5px; border-radius: 3px; font-family: "Cascadia Code", "Consolas", "Courier New", "Noto Sans Mono CJK SC", "DejaVu Sans Mono", "Source Han Mono SC", monospace; font-size: 0.9em; }
pre { background: #f6f8fa; border: 1px solid #ddd; border-radius: 5px; padding: 12px; overflow-x: auto; }
pre code { background: none; padding: 0; }
ul, ol { padding-left: 1.5em; }
li { margin: 0.3em 0; }
blockquote { border-left: 4px solid #ddd; margin: 0.5em 0; padding: 0.5em 1em; color: #666; background: #f9f9f9; }
table { border-collapse: collapse; width: 100%; margin: 0.8em 0; }
th, td { border: 1px solid #ddd; padding: 8px; text-align: left; }
th { background: #f2f2f2; font-weight: bold; }
a { color: #1a73e8; text-decoration: none; }
a:hover { text-decoration: underline; }
hr { border: none; border-top: 1px solid #ddd; margin: 1em 0; }
strong { font-weight: bold; color: #222; }
.msg-user { background: #dbeafe; padding: 8px 14px; border-radius: 8px; margin: 6px 0; border-left: 4px solid #3b82f6; }
.msg-user h3 { color: #1e40af; margin-top: 0; }
.msg-ai { background: #f3f4f6; padding: 8px 14px; border-radius: 8px; margin: 6px 0; border-left: 4px solid #6b7280; }
.msg-ai h3 { color: #374151; margin-top: 0; }
/* code blocks = tool calls/results */
.msg-ai pre { background: #ecfdf5; border-left: 4px solid #10b981; padding: 8px 12px; border-radius: 4px; margin: 6px 0; font-size: 0.9em; }
.msg-ai code { background: #d1fae5; color: #065f46; padding: 1px 4px; border-radius: 3px; font-size: 0.9em; }
/* notice / system */
.msg-notice { background: #fce7f3; padding: 8px 14px; border-radius: 8px; margin: 6px 0; border-left: 4px solid #ec4899; }
.msg-notice h3 { color: #9d174d; margin-top: 0; }
/* tool rounds */
.msg-tool { background: #ecfdf5; padding: 8px 14px; border-radius: 8px; margin: 6px 0; border-left: 4px solid #10b981; }
.msg-tool h5 { color: #065f46; margin-top: 0; font-size: 1em; }
/* Think/Reasoning block — div 方案（tkinterweb 不支持 HTML5 details） */
.msg-think { background: #fef3c7; border-radius: 8px; margin: 6px 0; border-left: 4px solid #f59e0b; overflow: hidden; padding: 8px 14px; }
.msg-think h3 { color: #92400e; margin: 0 0 6px 0; font-size: 1.05em; }
.msg-think p { color: #92400e; font-style: italic; margin: 0.4em 0; }
/* tool call container — div 方案 */
.tool-call-container {
    background: #ecfdf5;
    border-radius: 8px;
    margin: 6px 0;
    border-left: 4px solid #10b981;
    overflow: hidden;
}
.tc-header-bar {
    padding: 8px 14px;
    font-weight: 600;
    color: #065f46;
    display: flex;
    align-items: center;
    gap: 6px;
    border-bottom: 1px solid rgba(16,185,129,0.15);
}
.tc-summary-icon { font-size: 1em; }
.tc-badge {
    margin-left: auto;
    font-size: 0.75em;
    font-weight: 700;
    padding: 1px 8px;
    border-radius: 10px;
    background: rgba(16,185,129,0.12);
    color: #065f46;
}
.tc-list { padding: 0 14px 8px; }
.tc-item {
    border-top: 1px solid rgba(16,185,129,0.15);
    padding: 6px 0;
}
.tc-item:first-child { border-top: none; }
.tc-header {
    display: flex;
    align-items: center;
    gap: 6px;
}
.tc-status { font-size: 0.85em; padding-right: 2px; }
.tc-name {
    font-family: "Cascadia Code", "Consolas", monospace;
    font-size: 0.85em;
    background: rgba(16,185,129,0.08);
    color: #065f46;
    padding: 1px 6px;
    border-radius: 3px;
    word-break: break-all;
}
.tc-params { margin: 2px 0 0 24px; }
.tc-params pre {
    background: rgba(16,185,129,0.04);
    border: none;
    border-left: 2px solid rgba(16,185,129,0.2);
    padding: 4px 8px;
    margin: 2px 0;
    font-size: 0.8em;
    border-radius: 0 4px 4px 0;
    color: #065f46;
    overflow-x: auto;
}
.tc-result {
    margin: 2px 0 0 24px;
    font-size: 0.8em;
    color: #065f46;
    display: flex;
    gap: 4px;
    align-items: flex-start;
}
.tc-result code {
    background: rgba(16,185,129,0.06);
    color: #065f46;
    padding: 1px 5px;
    border-radius: 3px;
    font-size: 0.9em;
    word-break: break-all;
}
.tc-info {
    color: #065f46;
    font-size: 0.85em;
    padding: 2px 0;
    display: flex;
    gap: 4px;
    align-items: center;
}
/* running spinner */
.tc-running .tc-status::after {
    content: '';
    display: inline-block;
    width: 12px;
    height: 12px;
    border: 2px solid #10b981;
    border-top-color: transparent;
    border-radius: 50%;
    animation: tc-spin 0.6s linear infinite;
    vertical-align: middle;
    margin-left: 2px;
}
@keyframes tc-spin { to { transform: rotate(360deg); } }
em { font-style: italic; }
.msg-timestamp { font-size: 0.8em; color: #999; margin-bottom: 0.3em; }
.msg-divider { border: none; border-top: 2px solid #e8e8e8; margin: 1.2em 0; }
.chat-images { display: flex; flex-wrap: wrap; gap: 8px; margin: 8px 0; }
.chat-image { max-width: 400px; max-height: 300px; border-radius: 8px; border: 1px solid #ddd; object-fit: contain; cursor: pointer; }
.chat-image:hover { border-color: #3b82f6; box-shadow: 0 2px 8px rgba(59,130,246,0.3); }
a.chat-image-link { text-decoration: none; display: inline-block; }
a.chat-image-link:hover { text-decoration: none; }
</style>
""")
def _render_markdown(text: str, font_size: int = _DEFAULT_FONT_SIZE) -> str:
    """将 markdown 文本转换为带样式的 HTML 片段"""
    if not HAS_TKINTERWEB:
        return text
    html_body = markdown.markdown(text, extensions=["fenced_code", "tables", "codehilite", "md_in_html"])
    # 修复全文双重转义（&amp;lt;→&lt; 等），再修复 <code> 块内彻底 unescape
    html_body = _fix_double_escape_all(html_body)
    html_body = _fix_double_escape_in_code(html_body)
    css = _MD_CSS_TEMPLATE.safe_substitute(font_size=font_size)
    return f"<html><head>{css}</head><body>{html_body}</body></html>"

# 导致 <code> 块内 &amp; → &amp;amp;，显示为 &amp; 字面量而非正确渲染
# 此函数在最终 HTML 中，将 <code>...</code> 和 <pre>...</pre> 内部的 HTML 实体还原为原始字符
def _fix_double_escape_in_code(html: str) -> str:
    """修复代码块内的双重 HTML 转义并还原实体。

    HtmlFrame(tkinterweb) 在 <code> 和 <pre> 块内不解析实体，
    所以需要将 &lt; &gt; &amp; &quot; 等彻底还原为原始字符。
    由于流程中可能存在多重转义，此处采用循环 unescape 直到稳定。
    """
    import html as _html

    def _fix_code_block(m):
        """Internal: fix code block — 彻底还原 HTML 实体为原始字符。"""
        tag_start = m.group(1) # e.g. '<code class="...">' or '<pre>'
        inner = m.group(3)
        tag_end = m.group(4)   # '</code>' or '</pre>'

        # 1. 先修复明确的双重转义 pattern（加速处理）
        inner = inner.replace('&amp;amp;', '&amp;')
        inner = inner.replace('&amp;lt;', '&lt;')
        inner = inner.replace('&amp;gt;', '&gt;')
        inner = inner.replace('&amp;quot;', '&quot;')
        inner = inner.replace('&amp;#39;', '&#39;')
        inner = inner.replace('&amp;#x27;', '&#x27;')

        # 2. 循环还原所有 HTML 实体为原始字符，直到不再变化（应对多重转义）
        last_inner = ""
        while last_inner != inner:
            last_inner = inner
            inner = _html.unescape(inner)

        return f"{tag_start}{inner}{tag_end}"

    # 匹配 <code...>...</code> 或 <pre...>...</pre>
    # 使用 (code|pre) 捕获标签名，确保起始和结束标签匹配
    return re.sub(r'(<(code|pre)[^>]*>)(.*?)(</\2>)', _fix_code_block, html, flags=re.DOTALL)

def _fix_double_escape_all(html: str) -> str:
    """修复整个 HTML 正文中的双重转义（不仅限于 <code> 块）。

    流程: _chat_to_markdown 做 html_mod.escape → markdown.markdown 可能
    再次转义（尤其 md_in_html 扩展），导致 &lt; → &amp;lt;、
    &amp; → &amp;amp; 等。此函数还原明确的双重转义 pattern。
    """
    html = html.replace('&amp;amp;', '&amp;')
    html = html.replace('&amp;lt;', '&lt;')
    html = html.replace('&amp;gt;', '&gt;')
    html = html.replace('&amp;quot;', '&quot;')
    html = html.replace('&amp;#39;', '&#39;')
    html = html.replace('&amp;#x27;', '&#x27;')
    return html

def _build_tool_blocks(messages):

    """扫描消息列表，将连续 tool 消息合并为分组 markdown 字符串。

    返回与原始消息列表等长的字符串列表，非 tool 位置为空字符串，tool 组只在组首输出。"""

    n = len(messages)

    result = [""] * n

    i = 0

    while i < n:

        if messages[i].get("role") != "tool":

            i += 1

            continue

        start = i

        while i < n and messages[i].get("role") == "tool":

            i += 1

        group = messages[start:i]

        ts = group[0].get("timestamp", "")

        ts_display = f'<span class="msg-timestamp">{ts}</span>' if ts else ""

        block = _render_tool_group(group, ts_display)

        result[start] = f'<div>\n{block}\n</div>'

    return result

def _render_tool_group(group, ts_display):
    """将一组连续的 tool 消息渲染为可折叠 HTML 结构"""
    import html as _html
    items_parts = []
    for msg in group:
        text = msg.get("content", "").strip()
        m_new = re.match(r'🔧 调用工具：(\w+)\n参数：\n(.+)', text, re.DOTALL)
        m_old = re.match(r'🔧 调用工具：(\w+)\((.+)\)', text)
        if m_new:
            tool_name = _html.escape(m_new.group(1))
            args_raw = m_new.group(2).strip()
            params_pre = _html.escape(args_raw)
            items_parts.append(
                f'<div class="tc-item tc-running">'
                f'<div class="tc-header"><span class="tc-status">⚡</span>'
                f'<span class="tc-name">{tool_name}</span></div>'
                f'<div class="tc-params"><pre>{params_pre}</pre></div>'
                f'</div>'
            )
            continue
        if m_old:
            tool_name = _html.escape(m_old.group(1))
            args_raw = m_old.group(2).strip()
            items_parts.append(
                f'<div class="tc-item tc-running">'
                f'<div class="tc-header"><span class="tc-status">⚡</span>'
                f'<span class="tc-name">{tool_name}</span></div>'
                f'<div class="tc-params"><pre>{_html.escape(args_raw)}</pre></div>'
                f'</div>'
            )
            continue
        if text.startswith("📋 结果："):
            result_text = text[6:].strip()
            items_parts.append(
                f'<div class="tc-item tc-success">'
                f'<div class="tc-result"><span>📋</span>'
                f'<code>{_html.escape(result_text)}</code></div>'
                f'</div>'
            )
            continue
        if text.startswith("ℹ️ "):
            info = text[3:].strip()
            items_parts.append(
                f'<div class="tc-item tc-info">'
                f'<span>ℹ️</span><span>{_html.escape(info)}</span>'
                f'</div>'
            )
            continue
        # fallback
        display = _html.escape(text)
        items_parts.append(
            f'<div class="tc-item"><div class="tc-header">'
            f'<span class="tc-status">🔧</span>'
            f'<span class="tc-name">{display}</span></div></div>'
        )
    items_inner = "\n".join(items_parts)
    badge = f'<span class="tc-badge">{len(group)}个</span>'
    # 【注意】tkinterweb 不支持 HTML5 details/summary，使用 div+CSS 方案
    return (
        f'{ts_display}'
        f'<div class="tool-call-container">'
        f'<div class="tc-header-bar">'
        f'<span class="tc-summary-icon">🔧</span> 工具调用 {badge}'
        f'</div>'
        f'<div class="tc-list">\n{items_inner}\n</div>'
        f'</div>'
    )
def _chat_to_markdown(messages, image_cache=None):
    """将聊天消息列表转换为 markdown 格式，包含时间戳和分割线"""
    import html as html_mod  # 2026-05-16 fix: HTML转义防止未转义标签导致HtmlFrame解析错误
    # 预计算工具轮分组块
    tool_blocks = _build_tool_blocks(messages)
    parts = []
    for i, msg in enumerate(messages):
        role = msg.get("role", "")
        content = msg.get("content", "")
        ts = msg.get("timestamp", "")
        ts_display = f'<span class="msg-timestamp">{ts}</span>' if ts else ""
        if role == "user":
            img_html = ""
            imgs = msg.get("images", [])
            if imgs:
                img_tags = []
                import base64
                import os
                for img_path in imgs:
                    try:
                        # 支持直接渲染 Base64 数据（由 Storage 持久化后返回）
                        if img_path.startswith("data:image/"):
                            if image_cache is not None:
                                mime, b64_data = img_path.split(",", 1)
                                cache_idx = len(image_cache)
                                image_cache.append((b64_data, mime.split(";")[0]))
                                img_tags.append(f'<a href="tea://image/{cache_idx}" class="chat-image-link"><img src="{img_path}" class="chat-image" alt="用户上传图片" /></a>')
                            else:
                                img_tags.append(f'<img src="{img_path}" class="chat-image" alt="用户上传图片" />')
                        elif os.path.isfile(img_path):
                            with open(img_path, "rb") as f:
                                b64 = base64.b64encode(f.read()).decode("utf-8")
                            ext = os.path.splitext(img_path)[1].lower()
                            mime_map = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                                       ".gif": "image/gif", ".webp": "image/webp", ".bmp": "image/bmp"}
                            mime = mime_map.get(ext, "image/png")
                            if image_cache is not None:
                                cache_idx = len(image_cache)
                                image_cache.append((b64, mime))
                                img_tags.append(f'<a href="tea://image/{cache_idx}" class="chat-image-link"><img src="data:{mime};base64,{b64}" class="chat-image" alt="用户上传图片" /></a>')
                            else:
                                img_tags.append(f'<img src="data:{mime};base64,{b64}" class="chat-image" alt="用户上传图片" />')
                        else:
                            img_tags.append(f'<p class="img-error">⚠️ 找不到图片: {os.path.basename(img_path)}</p>')
                    except Exception:
                        img_tags.append(f'<p class="img-error">⚠️ 无法加载图片: {os.path.basename(img_path)}</p>')
                if img_tags:
                    img_html = '<div class="chat-images">' + "".join(img_tags) + '</div>'
            # 2026-05-16 fix: 对content进行HTML转义，防止未转义标签导致HtmlFrame解析错误
            safe_content = _transform_non_code_segments(content.strip(), html_mod.escape)
            parts.append(f'{ts_display}\n\n<div class="msg-user" markdown="1">\n\n### 👤 你\n\n{img_html}\n\n{safe_content}\n</div>\n')
        elif role == "think":
            # 对content进行HTML转义，保护代码段
            safe_content = _transform_non_code_segments(content.strip(), html_mod.escape)
            # 【注意】tkinterweb 不支持 HTML5 details/summary，所以使用 div+CSS 方案
            # 预渲染 think 内容为 HTML，避免 md_in_html 在 div 内不可靠处理
            think_html = markdown.markdown(safe_content, extensions=["fenced_code", "tables", "codehilite"])
            parts.append(f'{ts_display}\n\n<div class="msg-think">\n\n<h3>💭 思考过程</h3>\n\n{think_html}\n</div>\n\n---\n')
        elif role == "ai":
            # 2026-05-16 fix: 对content进行HTML转义
            safe_content = _transform_non_code_segments(content.strip(), html_mod.escape)
            safe_content = _transform_non_code_segments(safe_content, _escape_orphan_brackets)
            parts.append(f'{ts_display}\n\n<div class="msg-ai" markdown="1">\n\n### 🤖 AI\n\n{safe_content}\n</div>\n\n---\n')
        elif role == "tool":
            if tool_blocks[i]:
                parts.append(tool_blocks[i])
        elif role == "notice":
            parts.append(f"\n{content.strip()}\n")
    return "\n".join(parts)


def _transform_non_code_segments(text: str, transform) -> str:
    """仅对代码段之外的文本应用变换。

    保护两类 Markdown 代码语法：
    - fenced code block: ```...```
    - inline code: `...`
    """
    parts = re.split(r'(```[\s\S]*?```|`[^`\n]+`)', text)
    out = []
    for part in parts:
        if ((part.startswith("```") and part.endswith("```"))
                or (part.startswith("`") and part.endswith("`"))):
            out.append(part)
        else:
            out.append(transform(part))
    return "".join(out)

def _sanitize_html_control_chars(html: str) -> str:
    """移除 HTML 中的控制字符（保留 \\n 0x0a 和 \\t 0x09）。

    过滤范围：
    - ASCII 0x00-0x08, 0x0b-0x0c, 0x0e-0x1f (C0 控制字符，除 \n \t)
    - 0x7f (DEL)
    - 0x80-0x9f (C1 控制字符)
    - 零宽字符：U+200B-U+200F, U+2028-U+202E, U+2060-U+206F
    - BOM：U+FEFF
    """
    # 第一层：ASCII 控制字符
    html = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\x80-\x9f]', '', html)
    # 第二层：Unicode 零宽字符和特殊控制字符
    html = re.sub(r'[\u200b-\u200f\u2028-\u202e\u2060-\u206f\ufeff]', '', html)
    return html

def _escape_orphan_brackets(text: str) -> str:
    """转义孤立的 [ 或 ] 方括号。

    Markdown 中 [text](url) 是链接语法，如果 AI 输出中包含未配对的 [，
    解析器可能生成损坏的 HTML 结构。此函数将孤立的 [ 和 ] 转义为 HTML 实体。
    """
    # 先处理已配对的 [text](url) 形式的链接，保护它们不被转义
    # 匹配 [xxx](yyy) 或 [xxx] 形式
    protected_ranges = []
    for m in re.finditer(r'\[([^\]]*)\](?:\([^)]*\))?', text):
        protected_ranges.append((m.start(), m.end()))

    # 逐字符扫描，转义不在保护范围内的 [ 和 ]
    result = []
    i = 0
    while i < len(text):
        # 检查当前位置是否在保护范围内
        in_protected = False
        for start, end in protected_ranges:
            if start <= i < end:
                in_protected = True
                # 直接复制整个保护范围
                result.append(text[start:end])
                i = end
                break

        if in_protected:
            continue

        char = text[i]
        if char == '[':
            result.append('&#91;')  # [ 的 HTML 实体
        elif char == ']':
            result.append('&#93;')  # ] 的 HTML 实体
        else:
            result.append(char)
        i += 1

    return ''.join(result)

_KNOWN_HTML_TAGS = {'textarea', 'script', 'section', 'details', 'img', 'ul', 'h2', 'article', 'source', 'link', 'audio', 'h3', 'select', 'th', 'tr', 'tfoot', 'h1', 'h6', 'label', 'html', 'dt', 's', 'ol', 'colgroup', 'ins', 'code', 'summary', 'body', 'blockquote', 'abbr', 'tt', 'b', 'dd', 'input', 'nav', 'button', 'option', 'title', 'data', 'fieldset', 'head', 'iframe', 'sup', 'style', 'td', 'a', 'h5', 'dl', 'hr', 'main', 'figcaption', 'tbody', 'col', 'del', 'video', 'meta', 'sub', 'header', 'wbr', 'span', 'template', 'li', 'pre', 'caption', 'figure', 'strike', 'thead', 'form', 'footer', 'table', 'u', 'mark', 'canvas', 'legend', 'time', 'center', 'small', 'h4', 'strong', 'br', 'aside', 'div', 'big', 'p', 'em', 'font', 'i'}

def _validate_html_structure(html: str) -> tuple:
    """快速校验 HTML 基本结构：长度、html 标签、标签配对。
    返回 (ok: bool, 诊断信息: str, unclosed_tags: list)。
    unclosed_tags 为未闭合标签名列表（栈顺序，从内到外）。"""
    if len(html) < 10:
        return False, f"HTML 过短 ({len(html)} 字节)", []
    lower = html.lower()
    if '<html>' not in lower and '<html ' not in lower:
        return False, "缺少 <html> 标签", []
    # 用 HTMLParser 检查标签配对
    from html.parser import HTMLParser

    class _TagChecker(HTMLParser):
        """_TagChecker class."""
        def __init__(self):
            """Initialize  ."""
            super().__init__()
            self.stack = []
            self.errors = []
            self.unclosed = []  # 单独跟踪解析中检测到的未闭合标签
            self.known_tags = _KNOWN_HTML_TAGS
            self.void_elements = {'br', 'hr', 'img', 'input', 'meta', 'link',
                                  'area', 'base', 'col', 'embed', 'source', 'track', 'wbr'}

        def handle_starttag(self, tag, attrs):
            """Handle starttag.

            Args:
                tag: Description.
                attrs: Description.
            """
            if tag in self.known_tags and tag not in self.void_elements:
                self.stack.append(tag)

        def handle_endtag(self, tag):
            """Handle endtag.

            Args:
                tag: Description.
            """
            if tag not in self.known_tags or tag in self.void_elements:
                return
            if not self.stack:
                self.errors.append(f"多余的闭合标签 </{tag}>")
            elif self.stack[-1] == tag:
                self.stack.pop()
            else:
                if tag in self.stack:
                    while self.stack and self.stack[-1] != tag:
                        unclosed_tag = self.stack.pop()
                        self.unclosed.append(unclosed_tag)
                        self.errors.append(f"未闭合 <{unclosed_tag}>")
                    if self.stack:
                        self.stack.pop()
                else:
                    self.errors.append(f"未预期的闭合标签 </{tag}>")

        def get_result(self):
            """Get the result."""
            # 栈中残留的也是未闭合
            for tag in reversed(self.stack):
                self.unclosed.append(tag)
                self.errors.append(f"未闭合 <{tag}>")
            return len(self.errors) == 0, self.errors, self.unclosed

    try:
        checker = _TagChecker()
        checker.feed(html)
        ok, errors, unclosed = checker.get_result()
        if ok:
            return True, "OK", []
        else:
            return False, "; ".join(errors[:3]), unclosed
    except Exception as e:
        return False, f"HTML 解析异常: {e}", []


def _auto_close_unclosed_tags(html: str, unclosed_tags: list) -> str:
    """自动闭合未关闭的 HTML 标签。

    策略：对每个未闭合标签，在其最后一个 <tag> 之后找到第一个 </xxx>，
    在该位置之前插入 </tag>，确保闭合顺序正确。

    Args:
        html: 原始 HTML 字符串
        unclosed_tags: 未闭合标签列表（栈顺序，从内到外）

    Returns:
        修复后的 HTML 字符串
    """
    if not unclosed_tags:
        return html
    # 跳过 html（通常已有 </html>）
    to_close = [t for t in unclosed_tags if t != 'html']
    if not to_close:
        return html
    result = html
    lower = result.lower()
    for tag in to_close:
        lower = result.lower()
        # 找到最后一个 <tag> 开始位置
        last_open = max(lower.rfind(f'<{tag}>'), lower.rfind(f'<{tag} '))
        if last_open < 0:
            continue
        # 从该位置向后找第一个 </xxx>（任意闭合标签）
        idx = last_open + 1
        while idx < len(result) - 1:
            if result[idx] == '<' and result[idx + 1] == '/':
                # 在此闭合标签之前插入 </tag>
                result = result[:idx] + f'</{tag}>' + result[idx:]
                break
            idx += 1
        else:
            # 没找到后续闭合标签，追加在末尾
            result = result + f'</{tag}>'
    return result
