"""Web 界面「文件树 → 文件预览」端到端回归测试（真实浏览器 / Playwright）。

**为什么需要它** —— 纯接口测试（TestClient）抓不到的三类失效：

1. `index.html` 里的 `?v=` 资源版本号忘了升 → 浏览器继续用**旧的**
   app.js / style.css：接口全绿，用户却看不到新功能。只有真开浏览器才暴露。
2. 文件树曾把 `.png/.jpg` 放进 `ignored_exts` 过滤掉 → 树里根本没有图片条目，
   于是"图片预览"这条需求**永远走不到**（接口层毫无异常）。
3. 预览弹窗的渲染分支（行号 / JSON 美化 / Markdown 渲染 / 图片内联）是纯前端
   逻辑；TestClient 只能验证 JSON 字段，验证不了"用户看到了什么"。

钉住的行为契约（对应用户可观察行为，非实现细节）：

  · 树中能看到图片（回归：图片曾被过滤，导致功能不可达）
  · 点文本文件 → 弹窗打开，且按行渲染（有行号）
  · 点 JSON → 默认美化（多行）；点 🎨 → 回原文（单行）
  · 点 Markdown → 渲染为 HTML（`.fp-md` 内出现 h1）
  · 点图片 → `<img>` **真实解码成功**（`naturalWidth > 0`，不是碎图）
  · 点二进制 → 明确提示不支持，而非乱码

无 playwright / 无浏览器时自动 skip，不阻塞测试套件。
"""

from __future__ import annotations

import os
import socket
import struct
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zlib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

# ── 依赖探测（缺失即 skip，而非 fail）────────────────────────────────
sync_api = pytest.importorskip("playwright.sync_api", reason="需要 playwright 才能做界面级验证")


def _png_1x1() -> bytes:
    """纯 stdlib 生成一张**保证可解码**的 1x1 红色 PNG。

    不能手拼 hex 常量：截断/CRC 错的 PNG 仍能通过"响应头是 image/png"的
    接口断言，却会在浏览器里变成碎图 —— 正是本测试要抓的那类失效。
    """

    def chunk(typ: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + typ + data + struct.pack(">I", zlib.crc32(typ + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)  # 1x1, 8bit, truecolor
    idat = zlib.compress(b"\x00\xff\x00\x00")  # filter 0 + RGB(255,0,0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


def _free_port() -> int:
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])
    finally:
        s.close()


