#!/usr/bin/env python3
"""
Tea Agent Server API — 外部黑盒测试套件。

覆盖：
  1. 健康检查 & 基础连通性
  2. tuc- 主题管理（查询/创建/验证）
  3. 配置信息 & 模型信息提取
  4. 多主题创建/聊天/切换/内容验证
  5. 删除主题 & 重命名测试
  6. PDF 导出 4 种组合
  7. 附属接口（工具/文件/todo）
  8. 错误路径 & 异常边界

用法：python tests/test_server_api.py [--host HOST] [--port PORT]
"""
import argparse, json, os, sys, time, io, uuid, traceback
try:
    import requests
except ImportError:
    print("需要 pip install requests"); sys.exit(1)


class APITestClient:
    def __init__(self, host="127.0.0.1", port=8282):
        self.base = f"http://{host}:{port}"
        self.s = requests.Session()
        self.s.timeout = 10
        self._created = []

    def _get(self, p, **kw): return self.s.get(self.base + p, **kw)
    def _post(self, p, j=None, **kw): return self.s.post(self.base + p, json=j or {}, **kw)
    def _put(self, p, j=None, **kw): return self.s.put(self.base + p, json=j or {}, **kw)
    def _delete(self, p, **kw): return self.s.delete(self.base + p, **kw)

    def _sse(self, p, j=None, timeout=30):
        r = self.s.post(self.base + p, json=j or {}, stream=True, timeout=timeout)
        evts = []
        if not r.ok: return evts, r
        for line in r.iter_lines(decode_unicode=True):
            if not line or line.startswith(":"): continue
            if line.startswith("data: "):
                ds = line[6:].strip()
                if ds == "[DONE]": break
                try: evts.append(json.loads(ds))
                except: evts.append({"raw": ds})
        r.close()
        return evts, r
    # ── test methods ──
    def test_health(self):
        r = self._get("/health")
        assert r.ok, f"/health {r.status_code}"
        d = r.json()
        print(f"  /health status={d.get('status','?')} v={d.get('version','?')}")

    def test_list_sessions(self, limit=50):
        r = self._get(f"/api/sessions?limit={limit}")
        assert r.ok
        d = r.json()
        ss = d.get("sessions", [])
        print(f"  /api/sessions -> {len(ss)} topics")
        return ss

    def test_create_topic(self, title):
        r = self._post("/api/new_topic", {"title": title})
        assert r.ok, f"create fail: {r.status_code} {r.text}"
        d = r.json()
        tid = d["topic_id"]
        self._created.append(tid)
        print(f"  CREATE [{title}] -> {tid[:8]}...")
        return tid

    def test_topic_info(self, topic_id):
        r = self._get(f"/api/topic/{topic_id}")
        assert r.ok, f"GET topic {r.status_code}"
        info = r.json().get("topic", {})
        print(f"  TOPIC {topic_id[:8]}.. title={info.get('title','?')}")
        return info

    def test_rename(self, topic_id, new_title):
        r = self._put(f"/api/topic/{topic_id}", {"title": new_title})
        assert r.ok, f"rename {r.status_code}"
        assert r.json().get("ok"), f"rename not ok"
        print(f"  RENAME -> [{new_title}]")

    def test_delete(self, topic_id, expect_ok=True):
        r = self._delete(f"/api/topic/{topic_id}")
        if expect_ok:
            assert r.ok, f"delete {r.status_code} {r.text}"
            assert r.json().get("ok")
            print(f"  DELETE {topic_id[:8]}...")

    def test_status(self, topic_id):
        r = self._get(f"/api/topic/{topic_id}/status")
        assert r.ok
        d = r.json()
        print(f"  STATUS active={d.get('active')} bg={d.get('background')}")

    def test_convs(self, topic_id):
        r = self._get(f"/api/topic/{topic_id}/conversations?limit=10")
        assert r.ok
        d = r.json()
        print(f"  CONVS count={d.get('count',0)}")
        return d.get("conversations", [])

    def test_config(self):
        r = self._get("/api/config")
        assert r.ok
        d = r.json()
        print(f"  CONFIG keys={list(d.keys())[:6]}...")
        return d

    def test_model(self):
        r = self._get("/api/model")
        assert r.ok
        print(f"  MODEL OK")
        return r.json()

    def test_v1_config(self):
        r = self._get("/v1/config")
        assert r.ok
        print(f"  V1/CONFIG OK")

    def test_v1_sessions(self):
        r = self._get("/v1/sessions")
        assert r.ok
        d = r.json()
        print(f"  V1/SESSIONS -> {len(d.get('data',[]))}")

    def test_configs(self):
        r = self._get("/api/configs")
        assert r.ok
        d = r.json()
        print(f"  CONFIGS -> {len(d.get('configs',[]))}")

    def test_tools(self):
        r = self._get("/api/tools")
        assert r.ok
        d = r.json()
        print(f"  TOOLS -> {len(d.get('tools',[]))}")

    def test_todos(self, topic_id):
        r = self._get(f"/api/topic/{topic_id}/todos")
        if r.status_code == 404:
            print(f"  TODOS 404")
            return []
        assert r.ok
        d = r.json()
        print(f"  TODOS -> {len(d.get('todos',[]))}")

    def test_chat(self, topic_id, msg, timeout=25):
        evts, r = self._sse("/api/chat", {"topic_id": topic_id, "message": msg}, timeout=timeout)
        if not evts and not r.ok:
            body = r.json()
            if body.get("queued"):
                print(f"  CHAT queued pos={body.get('position')}")
                return ""
            print(f"  CHAT fail: {r.status_code}")
            return ""
        print(f"  CHAT -> {len(evts)} SSE events")
        texts = []
        for ev in evts:
            if isinstance(ev, dict):
                c = ev.get("choices", [{}])[0].get("delta", {}).get("content", "")
                if c: texts.append(c)
        reply = "".join(texts)
        print(f"    reply {len(reply)} chars")
        return reply

    def test_pdf(self, topic_id, mode="latest", fm="final"):
        r = self._get(f"/v1/export/pdf/{topic_id}?mode={mode}&filter={fm}", stream=True)
        content = r.content
        ok = content[:4] == b"%PDF"
        print(f"  PDF [{mode}/{fm}] -> {len(content)}B {'OK' if ok else 'NOT PDF'}")
        return content if ok else None

    def test_files(self):
        r = self._get("/api/files")
        assert r.ok
        print(f"  FILES OK")

    def cleanup(self):
        for tid in self._created[:]:
            try:
                self._delete(f"/api/topic/{tid}")
                self._created.remove(tid)
            except:
                pass
        if self._created:
            print(f"  Cleaned {len(self._created)} topics")

