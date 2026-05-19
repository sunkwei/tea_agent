"""
@2026-05-15 gen by tea_agent, Markdown → HTML 渲染工具函数
从 main_db_gui.py 提取，供 ChatRenderer 等组件使用。
"""

import string
import re
import markdown

try:
    from tkinterweb import HtmlFrame
    HAS_TKINTERWEB = True
except ImportError:
    HAS_TKINTERWEB = False

_DEFAULT_FONT_SIZE = 16  # 模块级默认

_DEFAULT_FONT_SIZE = 16  # 模块级默认
# ====================== Markdown → HTML 渲染 ======================

_MD_CSS_TEMPLATE = string.Template("""
<style>
body { font-family: "Microsoft YaHei", "Microsoft YaHei UI", "DengXian", "SimHei", "SimSun", "Noto Sans SC", "Noto Sans CJK SC", "Source Han Sans SC", "WenQuanYi Micro Hei", "DejaVu Sans", sans-serif; font-size: ${font_size}px; line-height: 1.6; color: #333; padding: 8px; }
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
/* NOTE: 2026-05-15 gen by tea_agent, 不同角色背景色区分 */
.msg-user { background: #dbeafe; padding: 8px 14px; border-radius: 8px; margin: 6px 0; border-left: 4px solid #3b82f6; }
.msg-user h3 { color: #1e40af; margin-top: 0; }
.msg-ai { background: #f3f4f6; padding: 8px 14px; border-radius: 8px; margin: 6px 0; border-left: 4px solid #6b7280; }
.msg-ai h3 { color: #374151; margin-top: 0; }
/* Think/reasoning message (独立角色) */
.msg-think { background: #fef3c7; padding: 8px 14px; border-radius: 8px; margin: 6px 0; border-left: 4px solid #f59e0b; }
.msg-think h3 { color: #92400e; margin-top: 0; }
.msg-think p { color: #92400e; font-style: italic; }
/* code blocks = tool calls/results */
.msg-ai pre { background: #ecfdf5; border-left: 4px solid #10b981; padding: 8px 12px; border-radius: 4px; margin: 6px 0; font-size: 0.9em; }
.msg-ai code { background: #d1fae5; color: #065f46; padding: 1px 4px; border-radius: 3px; font-size: 0.9em; }
/* notice / system */
.msg-notice { background: #fce7f3; padding: 8px 14px; border-radius: 8px; margin: 6px 0; border-left: 4px solid #ec4899; }
.msg-notice h3 { color: #9d174d; margin-top: 0; }
/* tool rounds */
.msg-tool { background: #ecfdf5; padding: 8px 14px; border-radius: 8px; margin: 6px 0; border-left: 4px solid #10b981; }
.msg-tool h5 { color: #065f46; margin-top: 0; font-size: 1em; }
em { font-style: italic; }
.msg-timestamp { font-size: 0.8em; color: #999; margin-bottom: 0.3em; }
.msg-divider { border: none; border-top: 2px solid #e8e8e8; margin: 1.2em 0; }
/* NOTE: 2026-05-15 gen by tea_agent, 聊天图片样式 */
.chat-images { display: flex; flex-wrap: wrap; gap: 8px; margin: 8px 0; }
.chat-image { max-width: 400px; max-height: 300px; border-radius: 8px; border: 1px solid #ddd; object-fit: contain; cursor: pointer; }
.chat-image:hover { border-color: #3b82f6; box-shadow: 0 2px 8px rgba(59,130,246,0.3); }
/* @2026-05-15 gen by tea_agent, 图片点击放大弹窗 */
a.chat-image-link { text-decoration: none; display: inline-block; }
a.chat-image-link:hover { text-decoration: none; }
</style>
""")
def _render_markdown(text: str, font_size: int = _DEFAULT_FONT_SIZE) -> str:
    """将 markdown 文本转换为带样式的 HTML 片段"""
    if not HAS_TKINTERWEB:
        return text
    html_body = markdown.markdown(text, extensions=["fenced_code", "tables", "codehilite", "md_in_html"])
    html_body = _fix_double_escape_in_code(html_body)
    css = _MD_CSS_TEMPLATE.safe_substitute(font_size=font_size)
    return f"<html><head>{css}</head><body>{html_body}</body></html>"


