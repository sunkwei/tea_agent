"""会话图片存储链路回归测试。

背景（修复前的缺陷）：
  1. Web 主路径 ``agent_module._save_chat_result`` 把 ``{"text","images"}``
     展平成纯文本再调 ``save_msg`` → ``images`` 键在入库前丢失，
     ``images`` 表恒为空（实测真实库 125 轮对话 / 0 张图）。
  2. ``/api/chat`` 先把图片写进 ``uploads/`` 目录再存库，文件系统留下
     无清理策略的副本；工作目录变更即导致历史图片永久丢失。
  3. ``save_msg`` 把 base64 内联进 ``user_msg``，而 ``get_conversations``
     每轮历史都 SELECT 该字段 → 每轮搬运数 MB。

修复后的契约（本文件钉住的行为）：
  - 图片二进制**只**存 ``images`` 表；``user_msg["images"]`` 只存 ``img:<id>`` 引用
  - Web 保存路径必须保留 images 字段（不得展平）
  - HTTP 入口不得在文件系统留副本
  - 导出（PDF/Markdown）必须把图片带上
"""

import base64
import json
import os

from tea_agent.image_ref import (
    build_data_url,
    is_image_ref,
    make_image_ref,
    parse_data_url,
    parse_image_ref,
)

# 1×1 有效 PNG（红点）
PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFAAH/q842iQAAAABJRU5ErkJggg=="
)


def _data_url(blob: bytes = PNG_BYTES, mime: str = "image/png") -> str:
    return f"data:{mime};base64," + base64.b64encode(blob).decode("ascii")


def _make_real_png() -> bytes:
    """用 Pillow 生成一张真实可解析的 PNG（尺寸 > 1px，供 PDF 嵌入用）。"""
    from io import BytesIO

    from PIL import Image

    buf = BytesIO()
    Image.new("RGB", (64, 48), (200, 30, 30)).save(buf, format="PNG")
    return buf.getvalue()


# ══════════════════════════════════════════════════════════
#  image_ref 编解码
# ══════════════════════════════════════════════════════════

class TestImageRef:
    def test_make_and_parse_roundtrip(self):
        assert make_image_ref(7) == "img:7"
        assert parse_image_ref("img:7") == 7

    def test_parse_rejects_non_refs(self):
        """文件路径 / data URL / 外链 / 空值一律不是引用（向后兼容旧数据）。"""
        for bad in ["uploads/x.png", "data:image/png;base64,AAA",
                    "https://example.com/a.png", "", None, "img:", "img:abc",
                    "img:0", "img:-1", 0, -3, True, False, 1.5]:
            assert parse_image_ref(bad) is None, bad

    def test_parse_accepts_positive_int(self):
        assert parse_image_ref(12) == 12
        assert is_image_ref(12) and is_image_ref("img:12")
        assert not is_image_ref("uploads/x.png")

    def test_parse_data_url(self):
        mime, blob = parse_data_url(_data_url(b"hello", "image/jpeg"))
        assert mime == "image/jpeg" and blob == b"hello"

    def test_parse_data_url_invalid(self):
        for bad in ["", "not-a-data-url", "data:image/png;base64,",
                    "data:image/png,"]:
            mime, blob = parse_data_url(bad)
            assert blob is None, bad

    def test_build_data_url(self):
        url = build_data_url(b"abc", "image/png")
        assert url.startswith("data:image/png;base64,")
        assert base64.b64decode(url.split(",", 1)[1]) == b"abc"
        assert build_data_url(b"", "image/png") == ""


# ══════════════════════════════════════════════════════════
#  save_msg 图片入库（核心契约）
# ══════════════════════════════════════════════════════════

