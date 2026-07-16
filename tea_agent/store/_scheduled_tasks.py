"""
"""
import logging
from datetime import datetime, timedelta

from ._component import StoreComponent

logger = logging.getLogger("Storage.ScheduledTasks")

# cron 表达式解析 (简易: 分 时 日 月 周)
_CRON_MAP_WEEKDAY = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}

class ScheduledTaskStore(StoreComponent):
    """定时任务管理：增删改查、下次执行时间计算。"""

    # ── 调度格式解析 ──

    @staticmethod
    def parse_schedule(schedule: str, from_time: datetime = None) -> datetime | None:
        """解析 schedule 字符串，返回下次执行时间；None 表示单次已过期或无匹配。

        支持格式:
          once:2026-05-17T09:00          单次
          daily:09:00                    每天
          hourly:30                      每小时第30分
          interval:3600                  间隔秒数
          weekly:mon:09:00               每周一
          cron:0 9 * * *                 标准cron(5字段)
        """
        if not schedule:
            return None
        now = from_time or datetime.now()
        s = schedule.strip()

        try:
            # once:ISO
            if s.startswith("once:"):
                ts = s[5:]
                dt = datetime.fromisoformat(ts)
                return dt if dt > now else None

            # daily:HH:MM
            if s.startswith("daily:"):
                hm = s[6:]
                h, m = map(int, hm.split(":"))
                dt = now.replace(hour=h, minute=m, second=0, microsecond=0)
                if dt <= now:
                    dt += timedelta(days=1)
                return dt

            # hourly:MM
            if s.startswith("hourly:"):
                mm = int(s[7:])
                dt = now.replace(minute=mm, second=0, microsecond=0)
                if dt <= now:
                    dt += timedelta(hours=1)
                return dt

            # interval:SECONDS
            if s.startswith("interval:"):
                secs = int(s[9:])
                return now + timedelta(seconds=secs)

            # weekly:DAY:HH:MM
            if s.startswith("weekly:"):
                parts = s[7:].split(":")
                if len(parts) == 3:
                    day_name, h, m = parts[0].lower(), int(parts[1]), int(parts[2])
                    target_wd = _CRON_MAP_WEEKDAY.get(day_name)
                    if target_wd is not None:
                        current_wd = now.weekday()
                        days_ahead = (target_wd - current_wd) % 7
                        if days_ahead == 0:
                            dt = now.replace(hour=h, minute=m, second=0, microsecond=0)
                            if dt <= now:
                                days_ahead = 7
                        if days_ahead > 0:
                            dt = now.replace(hour=h, minute=m, second=0, microsecond=0) + timedelta(days=days_ahead)
                            return dt

            # cron: 5-field
            if s.startswith("cron:"):
                return _parse_cron(s[5:].strip(), now)

        except (ValueError, IndexError):
            logger.warning(f"无法解析调度: {schedule}")
        return None

    # ── CRUD ──

    def add_task(
        self, name: str, command: str, schedule: str, enabled: bool = True
    ) -> str:
        """新增定时任务，返回 task_id。"""
        tid = self._new_id()
        next_run = self.parse_schedule(schedule)
        c = self.conn.cursor()
        c.execute(
            """INSERT INTO scheduled_tasks
               (id, name, command, schedule, enabled, next_run, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""",
            (tid, name.strip(), command.strip(), schedule.strip(),
             1 if enabled else 0,
             next_run.isoformat() if next_run else None),
        )
        self.conn.commit()
        logger.info(f"新增定时任务: {name} (schedule={schedule}, next={next_run})")
        return tid

    def update_task(self, task_id: str, **kwargs) -> bool:
        """更新任务字段: name, command, schedule, enabled, last_run, last_result, last_exit_code, next_run."""
        allowed = {"name", "command", "schedule", "enabled", "last_run",
                   "last_result", "last_exit_code", "next_run"}
        updates = {k: v for k, v in kwargs.items() if k in allowed}
        if not updates:
            return False
        if "schedule" in updates and "next_run" not in updates:
            updates["next_run"] = self.parse_schedule(updates["schedule"])
        if updates:
            updates["updated_at"] = "CURRENT_TIMESTAMP"
        # SAFETY: `k` comes from TaskStore.update_task(kwargs) - internal code, not user input
        _ALLOWED_COLUMNS = {"name", "command", "schedule", "enabled", "updated_at"}  # noqa: N806
        for k in updates:
            assert k in _ALLOWED_COLUMNS, f"invalid column: {k}"
        set_clause = ", ".join(
            f"{k}=?" if k != "updated_at" else f"{k}=CURRENT_TIMESTAMP"
            for k in updates
        )
        values = [v for k, v in updates.items() if k != "updated_at"]
        values.append(task_id)
        c = self.conn.cursor()
        c.execute(f"UPDATE scheduled_tasks SET {set_clause} WHERE id=?", values)
        self.conn.commit()
        return c.rowcount > 0

    def delete_task(self, task_id: str) -> bool:
        """删除任务。"""
        c = self.conn.cursor()
        c.execute("DELETE FROM scheduled_tasks WHERE id=?", (task_id,))
        self.conn.commit()
        return c.rowcount > 0

    def get_task(self, task_id: str) -> dict | None:
        """获取单个任务。"""
        c = self.conn.cursor()
        c.execute("SELECT * FROM scheduled_tasks WHERE id=?", (task_id,))
        row = c.fetchone()
        return dict(row) if row else None

    def list_tasks(self, enabled_only: bool = False) -> list[dict]:
        """列出所有任务。"""
        c = self.conn.cursor()
        if enabled_only:
            c.execute("SELECT * FROM scheduled_tasks WHERE enabled=1 ORDER BY next_run ASC")
        else:
            c.execute("SELECT * FROM scheduled_tasks ORDER BY enabled DESC, next_run ASC")
        return [dict(row) for row in c.fetchall()]

    def get_due_tasks(self) -> list[dict]:
        """获取所有到期需要执行的任务 (enabled=1 AND next_run <= now)。"""
        now = datetime.now().isoformat()
        c = self.conn.cursor()
        c.execute(
            "SELECT * FROM scheduled_tasks WHERE enabled=1 AND next_run IS NOT NULL AND next_run <= ?",
            (now,),
        )
        return [dict(row) for row in c.fetchall()]

    def mark_run(self, task_id: str, exit_code: int, result: str, next_run: str | None = None):
        """标记任务执行完成，更新 last_run/result/exit_code/next_run."""
        c = self.conn.cursor()
        c.execute(
            """UPDATE scheduled_tasks
               SET last_run=CURRENT_TIMESTAMP, last_exit_code=?, last_result=?,
                   next_run=?, updated_at=CURRENT_TIMESTAMP
               WHERE id=?""",
            (exit_code, result[:2000], next_run, task_id),
        )
        self.conn.commit()