# NOTE: 2026-05-20 gen by tea_agent, 修复双重转义：html_mod.escape + markdown.codehilite
# 导致 <code> 块内 &amp; → &amp;amp;，显示为 &amp; 字面量而非正确渲染
# 此函数在最终 HTML 中，将 <code>...</code> 内部的 &amp; 还原为 &
def _fix_double_escape_in_code(html: str) -> str:
    """修复 <code> 块内的双重 HTML 转义。
    
    由于 _chat_to_markdown 先做了 html_mod.escape，markdown.codehilite
    又对代码块内容再次转义，导致 <code> 内 &amp; 变成 &amp;amp;。
    此函数仅还原明确的双重转义 pattern（&amp;amp; → &amp; 等），
    避免破坏内联代码中的单次转义。
    NOTE: 2026-05-20 gen by tea_agent, 修复：仅替换双重转义，保护内联代码的单次转义。"""
    def _fix_code_block(m):
        inner = m.group(1)
        # 仅替换已知的双重转义 pattern，不影响单次转义
        inner = inner.replace('&amp;amp;', '&amp;')
        inner = inner.replace('&amp;lt;', '&lt;')
        inner = inner.replace('&amp;gt;', '&gt;')
        inner = inner.replace('&amp;quot;', '&quot;')
        inner = inner.replace('&amp;#39;', '&#39;')
        inner = inner.replace('&amp;#x27;', '&#x27;')
        return '<code>' + inner + '</code>'
    return re.sub(r'<code>(.*?)</code>', _fix_code_block, html, flags=re.DOTALL)


# NOTE: 2026-05-08 gen by tea_agent, 工具轮分组渲染：合并连续tool消息，生成带轮次编号的蓝色标题块

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

        result[start] = f'<div class="msg-tool" markdown="1">\n\n{block}\n</div>'

    return result





# NOTE: 2026-05-16 gen by tea_agent, 支持多行参数格式
def _render_tool_group(group, ts_display):

    """将一组连续的 tool 消息渲染为 markdown，带轮次编号"""

    lines_out = [f"{ts_display}\n##### 🔧 工具"]

    round_num = 0

    for msg in group:

        text = msg.get("content", "").strip()

        # @2026-05-16 gen by tea_agent, 支持新旧两种工具调用格式
        m_new = re.match(r'🔧 调用工具：(\w+)\n参数：\n(.+)', text, re.DOTALL)
        m_old = re.match(r'🔧 调用工具：(\w+)\((.+)\)', text)
        if m_new:
            round_num += 1

            tool_name = m_new.group(1)

            args = m_new.group(2).strip()

            if len(args) > 200:

                args = args[:200] + "..."

            lines_out.append(f"\n**第 {round_num} 轮**")

            lines_out.append(f"- **调用**: `{tool_name}`")

            lines_out.append(f"- **参数**: \n```\n{args}\n```")

            continue
        if m_old:
            round_num += 1

            tool_name = m_old.group(1)

            args = m_old.group(2)

            if len(args) > 160:

                args = args[:160] + "..."

            lines_out.append(f"\n**第 {round_num} 轮**")

            lines_out.append(f"- **调用**: `{tool_name}`")

            lines_out.append(f"- **参数**: `{args}`")

            continue

        if text.startswith("📋 结果："):

            result = text[6:]

            if len(result) > 200:

                result = result[:200] + "..."

            lines_out.append(f"- **结果**: {result}")

            continue

        if text.startswith("ℹ️ "):

            info = text[3:]

            if len(info) > 200:

                info = info[:200] + "..."

            lines_out.append(f"\nℹ️ {info}")

            continue

        display = text

        if len(display) > 200:

            display = display[:200] + "..."

        lines_out.append(f"🔧 {display}")

    lines_out.append("")

    return "\n".join(lines_out)



# NOTE: 2026-05-16 15:30:11, self-evolved by tea_agent --- 修复HTML渲染：在_chat_to_markdown中对content进行HTML转义，防止未转义HTML标签导致HtmlFrame解析错误
# @2026-05-15 gen by tea_agent, 图片点击放大弹窗
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
            # NOTE: 2026-05-15 gen by tea_agent, 支持图片附件渲染
            img_html = ""
