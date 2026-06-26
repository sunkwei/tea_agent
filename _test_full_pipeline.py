import markdown
import re
import html as _html

def _fix_double_escape_in_code(html: str) -> str:
    def _fix_code_block(m):
        tag_start = m.group(1)
        inner = m.group(3)
        tag_end = m.group(4)
        
        inner = inner.replace('&amp;amp;', '&amp;')
        inner = inner.replace('&amp;lt;', '&lt;')
        inner = inner.replace('&amp;gt;', '&gt;')
        inner = inner.replace('&amp;quot;', '&quot;')
        inner = inner.replace('&amp;#39;', '&#39;')
        inner = inner.replace('&amp;#x27;', '&#x27;')
        
        last_inner = ""
        while last_inner != inner:
            last_inner = inner
            inner = _html.unescape(inner)
        
        return f"{tag_start}{inner}{tag_end}"

    return re.sub(r'(<(code|pre)[^>]*>)(.*?)(</\2>)', _fix_code_block, html, flags=re.DOTALL)

text = """Hello

```python
print("hello")
```

World"""

html_body = markdown.markdown(text, extensions=["fenced_code", "tables", "codehilite", "md_in_html"])
print("=== Before fix ===")
print(html_body)
print()

html_body = _fix_double_escape_in_code(html_body)
print("=== After fix ===")
print(html_body)
print()

# Full HTML
css = """<style>
body { font-family: "DengXian", sans-serif; font-size: 16px; line-height: 1.7; }
</style>"""
full_html = f"<html><head>{css}</head><body>{html_body}</body></html>"
print("=== Full HTML ===")
print(full_html)
print()

# Check for unclosed tags
from html.parser import HTMLParser

class TagChecker(HTMLParser):
    def __init__(self):
        super().__init__()
        self.stack = []
        self.errors = []
        self.void_elements = {'br', 'hr', 'img', 'input', 'meta', 'link',
                              'area', 'base', 'col', 'embed', 'source', 'track', 'wbr'}
        self.known_tags = {'textarea', 'script', 'section', 'details', 'img', 'ul', 'h2', 'article', 'source', 'link', 'audio', 'h3', 'select', 'th', 'tr', 'tfoot', 'h1', 'h6', 'label', 'html', 'dt', 's', 'ol', 'colgroup', 'ins', 'code', 'summary', 'body', 'blockquote', 'abbr', 'tt', 'b', 'dd', 'input', 'nav', 'button', 'option', 'title', 'data', 'fieldset', 'head', 'iframe', 'sup', 'style', 'td', 'a', 'h5', 'dl', 'hr', 'main', 'figcaption', 'tbody', 'col', 'del', 'video', 'meta', 'sub', 'header', 'wbr', 'span', 'template', 'li', 'pre', 'caption', 'figure', 'strike', 'thead', 'form', 'footer', 'table', 'u', 'mark', 'canvas', 'legend', 'time', 'center', 'small', 'h4', 'strong', 'br', 'aside', 'div', 'big', 'p', 'em', 'font', 'i'}

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

checker = TagChecker()
checker.feed(full_html)
ok, errors = checker.get_result()
print(f"Validation OK: {ok}")
if errors:
    print(f"Errors: {errors}")
