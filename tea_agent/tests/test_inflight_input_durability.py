"""会话输入（文本 + 图片）在「回合进行中切走再切回」时不得丢失的回归测试。

背景（用户实测报告 + 端到端复现）：
  回合进行中发送带图消息 → 切到其它主题 → 切回原主题，图片看不到。
  用户判断「入库之前切换了主题」，实测确认两个叠加缺陷：

  ① data URL 被快照截断成损坏值
     回合开始记录的 user_message 事件放的是完整 data URL（实测 45k 字符），
     而快照 _shrink 上限 2000 → 存成 'data:image/png;base64,AAAA…[truncated]'。
     前端 <img src> 拿到这个值只会渲染出破图。

  ② 图片只活在内存里，切回无从恢复
     图片原本要等回合结束的 save_msg 才入库，而切走再切回时回合还没结束，
     DB 查不到、快照里的 data URL 又是坏的 → 图片彻底丢失。

修复：回合**开始**即把图片入库（conversation_id='' 暂未归属），全程改用
img:<id> 短引用；归属由回合结束的 save_msg 补齐（_adopt_image）。
"""

from __future__ import annotations

import base64
import io
import json

import pytest

from tea_agent.image_ref import make_image_ref, parse_image_ref
from tea_agent.server import turn_snapshot as ts
from tea_agent.server.modules import state as state_mod
from tea_agent.store import Storage


@pytest.fixture()
def db(tmp_path, monkeypatch):
    """隔离的临时快照库。"""
    p = tmp_path / "server_state.db"
    monkeypatch.setenv("TEA_SERVER_STATE_DB", str(p))
    ts._last_write.clear()
    return str(p)


def _png() -> bytes:
    """真实 PNG（避免用坏样本掩盖问题）。"""
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (60, 40), (20, 140, 220)).save(buf, format="PNG")
    return buf.getvalue()


def _data_url(blob: bytes | None = None) -> str:
    return "data:image/png;base64," + base64.b64encode(blob or _png()).decode()


@pytest.fixture()
def state_mod(monkeypatch):
    """真实 state 模块，用完清空全局态。"""
    from tea_agent.server.modules import state as st

    st.clear_all()
    yield st
    st.clear_all()


@pytest.fixture()
def storage(tmp_path):
    s = Storage(db_path=str(tmp_path / "chat.db"))
    yield s
    s.close()


# ════════════════════════════════════════════════════════════
# 1. 回合开始即入库（修复点：输入不丢失）
# ════════════════════════════════════════════════════════════


class TestPersistTurnImages:
    def test_data_url_becomes_short_ref(self, storage):
        """data URL → img:<id> 短引用（不再携带数万字符 base64）。"""
        from tea_agent.server.route_handlers import _persist_turn_images

        url = _data_url()
        refs = _persist_turn_images(storage, [url], label="t")

        assert len(refs) == 1
        assert refs[0].startswith("img:")
        assert "base64" not in refs[0]
        assert len(refs[0]) < 20, f"引用应短小，实为 {len(refs[0])} 字符"
        # 图片确实可回读，且字节一致
        img_id = parse_image_ref(refs[0])
        assert storage.get_image(img_id)["blob"] == _png()

    def test_no_storage_passthrough(self):
        """storage 缺失（fail-open）→ 原样返回，不抛异常、不丢输入。"""
        from tea_agent.server.route_handlers import _persist_turn_images

        url = _data_url()
        assert _persist_turn_images(None, [url], label="t") == [url]
        assert _persist_turn_images(None, [], label="t") == []
        assert _persist_turn_images(None, None, label="t") == []

    def test_broken_data_url_preserved(self, storage):
        """解析失败的 data URL 原样保留 —— 绝不静默丢输入。"""
        from tea_agent.server.route_handlers import _persist_turn_images

        bad = "data:image/png;base64,!!!not-base64!!!"
        assert _persist_turn_images(storage, [bad], label="t") == [bad]

    def test_external_url_preserved(self, storage):
        """外链（http/https）原样保留。"""
        from tea_agent.server.route_handlers import _persist_turn_images

        ext = "https://example.com/a.png"
        assert _persist_turn_images(storage, [ext], label="t") == [ext]

    def test_multiple_images_keep_order(self, storage):
        from tea_agent.server.route_handlers import _persist_turn_images

        a, b = _data_url(b"\x89PNG-a"), _data_url(b"\x89PNG-b")
        refs = _persist_turn_images(storage, [a, b], label="t")
        assert [storage.get_image(parse_image_ref(r))["blob"] for r in refs] == \
            [b"\x89PNG-a", b"\x89PNG-b"]


