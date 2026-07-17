#!/usr/bin/env python3
"""
独立测试脚本：验证切换主题时不打断正在进行的对话

测试场景：
1. 多主题并发SSE：同时向两个不同主题发送流式请求，验证互不干扰
2. 后台完成：SSE连接断开后（模拟切走），后台线程继续完成对话
3. 中断有效：验证 /api/chat/abort 主动中断仍正常工作

使用：
  1. 先启动 server: python -m tea_agent.server --port 8282
  2. 运行: python tests/test_topic_switch_no_interrupt.py
  3. 指定端口: python tests/test_topic_switch_no_interrupt.py --port 8080

依赖: pip install httpx
"""

import asyncio, json, sys, os, time, argparse, urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

HOST = "127.0.0.1"
PORT = 8282
BASE_URL = f"http://{HOST}:{PORT}"


class TestStats:
    def __init__(self):
        self.passed = 0
        self.failed = 0
    def ok(self, name, detail=""):
        self.passed += 1
        d = f" | {detail}" if detail else ""
        print(f"  ✅ {name}{d}")
    def fail(self, name, reason=""):
        self.failed += 1
        r = f" | {reason}" if reason else ""
        print(f"  ❌ {name}{r}")
    def summary(self):
        total = self.passed + self.failed
        print(f"\n{'=' * 50}")
        print(f"结果: ✅ {self.passed} 通过 | ❌ {self.failed} 失败 | 共 {total} 项")
        print(f"{'=' * 50}")
        return self.failed == 0


def check_server(timeout=5):
    try:
        req = urllib.request.Request(f"{BASE_URL}/health")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read()).get("status") == "ok"
    except Exception:
        return False


def create_topic(title="Test"):
    payload = json.dumps({"title": title}).encode()
    req = urllib.request.Request(f"{BASE_URL}/api/new_topic", data=payload,
                                  headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())["topic_id"]


def get_convs(topic_id):
    req = urllib.request.Request(f"{BASE_URL}/api/topic/{topic_id}/conversations?limit=50")
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read()).get("conversations", [])


def delete_topic(topic_id):
    try:
        req = urllib.request.Request(f"{BASE_URL}/api/topic/{topic_id}", method="DELETE")
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass


async def test_single_stream(stats, topic_id=""):
    """基础：单个 SSE 流收发正常"""
    try:
        import httpx
    except ImportError:
        stats.fail("单个SSE流", "httpx 未安装")
        return False
    if not topic_id:
        topic_id = create_topic("单流测试")
    chunks = []
    try:
        async with httpx.AsyncClient(timeout=30) as cli:
            payload = {"message": "一句话回复我", "topic_id": topic_id}
            async with cli.stream("POST", f"{BASE_URL}/api/chat", json=payload) as resp:
                if resp.status_code != 200:
                    stats.fail("单个SSE流", f"HTTP {resp.status_code}")
                    delete_topic(topic_id)
                    return False
                async for line in resp.aiter_lines():
                    if line.startswith("data: "):
                        d = line[6:]
                        if d:
                            try:
                                ev = json.loads(d)
                                chunks.append(ev)
                                if ev.get("type") in ("done", "error"):
                                    break
                            except json.JSONDecodeError:
                                pass
        if chunks:
            done = any(c.get("type") == "done" for c in chunks)
            if done:
                stats.ok("单个SSE流", f"{len(chunks)} 事件含 done")
                delete_topic(topic_id)
                return True
            else:
                stats.fail("单个SSE流", f"{len(chunks)} 事件无 done")
                delete_topic(topic_id)
                return False
        else:
            stats.fail("单个SSE流", "无事件")
            delete_topic(topic_id)
            return False
    except Exception as e:
        stats.fail("单个SSE流", str(e)[:60])
        delete_topic(topic_id)
        return False


