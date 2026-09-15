"""审计哈希链的跨进程完整性回归。

线上 test_builtin_safety_tasks_all_pass 长期失败，根因不是数据被篡改，而是
_chain_head() 的内存缓存**永不被判定过期**：本进程写过一次后，即使其它进程
又追加了记录，它仍拿旧的 _last_hash 当链头 → 新记录 prev 回指旧哈希、跳过中间
记录，append-only 可信链被判为「记录被删除/插入/重排」。

设备端跑 tea_agent_api（server 进程 + 子 Agent 进程 + 测试进程并发写同一日文件）
正是这个场景 —— 也就是说：**审计链在最真实的多进程部署形态下必然断裂**，
它作为防篡改基础设施的价值等于零。
"""
import json
import os
import subprocess
import sys

import pytest

from tea_agent.audit_log import GENESIS_HASH, AuditLog

_PKG_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _tool_calls(path: str) -> list[str]:
    return [r["event"] for r in AuditLog(directory=os.path.dirname(path))._read(path)]


class TestChainHeadFreshness:
    def test_stale_cache_detected_after_foreign_append(self, tmp_path):
        """他进程追加后，本进程的下一次记录必须以文件真实末行为链头。"""
        al = AuditLog(directory=str(tmp_path))
        first = al.record("tool/call", tool="a")
        assert first and first["prev"] == GENESIS_HASH

        # 模拟「另一个进程」写入一条（独立实例 → 不共享内存链头）
        other = AuditLog(directory=str(tmp_path))
        mid = other.record("tool/call", tool="interloper")
        assert mid and mid["prev"] == first["h"]

        # 原实例再写：修复前会用缓存里的 first['h'] → 跳过 mid → 断链
        third = al.record("tool/call", tool="b")
        assert third["prev"] == mid["h"], (
            "链头使用了过期缓存：prev 指向本进程上一条而非文件末行")
        assert al.verify()["ok"], "并发追加后审计链应仍然完整"

    def test_consecutive_appends_in_one_process_stay_chained(self, tmp_path):
        al = AuditLog(directory=str(tmp_path))
        for i in range(5):
            al.record("tool/call", tool=f"t{i}")
        assert al.verify() == {"ok": True, "files": 1, "records": 5,
                               "broken_at": None, "reason": "链路完整"}

    def test_detects_real_tampering(self, tmp_path):
        """修复不能削弱原有检测能力：改写历史记录必须被检出。"""
        al = AuditLog(directory=str(tmp_path))
        for i in range(4):
            al.record("tool/call", tool=f"t{i}")
        files = al.files()
        lines = open(files[0], encoding="utf-8").read().splitlines()
        rec = json.loads(lines[1])
        rec["tool"] = "tampered"
        lines[1] = json.dumps(rec, ensure_ascii=False, sort_keys=True)
        open(files[0], "w", encoding="utf-8").write("\n".join(lines) + "\n")
        v = al.verify()
        assert v["ok"] is False and v["reason"], f"篡改未被检出: {v}"

    def test_detects_record_deletion(self, tmp_path):
        al = AuditLog(directory=str(tmp_path))
        for i in range(5):
            al.record("tool/call", tool=f"t{i}")
        files = al.files()
        lines = open(files[0], encoding="utf-8").read().splitlines()
        del lines[2]
        open(files[0], "w", encoding="utf-8").write("\n".join(lines) + "\n")
        assert al.verify()["ok"] is False, "删除记录未被检出"

    def test_empty_file_and_missing_file(self, tmp_path):
        al = AuditLog(directory=str(tmp_path))
        assert al._read_last_line(str(tmp_path / "nope.jsonl")) is None
        p = tmp_path / "empty.jsonl"
        p.write_text("", encoding="utf-8")
        assert al._read_last_line(str(p)) == ""


class TestDirectoryProbe:
    """目录探测的并发正确性。

    旧实现所有进程共用同一个 `.write_probe` 文件名：并发启动时 A 建完删掉，
    B 的 os.remove 抛 FileNotFoundError，被 `except OSError` 误判为「目录不可写」，
    于是 B **静默改写到下一个候选目录**。审计记录散落到意外目录等于丢失，
    且 verify() 看不出问题（两处各自成链）—— 实测并发压测稳定丢整段记录。
    """

    def test_parallel_probes_all_resolve_to_same_dir(self, tmp_path):
        child = tmp_path / "_probe.py"
        child.write_text(
            "import json, sys\n"
            f"sys.path.insert(0, r'{_PKG_ROOT}')\n"
            "from tea_agent.audit_log import AuditLog\n"
            "al = AuditLog(directory=sys.argv[1])\n"
            "for i in range(10):\n"
            "    al.record('tool/call', tool='p' + sys.argv[2], detail={'i': i})\n"
            "print(json.dumps({'dir': al.directory(), 'leftover': "
            "[f for f in __import__('os').listdir(sys.argv[1]) if f.startswith('.write_probe')]}))\n",
            encoding="utf-8")
        nproc = 6
        procs = [subprocess.Popen([sys.executable, str(child), str(tmp_path), str(k)],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  text=True, encoding="utf-8") for k in range(nproc)]
        infos = []
        for p in procs:
            out, err = p.communicate(timeout=180)
            assert p.returncode == 0, err[-400:]
            infos.append(json.loads(out.strip().splitlines()[-1]))

        # 全部进程必须解析到同一个目录（否则就有记录写去了别处）
        dirs = {i["dir"] for i in infos}
        assert dirs == {str(tmp_path)}, f"进程解析到不同目录: {dirs}"

        landed = sum(1 for f in tmp_path.glob("audit-*.jsonl")
                     for l in open(f, encoding="utf-8") if l.strip())
        assert landed == nproc * 10, (
            f"落盘 {landed} != 期望 {nproc * 10} → 有进程被误判目录不可写而丢记录")

        leftovers = {n for i in infos for n in i["leftover"]}
        assert not leftovers, f"探测残留文件未清理: {leftovers}"

    def test_unwritable_dir_falls_back(self, tmp_path):
        """真正不可写的目录仍必须触发回退（别把防护修成失效）。"""
        target = tmp_path / "ro"
        target.mkdir()
        blocker = target / "audit"
        blocker.write_text("not a dir")  # 同名文件占位 → makedirs 必失败
        al = AuditLog(directory=str(blocker))
        resolved = al.directory()
        assert resolved is None or resolved != str(blocker), (
            "不可写目录被当作可用，写入将失败")

    def test_probe_failure_to_clean_up_does_not_reject_dir(self, tmp_path):
        """清理探测文件失败不应影响目录可用性判定。"""
        import tea_agent.audit_log as mod
        real_remove = mod.os.remove
        boom = {"on": True}

        def flaky_remove(path):
            if boom["on"] and ".write_probe" in str(path):
                raise PermissionError("simulated")
            return real_remove(path)

        mod.os.remove = flaky_remove
        try:
            al = AuditLog(directory=str(tmp_path))
            assert al._probe_writable(str(tmp_path)) is True
        finally:
            mod.os.remove = real_remove


