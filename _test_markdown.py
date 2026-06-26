import markdown

text = """Hello

```python
print("hello")
```

World"""

html = markdown.markdown(text, extensions=["fenced_code", "tables", "codehilite", "md_in_html"])
print("=== Raw markdown output ===")
print(html)
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

    def handle_starttag(self, tag, attrs):
        if tag not in self.void_elements:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag in self.void_elements:
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
checker.feed(html)
ok, errors = checker.get_result()
print(f"OK: {ok}")
if errors:
    print(f"Errors: {errors}")
