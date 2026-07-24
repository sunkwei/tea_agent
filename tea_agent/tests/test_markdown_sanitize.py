""" _markdown 测试 — HTML 消毒。"""

import pytest

from tea_agent._gui._markdown import _sanitize_html_dangerous_tags


class TestSanitizeHtmlDangerousTags:
    @pytest.mark.parametrize("html,expected", [
        ('<script>alert(1)</script>hello', 'hello'),
        ('<script type="text/javascript">evil()</script>safe', 'safe'),
        ('<SCRIPT>alert()</SCRIPT>', ''),
        ('x</script>y', 'x</script>y'),
    ])
    def test_strip_script_tags(self, html, expected):
        assert _sanitize_html_dangerous_tags(html) == expected

    @pytest.mark.parametrize("html,expected", [
        ('<iframe src="http://evil.com"></iframe>hello', 'hello'),
        ('<iframe src="http://evil.com"/>hello', 'hello'),
        ('<IFRAME src="http://evil.com"></IFRAME>', ''),
    ])
    def test_strip_iframe_tags(self, html, expected):
        assert _sanitize_html_dangerous_tags(html) == expected

    @pytest.mark.parametrize("html,expected", [
        ('<object data="evil.swf"></object>safe', 'safe'),
        ('<embed src="evil.swf">safe', 'safe'),
        ('<applet code="evil"></applet>safe', 'safe'),
    ])
    def test_strip_embed_object_applet(self, html, expected):
        assert _sanitize_html_dangerous_tags(html) == expected

    @pytest.mark.parametrize("html,expected", [
        ('<img src=x onerror=alert(1)>', '<img src=x>'),
        ('<div onclick="evil()">click</div>', '<div>click</div>'),
        ('<body onload="evil()">content</body>', '<body>content</body>'),
        ('<a href="#" onmouseover="evil()">link</a>', '<a href="#">link</a>'),
    ])
    def test_strip_event_handlers(self, html, expected):
        assert _sanitize_html_dangerous_tags(html) == expected

    @pytest.mark.parametrize("html,not_contain", [
        ('<a href="javascript:alert(1)">link</a>', 'javascript'),
        ('<a href=" javascript:alert(1)">link</a>', 'javascript'),
    ])
    def test_strip_javascript_protocol(self, html, not_contain):
        """javascript: 前缀被移除（不保证整个值被清空，但至少去掉危险协议）"""
        result = _sanitize_html_dangerous_tags(html)
        assert not_contain not in result

    def test_preserve_safe_html(self):
        """正常 HTML 结构不被破坏"""
        safe = '<p>hello <b>world</b></p><code>print(1)</code>'
        assert _sanitize_html_dangerous_tags(safe) == safe

    def test_preserve_markdown_html(self):
        """AI 生成的合法 Markdown/HTML 不被破坏"""
        safe = '''
        <div class="msg-ai">
        <h1>Title</h1>
        <p>Paragraph with <strong>bold</strong> and <em>italic</em></p>
        <pre><code>def hello():
            pass
        </code></pre>
        <ul><li>item 1</li><li>item 2</li></ul>
        <a href="https://example.com">link</a>
        <img src="data:image/png;base64,abc" alt="img">
        </div>
        '''
        result = _sanitize_html_dangerous_tags(safe)
        # 去掉前导和结尾空白再比较
        assert result.strip() == safe.strip()

    def test_nested_dangerous_in_code_block(self):
        """代码块内的危险标签被保留（<pre><code> 内不做内容消毒）"""
        html = '<pre><code>&lt;script&gt;alert(1)&lt;/script&gt;</code></pre>'
        assert _sanitize_html_dangerous_tags(html) == html

    def test_multiple_dangerous_tags(self):
        """混合多个危险标签全部移除"""
        html = '''
        <script>a()</script>
        <p>safe</p>
        <iframe src="bad"></iframe>
        <div onclick="x()">click</div>
        <object data="bad"></object>
        '''
        result = _sanitize_html_dangerous_tags(html)
        assert 'script>' not in result
        assert 'iframe>' not in result
        assert 'object>' not in result
        assert 'onclick' not in result
        assert '<p>safe</p>' in result
        assert 'click' in result
