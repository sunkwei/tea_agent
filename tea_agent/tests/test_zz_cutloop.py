"""临时探针：立即切断「删除记忆被重建」循环（用后删除）。

运行中的服务器仍是旧代码，无法等待重启；故直接清除**复活源**：
  analyze_interruptions 每轮读 `status='classified'` 的打断事件 → 有则重建记忆。
把 interruption_events 全部清掉 + 删除该记忆 → 循环立即终止（无需重启）。

对所有候选 DB 执行（会话与工具可能分属不同库）。
"""

import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NEEDLE = "打断模式"
DIRS = [ROOT / ".tea_agent_run", ROOT, Path.home() / ".tea_agent"]


def _cut(db: Path) -> dict:
    out: dict = {}
    try:
        c = sqlite3.connect(str(db), timeout=5)
    except sqlite3.Error as e:
        return {"error": str(e)}
    try:
        tabs = {r[0] for r in c.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        if "interruption_events" in tabs:
            n_cls = c.execute(
                "SELECT COUNT(*) FROM interruption_events WHERE status='classified'"
            ).fetchone()[0]
            c.execute("DELETE FROM interruption_events WHERE status='classified'")
            out["events_cleared"] = n_cls
            out["events_total"] = c.execute(
                "SELECT COUNT(*) FROM interruption_events").fetchone()[0]
        if "memories" in tabs:
            rows = c.execute("SELECT id FROM memories WHERE content LIKE ?",
                             (f"%{NEEDLE}%",)).fetchall()
            for (mid,) in rows:
                c.execute("DELETE FROM memories WHERE id=?", (mid,))
            out["memories_removed"] = len(rows)
        if "memories" in tabs or "interruption_events" in tabs:
            c.commit()
        return out
    except sqlite3.Error as e:
        return {"error": str(e)}
    finally:
        c.close()


def test_cut_resurrection_loop():
    report: dict = {}
    dbs: list = []
    for d in DIRS:
        if d.exists():
            dbs.extend(sorted(d.glob("*.db")))
            dbs.extend(sorted(d.glob("**/.tea_agent_run/*.db")))
    for db in dict.fromkeys(dbs):
        try:
            r = _cut(db)
        except OSError:
            continue
        if r:
            report[str(db)] = r

    changed = {k: v for k, v in report.items()
               if v.get("events_cleared") or v.get("memories_removed")}
    (ROOT / "_cut_loop.json").write_text(
        json.dumps(changed, ensure_ascii=False, indent=2), encoding="utf-8")
    raise AssertionError(json.dumps(changed, ensure_ascii=False)[:900])
