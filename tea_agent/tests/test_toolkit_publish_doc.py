"""test_toolkit_publish_doc — 文档发布下载链接（工具 + server 端点）。"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tea_agent.tlk import Toolkit
from tea_agent.toolkit.toolkit_publish_doc import _clean_filename, toolkit_publish_doc


class TestPublishDocTool:
    """toolkit_publish_doc 工具功能。"""

    def test_registered(self):
        """工具应注册到 Toolkit.meta_map"""
        tk = Toolkit()
        assert "toolkit_publish_doc" in tk.meta_map
        meta = tk.meta_map["toolkit_publish_doc"]
        assert meta["type"] == "function"
        assert meta["function"]["name"] == "toolkit_publish_doc"

    def test_publish_basic(self, tmp_path):
        """发布文档 → 返回下载 URL，文件复制到导出目录"""
        src = tmp_path / "api.md"
        src.write_text("# API 文档", encoding="utf-8")
        r = toolkit_publish_doc(source_path=str(src), title="接口文档")
        assert r["ok"] is True
        assert r["url"] == "/v1/download/接口文档.md"
        assert r["filename"] == "接口文档.md"
        assert os.path.isfile(r["local_path"])
        assert r["size"] > 0
        # 内容一致
        with open(r["local_path"], encoding="utf-8") as f:
            assert f.read() == "# API 文档"
        os.remove(r["local_path"])

    def test_publish_default_title(self, tmp_path):
        """未传 title 时用源文件名"""
        src = tmp_path / "report.md"
        src.write_text("x", encoding="utf-8")
        r = toolkit_publish_doc(source_path=str(src))
        assert r["ok"] is True
        assert r["filename"] == "report.md"
        assert r["url"] == "/v1/download/report.md"
        os.remove(r["local_path"])

    def test_publish_illegal_title(self, tmp_path):
        """非法字符文件名被清理"""
        src = tmp_path / "a.md"
        src.write_text("x", encoding="utf-8")
        r = toolkit_publish_doc(source_path=str(src), title="a/b\\c:d*e?f.md")
        assert r["ok"] is True
        assert "/" not in r["filename"] and "\\" not in r["filename"]
        assert "接口" not in r["filename"]
        os.remove(r["local_path"])

    def test_publish_missing_source(self):
        """源文件不存在 → 报错"""
        r = toolkit_publish_doc(source_path="/nonexistent/xx.md")
        assert r["ok"] is False

    def test_clean_filename(self):
        assert _clean_filename('a/b\\c:d*e?f"<>|g') == "a_b_c_d_e_f____g"
        assert _clean_filename("  ") == "document"
        assert _clean_filename("...") == "document"


@pytest.fixture(scope="module")
def download_client():
    from starlette.testclient import TestClient

    from tea_agent.server.route_handlers import exports_dir
    from tea_agent.server.server import create_app

    app = create_app()
    return TestClient(app), exports_dir()


class TestDownloadRoute:
    """GET /v1/download/{filename} server 端点。"""

    def test_download_ok(self, download_client):
        tc, d = download_client
        f = os.path.join(d, "下载测试.md")
        with open(f, "w", encoding="utf-8") as fh:
            fh.write("# 下载测试")
        try:
            r = tc.get("/v1/download/下载测试.md")
            assert r.status_code == 200
            assert "attachment" in r.headers.get("content-disposition", "")
            assert "# 下载测试" in r.text
        finally:
            os.remove(f)

    def test_path_traversal_rejected(self, download_client):
        tc, _ = download_client
        for evil in ["..%2F..%2Fetc%2Fpasswd", "..\\..\\config.yaml"]:
            r = tc.get("/v1/download/" + evil)
            assert r.status_code in (400, 403, 404), (evil, r.status_code)

    def test_not_found(self, download_client):
        tc, _ = download_client
        r = tc.get("/v1/download/不存在.md")
        assert r.status_code == 404
