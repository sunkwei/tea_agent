"""图片生成物内联预览（/v1/preview）回归测试。

缺陷背景：`/v1/download` 恒返回 `Content-Disposition: attachment` +
`application/octet-stream`，当 `<img src>` 用只会触发下载而非渲染 ——
图片生成物因此只有下载链接、没有预览。

修复：新增 `/v1/preview/{filename}`，用正确 `image/*` MIME + `inline`；
`toolkit_publish_doc` 对图片额外返回 `preview_url`；前端自动补缩略图。

钉住的行为契约（非实现细节）：
  · preview 端点可直接内联（inline + image MIME）
  · download 端点**保持** attachment + octet-stream（不可为预览而改坏下载语义）
  · 两个端点共用同一套路径遍历防护（不能因新增端点开洞）
  · 非图片不给预览（415），SVG 额外加 sandbox CSP（防存储型 XSS）
"""

import os

import pytest


@pytest.fixture(scope="module")
def client_and_dir():
    from starlette.testclient import TestClient

    from tea_agent.server.route_handlers import exports_dir
    from tea_agent.server.server import create_app

    return TestClient(create_app()), exports_dir()


@pytest.fixture
def png_file(client_and_dir):
    """写入一张最小合法 PNG（1x1）到 exports 目录。"""
    _tc, d = client_and_dir
    path = os.path.join(d, "_preview测试.png")
    # 1x1 透明 PNG
    data = bytes.fromhex(
        "89504e470d0a1a0a0000000d494844520000000100000001080600000"
        "01f15c4890000000a49444154789c6300010000050001"
    )
    with open(path, "wb") as fh:
        fh.write(data)
    yield "_preview测试.png"
    if os.path.exists(path):
        os.remove(path)


class TestPreviewEndpoint:
    """GET /v1/preview/{filename} — 内联预览。"""

    def test_preview_image_is_inline(self, client_and_dir, png_file):
        tc, _ = client_and_dir
        r = tc.get("/v1/preview/" + png_file)
        assert r.status_code == 200, r.text
        assert r.headers["content-type"].startswith("image/png"), r.headers["content-type"]
        assert "inline" in r.headers.get("content-disposition", "").lower()
        assert r.headers.get("x-content-type-options") == "nosniff"

    def test_download_still_attachment(self, client_and_dir, png_file):
        """下载端点契约不变：仍是 attachment + octet-stream。"""
        tc, _ = client_and_dir
        r = tc.get("/v1/download/" + png_file)
        assert r.status_code == 200
        assert "attachment" in r.headers.get("content-disposition", "").lower()
        assert r.headers["content-type"] == "application/octet-stream"

    def test_non_image_rejected_415(self, client_and_dir):
        tc, d = client_and_dir
        f = os.path.join(d, "_preview非图片.md")
        with open(f, "w", encoding="utf-8") as fh:
            fh.write("# x")
        try:
            r = tc.get("/v1/preview/_preview非图片.md")
            assert r.status_code == 415, r.status_code
            assert "previewable" in r.json()
        finally:
            os.remove(f)

    def test_not_found_404(self, client_and_dir):
        tc, _ = client_and_dir
        assert tc.get("/v1/preview/_不存在.png").status_code == 404

    def test_path_traversal_rejected(self, client_and_dir):
        """新增端点必须复用同一套防护，不能开洞。"""
        tc, _ = client_and_dir
        for evil in ["..%2F..%2Fetc%2Fpasswd.png", "..\\..\\config.yaml.png"]:
            r = tc.get("/v1/preview/" + evil)
            assert r.status_code in (400, 403, 404), (evil, r.status_code)

    def test_svg_gets_sandbox_csp(self, client_and_dir):
        """SVG 可内嵌 <script>：同源内联渲染 = 存储型 XSS，必须 sandbox。"""
        tc, d = client_and_dir
        f = os.path.join(d, "_preview脚本.svg")
        with open(f, "w", encoding="utf-8") as fh:
            fh.write("<svg xmlns='http://www.w3.org/2000/svg'><text>x</text></svg>")
        try:
            r = tc.get("/v1/preview/_preview脚本.svg")
            assert r.status_code == 200
            assert "sandbox" in r.headers.get("content-security-policy", "")
            assert r.headers["content-type"].startswith("image/svg+xml")
        finally:
            os.remove(f)


class TestIsPreviewableImage:
    """扩展名白名单判定（大小写不敏感）。"""

    @pytest.mark.parametrize("name", ["a.png", "a.PNG", "a.jpg", "a.jpeg", "a.gif",
                                      "a.webp", "a.bmp", "a.svg", "a.avif"])
    def test_images_are_previewable(self, name):
        from tea_agent.server.route_handlers import is_previewable_image

        assert is_previewable_image(name) is True

    @pytest.mark.parametrize("name", ["a.md", "a.txt", "a.pdf", "a.zip", "noext", "a.png.exe"])
    def test_non_images_are_not(self, name):
        from tea_agent.server.route_handlers import is_previewable_image

        assert is_previewable_image(name) is False


class TestPublishDocPreviewUrl:
    """toolkit_publish_doc 对图片返回 preview_url，非图片不返回。"""

    def test_image_returns_preview_url(self, tmp_path):
        from tea_agent.toolkit.toolkit_publish_doc import toolkit_publish_doc

        src = tmp_path / "chart.png"
        src.write_bytes(b"\x89PNG\r\n\x1a\n")
        r = toolkit_publish_doc(source_path=str(src))
        assert r["ok"] is True, r
        assert r["url"].startswith("/v1/download/")
        assert r["preview_url"] == "/v1/preview/" + r["filename"]
        assert "图片" in r["hint"]
        # 清理
        os.remove(r["local_path"])

    def test_markdown_has_no_preview_url(self, tmp_path):
        from tea_agent.toolkit.toolkit_publish_doc import toolkit_publish_doc

        src = tmp_path / "doc.md"
        src.write_text("# hi", encoding="utf-8")
        r = toolkit_publish_doc(source_path=str(src))
        assert r["ok"] is True, r
        assert "preview_url" not in r
        os.remove(r["local_path"])
