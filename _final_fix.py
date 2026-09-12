"""最终收尾：在**活动配置**中暂停进化 + 清除会话库中的目标记忆。

关键认知（此前走弯路的原因）：
- 配置优先级为 `~/.tea_agent/config.yaml` > 包内 config.yaml
  → 我此前写的**仓库** config.yaml 从未被读取，故 interruption.enabled 仍为 True。
- 会话库（旧代码 Agent._init_storage 用 db_path_abs）= `~/.tea_agent/ds_flash.db`
  （41 条活跃记忆）。

本脚本：
1. 列出该库全部活跃记忆（定位被注入的那条）
2. 删除内容含「打断」的记忆
3. 在 ~/.tea_agent/config.yaml 中写入 interruption.enabled=false（幂等）
"""

import json
import os
import re
import sqlite3
from pathlib import Path

HOME_CFG = Path.home() / ".tea_agent" / "config.yaml"
SESSION_DB = Path.home() / ".tea_agent" / "ds_flash.db"
ROOT = Path(__file__).resolve().parent
NEEDLE = "打断"

out: dict = {"session_db": str(SESSION_DB), "cfg": str(HOME_CFG)}


def _dump_and_purge() -> dict:
    res: dict = {}
    c = sqlite3.connect(str(SESSION_DB), timeout=5)
    try:
        rows = c.execute(
            "SELECT id, category, priority, importance, tags, content FROM memories "
            "WHERE is_active = 1 ORDER BY priority ASC"
        ).fetchall()
        res["active_total"] = len(rows)
        res["all_contents"] = [
            {"id": str(r[0]), "cat": r[1], "prio": r[2], "imp": r[3],
             "tags": (r[4] or "")[:60], "content": (r[5] or "")[:100]}
            for r in rows
        ]
        targets = [r for r in rows if NEEDLE in (r[5] or "") or NEEDLE in (r[4] or "")]
        res["matched"] = len(targets)
        res["deleted_ids"] = []
        for r in targets:
            c.execute("DELETE FROM memories WHERE id = ?", (r[0],))
            res["deleted_ids"].append(str(r[0]))
        if targets:
            c.commit()
        res["active_after"] = c.execute(
            "SELECT COUNT(*) FROM memories WHERE is_active=1").fetchone()[0]
        return res
    finally:
        c.close()


if SESSION_DB.exists():
    out["session"] = _dump_and_purge()

# ── 活动配置：写入 interruption.enabled=false（幂等）──
if HOME_CFG.exists():
    text = HOME_CFG.read_text(encoding="utf-8")
    out["cfg_has_interruption"] = bool(re.search(r"^interruption\s*:", text, re.M))
    if out["cfg_has_interruption"]:
        # 已有 interruption 段：就地改 enabled
        new_text, n = re.subn(r"(?m)^(interruption\s*:\s*\n(?:(?:[ \t]+.*)?\n)*?[ \t]+)enabled\s*:.*$",
                              r"\1enabled: false", text)
        out["cfg_sub_replaced"] = n
    else:
        new_text = text.rstrip("\n") + (
            "\n\n# ── 暂停进化：关闭打断模式后台分析（自动沉淀记忆/skill）──\n"
            "# 该线程会每小时自动写入 preference 记忆；用户删除后会被重建（已修复，\n"
            "# 此处显式关闭以求稳妥）。记忆自此只由用户显式增删。\n"
            "interruption:\n"
            "  enabled: false\n"
        )
        out["cfg_sub_replaced"] = -1
    if new_text != text:
        HOME_CFG.write_text(new_text, encoding="utf-8")
        out["cfg_written"] = True
    else:
        out["cfg_written"] = False

(ROOT / "_final_fix.json").write_text(
    json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(out, ensure_ascii=False, indent=2)[:3000])