class TestReadLastLine:
    """末行读取的正确性 —— 它一旦读错，整条链从第二条起就全错。"""

    @pytest.mark.parametrize("count", [1, 2, 50])
    def test_returns_true_last_line(self, tmp_path, count):
        p = tmp_path / "a.jsonl"
        lines = [json.dumps({"i": i, "pad": "x" * 200}) for i in range(count)]
        p.write_text("\n".join(lines) + "\n", encoding="utf-8")
        al = AuditLog(directory=str(tmp_path))
        assert al._read_last_line(str(p)) == lines[-1]

    def test_no_trailing_newline(self, tmp_path):
        p = tmp_path / "a.jsonl"
        p.write_text('{"i":1}\n{"i":2}', encoding="utf-8")
        al = AuditLog(directory=str(tmp_path))
        assert al._read_last_line(str(p)) == '{"i":2}'

    def test_multibyte_across_block_boundary(self, tmp_path):
        """跨读取块边界时不得在多字节字符中间切断（会抛 UnicodeDecodeError）。"""
        p = tmp_path / "a.jsonl"
        # 让最后一条记录足够长，必然跨越 8KB 块边界
        big = json.dumps({"i": 1, "text": "中文字" * 4000}, ensure_ascii=False)
        p.write_text('{"i":0}\n' + big + "\n", encoding="utf-8")
        al = AuditLog(directory=str(tmp_path))
        got = al._read_last_line(str(p))
        assert got is not None and json.loads(got)["i"] == 1

    def test_blank_lines_at_end_skipped(self, tmp_path):
        p = tmp_path / "a.jsonl"
        p.write_text('{"i":1}\n\n\n', encoding="utf-8")
        al = AuditLog(directory=str(tmp_path))
        assert al._read_last_line(str(p)) == '{"i":1}'

    def test_corrupt_tail_falls_back_to_full_scan(self, tmp_path):
        """末行残缺（写入中断）时退回全量扫描，找到最后一条完整记录。"""
        al = AuditLog(directory=str(tmp_path))
        a = al.record("tool/call", tool="good")
        path = al.files()[0]
        with open(path, "a", encoding="utf-8") as f:
            f.write('{"broken": tru')  # 半行
        later = AuditLog(directory=str(tmp_path))
        b = later.record("tool/call", tool="after")
        assert b["prev"] == a["h"], "残缺末行应被跳过，链头取最后一条完整记录"


class TestCrossProcessConcurrency:
    """真并发：多进程同时写同一日文件。"""

    _CHILD = (
        "import sys\n"
        "sys.path.insert(0, r'{root}')\n"
        "from tea_agent.audit_log import AuditLog\n"
        "al = AuditLog(directory=sys.argv[1])\n"
        "ok = 0\n"
        "for i in range(15):\n"
        "    if al.record('tool/call', tool='p' + sys.argv[2], detail={{'i': i}}):\n"
        "        ok += 1\n"
        "print(ok)\n"
    )

    def test_concurrent_writers_keep_chain_intact(self, tmp_path):
        child = tmp_path / "_child.py"
        child.write_text(self._CHILD.format(root=_PKG_ROOT), encoding="utf-8")
        nproc = 6
        procs = [subprocess.Popen([sys.executable, str(child), str(tmp_path), str(k)],
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 text=True, encoding="utf-8")
                 for k in range(nproc)]
        reported = 0
        for p in procs:
            out, err = p.communicate(timeout=180)
            assert p.returncode == 0, f"子进程失败: {err[-400:]}"
            reported += int(out.strip().splitlines()[-1])

        al = AuditLog(directory=str(tmp_path))
        files = al.files()
        landed = sum(sum(1 for line in open(f, encoding="utf-8") if line.strip()) for f in files)
        recs = [json.loads(l) for f in files for l in open(f, encoding="utf-8") if l.strip()]

        assert reported == nproc * 15, f"有进程未写满: {reported}"
        assert landed == nproc * 15, f"落盘 {landed} != 自报 {reported} → 静默丢记录"
        assert len(recs) == len(set(r["h"] for r in recs)), "出现重复哈希（并发覆盖写）"
        prevs = [r["prev"] for r in recs]
        assert len(prevs) == len(set(prevs)), "重复 prev：两进程读到同一链头 → 跨进程锁未生效"
        assert al.verify()["ok"], "并发写入后审计链必须完整"
