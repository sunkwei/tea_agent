"""临时探针：枚举所有 DB，定位会话实际读写的库（用后删除）。

疑点：resolve_db_path 用 active_db_path_abs 的 basename 决定项目级库名，
实测文件是 .tea_agent_run/ds_flash.db（疑似 per-profile）。若会话与工具
(get_storage) 落在不同库，则「记忆增删不可靠」——用户删掉的记忆仍被注入。
"""

import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TARGET = "打断模式"


def _info(db: Path) -> dict:
    try:
        c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    except sqlite3.Error as e:
        return {"error": str(e)}
    try:
        tabs = [r[0] for r in c.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        out = {"tables": len(tabs), "mtime": db.stat().st_mtime}
        if "memories" in tabs:
            out["mem_total"] = c.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
            out["mem_active"] = c.execute(
                "SELECT COUNT(*) FROM memories WHERE is_active=1").fetchone()[0]
            out["has_target"] = c.execute(
                "SELECT COUNT(*) FROM memories WHERE content LIKE ?", (f"%{TARGET}%",)
            ).fetchone()[0]
        if "topics" in tabs:
            out["topics"] = c.execute("SELECT COUNT(*) FROM topics").fetchone()[0]
        if "conversations" in tabs:
            out["convs"] = c.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]
        return out
    except sqlite3.Error as e:
        return {"error": str(e)}
    finally:
        c.close()


def test_enumerate_all_dbs():
    out = {"dbs": {}}
    for base in [ROOT / ".tea_agent_run", Path.home() / ".tea_agent", ROOT]:
        if not base.exists():
            continue
        for db in sorted(base.glob("*.db")):
            out["dbs"][str(db)] = _info(db)
        for db in sorted(base.glob("**/*.db")):
            k = str(db)
            if k not in out["dbs"]:
                out["dbs"][k] = _info(db)

    # 解析当前进程的「活动库」与「用户库」
    try:
        from tea_agent.config import get_config
        cfg = get_config()
        p = cfg.paths
        out["cfg_db_path_abs"] = str(getattr(p, "db_path_abs", ""))
        out["cfg_active_db_path_abs"] = str(getattr(p, "active_db_path_abs", ""))
        out["cfg_storage_scope"] = str(getattr(p, "storage_scope", ""))
    except (ImportError, AttributeError) as e:
        out["cfg_error"] = str(e)

    from tea_agent.store import get_storage
    out["get_storage_path"] = str(getattr(get_storage(), "db_path", "?"))

    (ROOT / "_db_inventory.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    raise AssertionError(json.dumps(out, ensure_ascii=False, default=str)[:1600])
