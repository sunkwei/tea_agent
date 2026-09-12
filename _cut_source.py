"""切断重建源（收尾）：清空全部 interruption_events + 删除该记忆。

原理：后台分析器的输入是 `query_interruptions(status='classified')`。
只要该表为空，即使运行中的服务器仍是旧代码（enabled=true），也无从重建记忆。
这是**无需重启**即可止血的唯一手段。

同时清空 pending/其它状态事件，避免「稍后被分类 → 又触发重建」。
"""

import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent
NEEDLE = "打断"

cands: list[Path] = []
for d in [ROOT / ".tea_agent_run", ROOT, Path.home() / ".tea_agent",
          Path.home() / "AppData" / "Local" / "Temp"]:
    if d.exists():
        cands.extend(sorted(d.glob("*.db")))
# 额外：本轮全盘扫描命中的库
hitfile = ROOT / "_find_live.json"
if hitfile.exists():
    for k in json.loads(hitfile.read_text(encoding="utf-8")).get("hits", {}):
        cands.append(Path(k))

report: dict = {"events_deleted": {}, "memories_deleted": {}, "scanned": 0, "errors": []}
for db in dict.fromkeys(cands):
    if not db.exists():
        continue
    report["scanned"] += 1
    try:
        c = sqlite3.connect(str(db), timeout=5)
    except sqlite3.Error as e:
        report["errors"].append(f"{db}: {e}")
        continue
    try:
        tabs = {r[0] for r in c.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        if "interruption_events" in tabs:
            n = c.execute("SELECT COUNT(*) FROM interruption_events").fetchone()[0]
            if n:
                c.execute("DELETE FROM interruption_events")
                report["events_deleted"][str(db)] = n
        if "memories" in tabs:
            rows = c.execute("SELECT id FROM memories WHERE content LIKE ?",
                             (f"%{NEEDLE}%",)).fetchall()
            if rows:
                for (mid,) in rows:
                    c.execute("DELETE FROM memories WHERE id=?", (mid,))
                report["memories_deleted"][str(db)] = len(rows)
        c.commit()
    except sqlite3.Error as e:
        report["errors"].append(f"{db}: {e}")
    finally:
        c.close()

# ── 复核：干净库应无事件、无该记忆 ──
recheck: dict = {}
for db in dict.fromkeys(cands):
    if not db.exists():
        continue
    try:
        c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        tabs = {r[0] for r in c.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        dirty = {}
        if "interruption_events" in tabs:
            n = c.execute("SELECT COUNT(*) FROM interruption_events").fetchone()[0]
            if n:
                dirty["events"] = n
        if "memories" in tabs:
            n = c.execute("SELECT COUNT(*) FROM memories WHERE content LIKE ?",
                          (f"%{NEEDLE}%",)).fetchone()[0]
            if n:
                dirty["memories"] = n
        c.close()
        if dirty:
            recheck[str(db)] = dirty
    except sqlite3.Error:
        continue
report["recheck_dirty"] = recheck

(ROOT / "_cut_source.json").write_text(
    json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({
    "scanned": report["scanned"],
    "events_deleted_count": len(report["events_deleted"]),
    "events_deleted_sample": dict(list(report["events_deleted"].items())[:8]),
    "memories_deleted": report["memories_deleted"],
    "still_dirty": recheck,
}, ensure_ascii=False, indent=2)[:1500])