class TestSaveMsgImageStorage:
    def test_data_url_stored_as_blob_with_ref(self, storage):
        """data URL 入参 → BLOB 入库，user_msg 只留 img:<id> 引用。"""
        tid = storage.create_topic("t")
        cid = storage.save_msg(tid, {"text": "看图", "images": [_data_url()]}, "", False)

        rows = storage.get_images([cid])
        assert cid in rows and len(rows[cid]) == 1
        assert rows[cid][0]["blob"] == PNG_BYTES
        assert rows[cid][0]["mime_type"] == "image/png"

        raw = storage.get_conversations(tid, limit=1)[0]["user_msg"]
        payload = json.loads(raw)
        assert payload["text"] == "看图"
        assert payload["images"] == [f"img:{rows[cid][0]['id']}"]

    def test_base64_not_inlined_in_user_msg(self, storage):
        """user_msg 不得内联 base64 —— 否则每轮历史查询都要搬运数 MB。"""
        tid = storage.create_topic("t")
        storage.save_msg(tid, {"text": "看图", "images": [_data_url()]}, "", False)
        raw = storage.get_conversations(tid, limit=1)[0]["user_msg"]
        assert "base64" not in raw
        assert len(raw) < 200, f"user_msg 体积异常: {len(raw)}"

    def test_get_image_returns_blob(self, storage):
        tid = storage.create_topic("t")
        cid = storage.save_msg(tid, {"text": "x", "images": [_data_url()]}, "", False)
        img_id = storage.get_images([cid])[cid][0]["id"]

        img = storage.get_image(img_id)
        assert img["blob"] == PNG_BYTES
        assert img["conversation_id"] == cid
        assert img["mime_type"] == "image/png"
        assert storage.get_image(999999) is None

    def test_multiple_images_keep_order(self, storage):
        tid = storage.create_topic("t")
        a = _data_url(b"\x89PNG-a", "image/png")
        b = _data_url(b"\x89PNG-b", "image/jpeg")
        cid = storage.save_msg(tid, {"text": "两张", "images": [a, b]}, "", False)

        imgs = storage.get_images([cid])[cid]
        assert len(imgs) == 2
        assert imgs[0]["blob"] == b"\x89PNG-a"
        assert imgs[1]["blob"] == b"\x89PNG-b"
        assert imgs[1]["mime_type"] == "image/jpeg"

    def test_file_path_still_supported(self, storage, tmp_path):
        """旧调用方传文件路径 → 仍入库（向后兼容）。"""
        p = tmp_path / "pic.png"
        p.write_bytes(PNG_BYTES)
        tid = storage.create_topic("t")
        cid = storage.save_msg(tid, {"text": "看图", "images": [str(p)]}, "", False)

        imgs = storage.get_images([cid])[cid]
        assert len(imgs) == 1 and imgs[0]["blob"] == PNG_BYTES

    def test_resaving_ref_is_idempotent(self, storage):
        """重复保存已是引用的项 → 不重复入库（避免多轮膨胀）。

        引用保持原样，图片行仍归属**原**会话（不复制 BLOB）；
        导出按 image id 查询，不受归属影响。
        """
        tid = storage.create_topic("t")
        storage.save_msg(tid, {"text": "看图", "images": [_data_url()]}, "", False)
        ref = json.loads(storage.get_conversations(tid, limit=1)[0]["user_msg"])["images"][0]

        storage.save_msg(tid, {"text": "再看", "images": [ref]}, "", False)

        # 引用原样保留
        payload2 = json.loads(storage.get_conversations(tid, limit=1)[0]["user_msg"])
        assert payload2["images"] == [ref]
        # 未新增 BLOB 行
        c = storage.conn.cursor()
        c.execute("SELECT COUNT(*) FROM images")
        assert c.fetchone()[0] == 1
        c.close()
        # 原引用仍可取回
        assert storage.get_image(parse_image_ref(ref))["blob"] == PNG_BYTES

    def test_plain_text_msg_unchanged(self, storage):
        tid = storage.create_topic("t")
        storage.save_msg(tid, "纯文本", "", False)
        assert storage.get_conversations(tid, limit=1)[0]["user_msg"] == "纯文本"

    def test_broken_image_does_not_lose_text(self, storage):
        """坏图不得拖垮保存：文本保留，坏项原样回填。"""
        tid = storage.create_topic("t")
        storage.save_msg(
            tid, {"text": "文字还在", "images": ["data:image/png;base64,!!!bad!!!"]},
            "", False,
        )
        payload = json.loads(storage.get_conversations(tid, limit=1)[0]["user_msg"])
        assert payload["text"] == "文字还在"
        assert payload["images"]  # 原样保留，未静默丢弃

    def test_no_image_no_blob_row(self, storage):
        tid = storage.create_topic("t")
        cid = storage.save_msg(tid, {"text": "无图"}, "", False)
        assert storage.get_images([cid]) == {}

    def test_get_images_empty_input(self, storage):
        assert storage.get_images([]) == {}
        assert storage.get_images(None) == {}

    def test_images_cascade_deleted_with_topic(self, storage):
        """删主题 → 图片随对话级联清理（不留孤儿 BLOB）。"""
        tid = storage.create_topic("t")
        cid = storage.save_msg(tid, {"text": "x", "images": [_data_url()]}, "", False)
        img_id = storage.get_images([cid])[cid][0]["id"]

        storage.delete_topic(tid)
        assert storage.get_image(img_id) is None