# ═══════════════════════════════════════════════
#  Test Suites
# ═══════════════════════════════════════════════


def suite_01_health(c):
    """健康检查 & 基础连通性"""
    c.test_health()
    c.test_list_sessions(limit=3)


def suite_02_tuc_topics(c):
    """tuc- 主题管理：查询/创建/验证"""
    sessions = c.test_list_sessions()
    tuc_ids = [s["id"] for s in sessions if s.get("title","").startswith("tuc-")]
    print(f"    Existing tuc-: {len(tuc_ids)}")

    titles = ["tuc-配置测试", "tuc-聊天验证", "tuc-PDF导出"]
    created = []
    for t in titles:
        tid = c.test_create_topic(t)
        created.append(tid)

    sessions2 = c.test_list_sessions()
    found = [s for s in sessions2 if s.get("title","").startswith("tuc-")]
    assert len(found) >= len(titles), f"tuc- count: {len(found)} < {len(titles)}"
    print(f"    After create: {len(found)} tuc- topics")

    for tid in created:
        info = c.test_topic_info(tid)
        assert info.get("title","").startswith("tuc-")


def suite_03_config_model(c):
    """配置 & 模型信息"""
    config = c.test_config()
    main_m = config.get("main_model") or config.get("default_model","")
    cheap_m = config.get("cheap_model","")
    max_i = config.get("max_iterations") or config.get("max_turns","")
    print(f"    main_model={main_m}")
    print(f"    cheap_model={cheap_m}")
    print(f"    max_iterations={max_i}")
    c.test_model()
    c.test_v1_config()
    c.test_configs()


def suite_04_multi_topic(c):
    """多主题创建/聊天/切换/内容验证"""
    tid_a = c.test_create_topic("切换测试-A")
    tid_b = c.test_create_topic("切换测试-B")

    print("    [A] sending chat...")
    reply_a = c.test_chat(tid_a, "请用一句话确认：这是主题A")
    print("    [B] sending chat...")
    reply_b = c.test_chat(tid_b, "请用一句话确认：这是主题B")

    if reply_a:
        assert "A" in reply_a, f"A mismatch: {reply_a[:80]}"
        print(f"    A verified: {reply_a[:60]}...")
    if reply_b:
        assert "B" in reply_b, f"B mismatch: {reply_b[:80]}"
        print(f"    B verified: {reply_b[:60]}...")

    convs_b = c.test_convs(tid_b)
    print(f"    B conversation count: {len(convs_b)}")
    c.test_status(tid_a)
    c.test_status(tid_b)

    # 验证 A 和 B 的对话不会混
    info_a = c.test_topic_info(tid_a)
    info_b = c.test_topic_info(tid_b)
    print(f"    A title={info_a.get('title')}, B title={info_b.get('title')}")


