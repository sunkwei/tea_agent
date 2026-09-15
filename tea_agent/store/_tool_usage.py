"""ToolUsageStore — 工具使用统计（项目 db：$pwd/.tea_agent_run/）。

记录每个 toolkit_xxx 的调用次数与首次/最近使用时间，供 tool_shield 判定
「长期不用的工具默认屏蔽」。

设计要点：
- **一行一工具**，只累加不记明细：体量与工具数同阶（几十行），不是无界日志表。
- 记录点在 `Toolkit.call_tool`（所有会话/子 Agent/HTTP 直跑都经过它）。
- 写入 best-effort：统计是辅助能力，一次 DB 忙不能把真实工具调用带崩。
- 「零使用」与「没数据」是两回事：空表只代表尚未观测，屏蔽判定必须区分二者
  （见 tool_shield 的观测期规则），否则新装机第一次启动就会屏蔽掉全部工具。
"""

from __future__ import annotations

import logging
import sqlite3
import time
from datetime import datetime, timezone

from ._component import StoreComponent

logger = logging.getLogger("ToolUsageStore")

TABLE = "tool_usage"

# 建表 SQL 由本模块单一持有，migration.py 引用它 —— 避免两处 schema 各自漂移
CREATE_SQL = f"""
        CREATE TABLE IF NOT EXISTS {TABLE} (
            tool        TEXT PRIMARY KEY,
            uses        INTEGER NOT NULL DEFAULT 0,
            first_used  TEXT,
            last_used   TEXT,
            pin         INTEGER   -- NULL=按数据自动判定, 1=永久保留, 0=永久屏蔽
        )
"""


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ToolUsageStore(StoreComponent):
    """工具使用统计 CRUD。"""

    _TABLE = TABLE

    def ensure_table(self) -> None:
        """建表（幂等）。record_use 会自动补建，显式调用供测试/迁移用。"""
        try:
            c = self.conn.cursor()
            c.execute(CREATE_SQL)
            c.connection.commit()
            c.close()
        except Exception:
            logger.exception("ensure_table failed")

    # ── 写入 ─────────────────────────────────────────────
    def record_use(self, tool: str, when: str | None = None) -> bool:
        """累加一次工具调用。返回是否写入成功；失败不外抛。"""
        if not tool:
            return False
        ts = when or _utcnow()
        try:
            self._upsert_with_retry(tool, ts)
            return True
        except sqlite3.OperationalError as e:
            if "no such table" not in str(e):
                logger.warning("record_use(%s) 失败: %s", tool, e)
                return False
            # 老库尚未有该表：建一次再试。刻意不在每次调用前跑 DDL —— 这是每次
            # 工具调用都经过的热路径，无谓的建表语句会白付开销。
            self.ensure_table()
            try:
                self._upsert_with_retry(tool, ts)
                return True
            except Exception:
                logger.warning("record_use(%s) 建表后仍失败", tool, exc_info=True)
                return False
        except Exception:
            logger.warning("record_use(%s) 失败", tool, exc_info=True)
            return False

    def _upsert_with_retry(self, tool: str, ts: str, attempts: int = 3) -> None:
        """累加写入，遇写锁退避重试。

        ⚠️ 这里不能"记条日志就算了"：别处统计丢一条无所谓，本表少记一条会让
        **真在用的工具**被算成"长期没用"进而被屏蔽 —— 丢数据的代价方向正好相反。
        并发会话/子 Agent 共用一个库（WAL 并发读、单写），偶发 locked 属预期内。
        """
        delay = 0.02
        for attempt in range(attempts):
            try:
                self._upsert(tool, ts)
                return
            except sqlite3.OperationalError as e:
                low = str(e).lower()
                if ("locked" not in low) and ("busy" not in low):
                    raise
                if attempt == attempts - 1:
                    raise
                time.sleep(delay)
                delay *= 2  # 最坏 ~60ms，远小于一次工具调用本身

    def _upsert(self, tool: str, ts: str) -> None:
        # INSERT..ON CONFLICT 而非先查后写：并发记录同一工具时先查后写会丢累加。
        c = self.conn.cursor()
        c.execute(
            f"INSERT INTO {self._TABLE} (tool, uses, first_used, last_used)"
            " VALUES (?, 1, ?, ?)"
            " ON CONFLICT(tool) DO UPDATE SET"
            "   uses = uses + 1,"
            "   last_used = excluded.last_used,"
            "   first_used = COALESCE(first_used, excluded.first_used)",
            (tool, ts, ts),
        )
        c.connection.commit()
        c.close()

    # ── 读取 ─────────────────────────────────────────────
    def all_usage(self) -> dict[str, dict]:
        """{tool: {uses, first_used, last_used, pin}}；表不存在时返回 {}。"""
        try:
            c = self.conn.cursor()
            try:
                rows = c.execute(
                    f"SELECT tool, uses, first_used, last_used, pin FROM {self._TABLE}"
                ).fetchall()
            finally:
                c.close()
        except Exception:
            logger.debug("all_usage 失败（表可能尚未创建）", exc_info=True)
            return {}
        return {
            r["tool"]: {
                "uses": int(r["uses"] or 0),
                "first_used": r["first_used"],
                "last_used": r["last_used"],
                "pin": r["pin"],
            }
            for r in rows
        }

    def oldest_observed(self) -> str | None:
        """最早一条使用记录的时间 —— 「观测已持续多久」的基准。

        没有它就无法区分"刚装好还没用"与"用了很久但从没需要过它"；把前者也判成
        不活跃，等于新环境第一次启动就把工具全屏蔽。
        """
        try:
            c = self.conn.cursor()
            try:
                row = c.execute(f"SELECT MIN(first_used) AS m FROM {self._TABLE}").fetchone()
            finally:
                c.close()
        except Exception:
            return None
        return row["m"] if row and row["m"] else None

    # ── 人工覆盖 ─────────────────────────────────────────
    def set_pin(self, tool: str, pin: int | None) -> bool:
        """pin: 1=永久保留, 0=永久屏蔽, None=交回自动判定。

        工具行可能还不存在（从未被调用），故先建行再置位 —— 否则设置会在该工具
        第一次被使用时被 UPSERT 的默认值覆盖掉。
        """
        if not tool:
            return False
        try:
            c = self.conn.cursor()
            c.execute(f"INSERT OR IGNORE INTO {self._TABLE} (tool, uses) VALUES (?, 0)", (tool,))
            c.execute(f"UPDATE {self._TABLE} SET pin = ? WHERE tool = ?", (pin, tool))
            c.connection.commit()
            c.close()
            return True
        except Exception:
            logger.exception("set_pin failed")
            return False

    def prune(self, keep: list[str]) -> int:
        """删除已不在注册表中的工具行（工具被删后不留幽灵统计）。

        在 Python 侧算差集再逐条参数化删除，不拼 `NOT IN (?,?...)` 动态占位符：
        后者让 SQL 文本由变量拼成，既要额外论证安全，也会撞上项目的 SQL 插值
        不变量检查。本表按设计只有几十行，全表扫描代价可忽略。
        """
        keep_set = {k for k in (keep or []) if k}
        if not keep_set:
            return 0
        try:
            c = self.conn.cursor()
            try:
                rows = c.execute(f"SELECT tool FROM {self._TABLE}").fetchall()
                stale = [r["tool"] for r in rows if r["tool"] not in keep_set]
                n = 0
                for name in stale:
                    cur = c.execute(f"DELETE FROM {self._TABLE} WHERE tool = ?", (name,))
                    n += int(cur.rowcount or 0)
                c.connection.commit()
            finally:
                c.close()
            return n
        except Exception:
            logger.debug("prune failed", exc_info=True)
            return 0

    def report(self) -> list[dict]:
        """按使用次数降序（供展示）。"""
        usage = self.all_usage()
        return [
            {"tool": t, **v}
            for t, v in sorted(usage.items(), key=lambda kv: (-kv[1]["uses"], kv[0]))
        ]