# ══════════════════════════════════════════════════════════
#  Web 保存路径（原缺陷所在）
# ══════════════════════════════════════════════════════════

class _StubSession:
    """_save_chat_result 需要的最小 session 桩。"""

    _rounds_collector = None
    _last_usage = None
    _last_cheap_usage = None


class TestWebSavePathPreservesImages:
    def test_save_chat_result_keeps_images(self, storage):
        """回归锚点：修复前此处展平丢图，images 表恒为空。"""
        from tea_agent.server.modules.agent_module import AgentModule

        tid = storage.create_topic("t")
        user_msg = {"text": "看这张图", "images": [_data_url()]}
        AgentModule._save_chat_result(storage, _StubSession(), tid, user_msg, "AI 回复", False)

        convs = storage.get_conversations(tid, limit=1)
        cid = convs[0]["id"]
        assert storage.get_images([cid]).get(cid), "Web 保存路径丢失了图片"

    def test_save_chat_result_plain_text_still_str(self, storage):
        """纯文本路径不得被改成 dict（保持既有形态）。"""
        from tea_agent.server.modules.agent_module import AgentModule

        tid = storage.create_topic("t")
        AgentModule._save_chat_result(storage, _StubSession(), tid, "纯文本问题", "答", False)
        assert storage.get_conversations(tid, limit=1)[0]["user_msg"] == "纯文本问题"


# ══════════════════════════════════════════════════════════
#  HTTP 入口不落盘
# ══════════════════════════════════════════════════════════

def _handler_source(func_name: str) -> str:
    """按函数名截取 route_handlers 中该函数的源码（用于静态契约检查）。"""
    import ast

    import tea_agent.server.route_handlers as rh

    with open(rh.__file__, encoding="utf-8") as fh:
        src = fh.read()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func_name:
            return ast.get_source_segment(src, node) or ""
    raise AssertionError(f"{func_name} not found in route_handlers")


class TestNoFilesystemBuffering:
    def test_helper_returns_data_urls(self):
        from tea_agent.server.route_handlers import _images_to_data_urls

        raw_b64 = base64.b64encode(PNG_BYTES).decode("ascii")
        out = _images_to_data_urls([_data_url(), raw_b64, ""], label="t")
        assert len(out) == 2
        assert all(u.startswith("data:") for u in out)
        # 裸 base64 补 image/png 前缀
        assert out[1].startswith("data:image/png;base64,")

    def test_helper_skips_invalid(self):
        from tea_agent.server.route_handlers import _images_to_data_urls

        assert _images_to_data_urls(["!!!not-base64!!!"], label="t") == []
        assert _images_to_data_urls(None) == []

    def test_chat_and_steering_do_not_write_files(self):
        """对话/插话入口不得再写 uploads/（原缺陷：先落盘再入库）。

        注：``/v1/upload``（通用文件上传 API，返回 path+url）是另一功能，
        不属于会话图片链路，不在本断言范围内。
        """
        for fn in ("handle_web_chat", "handle_web_chat_steering"):
            body = _handler_source(fn)
            assert "uploads" not in body, f"{fn} 仍在写 uploads/ 目录"
            assert "write_bytes" not in body, f"{fn} 仍在落盘"
            assert "_images_to_data_urls" in body, f"{fn} 未走内存归一化路径"

    def test_uploads_dir_not_created_by_image_helper(self, tmp_path, monkeypatch):
        import tea_agent.server.route_handlers as rh

        monkeypatch.chdir(tmp_path)
        rh._images_to_data_urls([_data_url()], label="t")
        assert not (tmp_path / "uploads").exists()