# ════════════════════════════════════════════════════════════
# 2. 快照能承载图片（修复点：不被 _shrink 截断）
# ════════════════════════════════════════════════════════════


class TestSnapshotCarriesImageRef:
    def test_data_url_would_be_truncated(self):
        """反证：完整 data URL 会被 _shrink 截断成损坏值（故必须改存引用）。"""
        url = _data_url(_png() * 200)      # 放大到远超上限
        assert len(url) > ts.DEFAULT_MAX_FIELD
        shrunk = ts._shrink(url, ts.DEFAULT_MAX_FIELD)
        assert shrunk != url, "前提失效：该 data URL 未被截断"
        assert shrunk.endswith("[truncated]"), "截断后是损坏值，前端 <img> 无法渲染"

    def test_ref_survives_snapshot_roundtrip(self, db, storage):
        """img:<id> 引用经快照存取后完好（长度远小于上限，不被截断）。"""
        from tea_agent.server.route_handlers import _persist_turn_images

        refs = _persist_turn_images(storage, [_data_url()], label="t")
        ts.begin_turn("t1")
        ts.record_event("t1", {"type": "user_message", "text": "看图",
                               "images": refs}, 0, force=True)

        snap = ts.read_snapshot("t1")
        got = snap["events"][0]["event"]["images"]
        assert got == refs, "引用被改写"
        assert "truncated" not in json.dumps(got), "引用被截断"
        assert storage.get_image(parse_image_ref(got[0]))["blob"] == _png()

    def test_durable_across_process_restart(self, db, storage):
        """重启语义：进程态清空后，仅凭快照 + DB 仍能取回图片。"""
        from tea_agent.server.route_handlers import _persist_turn_images

        refs = _persist_turn_images(storage, [_data_url()], label="t")
        ts.begin_turn("t1")
        ts.record_event("t1", {"type": "user_message", "text": "看图",
                               "images": refs}, 0, force=True)
        ts.flush_pending("t1")

        # 模拟进程重启：清空全部内存态
        ts._pending.clear(); ts._next_index.clear(); ts._begun.clear()

        snap = ts.read_snapshot("t1")
        ref = snap["events"][0]["event"]["images"][0]
        assert storage.get_image(parse_image_ref(ref))["blob"] == _png()


# ════════════════════════════════════════════════════════════
# 3. 归属补齐（回合结束 save_msg）
# ════════════════════════════════════════════════════════════


class TestImageOwnershipAdoption:
    def test_pending_then_adopted(self, storage):
        """回合开始入库（未归属）→ save_msg 补上归属，且不新增行。"""
        tid = storage.create_topic("t")
        img_id = storage.add_pending_image(_png(), "image/png")
        assert storage.get_image(img_id)["conversation_id"] == ""

        cid = storage.save_msg(tid, {"text": "看图", "images": [make_image_ref(img_id)]},
                               "", False)

        assert storage.get_image(img_id)["conversation_id"] == cid
        c = storage.conn.cursor()
        c.execute("SELECT COUNT(*) FROM images")
        assert c.fetchone()[0] == 1, "归属补齐不应新增行"
        c.close()

    def test_already_owned_not_stolen(self, storage):
        """已归属的图片不被后续会话抢走（历史轮引用会指错会话）。"""
        tid = storage.create_topic("t")
        img_id = storage.add_pending_image(_png(), "image/png")
        cid1 = storage.save_msg(tid, {"text": "a", "images": [make_image_ref(img_id)]},
                                "", False)
        # 第二个会话重复引用同一张图
        storage.save_msg(tid, {"text": "b", "images": [make_image_ref(img_id)]}, "", False)

        assert storage.get_image(img_id)["conversation_id"] == cid1, "归属被抢走"

    def test_get_images_by_conv_after_adopt(self, storage):
        """导出路径按 conv_id 查图：归属补齐后必须命中。"""
        tid = storage.create_topic("t")
        img_id = storage.add_pending_image(_png(), "image/png")
        cid = storage.save_msg(tid, {"text": "看图", "images": [make_image_ref(img_id)]},
                               "", False)
        assert len(storage.get_images([cid]).get(cid, [])) == 1


