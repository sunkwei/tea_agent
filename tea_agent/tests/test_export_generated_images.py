"""生成物图片进 PDF/MD 导出（回归测试）。

缺陷背景：生成物图片（AI 生成的 .png 等）不在 images 表（那是用户上传的图），
只以 `/v1/download|preview/xxx.png` 链接形式出现在 AI 回复正文里。
导出只嵌 images 表 → 导出 PDF 时生成物图片全部丢失，只剩一行链接文字。

修复：新增 `_extract_generated_images`，「AI 回复中的图片链接 → 读回 bytes →
_render_images / _render_image_markdown」。
"""

import base64
import pathlib

import pytest

from tea_agent.toolkit import toolkit_export_last_pdf as ex

PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d4944415478da63fcffff3f030005fe02fea72d4b960000000049454e44ae426082"
)


@pytest.fixture
def exports(tmp_path, monkeypatch):
    """把 exports 目录指到临时目录（避免碰真实 ~/.tea_agent/exports）。"""
    monkeypatch.setattr(ex, "_exports_dir", lambda: tmp_path)
    return tmp_path


class TestExtractGeneratedImages:
    def test_download_link_extracted(self, exports):
        (exports / "图.png").write_bytes(PNG)
        got = ex._extract_generated_images("看这里 [下载图片](/v1/download/图.png)")
        assert got == [("image/png", PNG)]

    def test_preview_link_extracted(self, exports):
        """Markdown 图片语法 ![](/v1/preview/x.png) 同样要抓到。"""
        (exports / "x.png").write_bytes(PNG)
        assert ex._extract_generated_images("![说明](/v1/preview/x.png)") == [("image/png", PNG)]

    def test_url_encoded_chinese_name(self, exports):
        (exports / "青岛夜景.png").write_bytes(PNG)
        got = ex._extract_generated_images("[图](/v1/download/%E9%9D%92%E5%B2%9B%E5%A4%9C%E6%99%AF.png)")
        assert got == [("image/png", PNG)]

    def test_deduplicated(self, exports):
        (exports / "a.png").write_bytes(PNG)
        text = "[1](/v1/download/a.png) ... [2](/v1/download/a.png)"
        assert len(ex._extract_generated_images(text)) == 1

    def test_identical_name_across_download_and_preview_deduped(self, exports):
        (exports / "a.png").write_bytes(PNG)
        text = "[下载](/v1/download/a.png) 和 ![](/v1/preview/a.png)"
        assert len(ex._extract_generated_images(text)) == 1

    def test_missing_file_skipped_fail_open(self, exports):
        """文件缺失不得抛错（单张图缺失不能让整份导出失败）。"""
        assert ex._extract_generated_images("[x](/v1/download/不存在.png)") == []

    def test_path_traversal_rejected(self, exports):
        evil = "[x](/v1/download/..%2F..%2Fsecret.png)"
        assert ex._extract_generated_images(evil) == []

    def test_non_image_link_ignored(self, exports):
        (exports / "文档.md").write_bytes(b"# hi")
        assert ex._extract_generated_images("[doc](/v1/download/文档.md)") == []

    def test_glb_not_treated_as_image(self, exports):
        (exports / "模型.glb").write_bytes(b"glTF")
        assert ex._extract_generated_images("[m](/v1/download/模型.glb)") == []

    def test_no_links_returns_empty(self, exports):
        assert ex._extract_generated_images("纯文本，无链接") == []

    def test_multiple_texts_merged_in_order(self, exports):
        (exports / "1.png").write_bytes(PNG)
        (exports / "2.png").write_bytes(PNG)
        got = ex._extract_generated_images("[1](/v1/download/1.png)", "[2](/v1/download/2.png)")
        assert len(got) == 2


class TestMarkdownExportEmbedsGenerated:
    """Markdown 导出把生成物图片内联为 data URL（单文件自包含）。"""

    def _data_urls(self, text):
        return [t.split(")")[0] for t in text.split("](data:")[1:]]

    def test_single_conversation(self, exports):
        (exports / "图.png").write_bytes(PNG)
        md = ex._build_markdown_doc("标题", "2026-09-25", "问题", "结果 ![图](/v1/preview/图.png)")
        b64 = base64.b64encode(PNG).decode()
        assert f"data:image/png;base64,{b64}" in md

    def test_full_topic(self, exports):
        (exports / "图.png").write_bytes(PNG)
        md = ex._build_full_topic_markdown("标题", [
            {"stamp": "t", "user_msg": "问题", "ai_msg": "[图](/v1/download/图.png)"},
        ])
        b64 = base64.b64encode(PNG).decode()
        assert f"data:image/png;base64,{b64}" in md

    def test_pdf_renders_generated_image(self, exports):
        """pdf 导出路径必须把生成物图交给 _render_images（而非只渲染链接文字）。"""
        (exports / "图.png").write_bytes(PNG)
        seen = []
        real = ex._render_images

        def spy(pdf, images, *a, **k):
            seen.extend(images or [])
            return real(pdf, images, *a, **k)

        import unittest.mock as mock
        with mock.patch.object(ex, "_render_images", spy):
            out = ex._make_pdf("标题", "t", "问题", "[图](/v1/preview/图.png)", "", str(exports / "o.pdf"))
        assert pathlib.Path(out).is_file()
        assert [b for _m, b in seen] == [PNG]
