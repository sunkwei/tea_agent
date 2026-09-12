"""一次性清空「打断模式」记忆的所有载体（收尾脚本）。

依据 _find_live.json 的全盘扫描结果（613 个 DB，多个命中），逐库删除该记忆，
并顺带把 interruption_events 中 status='classified' 的记录清掉，
使运行中的旧版分析器无从重建（无需等待服务器重启）。
"""

import json
import sqlite3
from pathlib import Path

NEEDLE = "打断模式"
ROOT = Path(__file__).resolve().parent
HITS = ROOT / "_find_live.json"

report = {"purged": {}, "events_cleared": {}, "errors": []}

paths = []
if HITS.exists():
    data = json.loads(HITS.read_text(encoding="utf-8"))
    paths.extend(data.get("hits", {}).keys())

# 保底：再扫一遍候选目录（覆盖扫描期间新建的库）
extra = []
for d in [ROOT / ".tea_agent_run", ROOT, Path.home() / ".tea_agent",
          Path.home() / "AppData" / "Local" / "Temp"]:
    if d.exists():
        extra.extend(str(p) for p in d.glob("*.db"))
paths = list(dict.fromkeys(list(paths) + extra))

for p in paths:
    fp = Path(p)
    if not fp.exists():
        continue
    try:
        c = sqlite3.connect(str(fp), timeout=5)
    except sqlite3.Error as e:
        report["errors"].append(f"{p}: {e}")
        continue
    try:
        tabs = {r[0] for r in c.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        removed = 0
        if "memories" in tabs:
            rows = c.execute("SELECT id FROM memories WHERE content LIKE ?",
                             (f"%{NEEDLE}%",)).fetchall()
            for (mid,) in rows:
                c.execute("DELETE FROM memories WHERE id=?", (mid,))
                removed += 1
        if removed:
            report["purged"][p] = removed
        if "interruption_events" in tabs:
            n = c.execute(
                "SELECT COUNT(*) FROM interruption_events WHERE status='classified'"
            ).fetchone()[0]
            if n:
                c.execute("DELETE FROM interruption_events WHERE status='classified'")
                report["events_cleared"][p] = n
        c.commit()
    except sqlite3.Error as e:
        report["errors"].append(f"{p}: {e}")
    finally:
        c.close()

report["scanned"] = len(paths)
print(json.dumps(report, ensure_ascii=False, indent=2)[:2000])