# ════════════════════════════════════════════════════════════
# 4. 孤儿图片清理（崩溃遗留，且不得误删待恢复的图）
# ════════════════════════════════════════════════════════════


class TestOrphanImageCleanup:
    def test_cleanup_removes_unowned(self, storage):
        """未归属且无引用的图片被清理（否则永久占库且不可达）。"""
        storage.add_pending_image(_png(), "image/png")
        assert storage.cleanup_orphan_images(keep_ids=set()) == 1

    def test_cleanup_keeps_referenced(self, storage):
        """被在途快照引用的图片必须保留 —— 它是待恢复回合要显示的内容。"""
        keep_id = storage.add_pending_image(_png(), "image/png")
        storage.add_pending_image(_png(), "image/png")   # 真孤儿

        n = storage.cleanup_orphan_images(keep_ids={keep_id})

        assert n == 1, "只应删掉真孤儿"
        assert storage.get_image(keep_id) is not None, "待恢复的图片被误删"

    def test_cleanup_never_touches_owned(self, storage):
        """已归属的图片绝不被清理（即使在 keep_ids 之外）。"""
        tid = storage.create_topic("t")
        img_id = storage.add_pending_image(_png(), "image/png")
        storage.save_msg(tid, {"text": "看图", "images": [make_image_ref(img_id)]},
                         "", False)

        assert storage.cleanup_orphan_images(keep_ids=set()) == 0
        assert storage.get_image(img_id) is not None

    def test_snapshot_image_ids_collects_refs(self, db, storage):
        """snapshot_image_ids 收集快照里的 img:<id>。"""
        from tea_agent.server.route_handlers import _persist_turn_images

        refs = _persist_turn_images(storage, [_data_url()], label="t")
        ts.begin_turn("t1")
        ts.record_event("t1", {"type": "user_message", "text": "看图",
                               "images": refs}, 0, force=True)
        ts.flush_pending("t1")

        got = ts.snapshot_image_ids()
        assert got is not None
        assert parse_image_ref(refs[0]) in got

    def test_snapshot_image_ids_none_on_failure(self, monkeypatch):
        """读不到快照 → None（表示"未知"），调用方应跳过清理而非删光。"""
        def _boom(*a, **k):
            raise OSError("unreadable")

        monkeypatch.setattr(ts, "_connect", _boom)
        assert ts.snapshot_image_ids() is None, "必须返回 None 而非空集"


# ════════════════════════════════════════════════════════════
# 5. 端到端语义：切走再切回，图片 + 文本都能拿到
# ════════════════════════════════════════════════════════════


