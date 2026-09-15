"""server 队列落盘的版本守卫回归（state.py）。

`_persist_queues()` 原本「锁内取快照、锁外写文件」，两个并发落盘的**完成顺序
可能与快照顺序相反**：旧快照后写盘会把已删除/已消费的插话**复活到磁盘**。
内存是干净的，只有磁盘错 —— 于是重启后用户早已撤回的消息死灰复燃。
（与项目此前修过的「删除的记忆被后台重建」同族。）
"""
import builtins
import importlib
import json
import os
import sys
import tempfile
import threading
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


@pytest.fixture
def state(monkeypatch, tmp_path):
    """隔离 state 模块：独立状态文件 + 清空内存队列（并推进版本）。"""
    monkeypatch.setenv("TEA_SERVER_STATE_DB", str(tmp_path / "server_state.db"))
    mod = importlib.import_module("tea_agent.server.modules.state")
    with mod.message_queue_lock:
        mod.message_queue.clear()
        mod._bump_queue_version()
    yield mod
    with mod.message_queue_lock:
        mod.message_queue.clear()
        mod._bump_queue_version()


class TestStaleSnapshotGuard:
    def test_stale_snapshot_cannot_resurrect_deleted_message(self, state, monkeypatch):
        """旧快照晚落盘时必须被跳过，而不是把已删除的消息写回磁盘。

        阻塞点选在 ``_queue_store_path`` —— 代码里它正好位于「内存快照已取」
        与「进入写锁」之间，是唯一能稳定造出交错的时间窗。
        """
        entered = threading.Event()
        release = threading.Event()
        real_path = state._queue_store_path

        # 先正常入队并落盘（此时未挂钩，不会误占阻塞槽位）
        item_id = state.queue_add("t1", "用户已撤回的插话")

        def hooked_path():
            # 只卡住第一次调用：即 A 线程的 persist
            if not entered.is_set():
                entered.set()
                release.wait(timeout=5)
            return real_path()

        monkeypatch.setattr(state, "_queue_store_path", hooked_path)

        ta = threading.Thread(target=state._persist_queues)
        ta.start()
        assert entered.wait(timeout=2), "未能进入受控竞态窗口"

        # A 已取快照但还没写；B 删除并落盘（先完成）
        monkeypatch.setattr(state, "_queue_store_path", real_path)
        assert state.queue_remove("t1", item_id) is True
        state._persist_queues()
        path = real_path()
        assert json.loads(open(path, encoding="utf-8").read()) == {}, \
            "前置条件不成立：删除未先落盘"

        release.set()
        ta.join(timeout=5)

        on_disk = json.loads(open(path, encoding="utf-8").read())
        assert not on_disk.get("t1"), f"过期快照复活了已删除消息: {on_disk}"
        # 重启语义：恢复后不得再出现
        assert state.restore_queues() == 0

    def test_redundant_persist_skips_disk_write(self, state, monkeypatch):
        """队列未变更时不应再写盘（守卫顺带省掉的无谓 I/O）。"""
        state.queue_add("t1", "m")
        writes = {"n": 0}
        real_dump = json.dump

        def counting_dump(obj, f, *a, **kw):
            writes["n"] += 1
            return real_dump(obj, f, *a, **kw)

        monkeypatch.setattr(json, "dump", counting_dump)
        before = writes["n"]
        state._persist_queues()
        state._persist_queues()
        assert writes["n"] == before, "版本未变仍重复落盘"

        state.queue_add("t1", "m2")
        state._persist_queues()
        assert writes["n"] == before + 1, "队列变更后必须落盘"

    def test_normal_add_remove_still_persists(self, state):
        """守卫不得妨碍正常落盘（否则排队消息重启即丢）。"""
        state.queue_add("t1", "m1")
        state.queue_add("t1", "m2")
        path = state._queue_store_path()
        data = json.loads(open(path, encoding="utf-8").read())
        assert [it["message"] for it in data["t1"]] == ["m1", "m2"]

        state.queue_remove("t1", data["t1"][0]["id"])
        data2 = json.loads(open(path, encoding="utf-8").read())
        assert [it["message"] for it in data2["t1"]] == ["m2"]

    def test_pop_persists_consumption(self, state):
        """消费掉的插话必须从磁盘消失（否则重启重现一条已处理的插话）。"""
        state.queue_add("t1", "will-be-consumed")
        assert state.queue_pop("t1") is not None
        data = json.loads(open(state._queue_store_path(), encoding="utf-8").read())
        assert not data.get("t1"), f"已消费消息仍在磁盘: {data}"

    def test_restore_bumps_version(self, state):
        """restore 后必须能再次落盘：版本若不推进会被守卫跳过。"""
        path = state._queue_store_path()
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"t9": [{"id": "x1", "message": "restored",
                               "images": [], "timestamp": 1.0}]}, f)
        with state.message_queue_lock:
            state.message_queue.clear()
        assert state.restore_queues() == 1
        # 恢复结果必须可再落盘（守卫不得把它挡掉）
        state._persist_queues()
        data = json.loads(open(path, encoding="utf-8").read())
        assert [it["message"] for it in data["t9"]] == ["restored"]

    def test_concurrent_add_and_remove_keeps_disk_consistent(self, state):
        """并发增删后，磁盘最终态必须与内存最终态一致（不得残留幻影消息）。"""
        ids = []
        lock = threading.Lock()

        def adder():
            for i in range(30):
                iid = state.queue_add("tc", f"m{i}")
                with lock:
                    ids.append(iid)

        def remover():
            for _ in range(30):
                with lock:
                    batch = ids[:5]
                    for x in batch:
                        ids.remove(x)
                for x in batch:
                    state.queue_remove("tc", x)
                if not batch:
                    time.sleep(0.001)

        ths = [threading.Thread(target=f) for f in (adder, remover, adder, remover)]
        for t in ths:
            t.start()
        for t in ths:
            t.join(timeout=60)
        assert not any(t.is_alive() for t in ths), "疑似死锁"

        with state.message_queue_lock:
            mem = {tid: [it["id"] for it in items] for tid, items in state.message_queue.items()
                   if items}
        final_id = state._persist_queues()
        disk = json.loads(open(state._queue_store_path(), encoding="utf-8").read())
        disk_ids = {tid: sorted(it["id"] for it in items) for tid, items in disk.items() if items}
        mem_ids = {tid: sorted(v) for tid, v in mem.items()}
        assert disk_ids == mem_ids, f"磁盘与内存不一致 disk={disk_ids} mem={mem_ids}"
        assert final_id == sum(len(v) for v in mem.values())