# NOTE: 2026-05-15 15:11:05, self-evolved by tea_agent --- 修改 _chat_to_markdown 支持直接渲染 Base64 格式的图片数据
            imgs = msg.get("images", [])
            if imgs:
                img_tags = []
                import os, base64
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
            safe_content = html_mod.escape(content.strip())
            parts.append(f'{ts_display}\n\n<div class="msg-user" markdown="1">\n\n### 👤 你\n\n{img_html}\n\n{safe_content}\n</div>\n')
        elif role == "think":
            # 2026-05-16 fix: 对content进行HTML转义
            safe_content = html_mod.escape(content.strip())
            parts.append(f'{ts_display}\n\n<div class="msg-think" markdown="1">\n\n### 💭 思考过程\n\n{safe_content}\n</div>\n\n---\n')
        elif role == "ai":
            # 2026-05-16 fix: 对content进行HTML转义
            safe_content = html_mod.escape(content.strip())
            # NOTE: 2026-05-18 fix: 转义孤立的 [ ] 方括号，防止被 Markdown 解析器误认为链接语法导致 HTML 结构损坏
            safe_content = _escape_orphan_brackets(safe_content)
            parts.append(f'{ts_display}\n\n<div class="msg-ai" markdown="1">\n\n### 🤖 AI\n\n{safe_content}\n</div>\n\n---\n')
        elif role == "tool":
            if tool_blocks[i]:
                parts.append(tool_blocks[i])
        elif role == "notice":
            # NOTE: 2026-05-15 gen by tea_agent, 去掉 --- 包裹避免与 AI 末尾的 --- 连成三条水平线
            parts.append(f"\n{content.strip()}\n")
# NOTE: 2026-05-14 16:00:09, self-evolved by tea_agent --- HtmlFrame render 前增加 HTML 校验：控制字符清洗 + 标签配对检查
    return "\n".join(parts)


# NOTE: 2026-05-16 gen by tea_agent, HTML 校验：过滤控制字符，防止畸形字节流导致 HtmlFrame 渲染残缺
# NOTE: 2026-05-18 fix: 扩展控制字符过滤范围，包含 \x7f(DEL)、Unicode C0/C1 控制字符、零宽字符等
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


# NOTE: 2026-05-18 fix: 转义孤立的方括号，防止被 Markdown 解析器误认为链接/引用语法
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
    返回 (ok: bool, 诊断信息: str)。"""
    if len(html) < 10:
        return False, f"HTML 过短 ({len(html)} 字节)"
    lower = html.lower()
    if '<html>' not in lower and '<html ' not in lower:
        return False, "缺少 <html> 标签"
    # 用 HTMLParser 检查标签配对
    from html.parser import HTMLParser

    class _TagChecker(HTMLParser):
        def __init__(self):
            super().__init__()
            self.stack = []
            self.errors = []
            self.known_tags = _KNOWN_HTML_TAGS
            self.void_elements = {'br', 'hr', 'img', 'input', 'meta', 'link',
                                  'area', 'base', 'col', 'embed', 'source', 'track', 'wbr'}

        def handle_starttag(self, tag, attrs):
            if tag in self.known_tags and tag not in self.void_elements:
                self.stack.append(tag)

        def handle_endtag(self, tag):
            if tag not in self.known_tags or tag in self.void_elements:
                return
            if not self.stack:
                self.errors.append(f"多余的闭合标签 </{tag}>")
            elif self.stack[-1] == tag:
                self.stack.pop()
            else:
                if tag in self.stack:
                    while self.stack and self.stack[-1] != tag:
                        unclosed = self.stack.pop()
                        self.errors.append(f"未闭合 <{unclosed}>")
                    if self.stack:
                        self.stack.pop()
                else:
                    self.errors.append(f"未预期的闭合标签 </{tag}>")

        def get_result(self):
            for tag in reversed(self.stack):
                self.errors.append(f"未闭合 <{tag}>")
            return len(self.errors) == 0, self.errors

    try:
        checker = _TagChecker()
        checker.feed(html)
        ok, errors = checker.get_result()
        if ok:
            return True, "OK"
        else:
            return False, "; ".join(errors[:3])
    except Exception as e:
        return False, f"HTML 解析异常: {e}"