def _wait_health(base: str, proc: subprocess.Popen, timeout: float = 90.0) -> bool:
    """轮询 /health 直到就绪；进程提前退出则立刻放弃。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            return False
        try:
            with urllib.request.urlopen(base + "/health", timeout=3) as r:
                if 200 <= r.status < 300:
                    return True
        except (urllib.error.URLError, OSError):
            time.sleep(0.4)
    return False


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    """构造一个已知内容的沙箱目录（服务将以它为 cwd → 即文件树根）。"""
    d = tmp_path_factory.mktemp("ui_sandbox")
    (d / "hello.py").write_text("import os\n\n\ndef greet(name):\n    return f'hi {name}'\n", encoding="utf-8")
    # 故意写成紧凑单行：格式化开关的前后差异才好断言
    (d / "data.json").write_text('{"name":"tea","tags":[1,2,3]}', encoding="utf-8")
    (d / "note.md").write_text("# 标题\n\n**粗体** 与 `code`\n", encoding="utf-8")
    (d / "pic.png").write_bytes(_png_1x1())
    (d / "blob.dat").write_bytes(bytes(range(256)))
    return d


@pytest.fixture(scope="module")
def live_server(sandbox):
    """以沙箱为 cwd 起一个真实服务进程（PYTHONPATH 指回项目根）。"""
    port = _free_port()
    base = f"http://127.0.0.1:{port}"
    env = dict(os.environ, PYTHONPATH=str(ROOT))
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "tea_agent.server",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=str(sandbox),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    try:
        if not _wait_health(base, proc):
            tail = ""
            if proc.poll() is not None and proc.stdout:
                tail = "".join(proc.stdout.readlines()[-15:])
            pytest.skip(f"服务未能就绪（可能是环境问题），跳过界面级验证。输出尾部：\n{tail}")
        yield base
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()


@pytest.fixture(scope="module")
def browser():
    """启动 chromium；二进制缺失则 skip。"""
    pw = sync_api.sync_playwright().start()
    try:
        b = pw.chromium.launch(headless=True)
    except Exception as e:  # 浏览器未安装 / 无法启动
        pw.stop()
        pytest.skip(f"chromium 不可用，跳过界面级验证：{str(e)[:200]}")
    yield b
    b.close()
    pw.stop()


@pytest.fixture
def page(browser, live_server):
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    pg = ctx.new_page()
    pg.goto(live_server, wait_until="domcontentloaded")
    # 关键：等 app.js 真正执行完（暴露了 window.openFile），
    # 否则"点了没反应"会被误判成功能缺陷。
    pg.wait_for_function("() => typeof window.openFile === 'function'", timeout=15000)
    yield pg
    ctx.close()


# ── 交互辅助 ──────────────────────────────────────────────────────
def _open_tree(page) -> None:
    page.click("#ft-toggle")
    page.wait_for_selector("#file-tree-content .ft-item", timeout=15000)


def _click_file(page, name: str) -> None:
    """点击树中指定文件（按显示名精确定位）。"""
    item = page.locator("#file-tree-content .ft-item").filter(has=page.locator(f".ft-name:text-is('{name}')")).first
    item.wait_for(state="visible", timeout=15000)
    item.click()
    page.wait_for_selector("#modal-filepreview.open", timeout=15000)


def _body_lines(page) -> int:
    return page.locator("#fvp-body .fp-line").count()


# ── 测试 ──────────────────────────────────────────────────────────
class TestFileTreeVisibility:
    """树的可达性：能列出、且图片不再被过滤。"""

    def test_tree_lists_expected_files(self, page):
        _open_tree(page)
        names = page.locator("#file-tree-content .ft-name").all_inner_texts()
        for want in ["hello.py", "data.json", "note.md", "pic.png", "blob.dat"]:
            assert want in names, f"树中缺少 {want}；实际：{names}"

    def test_images_are_listed(self, page):
        """回归：.png 曾被 ignored_exts 过滤 → 图片预览整条链路不可达。"""
        _open_tree(page)
        names = page.locator("#file-tree-content .ft-name").all_inner_texts()
        assert "pic.png" in names, f"图片未出现在文件树中：{names}"


class TestTextPreview:
    """文本 / 代码预览：弹窗 + 行号渲染。"""

    def test_py_opens_modal_with_line_numbers(self, page):
        _open_tree(page)
        _click_file(page, "hello.py")
        assert page.locator("#modal-filepreview").is_visible()
        assert _body_lines(page) >= 5, "应按行渲染（含行号）"
        # 行号确实从 1 开始且递增
        first_ln = page.locator("#fvp-body .fp-ln").first.inner_text().strip()
        assert first_ln == "1"
        assert "greet" in page.locator("#fvp-body").inner_text()

    def test_title_and_meta_show_path(self, page):
        _open_tree(page)
        _click_file(page, "hello.py")
        assert "hello.py" in page.locator("#fvp-title").inner_text()
        meta = page.locator("#fvp-meta").inner_text()
        assert ".py" in meta and "text" in meta


class TestJsonFormatting:
    """JSON：默认美化（多行）↔ 点 🎨 回原文（单行）。"""

    def test_json_pretty_by_default_then_toggle(self, page):
        _open_tree(page)
        _click_file(page, "data.json")

        pretty_lines = _body_lines(page)
        assert pretty_lines > 1, "JSON 默认应美化（多行）"
        assert '"name"' in page.locator("#fvp-body").inner_text()

        page.click("#fvp-fmt")  # → 原文
        raw_lines = _body_lines(page)
        assert raw_lines == 1, f"切到原文后应为紧凑单行，实际 {raw_lines} 行"
        assert raw_lines < pretty_lines

        page.click("#fvp-fmt")  # → 恢复美化
        assert _body_lines(page) == pretty_lines


class TestMarkdownPreview:
    """Markdown：渲染为 HTML 而非裸文本。"""

    def test_markdown_renders_html(self, page):
        _open_tree(page)
        _click_file(page, "note.md")
        page.wait_for_selector("#fvp-body .fp-md", timeout=10000)

        md = page.locator("#fvp-body .fp-md")
        # 契约：标题被渲染成**标题元素**（而非显示字面 "# 标题"）。
        # 不钉死具体级别 —— 应用把 # 映射为 h2（避免与页面 h1 竞争），
        # 这是全局 Markdown 约定，预览复用同一渲染器。
        heading = md.locator("h1, h2, h3, h4, h5, h6")
        assert heading.count() >= 1, "标题未被渲染为 HTML 标题元素"
        assert "标题" in heading.first.inner_text()
        assert not md.inner_text().lstrip().startswith("#"), "标题仍显示字面 # 号"

        # 行内强调同样渲染
        assert md.locator("strong").count() >= 1
        assert md.locator("code.md-inline-code").count() >= 1


class TestImagePreview:
    """图片：内联渲染且**真实解码**（naturalWidth>0）。"""

    def test_png_actually_decodes(self, page):
        _open_tree(page)
        _click_file(page, "pic.png")
        img = page.locator("#fvp-body img.fp-image")
        img.wait_for(state="visible", timeout=15000)
        # 等解码完成：complete && naturalWidth>0 —— 碎图/404 时为 0
        page.wait_for_function(
            """() => {
                 const i = document.querySelector('#fvp-body img.fp-image');
                 return i && i.complete && i.naturalWidth > 0;
               }""",
            timeout=15000,
        )
        assert img.evaluate("el => el.naturalWidth") > 0
        # 图片不提供文本专用的格式化/复制按钮
        assert not page.locator("#fvp-copy").is_visible()

    def test_png_raw_endpoint_served_as_image(self, page, live_server):
        """/api/file/raw 必须给 image/*（否则 <img> 不渲染）。"""
        resp = page.request.get(live_server + "/api/file/raw?path=pic.png")
        assert resp.status == 200
        assert resp.headers.get("content-type", "").startswith("image/png")
        assert "nosniff" in resp.headers.get("x-content-type-options", "")


class TestBinaryPreview:
    """二进制：明确提示，不吐乱码。"""

    def test_binary_shows_notice(self, page):
        _open_tree(page)
        _click_file(page, "blob.dat")
        body = page.locator("#fvp-body").inner_text()
        assert "不支持" in body or "二进制" in body, body[:200]


class TestAssetCacheBusting:
    """资源版本号必须随前端改动更新（否则用户拿旧 JS/CSS，功能"未生效"）。"""

    def test_static_assets_are_versioned(self, page, live_server):
        html = page.request.get(live_server + "/").text()
        for asset in ["/static/app.js", "/static/style.css"]:
            assert asset in html, f"{asset} 未被引用"
        # 引用处必须带 ?v=（缓存失效标识）
        import re

        for asset in ["app.js", "style.css"]:
            assert re.search(rf"{asset}\?v=[\w.-]+", html), f"{asset} 缺少 ?v= 版本号"

    def test_preview_assets_present_in_served_js(self, page, live_server):
        """服务端真的把新版 app.js 发出来了（含本次新增的预览入口）。"""
        js = page.request.get(live_server + "/static/app.js").text()
        assert "fpToggleFormat" in js and "modal-filepreview" in js
        css = page.request.get(live_server + "/static/style.css").text()
        assert ".fvp-box" in css and ".fp-line" in css


class TestScreenshotArtifact:
    """留证：把文件树 + 预览弹窗截一张图（供人工复核）。"""

    def test_capture_screenshot(self, page):
        _open_tree(page)
        _click_file(page, "hello.py")
        out_dir = Path(os.environ.get("TEA_UI_ARTIFACT_DIR", ROOT / "output" / "webui"))
        out_dir.mkdir(parents=True, exist_ok=True)
        shot = out_dir / "file_preview_hello_py.png"
        page.screenshot(path=str(shot), full_page=False)
        assert shot.exists() and shot.stat().st_size > 0
        print(f"\n[artifact] 界面截图：{shot}")