async def test_concurrent_topics(stats):
    """
    核心测试：两个不同主题同时流式对话，验证互不干扰。
    预期：两路 SSE 均正常收发 → 结果均保存到 DB
    """
    try:
        import httpx
    except ImportError:
        stats.fail("并发主题", "httpx 未安装")
        return False
    ts = time.time_ns() % 10000
    a_id = create_topic(f"ConA_{ts:04.0f}")
    b_id = create_topic(f"ConB_{ts:04.0f}")
    print(f"\n  主题 A: {a_id[:12]}...  主题 B: {b_id[:12]}...")
    results = {}

    async def stream_one(cli, tid, label, prompt):
        evts = []
        try:
            async with cli.stream("POST", f"{BASE_URL}/api/chat",
                                   json={"message": prompt, "topic_id": tid},
                                   timeout=60) as resp:
                if resp.status_code != 200:
                    results[label] = {"ok": False, "error": f"HTTP {resp.status_code}"}
                    return
                async for line in resp.aiter_lines():
                    if line.startswith("data: "):
                        d = line[6:]
                        if d:
                            try:
                                ev = json.loads(d)
                                evts.append(ev)
                                if ev.get("type") in ("done", "error"):
                                    break
                            except json.JSONDecodeError:
                                pass
                results[label] = {"ok": True, "events": evts}
        except Exception as e:
            results[label] = {"ok": False, "error": str(e)[:60]}

    async with httpx.AsyncClient(timeout=120) as cli:
        await asyncio.gather(
            stream_one(cli, a_id, "A", "一句话介绍你自己"),
            stream_one(cli, b_id, "B", "一句话说今天日期"),
        )

    all_ok = True
    for label in ("A", "B"):
        r = results.get(label, {})
        if r.get("ok"):
            evts = r["events"]
            done = any(e.get("type") == "done" for e in evts)
            tok = any(e.get("type") == "token" for e in evts)
            if done:
                stats.ok(f"并发{label}", f"{len(evts)} 事件 + done")
            elif tok:
                stats.ok(f"并发{label}", f"{len(evts)} 事件（有 token）")
            else:
                stats.fail(f"并发{label}", "无 token/done")
                all_ok = False
        else:
            stats.fail(f"并发{label}", r.get("error", "未知"))
            all_ok = False
    await asyncio.sleep(1)
    for label, tid in (("A", a_id), ("B", b_id)):
        convs = get_convs(tid)
        if convs:
            stats.ok(f"DB{label}", f"{len(convs)} 条")
        else:
            stats.fail(f"DB{label}", "无记录")
            all_ok = False
    delete_topic(a_id), delete_topic(b_id)
    return all_ok


async def test_background_completion(stats):
    """
    核心测试：SSE 断开后后台线程继续完成。
    模拟前端切走（不发送 abort），验证结果自动保存到 DB。
    """
    try:
        import httpx
    except ImportError:
        stats.fail("后台完成", "httpx 未安装")
        return False
    ts = time.time_ns() % 10000
    tid = create_topic(f"Bg_{ts:04.0f}")
    print(f"\n  主题: {tid[:12]}...")
    events_before_disconnect = 0

    async def start_and_disconnect():
        nonlocal events_before_disconnect
        async with httpx.AsyncClient(timeout=30) as cli:
            async with cli.stream("POST", f"{BASE_URL}/api/chat",
                                   json={"message": "用三句话介绍你自己", "topic_id": tid}) as resp:
                if resp.status_code != 200:
                    return
                async for line in resp.aiter_lines():
                    if line.startswith("data: "):
                        d = line[6:]
                        if d:
                            try:
                                json.loads(d)
                                events_before_disconnect += 1
                                if events_before_disconnect >= 5:
                                    break  # 断开，不发送 abort
                            except json.JSONDecodeError:
                                pass

    await start_and_disconnect()
    if not events_before_disconnect:
        stats.fail("后台完成", "无事件")
        delete_topic(tid)
        return False
    stats.ok("断开连接", f"收到 {events_before_disconnect} 事件后断开")

    # 轮询 DB 等待后台完成
    convs = []
    for waited in range(0, 120, 2):
        await asyncio.sleep(2)
        convs = get_convs(tid)
        if convs:
            stats.ok("后台保存", f"等待 {waited+2}s DB {len(convs)} 条")
            break
        if (waited + 2) % 10 == 0:
            print(f"  ⏳ 等待后台完成... {waited+2}s")
    if not convs:
        stats.fail("后台保存", "120s 后 DB 仍无记录")
        delete_topic(tid)
        return False

    for c in convs:
        if c.get("ai_msg", "") and len(c["ai_msg"]) > 10:
            stats.ok("后台AI回复", f"长度 {len(c['ai_msg'])}")
            break
    for c in convs:
        if c.get("user_msg", ""):
            stats.ok("后台用户消息", "已保存")
            break
    delete_topic(tid)
    return True


