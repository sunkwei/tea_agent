"""文件树 → 文件预览 回归测试（/api/files · /api/file · /api/file/raw）。

缺陷背景（2026-10）：文件树能列目录、能读文本，但**图片看不到**——
`handle_file_tree` 的 `ignored_exts` 把 .png/.jpg/.gif/.svg/.webp 一律过滤掉，
所以树里根本没有图片条目，自然无从预览；即便手工构造 /api/file?path=x.png，
也会被 `read_text()` 当文本读成乱码。

修复：图片放行并标注 kind；文本按类型分流（json/md/code 给 format_hint）；
新增 /api/file/raw 用正确 MIME + inline 输出原始字节（供 <img src>）。

钉住的行为契约（非实现细节）：
  · 文件树**必须**列出图片（否则预览入口不存在）
  · /api/file 对图片**不得**返回 content（二进制当文本读 = 乱码）
  · /api/file/raw 可直接内联（正确 image MIME），非图片 415
  · 三个端点共用同一套路径遍历防护（不能因新增端点开洞）
  · 图片白名单与 /v1/preview 同源（同一文件不该一处能预览、一处不能）
"""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

# 1x1 透明 PNG（最小合法图片）
PNG_1PX = bytes.fromhex(
    "89504e470d0a1a0a0000000d494844520000000100000001080600000"
    "01f15c4890000000a49444154789c6300010000050001"
)


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """把服务端"启动目录"指向临时目录。

    handler 内部是 `import os as _os; _os.getcwd()` —— 绑定的是 os **模块**，
    所以 patch `os.getcwd` 即可生效（无需重启 app）。
    """
    (tmp_path / "sub").mkdir()
    (tmp_path / "hello.py").write_text("print('hi')\n# 注释\n", encoding="utf-8")
    (tmp_path / "data.json").write_text('{"a":1,"b":[2,3]}', encoding="utf-8")
    (tmp_path / "note.md").write_text("# 标题\n\n正文", encoding="utf-8")
    (tmp_path / "plain.txt").write_text("hello", encoding="utf-8")
    (tmp_path / "pic.png").write_bytes(PNG_1PX)
    (tmp_path / "sub" / "deep.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "archive.zip").write_bytes(b"PK\x03\x04fake")
    # .dat 既非文本也非图片，且不在 ignored_exts 里 → 应作为 binary 出现在树中
    (tmp_path / "blob.dat").write_bytes(b"\x00\x01\x02\xff")
    monkeypatch.setattr(os, "getcwd", lambda: str(tmp_path))
    return tmp_path


@pytest.fixture(scope="module")
def client():
    from starlette.testclient import TestClient

    from tea_agent.server.server import create_app

    return TestClient(create_app())


# ════════════════════════════════════════════════════════════
# 1. 纯函数：类型判定
# ════════════════════════════════════════════════════════════

class TestClassifyFile:
    @pytest.mark.parametrize("name", ["a.png", "a.PNG", "a.jpg", "a.jpeg", "a.gif", "a.webp", "a.svg", "a.bmp"])
    def test_images(self, name):
        from tea_agent.server.route_handlers_dag import classify_file

        kind, mime = classify_file(name)
        assert kind == "image"
        assert mime.startswith("image/")

    @pytest.mark.parametrize("name", ["a.py", "a.txt", "a.json", "a.md", "a.yaml", "a.sh", "a.log", "a.csv"])
    def test_texts(self, name):
        from tea_agent.server.route_handlers_dag import classify_file

        assert classify_file(name)[0] == "text"

    @pytest.mark.parametrize("name", ["a.zip", "a.exe", "a.bin", "a.mp4", "a.pdf", "noext"])
    def test_binaries(self, name):
        from tea_agent.server.route_handlers_dag import classify_file

        kind, mime = classify_file(name)
        assert kind == "binary"
        assert mime == "application/octet-stream"

    def test_extensionless_common_texts(self):
        """Dockerfile/Makefile/LICENSE 无扩展名但确实是文本。"""
        from tea_agent.server.route_handlers_dag import classify_file

        for n in ("Dockerfile", "Makefile", "LICENSE", "README"):
            assert classify_file(n)[0] == "text", n

    def test_image_whitelist_shared_with_preview(self):
        """图片白名单必须与 /v1/preview 同源（否则两处行为漂移）。"""
        from tea_agent.server.route_handlers_dag import classify_file
        from tea_agent.server.route_handlers_exports import _IMAGE_MIME

        for ext in _IMAGE_MIME:
            assert classify_file("x" + ext)[0] == "image", ext


# ════════════════════════════════════════════════════════════
# 2. 文件树：图片必须可见 + kind 标注
# ════════════════════════════════════════════════════════════

class TestFileTree:
    def test_images_are_listed(self, client, sandbox):
        """核心回归：图片此前被 ignored_exts 过滤，树里根本看不到。"""
        r = client.get("/api/files")
        assert r.status_code == 200, r.text
        names = {i["name"] for i in r.json()["items"]}
        assert "pic.png" in names, f"图片未出现在文件树: {sorted(names)}"

    def test_items_carry_kind(self, client, sandbox):
        r = client.get("/api/files")
        by_name = {i["name"]: i for i in r.json()["items"]}
        assert by_name["pic.png"]["kind"] == "image"
        assert by_name["hello.py"]["kind"] == "text"
        assert by_name["data.json"]["kind"] == "text"
        assert by_name["note.md"]["kind"] == "text"
        assert by_name["blob.dat"]["kind"] == "binary"
        assert by_name["sub"]["type"] == "dir"

    def test_heavy_binaries_still_hidden(self, client, sandbox):
        """放行图片不等于放行一切：.zip/.pyc 等仍应过滤（避免刷屏）。"""
        (sandbox / "mod.pyc").write_bytes(b"\x00\x01")
        r = client.get("/api/files")
        names = {i["name"] for i in r.json()["items"]}
        assert "archive.zip" not in names
        assert "mod.pyc" not in names

    def test_subdir_listing(self, client, sandbox):
        r = client.get("/api/files?path=sub")
        assert r.status_code == 200
        items = r.json()["items"]
        assert [i["name"] for i in items] == ["deep.py"]
        assert items[0]["path"].replace("\\", "/") == "sub/deep.py"


# ════════════════════════════════════════════════════════════
# 3. /api/file：按 kind 分流
# ════════════════════════════════════════════════════════════

class TestFileRead:
    def test_text_returns_content_and_hint(self, client, sandbox):
        r = client.get("/api/file?path=hello.py")
        d = r.json()
        assert d["ok"] is True
        assert d["kind"] == "text"
        assert "print('hi')" in d["content"]
        assert d["format_hint"] == "code"
        assert d["ext"] == ".py"

    def test_json_hint_is_json(self, client, sandbox):
        d = client.get("/api/file?path=data.json").json()
        assert d["kind"] == "text" and d["format_hint"] == "json"

    def test_markdown_hint_is_markdown(self, client, sandbox):
        d = client.get("/api/file?path=note.md").json()
        assert d["kind"] == "text" and d["format_hint"] == "markdown"

    def test_image_has_no_content_but_raw_url(self, client, sandbox):
        """图片不得被当文本读（二进制 → 乱码），改为指向 raw 端点。"""
        d = client.get("/api/file?path=pic.png").json()
        assert d["ok"] is True
        assert d["kind"] == "image"
        assert d["mime"] == "image/png"
        assert "content" not in d, "图片不应返回文本 content"
        assert d["raw_url"].startswith("/api/file/raw?path=")

    def test_binary_returns_message_not_content(self, client, sandbox):
        d = client.get("/api/file?path=archive.zip").json()
        assert d["kind"] == "binary"
        assert "content" not in d
        assert "不支持预览" in d["message"]

    def test_missing_path_400(self, client, sandbox):
        assert client.get("/api/file").status_code == 400

    def test_nonexistent_404(self, client, sandbox):
        assert client.get("/api/file?path=nope.py").status_code == 404


# ════════════════════════════════════════════════════════════
# 4. /api/file/raw：图片内联
# ════════════════════════════════════════════════════════════

class TestFileRaw:
    def test_png_inline_with_correct_mime(self, client, sandbox):
        r = client.get("/api/file/raw?path=pic.png")
        assert r.status_code == 200, r.text
        assert r.headers["content-type"].startswith("image/png")
        assert r.headers.get("x-content-type-options") == "nosniff"
        assert r.content == PNG_1PX

    def test_non_image_415(self, client, sandbox):
        r = client.get("/api/file/raw?path=hello.py")
        assert r.status_code == 415, r.status_code
        assert "previewable" in r.json()

    def test_svg_gets_sandbox_csp(self, client, sandbox):
        """SVG 可内嵌 <script>：同源内联 = 存储型 XSS，必须 sandbox。"""
        (sandbox / "vec.svg").write_text(
            "<svg xmlns='http://www.w3.org/2000/svg'><text>x</text></svg>", encoding="utf-8"
        )
        r = client.get("/api/file/raw?path=vec.svg")
        assert r.status_code == 200
        assert "sandbox" in r.headers.get("content-security-policy", "")
        assert r.headers["content-type"].startswith("image/svg+xml")

    def test_missing_file_404(self, client, sandbox):
        assert client.get("/api/file/raw?path=nope.png").status_code == 404


# ════════════════════════════════════════════════════════════
# 5. 路径遍历防护（三个端点共用同一套）
# ════════════════════════════════════════════════════════════

class TestPathTraversal:
    @pytest.mark.parametrize("evil", [
        "../outside.txt",
        "../../etc/passwd",
        "..\\..\\windows\\win.ini",
        "sub/../../outside.txt",
    ])
    def test_traversal_rejected_on_all_endpoints(self, client, sandbox, evil):
        """新增 raw 端点不得开洞；树/读/raw 三处口径一致。"""
        for url in (
            "/api/files?path=" + evil,
            "/api/file?path=" + evil,
            "/api/file/raw?path=" + evil,
        ):
            r = client.get(url)
            assert r.status_code in (400, 403, 404), (url, r.status_code)

    def test_sibling_prefix_dir_not_escaped(self, client, sandbox, tmp_path):
        """startswith 式校验会把 /root2 误判为 /root 子路径 —— 必须用 relative_to。"""
        outside = Path(str(sandbox) + "_evil")
        outside.mkdir(exist_ok=True)
        (outside / "secret.png").write_bytes(PNG_1PX)
        try:
            r = client.get("/api/file/raw?path=" + outside.name + "/secret.png")
            assert r.status_code in (403, 404), r.status_code
        finally:
            (outside / "secret.png").unlink(missing_ok=True)
            outside.rmdir()

    def test_absolute_path_rejected(self, client, sandbox):
        abs_evil = str(sandbox / "pic.png")
        r = client.get("/api/file?path=" + abs_evil)
        # 绝对路径拼接后仍落在 root 内时可能放行；越界必须拒绝
        if r.status_code == 200:
            d = r.json()
            assert d["path"] == abs_evil  # 同文件，无泄漏
        else:
            assert r.status_code in (400, 403, 404)