# ══════════════════════════════════════════════════════════
#  LLM 请求路径：img:<id> → data URL
# ══════════════════════════════════════════════════════════

class TestToMultimodalResolvesRefs:
    def _ctx(self, storage):
        class _Ctx:
            pass

        c = _Ctx()
        c.storage = storage
        return c

    def test_resolver_fetches_blob_from_db(self, storage):
        from tea_agent.session.history_builder import _image_resolver_of, to_multimodal

        tid = storage.create_topic("t")
        storage.save_msg(tid, {"text": "x", "images": [_data_url()]}, "", False)
        ref = json.loads(storage.get_conversations(tid, limit=1)[0]["user_msg"])["images"][0]

        msg = {"role": "user", "content": "看图", "images": [ref]}
        out = to_multimodal(msg, supports_vision=True,
                            image_resolver=_image_resolver_of(self._ctx(storage)))
        parts = out["content"]
        assert isinstance(parts, list)
        urls = [p["image_url"]["url"] for p in parts if p["type"] == "image_url"]
        assert len(urls) == 1
        assert base64.b64decode(urls[0].split(",", 1)[1]) == PNG_BYTES

    def test_resolver_none_skips_refs(self, storage):
        """无 resolver 时引用被跳过（不炸、不产生非法 content）。"""
        from tea_agent.session.history_builder import to_multimodal

        out = to_multimodal({"role": "user", "content": "看图", "images": ["img:1"]},
                            supports_vision=True, image_resolver=None)
        assert out["content"] == "看图"

    def test_missing_image_skipped(self, storage):
        from tea_agent.session.history_builder import _image_resolver_of, to_multimodal

        out = to_multimodal({"role": "user", "content": "看图", "images": ["img:999999"]},
                            supports_vision=True,
                            image_resolver=_image_resolver_of(self._ctx(storage)))
        assert out["content"] == "看图"

    def test_no_storage_returns_none_resolver(self):
        from tea_agent.session.history_builder import _image_resolver_of

        class _Ctx:
            storage = None

        assert _image_resolver_of(_Ctx()) is None


# ══════════════════════════════════════════════════════════
#  导出：PDF / Markdown 必须带上图片
# ══════════════════════════════════════════════════════════