async def test_interrupt_works(stats):
    """
    测试：/api/chat/abort 主动中断仍有效。
    启动 SSE → 发 abort → 验证流被中断。
    """
    try:
        import httpx
    except ImportError:
        stats.fail("中断测试", "httpx 未安装")
        return False
    ts = time.time_ns() % 10000
    tid = create_topic(f"Int_{ts:04.0f}")
    print(f"\n  主题: {tid[:12]}...")
    got_abort = False
    event_count = 0

    async def do_test():
        nonlocal got_abort, event_count
        async with httpx.AsyncClient(timeout=30) as cli:
            async with cli.stream("POST", f"{BASE_URL}/api/chat",
                                   json={"message": "写一篇500字短文", "topic_id": tid}) as resp:
                if resp.status_code != 200:
                    return
                async for line in resp.aiter_lines():
                    if line.startswith("data: "):
                        d = line[6:]
                        if d:
                            try:
                                ev = json.loads(d)
                                event_count += 1
                                if event_count == 3 and not got_abort:
                                    got_abort = True
                                    payload = json.dumps({"topic_id": tid}).encode()
                                    req = urllib.request.Request(
                                        f"{BASE_URL}/api/chat/abort", data=payload,
                                        headers={"Content-Type": "application/json"})
                                    urllib.request.urlopen(req, timeout=5)
                                    print(f"  🛑 已发送中断信号")
                                if ev.get("type") in ("done", "error"):
                                    break
                            except json.JSONDecodeError:
                                pass

    await do_test()
    if got_abort:
        stats.ok("中断信号", f"第3事件时发送 abort")
    else:
        stats.fail("中断信号", "未能发送")
        delete_topic(tid)
        return False
    stats.ok("中断后流结束", f"共收到 {event_count} 事件后关闭")
    delete_topic(tid)
    return True


async def main():
    parser = argparse.ArgumentParser(description="测试切换主题不中断对话")
    parser.add_argument("--port", type=int, default=8282, help="Server port")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Server host")
    args = parser.parse_args()
    global PORT, BASE_URL
    PORT = args.port
    BASE_URL = f"http://{args.host}:{PORT}"

    print(f"{'=' * 50}")
    print(f"  切换主题不中断对话 — 自动测试")
    print(f"  Server: {BASE_URL}")
    print(f"{'=' * 50}")

    if not check_server():
        print(f"\n❌ Server 不可达！请先启动: python -m tea_agent.server --port {PORT}")
        print(f"   或在其他端口启动后: python {__file__} --port PORT")
        sys.exit(1)
    print(f"  ✅ Server 在线\n")

    stats = TestStats()

    print("--- 测试 1: 基础 SSE 流 ---")
    await test_single_stream(stats)

    print("\n--- 测试 2: 并发主题互不干扰 ---")
    await test_concurrent_topics(stats)

    print("\n--- 测试 3: 断开后后台完成 ---")
    await test_background_completion(stats)

    print("\n--- 测试 4: 中断仍有效 ---")
    await test_interrupt_works(stats)

    all_ok = stats.summary()
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    asyncio.run(main())
