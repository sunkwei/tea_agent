"""Web 前端 Markdown 列表渲染回归测试。

缺陷（NS-1「两条数据渲染出三个序号」）：``static/app.js`` 的 ``formatMarkdown``
用单条正则识别列表 —— ``^(\\s*\\d+\\.\\s+.+(?:\\n\\s*\\d+\\.\\s+.+)*)$``。正则里的 ``\\s``
**匹配换行**，于是列表前的空行（标题/段落与列表之间的标准写法）被吞进匹配串，
匹配串因此以 ``\\n`` 开头；``match.split('\\n')`` 后首元素是空串，被无条件包成
``<li>`` —— 凭空多出一个空条目：两条数据渲染成「1. / 2. / 3.」，且 ``<ol>`` 的
自动编号整体后移，显示序号与原文序号错位（空行越多，幽灵条目越多）。

断言钉的是**行为契约**而非实现细节：

1. 渲染出的条目数 == 源码条目数（列表前的空行不得变成条目）
2. 任何情况下都不得出现空 ``<li>``
3. 源码序号不被改写（从 ``2.`` 起的列表要显示 2、3，而不是重排成 1、2）

测试通过 node 直接执行 app.js 中抽取的 ``formatMarkdown``（纯函数，无 DOM 依赖）。
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

APP_JS = Path(__file__).resolve().parents[1] / "server" / "static" / "app.js"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None,
    reason="需要 node 执行前端 formatMarkdown（JS 纯函数，Python 无法直接调用）",
)

# 抽取 formatMarkdown 后逐用例执行；app 路径与用例都经 stdin 以 JSON 传入
# （脚本用 `node -e` 直接执行，不落盘、免命令行转义问题）。
_HARNESS = r"""
const fs = require('fs');
const payload = JSON.parse(fs.readFileSync(0, 'utf8'));
const src = fs.readFileSync(payload.app, 'utf8').replace(/\r\n/g, '\n');
const lines = src.split('\n');
const start = lines.findIndex(l => l.startsWith('function formatMarkdown(text) {'));
if (start < 0) throw new Error('app.js 中找不到 formatMarkdown —— 抽取锚点失效');
const end = lines.findIndex((l, i) => i > start && l === '}');
if (end < 0) throw new Error('formatMarkdown 结尾大括号定位失败');
const fnSrc = lines.slice(start, end + 1).join('\n');
if (!fnSrc.includes('return html;')) throw new Error('抽取到的 formatMarkdown 源码不完整');