class TestExportIncludesImages:
    def _seed(self, storage):
        tid = storage.create_topic("图片导出测试")
        png = _make_real_png()
        cid = storage.save_msg(
            tid, {"text": "看这张图", "images": [_data_url(png)]}, "我看到了", False
        )
        storage.update_msg_rounds(conversation_id=cid, ai_msg="我看到了",
                                   is_func_calling=False, rounds=None)
        return tid, cid, png

    def test_parse_user_payload_extracts_ids(self):
        from tea_agent.toolkit.toolkit_export_last_pdf import _parse_user_payload

        text, ids = _parse_user_payload('{"text": "hi", "images": ["img:3", "img:9"]}')
        assert text == "hi" and ids == [3, 9]

    def test_parse_user_payload_backcompat(self):
        """旧数据（路径/dataURL）不产出 id，但仍返回文本。"""
        from tea_agent.toolkit.toolkit_export_last_pdf import _parse_user_payload

        text, ids = _parse_user_payload('{"text": "hi", "images": ["uploads/a.png"]}')
        assert text == "hi" and ids == []
        assert _parse_user_payload("纯文本") == ("纯文本", [])
        assert _parse_user_payload(None) == ("", [])

    def test_pdf_latest_embeds_image(self, storage, tmp_path):
        from tea_agent.toolkit.toolkit_export_last_pdf import export_topic_pdf

        tid, _cid, _png = self._seed(storage)
        out = str(tmp_path / "o.pdf")
        export_topic_pdf(tid, output_path=out, db_path=storage.db_path, mode="latest")

        with open(out, "rb") as fh:
            data = fh.read()
        assert data.startswith(b"%PDF")
        assert b"/Image" in data and b"/XObject" in data, "PDF 未嵌入图像对象"

    def test_pdf_full_topic_embeds_image(self, storage, tmp_path):
        from tea_agent.toolkit.toolkit_export_last_pdf import export_topic_pdf

        tid, _cid, _png = self._seed(storage)
        storage.save_msg(tid, "无图第二轮", "答", False)
        out = str(tmp_path / "f.pdf")
        export_topic_pdf(tid, output_path=out, db_path=storage.db_path, mode="full_topic")

        with open(out, "rb") as fh:
            data = fh.read()
        assert b"/Image" in data, "full_topic PDF 未嵌入图像"

    def test_markdown_latest_inlines_image(self, storage, tmp_path):
        from tea_agent.toolkit.toolkit_export_last_pdf import export_topic_markdown

        tid, _cid, _png = self._seed(storage)
        out = str(tmp_path / "o.md")
        export_topic_markdown(tid, output_path=out, db_path=storage.db_path, mode="latest")

        with open(out, encoding="utf-8") as fh:
            md = fh.read()
        assert "![图片](data:image/png;base64," in md
        assert "看这张图" in md

    def test_markdown_full_topic_inlines_image(self, storage, tmp_path):
        from tea_agent.toolkit.toolkit_export_last_pdf import export_topic_markdown

        tid, _cid, _png = self._seed(storage)
        out = str(tmp_path / "f.md")
        export_topic_markdown(tid, output_path=out, db_path=storage.db_path, mode="full_topic")

        with open(out, encoding="utf-8") as fh:
            md = fh.read()
        assert "![图片](data:image/png;base64," in md

    def test_export_without_images_still_works(self, storage, tmp_path):
        """无图对话导出不得回归（导出路径不能强依赖图片）。"""
        from tea_agent.toolkit.toolkit_export_last_pdf import (
            export_topic_markdown,
            export_topic_pdf,
        )

        tid = storage.create_topic("纯文本")
        storage.save_msg(tid, "只有文字", "回复", False)

        p = str(tmp_path / "n.pdf")
        m = str(tmp_path / "n.md")
        export_topic_pdf(tid, output_path=p, db_path=storage.db_path, mode="latest")
        export_topic_markdown(tid, output_path=m, db_path=storage.db_path, mode="latest")
        with open(p, "rb") as fh:
            assert fh.read().startswith(b"%PDF")
        with open(m, encoding="utf-8") as fh:
            assert "只有文字" in fh.read()

    def test_render_images_failopen_on_bad_blob(self):
        """坏图只告警跳过，绝不抛异常中断导出。"""
        from fpdf import FPDF

        from tea_agent.toolkit.toolkit_export_last_pdf import _render_images

        pdf = FPDF()
        pdf.add_page()
        _render_images(pdf, [("image/png", b"not-an-image")])  # 不应抛错

    def test_normalize_image_fixes_odd_modes(self):
        """重编码兜底：调色板/alpha 等形态转 RGB PNG。"""
        from io import BytesIO

        from PIL import Image

        from tea_agent.toolkit.toolkit_export_last_pdf import _normalize_image

        buf = BytesIO()
        Image.new("P", (8, 8)).save(buf, format="PNG")
        out = _normalize_image(buf.getvalue())
        assert out and out.startswith(b"\x89PNG")
        assert _normalize_image(b"garbage") is None


# ══════════════════════════════════════════════════════════
#  前端解析契约（静态检查，防回归）
# ══════════════════════════════════════════════════════════