def suite_05_delete_rename(c):
    """删除主题 & 重命名"""
    tid = c.test_create_topic("待删除-TEMP")
    info = c.test_topic_info(tid)
    orig = info.get("title","")
    print(f"    Original: {orig}")

    new = f"已重命名-{uuid.uuid4().hex[:6]}"
    c.test_rename(tid, new)
    info2 = c.test_topic_info(tid)
    assert info2.get("title") == new, f"Rename fail: {info2.get('title')} != {new}"
    print(f"    Rename verified: {info2.get('title')}")

    c.test_delete(tid)
    r = c._get(f"/api/topic/{tid}")
    assert r.status_code == 404, f"Deleted topic should 404, got {r.status_code}"
    print(f"    Deletion verified: GET -> 404")
    if tid in c._created: c._created.remove(tid)


def suite_06_pdf_export(c):
    """4种 PDF 导出组合"""
    tid = c.test_create_topic("PDF导出测试")
    print("    Sending chat for PDF content...")
    c.test_chat(tid, "请回复一句：测试PDF导出功能")

    combos = [("latest","final"),("latest","full"),("full_topic","final"),("full_topic","full")]
    results = []
    for mode, fm in combos:
        content = c.test_pdf(tid, mode=mode, fm=fm)
        results.append(content is not None)
    ok = sum(results)
    assert ok >= 2, f"At least 2 PDF combos should succeed, got {ok}"
    print(f"    PDF export: {ok}/4 succeeded")


def suite_07_misc(c):
    """附属接口"""
    c.test_tools()
    c.test_files()
    c.test_v1_sessions()
    sessions = c.test_list_sessions(limit=5)
    if sessions:
        c.test_todos(sessions[0]["id"])


def suite_08_errors(c):
    """错误路径 & 异常边界"""
    fake = "00000000-0000-0000-0000-000000000000"

    r = c._get(f"/api/topic/{fake}")
    assert r.status_code in (404,500), f"Expected 404, got {r.status_code}"
    print(f"  GET fake topic -> {r.status_code}")

    r = c._delete(f"/api/topic/{fake}")
    print(f"  DELETE fake -> {r.status_code}")

    r = c._put(f"/api/topic/{fake}", {})
    assert r.status_code in (400,422,500), f"Expected 400, got {r.status_code}"
    print(f"  PUT no title -> {r.status_code}")

    r = c._post("/api/chat", {})
    assert r.status_code in (400,422), f"Expected 400, got {r.status_code}"
    print(f"  POST chat empty -> {r.status_code}")

    r = c._post("/api/new_topic", {})
    assert r.ok, f"Create topic without title fail: {r.status_code}"
    d = r.json()
    assert "topic_id" in d
    print(f"  POST new_topic no title -> OK (default)")
    tid = d["topic_id"]
    if tid in c._created: c._created.remove(tid)
    c.test_delete(tid)

    r = c._get(f"/v1/export/pdf/{fake}")
    print(f"  PDF fake topic -> {r.status_code}")

    r = c._get("/api/topic//conversations")
    print(f"  GET empty topic -> {r.status_code}")

    r = c._get("/nonexistent")
    print(f"  GET /nonexistent -> {r.status_code}")


# ═══════════════════════════════════════════════
#  Main Runner
# ═══════════════════════════════════════════════


def run_all(host="127.0.0.1", port=8282):
    c = APITestClient(host=host, port=port)

    suites = [
        ("① 健康检查", suite_01_health),
        ("② tuc-主题管理", suite_02_tuc_topics),
        ("③ 配置&模型信息", suite_03_config_model),
        ("④ 多主题切换", suite_04_multi_topic),
        ("⑤ 删除&重命名", suite_05_delete_rename),
        ("⑥ PDF导出4组合", suite_06_pdf_export),
        ("⑦ 附属接口", suite_07_misc),
        ("⑧ 错误路径", suite_08_errors),
    ]

    passed = failed = 0
    for name, fn in suites:
        print(f"\n{'='*50}")
        print(f"  {name}")
        print(f"{'='*50}")
        try:
            fn(c)
            print(f"  ✅ 通过")
            passed += 1
        except Exception as e:
            print(f"  ❌ 失败: {e}")
            traceback.print_exc()
            failed += 1

    print(f"\n{'='*50}")
    print(f"  结果: {passed} 通过, {failed} 失败 / {len(suites)} 套件")
    print(f"{'='*50}")

    c.cleanup()
    return failed == 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Tea Agent Server API 测试")
    parser.add_argument("--host", default="127.0.0.1", help="Server host")
    parser.add_argument("--port", type=int, default=8282, help="Server port")
    args = parser.parse_args()
    success = run_all(host=args.host, port=args.port)
    sys.exit(0 if success else 1)