class TestSwitchBackEndToEnd:
    def test_switch_back_sees_image_and_text(self, db, storage, state_mod):
        """回合进行中切回：提问文本 + 图片引用都从缓冲区拿到，且图片可回读。"""
        from tea_agent.server._compat import _seed_buffer_from_snapshot
        from tea_agent.server.route_handlers import _persist_turn_images

        refs = _persist_turn_images(storage, [_data_url()], label="t")
        ts.begin_turn("t1")
        ts.record_event("t1", {"type": "user_message", "text": "看看这张图",
                               "images": refs}, 0, force=True)
        ts.record_event("t1", {"type": "token", "text": "收到"}, 1, force=True)

        state_mod.create_background_buffer("t1")
        _seed_buffer_from_snapshot("t1")
        events = state_mod.read_buffer_since("t1", -1)["events"]

        um = [e["event"] for e in events if e["event"]["type"] == "user_message"]
        assert um, f"切回后看不到提问：{[e['event']['type'] for e in events]}"
        assert um[0]["text"] == "看看这张图"
        got_ref = um[0]["images"][0]
        assert got_ref.startswith("img:"), f"图片引用形态异常：{got_ref[:40]}"
        # 关键：引用可回读为真实字节（前端 /api/image/<id> 即走这条路径）
        assert storage.get_image(parse_image_ref(got_ref))["blob"] == _png()

    def test_llm_still_receives_image(self, db, storage):
        """改用引用后，发给 LLM 的多模态内容仍含真实图片（能力未回退）。"""
        import base64 as b64

        from tea_agent.server.route_handlers import _persist_turn_images
        from tea_agent.session.history_builder import _image_resolver_of, to_multimodal

        refs = _persist_turn_images(storage, [_data_url()], label="t")

        class _Ctx:
            pass

        ctx = _Ctx()
        ctx.storage = storage
        out = to_multimodal({"role": "user", "content": "看图", "images": refs},
                            supports_vision=True,
                            image_resolver=_image_resolver_of(ctx))
        urls = [p["image_url"]["url"] for p in out["content"]
                if p.get("type") == "image_url"]
        assert len(urls) == 1, f"LLM 未收到图片：{out}"
        assert b64.b64decode(urls[0].split(",", 1)[1]) == _png()

    def test_no_image_input_unchanged(self, db, storage):
        """纯文本输入：payload 保持 str 形态（不引入 dict 包装）。"""
        from tea_agent.server.route_handlers import _persist_turn_images

        assert _persist_turn_images(storage, [], label="t") == []


# ════════════════════════════════════════════════════════════
# 6. Handler 接线（判别性：还原旧实现必须变红）
# ════════════════════════════════════════════════════════════


def _handler_source(func_name: str) -> str:
    """按函数名截取 route_handlers 中该函数的源码。"""
    import ast

    import tea_agent.server.route_handlers as rh

    with open(rh.__file__, encoding="utf-8") as f:
        src = f.read()
    for node in ast.walk(ast.parse(src)):
        if (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == func_name):
            return ast.get_source_segment(src, node) or ""
    raise AssertionError(f"{func_name} not found")


class TestHandlerWiring:
    """静态接线契约：前面的用例只验了构件，这里钉住 handler 真的用了它们。

    元验证发现：若只测 ``_persist_turn_images`` 本身，把 handler 还原成
    「直接传 data URL」时测试仍全绿 —— 因为构件没变。本类补上这一环。
    """

    def test_chat_handler_persists_images_before_snapshot(self):
        body = _handler_source("handle_web_chat")

        assert "_persist_turn_images(storage, image_paths" in body, \
            "handler 未在回合开始把图片入库"
        assert '"images": _img_refs' in body, \
            "快照事件未使用 img:<id> 短引用"
        assert '"images": image_paths' not in body, \
            "快照仍在写 data URL —— 会被 _shrink 截断成损坏值"
        assert "_turn_payload" in body, \
            "未把引用传给对话线程（LLM 将拿不到图片）"

    def test_turn_payload_prefers_refs(self):
        body = _handler_source("handle_web_chat")
        assert '"images": _img_refs}' in body, "payload 未携带引用"

    def test_user_message_recorded_with_refs(self):
        body = _handler_source("handle_web_chat")
        idx = body.find("user_message")
        assert idx > 0, "未记录 user_message 快照事件"
        seg = body[idx:idx + 220]
        assert "_img_refs" in seg, f"快照事件未带引用：{seg[:120]}"