class TestFrontendParsing:
    def test_app_js_has_parse_user_msg(self):
        import tea_agent.server.route_handlers as rh

        app_js = os.path.join(os.path.dirname(rh.__file__), "static", "app.js")
        with open(app_js, encoding="utf-8") as fh:
            src = fh.read()
        assert "function parseUserMsg" in src
        assert "/api/image/" in src, "前端未把 img:<id> 映射到回读路由"

    def test_image_route_registered(self):
        """契约：图片回读路由必须在路由层注册。

        断言的是**路由被注册**这一契约，而非「该字符串恰好写在 server.py 里」。
        原先只读 server.py —— 那是实现细节：路由表已抽到 server/_routes.py
        （拆 _build_routes 以降低单文件体积），白盒扫描随即误报失败，而真实
        路由并未丢失（应用内仍有 /api/image/{image_id:str}）。
        改为扫描 server 包内的路由定义源码，对后续任何模块拆分都免疫。
        """
        import pathlib

        import tea_agent.server as srv_pkg

        pkg_dir = pathlib.Path(srv_pkg.__file__).parent
        needle = "/api/image/{image_id:str}"
        hits = []
        for p in pkg_dir.rglob("*.py"):
            if "__pycache__" in p.parts:
                continue
            if needle in p.read_text(encoding="utf-8"):
                hits.append(p.name)
        assert hits, (
            f"路由层（{pkg_dir.name}/）未注册 {needle} —— 图片回读路由丢失"
        )


# ══════════════════════════════════════════════════════════
#  回读接口
# ══════════════════════════════════════════════════════════

class TestImageHttpEndpoint:
    """回读接口。项目未装 pytest-asyncio，统一用 asyncio.run 驱动。"""

    @staticmethod
    def _run(coro):
        import asyncio

        return asyncio.run(coro)

    def test_handle_web_image_returns_bytes(self, storage, monkeypatch):
        from tea_agent.server import route_handlers as rh

        tid = storage.create_topic("t")
        cid = storage.save_msg(tid, {"text": "x", "images": [_data_url()]}, "", False)
        img_id = storage.get_images([cid])[cid][0]["id"]

        class _Srv:
            def get_image(self, i):
                return storage.get_image(i)

        monkeypatch.setattr(rh, "get_server", lambda: _Srv())

        class _Req:
            path_params = {"image_id": str(img_id)}

        resp = self._run(rh.handle_web_image(_Req()))
        assert resp.status_code == 200
        assert resp.body == PNG_BYTES
        assert "image/png" in resp.headers.get("content-type", "")

    def test_handle_web_image_404(self, storage, monkeypatch):
        from tea_agent.server import route_handlers as rh

        class _Srv:
            def get_image(self, i):
                return None

        monkeypatch.setattr(rh, "get_server", lambda: _Srv())

        class _Req:
            path_params = {"image_id": "42"}

        resp = self._run(rh.handle_web_image(_Req()))
        assert resp.status_code == 404

    def test_handle_web_image_bad_id(self, monkeypatch):
        from tea_agent.server import route_handlers as rh

        class _Req:
            path_params = {"image_id": "abc"}

        resp = self._run(rh.handle_web_image(_Req()))
        assert resp.status_code == 400


# ══════════════════════════════════════════════════════════
#  schema
# ══════════════════════════════════════════════════════════

class TestImagesSchema:
    def test_images_table_columns(self, storage):
        c = storage.conn.cursor()
        c.execute("PRAGMA table_info(images)")
        cols = {r["name"] for r in c.fetchall()}
        c.close()
        assert {"id", "conversation_id", "image_blob", "mime_type"} <= cols

    def test_blob_is_binary_not_text(self, storage):
        """确认 BLOB 类型（TEXT 会因编码截断二进制）。"""
        tid = storage.create_topic("t")
        cid = storage.save_msg(tid, {"text": "x", "images": [_data_url()]}, "", False)
        c = storage.conn.cursor()
        c.execute("SELECT typeof(image_blob) FROM images WHERE conversation_id = ?", (cid,))
        assert c.fetchone()[0] == "blob"
        c.close()
