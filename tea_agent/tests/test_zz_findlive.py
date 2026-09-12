"""临时探针：全盘定位「仍存活的打断模式记忆」在哪个库（用后删除）。

背景：注入持续，但已清的候选库均 memories_removed=0 → 真正持有它的库尚未定位。
可能原因：服务器启动目录与我当前 cwd 不同 → 其项目级库在别处
（resolve_db_path 用 **启动目录** 决定 .tea_agent_run 位置）。

本探针扫描 C:/Users/Hetin 下所有 .db（含 -wal/-shm 同名），
返回持有该记忆的库的绝对路径与行内容。
"""

import json
import os
import sqlite3
from pathlib import Path

NEEDLE = "打断模式"
OUT = Path(__file__).resolve().parents[2] / "_find_live.json"
ROOT_SCAN = Path.home()
SKIP = {".git", "__pycache__", "node_modules", ".venv", "venv_work", "site-packages",
        "build_mini_dist", "Lib", "Scripts", "lib", "bin"}


def _probe(db: Path) -> dict | None:
    try:
        c = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=3)
    except sqlite3.Error:
        return None
    try:
        tabs = {r[0] for r in c.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        if "memories" not in tabs:
            return None
        rows = c.execute(
            "SELECT id, is_active, category, priority, substr(content,1,80) "
            "FROM memories WHERE content LIKE ?", (f"%{NEEDLE}%",)).fetchall()
        if not rows:
            return None
        return {"rows": [[str(x) for x in r] for r in rows],
                "mtime": db.stat().st_mtime,
                "size": db.stat().st_size}
    except sqlite3.Error:
        return None
    finally:
        c.close()


def test_find_live_db_holding_memory():
    hits: dict = {}
    scanned = 0
    for dirpath, dirnames, filenames in os.walk(ROOT_SCAN):
        dirnames[:] = [d for d in dirnames if d not in SKIP]
        for fn in filenames:
            if not fn.endswith((".db", ".sqlite", ".sqlite3")):
                continue
            p = Path(dirpath) / fn
            try:
                if p.stat().st_size < 4096:
                    continue
            except OSError:
                continue
            scanned += 1
            r = _probe(p)
            if r:
                hits[str(p)] = r
        if scanned > 4000:
            break

    OUT.write_text(json.dumps({"scanned": scanned, "hits": hits},
                              ensure_ascii=False, indent=2), encoding="utf-8")
    raise AssertionError(f"scanned={scanned} hits={json.dumps(hits, ensure_ascii=False)[:900]}")