def _parse_cron(expr: str, now: datetime) -> datetime | None:
    """简易 5 字段 cron 解析，返回下次匹配时间 (精度到分钟)。"""
    try:
        parts = expr.strip().split()
        if len(parts) != 5:
            return None
        minute, hour, day, month, weekday = parts
        # 检查未来 7 天每分钟 (简单暴力但可靠)
        dt = now.replace(second=0, microsecond=0) + timedelta(minutes=1)
        for _ in range(7 * 24 * 60):
            if _match_cron_field(minute, dt.minute) and \
               _match_cron_field(hour, dt.hour) and \
               _match_cron_field(day, dt.day) and \
               _match_cron_field(month, dt.month) and \
               _match_cron_field(weekday, dt.weekday()):
                return dt
            dt += timedelta(minutes=1)
        return None
    except Exception:
        return None

def _match_cron_field(pattern: str, value: int) -> bool:
    """匹配单个 cron 字段: * / 步长 , 列表 - 范围"""
    if pattern == "*":
        return True
    for part in pattern.split(","):
        part = part.strip()
        if "/" in part:
            base, step = part.split("/")
            step = int(step)
            if base == "*":
                if value % step == 0:
                    return True
            else:
                lo = int(base)
                if value >= lo and (value - lo) % step == 0:
                    return True
        elif "-" in part:
            lo, hi = map(int, part.split("-"))
            if lo <= value <= hi:
                return True
        else:
            if int(part) == value:
                return True
    return False