const enc = t => String(t).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
const decodeEntities = t => String(t || '')
  .replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"')
  .replace(/&#39;/g, "'").replace(/&amp;/g, '&');
const escAttr = t => String(t).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/'/g, '&#39;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

const formatMarkdown = new Function(
  'esc', 'decodeEntities', 'escAttr', fnSrc + '\nreturn formatMarkdown;'
)(enc, decodeEntities, escAttr);

const out = {};
for (const [name, input] of Object.entries(payload.cases)) out[name] = formatMarkdown(input);
process.stdout.write(JSON.stringify(out));
"""

EMPTY_LI = '<li class="md-li"></li>'


@pytest.fixture(scope="module")
def render():
    """返回 ``render(cases) -> {name: html}``（node -e 执行，不在源码树落文件）。"""

    def _render(cases: dict[str, str]) -> dict[str, str]:
        payload = json.dumps({"app": str(APP_JS), "cases": cases}, ensure_ascii=False)
        # harness 必须**落盘后执行**，不能走 `node -e <多行脚本>`：
        # Windows 上 node 常由 Volta shim 转发，多行脚本会被静默吞掉 ——
        # 进程 rc=0、stdout 为空，脚本根本没跑。此时旧的
        # 「assert returncode == 0」照样通过，测试要么以 JSONDecodeError 报错，
        # 要么把「整测试静默失效」固化成绿色契约（本文件曾在 Windows 上
        # 因此 14 例永久变红，而产品代码 formatMarkdown 实为正确）。
        with tempfile.TemporaryDirectory() as _tmpdir:
            _script = Path(_tmpdir) / "format_markdown_harness.js"
            _script.write_text(_HARNESS, encoding="utf-8")
            proc = subprocess.run(
                ["node", str(_script)],
                input=payload,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=120,
            )
        assert proc.returncode == 0, f"node 执行失败:\n{proc.stderr}"
        # 关键契约：rc=0 **不代表**脚本真的执行过（shim 静默空跑正是 rc=0）。
        # 无输出必须判失败，否则「测试从未真正运行」会长期伪装成通过。
        assert proc.stdout.strip(), (
            "node 未产出任何输出（rc=0 但 stdout 为空）—— harness 静默空跑，"
            f"本测试并未真正执行 formatMarkdown。stderr={proc.stderr[:500]!r}"
        )
        return json.loads(proc.stdout)

    return _render


def _li_count(html: str) -> int:
    return html.count("<li")


def _empty_li_count(html: str) -> int:
    return html.count(EMPTY_LI)


# 列表前的「上文」——按 Markdown 惯例都带一个空行，缺陷版本会把该空行变成空条目
_LEADING_CONTEXTS = {
    "session_start": "",
    "parent_heading": "## 两点观察\n\n",
    "paragraph": "清理完成，下面两点观察：\n\n",
    "code_block": "```\nrm -f x.db\n```\n\n",
    "table": "| a | b |\n|---|---|\n| 1 | 2 |\n\n",
}

_TWO_ITEMS = "1. **下次 rotation 会先归档再累积**：`copy2` 每个换周都复制一份\n2. **磁盘大头不是归档**：`symbol_index.db` 90.5 MB 是第一名"


@pytest.mark.parametrize("ctx_name", sorted(_LEADING_CONTEXTS))
def test_leading_blank_line_creates_no_phantom_item(render, ctx_name):
    """列表前的空行不得变成条目：两条数据 → 两个 ``<li>``。"""
    html = render({"case": _LEADING_CONTEXTS[ctx_name] + _TWO_ITEMS})["case"]
    assert _empty_li_count(html) == 0, f"出现空条目（幽灵序号）：{html}"
    assert _li_count(html) == 2, f"两条数据渲染出 {_li_count(html)} 个条目：{html}"


def test_loose_list_with_blank_line_between_items(render):
    """条目之间夹空行的松散列表仍是两条，不得插入空条目。"""
    html = render({"case": "1. 甲\n\n2. 乙"})["case"]
    assert _empty_li_count(html) == 0, f"出现空条目：{html}"
    assert _li_count(html) == 2, f"松散列表条目数错误：{html}"
    assert html.count("<ol") == 1, f"松散列表被拆成多个列表：{html}"


def test_bare_number_line_is_not_an_empty_item(render):
    """裸编号行（``1.`` 后无内容）不算条目，更不得吞掉下一行。"""
    html = render({"case": "1.\n2. **甲**：a\n3. **乙**：b"})["case"]
    assert _empty_li_count(html) == 0, f"出现空条目：{html}"
    assert _li_count(html) == 2, f"条目数错误：{html}"


@pytest.mark.parametrize(
    ("source", "expected_start"),
    [("2. **甲**：a\n3. **乙**：b", 2), ("1. **甲**：a\n2. **乙**：b", None)],
)
def test_source_start_number_preserved(render, source, expected_start):
    """源码序号不被改写：从 2. 起的列表显示 2/3，而不是重排成 1/2。"""
    html = render({"case": source})["case"]
    assert _empty_li_count(html) == 0
    assert _li_count(html) == 2, html
    if expected_start is None:
        assert "start=" not in html, f"从 1 起的列表不该带 start：{html}"
    else:
        assert f'start="{expected_start}"' in html, f"源起序号丢失：{html}"


def test_unordered_list_after_paragraph(render):
    """无序列表同样不得凭空多出空条目。"""
    html = render({"case": "结论如下：\n\n- 甲\n- 乙"})["case"]
    assert _empty_li_count(html) == 0, f"出现空条目：{html}"
    assert _li_count(html) == 2, html
    assert '<ul class="md-ul">' in html


def test_stored_message_shape_renders_two_items(render):
    """真实事故文本的完整形态（标题 + 表格 + 代码块 + 两条目）条目数守恒。"""
    source = (
        "## 做了什么\n\n"
        "| 校验项 | 结果 |\n|---|---|\n| rotation 是否截断 | 无 |\n\n"
        "## 清理后现状\n\n"
        "```\n 90.52 MB  symbol_index.db\n```\n\n"
        "## 两点观察\n\n"
        "1. **下次 rotation 会先归档再累积**：`maybe_rotate_db` 每次换周都 `copy2` 一份完整现役库。\n"
        "2. **磁盘大头其实不是归档**：`symbol_index.db` 90.5 MB 是第一名。\n\n"
        "（本次只删数据，未改源码。）"
    )
    html = render({"case": source})["case"]
    assert _empty_li_count(html) == 0, f"出现空条目：{html}"
    assert _li_count(html) == 2, f"两条观察渲染出 {_li_count(html)} 个条目：{html}"


def test_list_marker_count_equals_rendered_items(render):
    """守恒律：源码条目行数 == 渲染条目数（1/2/3/5 条各验一次）。"""
    cases = {str(n): "前言\n\n" + "\n".join(f"{i}. 条目{i}" for i in range(1, n + 1)) for n in (1, 2, 3, 5)}
    out = render(cases)
    for n_str, html in out.items():
        assert _li_count(html) == int(n_str), f"{n_str} 条 → {_li_count(html)} 个条目：{html}"
        assert _empty_li_count(html) == 0, html


def test_inline_code_and_bold_outside_list_unaffected(render):
    """修复不得破坏原有内联处理：列表内行内代码、列表外粗体照常渲染。"""
    out = render(
        {
            "inline_in_item": "1. 用 `copy2` 复制\n2. 用 `migration.py` 收尾",
            "bold_outside": "**粗体** 普通一行\n\n1. 甲\n2. 乙",
        }
    )
    assert out["inline_in_item"].count('<code class="md-inline-code">') == 2, out["inline_in_item"]
    assert '<strong class="md-strong">粗体</strong>' in out["bold_outside"], out["bold_outside"]
    assert _li_count(out["bold_outside"]) == 2, out["bold_outside"]


def test_adjacent_list_type_switch_stays_separate(render):
    """相邻的有序/无序条目属于两个列表，不得混成一个。"""
    html = render({"case": "1. 甲\n2. 乙\n\n- 丙\n- 丁"})["case"]
    assert _li_count(html) == 4, html
    assert html.count("<ol") == 1 and html.count("<ul") == 1, html
    assert _empty_li_count(html) == 0, html
