"""临时探针：全库清除该记忆 + 判定「活库」（用后删除）。

载体清单确认：该记忆现存活于 .tea_agent_run/chat_history_2026-09-12.db（今日新建，
此前清单中不存在）。已删的 09-08 库不是会话实际读取的库。

本探针：
1. 对每个候选 DB 统计「最近对话时间戳」→ 判定哪个是当前会话的活库
2. 从所有 DB 中删除该记忆（确保注入停止）
3. 复核
"""

import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NEEDLE = "打断模式"
CANDIDATE_DIRS = [ROOT / ".tea_agent_run", ROOT, Path.home() / ".tea_agent"]


def _db_info(db: Path) -> dict:
    info: dict = {"mtime": db.stat().st_mtime}
    try:
        c = sqlite3.connect(str(db), timeout=5)
    except sqlite3.Error as e:
        return {"error": str(e)}
    try:
        tabs = {r[0] for r in c.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        info["tables"] = len(tabs)
        if "memories" in tabs:
            info["mem_needle"] = c.execute(
                "SELECT COUNT(*) FROM memories WHERE content LIKE ?",
                (f"%{NEEDLE}%",)).fetchone()[0]
            info["mem_total"] = c.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
        if "conversations" in tabs:
            row = c.execute("SELECT MAX(stamp) FROM conversations").fetchone()
            info["latest_conv"] = row[0] if row else None
            info["convs"] = c.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]
        if "topics" in tabs:
            row = c.execute(
                "SELECT title, created_at FROM topics ORDER BY rowid DESC LIMIT 1").fetchone()
            info["last_topic"] = [str(x)[:60] for x in row] if row else None
        return info
    except sqlite3.Error as e:
        return {"error": str(e)}
    finally:
        c.close()


def _purge(db: Path) -> list:
    removed = []
    try:
        c = sqlite3.connect(str(db), timeout=5)
    except sqlite3.Error:
        return removed
    try:
        tabs = {r[0] for r in c.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        if "memories" not in tabs:
            return removed
        rows = c.execute(
            "SELECT id, is_active, substr(content,1,40) FROM memories WHERE content LIKE ?",
            (f"%{NEEDLE}%",)).fetchall()
        for mid, _active, _txt in rows:
            c.execute("DELETE FROM memories WHERE id = ?", (mid,))
            removed.append(str(mid))
        c.commit()
        return removed
    except sqlite3.Error:
        return removed
    finally:
        c.close()


def test_purge_all_and_identify_live_db():
    out: dict = {"before": {}, "purged": {}, "after": {}}
    dbs: list = []
    for d in CANDIDATE_DIRS:
        if d.exists():
            dbs.extend(sorted(d.glob("*.db")))
            dbs.extend(sorted(d.glob("**/.tea_agent_run/*.db")))
    dbs = list(dict.fromkeys(dbs))

    for db in dbs:
        try:
            i = _db_info(db)
        except OSError:
            continue
        if i.get("tables"):
            out["before"][str(db)] = i

    for db in dbs:
        try:
            r = _purge(db)
        except OSError:
            continue
        if r:
            out["purged"][str(db)] = r

    for db in dbs:
        try:
            i = _db_info(db)
        except OSError:
            continue
        if i.get("tables"):
            out["after"][str(db)] = i

    (ROOT / "_purge_all.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    raise AssertionError(json.dumps(out["purged"], ensure_ascii=False)[:600])
