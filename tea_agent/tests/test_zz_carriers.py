"""临时探针：全盘定位「打断模式」文本的所有载体（用后删除）。

已从 .tea_agent_run/chat_history_2026-09-08.db 的 memories 表删除并确认 active=0，
但注入仍在继续 → 说明该文本还有别的载体（其它库/WAL/JSON/Markdown/项目记忆）。
本探针穷举搜索所有文本与二进制文件，给出确切清单。
"""

import json
import os
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NEEDLE = "打断模式"
HOME = Path.home()

SEARCH_DIRS = [
    ROOT / ".tea_agent_run",
    HOME / ".tea_agent",
    ROOT / "tea_agent" / "kb",
    ROOT / "docs",
    ROOT,
]
TEXT_EXT = {".json", ".md", ".txt", ".yaml", ".yml", ".db-wal", ".db", ".log", ""}


def test_find_all_carriers():
    hits: dict = {"files": [], "sqlite": {}, "dirs_scanned": 0}

    seen_dirs: set = set()
    for d in SEARCH_DIRS:
        if not d.exists():
            continue
        for dirpath, dirnames, filenames in os.walk(d):
            # 跳过明显无关的大目录
            dirnames[:] = [x for x in dirnames
                           if x not in {".git", "__pycache__", "node_modules", "build",
                                        "dist", ".venv", "venv_work", "build_mini_dist"}]
            if dirpath in seen_dirs:
                continue
            seen_dirs.add(dirpath)
            hits["dirs_scanned"] += 1
            for fn in filenames:
                p = Path(dirpath) / fn
                try:
                    if p.stat().st_size > 60 * 1024 * 1024:
                        continue
                except OSError:
                    continue
                # 1) SQLite 文件：直接查表
                if fn.endswith((".db", ".sqlite", ".sqlite3")):
                    try:
                        c = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
                        tabs = [r[0] for r in c.execute(
                            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
                        found = {}
                        for t in tabs:
                            try:
                                cols = [r[1] for r in c.execute(f"PRAGMA table_info({t})").fetchall()]
                                for col in cols:
                                    n = c.execute(
                                        f"SELECT COUNT(*) FROM {t} WHERE {col} LIKE ?",
                                        (f"%{NEEDLE}%",)).fetchone()[0]
                                    if n:
                                        found[f"{t}.{col}"] = n
                            except sqlite3.Error:
                                continue
                        c.close()
                        if found:
                            hits["sqlite"][str(p)] = found
                    except sqlite3.Error:
                        pass
                    continue
                # 2) 文本文件：按字节找
                if p.suffix.lower() in TEXT_EXT or p.suffix == "":
                    try:
                        raw = p.read_bytes()
                        if NEEDLE.encode("utf-8") in raw:
                            hits["files"].append(
                                {"path": str(p), "size": len(raw)})
                    except OSError:
                        continue

    (ROOT / "_carriers.json").write_text(
        json.dumps(hits, ensure_ascii=False, indent=2), encoding="utf-8")
    raise AssertionError(json.dumps(hits, ensure_ascii=False)[:1500])
