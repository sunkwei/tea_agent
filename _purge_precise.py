"""精确定位会话实际使用的库并彻底清掉该记忆（收尾脚本）。

前一轮已清空 50+ 个 Temp 库仍持续注入 → 说明会话库另有其处。
本脚本不再猜测，而是：
1. 用与原程序**完全相同的解析链**求出会话库路径
   （Agent._init_storage 修复后用 active_db_path_abs；
     store.get_storage 用 active_db_path_abs）
2. 列出该库中所有活跃记忆（确认是否含目标）
3. 删除目标记忆 + 清空**全部** interruption_events（不只 classified，
   防「pending 稍后被分类又触发重建」）
4. 复核
"""

import json
import sqlite3
from pathlib import Path

NEEDLE = "打断模式"
ROOT = Path(__file__).resolve().parent

from tea_agent.config import get_config  # noqa: E402
from tea_agent.store import get_storage  # noqa: E402

cfg = get_config()
out: dict = {
    "cfg.db_path_abs": str(cfg.paths.db_path_abs),
    "cfg.active_db_path_abs": str(getattr(cfg.paths, "active_db_path_abs", "")),
    "cfg.interruption": dict(getattr(cfg, "interruption", {}) or {}),
}

targets = [str(cfg.paths.db_path_abs), str(getattr(cfg.paths, "active_db_path_abs", ""))]
st = get_storage()
targets.append(str(getattr(st, "db_path", "")))
# 保底：用户级与项目级的全部候选
for d in [ROOT / ".tea_agent_run", Path.home() / ".tea_agent"]:
    if d.exists():
        targets.extend(str(p) for p in d.glob("*.db"))
targets = list(dict.fromkeys([t for t in targets if t]))

out["targets"] = targets
out["probe"] = {}
out["purged"] = {}

for t in targets:
    fp = Path(t)
    if not fp.exists():
        out["probe"][t] = "missing"
        continue
    try:
        c = sqlite3.connect(str(fp), timeout=5)
    except sqlite3.Error as e:
        out["probe"][t] = f"err:{e}"
        continue
    try:
        tabs = {r[0] for r in c.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        info: dict = {}
        if "memories" in tabs:
            rows = c.execute(
                "SELECT id, category, priority, substr(content,1,40) FROM memories "
                "WHERE is_active=1").fetchall()
            info["active"] = len(rows)
            info["has_needle"] = sum(1 for r in rows if NEEDLE in (r[3] or ""))
            if info["has_needle"]:
                ids = [r[0] for r in rows if NEEDLE in (r[3] or "")]
                for mid in ids:
                    c.execute("DELETE FROM memories WHERE id=?", (mid,))
                out["purged"][t] = {"memory_ids": [str(i) for i in ids]}
        if "interruption_events" in tabs:
            n = c.execute("SELECT COUNT(*) FROM interruption_events").fetchone()[0]
            info["events"] = n
            if n:
                c.execute("DELETE FROM interruption_events")
                out["purged"].setdefault(t, {})["events_deleted"] = n
        if "memories" in tabs or "interruption_events" in tabs:
            c.commit()
        out["probe"][t] = info
    except sqlite3.Error as e:
        out["probe"][t] = f"err:{e}"
    finally:
        c.close()

# 复核
out["recheck"] = {}
for t in targets:
    fp = Path(t)
    if not fp.exists():
        continue
    try:
        c = sqlite3.connect(f"file:{fp}?mode=ro", uri=True)
        n = c.execute("SELECT COUNT(*) FROM memories WHERE content LIKE ?",
                      (f"%{NEEDLE}%",)).fetchone()[0]
        c.close()
        if n:
            out["recheck"][t] = n
    except sqlite3.Error:
        continue

(ROOT / "_final_purge.json").write_text(
    json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(out, ensure_ascii=False, indent=2)[:2500])
