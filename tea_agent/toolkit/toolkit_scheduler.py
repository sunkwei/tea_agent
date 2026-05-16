## @2026-05-16 gen by tea_agent, 定时任务管理器 — 独立 scheduler.db，支持增删改查/启停/调度执行/通知
# version: 1.0.0

import logging
logger = logging.getLogger("toolkit")

def toolkit_scheduler(action: str, **kwargs):
    """定时任务管理工具。

    action:
      list              — 列出所有任务
      add               — 新增任务 (需: name, command, schedule)
      update            — 更新任务 (需: task_id, 可选: name/command/schedule/enabled)
      delete            — 删除任务 (需: task_id)
      enable/disable    — 启停任务 (需: task_id)
      run               — 立即执行指定任务 (需: task_id)
      start/stop/status — 调度线程管理
      test_schedule     — 测试调度表达式 (需: schedule)

    schedule 格式:
      once:2026-05-17T09:00    单次
      daily:09:00              每天
      hourly:30                每小时第30分
      interval:3600            间隔秒
      weekly:mon:09:00         每周一
      cron:0 9 * * *           cron表达式
    """
    logger.info(f"toolkit_scheduler called: action={action!r}")

    import os, json, time, sqlite3, threading, subprocess
    from datetime import datetime, timedelta
    from pathlib import Path

    # ── DB 路径 ──
    try:
        from tea_agent.config import get_config
        DB_PATH = os.path.join(get_config().paths.data_dir_abs, "scheduler.db")
    except Exception:
        DB_PATH = os.path.expanduser("~/.tea_agent/scheduler.db")

    CHECK_INTERVAL = 60  # 每分钟检查一次

    _CRON_WEEKDAY = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}

    # ── DB 初始化 ──
    def _get_conn():
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute('''
            CREATE TABLE IF NOT EXISTS scheduled_tasks (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                command TEXT NOT NULL,
                schedule TEXT NOT NULL,
                enabled INTEGER DEFAULT 1,
                last_run TIMESTAMP,
                last_result TEXT DEFAULT '',
                last_exit_code INTEGER,
                next_run TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.commit()
        return conn

    # ── 调度解析 ──
    def parse_schedule(schedule: str, from_time: datetime = None):
        if not schedule:
            return None
        now = from_time or datetime.now()
        s = schedule.strip()
        try:
            if s.startswith("once:"):
                dt = datetime.fromisoformat(s[5:])
                return dt if dt > now else None
            if s.startswith("daily:"):
                h, m = map(int, s[6:].split(":"))
                dt = now.replace(hour=h, minute=m, second=0, microsecond=0)
                return dt if dt > now else dt + timedelta(days=1)
            if s.startswith("hourly:"):
                mm = int(s[7:])
                dt = now.replace(minute=mm, second=0, microsecond=0)
                return dt if dt > now else dt + timedelta(hours=1)
            if s.startswith("interval:"):
                return now + timedelta(seconds=int(s[9:]))
            if s.startswith("weekly:"):
                parts = s[7:].split(":")
                day_name, h, m = parts[0].lower(), int(parts[1]), int(parts[2])
                target_wd = _CRON_WEEKDAY.get(day_name)
                if target_wd is not None:
                    days_ahead = (target_wd - now.weekday()) % 7
                    if days_ahead == 0:
                        dt = now.replace(hour=h, minute=m, second=0, microsecond=0)
                        if dt <= now:
                            days_ahead = 7
                    if days_ahead > 0:
                        return now.replace(hour=h, minute=m, second=0, microsecond=0) + timedelta(days=days_ahead)
            if s.startswith("cron:"):
                return _parse_cron(s[5:].strip(), now)
        except (ValueError, IndexError):
            pass
        return None

    def _match_cron(pattern: str, value: int) -> bool:
        if pattern == "*":
            return True
        for part in pattern.split(","):
            part = part.strip()
            if "/" in part:
                base, step = part.split("/")
                step = int(step)
                lo = 0 if base == "*" else int(base)
                if value >= lo and (value - lo) % step == 0:
                    return True
            elif "-" in part:
                lo, hi = map(int, part.split("-"))
                if lo <= value <= hi:
                    return True
            elif int(part) == value:
                return True
        return False

    def _parse_cron(expr: str, now: datetime):
        parts = expr.strip().split()
        if len(parts) != 5:
            return None
        dt = now.replace(second=0, microsecond=0) + timedelta(minutes=1)
        for _ in range(7 * 24 * 60):
            if all(_match_cron(p, v) for p, v in zip(parts, [dt.minute, dt.hour, dt.day, dt.month, dt.weekday()])):
                return dt
            dt += timedelta(minutes=1)
        return None

    # ── 通知 ──
    def _notify(title: str, msg: str):
        """发送系统通知"""
        try:
            from tea_agent.toolkit.toolkit_subconscious import toolkit_subconscious as _ts
            # 复用潜意识的通知基础设施
            pass
        except Exception:
            pass
        try:
            import sys
            if sys.platform == 'linux':
                subprocess.run(['notify-send', '--app-name=TeaAgent', title, msg],
                               capture_output=True, timeout=5)
            elif sys.platform == 'darwin':
                subprocess.run(['osascript', '-e',
                    f'display notification "{msg}" with title "{title}"'],
                    capture_output=True, timeout=5)
        except Exception:
            pass

    # ── 执行任务 ──
    def _execute_task(task: dict):
        """执行命令行任务，返回 (exit_code, output)"""
        cmd = task["command"]
        logger.info(f"执行定时任务: {task['name']} -> {cmd}")
        try:
            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, timeout=300, cwd=os.getcwd()
            )
            output = (result.stdout + result.stderr)[:2000]
            return result.returncode, output
        except subprocess.TimeoutExpired:
            return -1, "任务超时 (5分钟)"
        except Exception as e:
            return -2, str(e)[:500]

    # ── 调度守护线程 ──
    _scheduler_running = False
    _scheduler_pid = None

    def _scheduler_loop():
        nonlocal _scheduler_running, _scheduler_pid
        _scheduler_running = True
        _scheduler_pid = os.getpid()
        logger.info(f"定时任务调度器已启动 (pid={_scheduler_pid})")
        _notify("⏰ 定时任务调度器", f"已启动，每{CHECK_INTERVAL}秒检查")

        while _scheduler_running:
            try:
                conn = _get_conn()
                due = conn.execute(
                    "SELECT * FROM scheduled_tasks WHERE enabled=1 AND next_run IS NOT NULL AND next_run <= ?",
                    (datetime.now().isoformat(),)
                ).fetchall()
                conn.close()

                for task_row in due:
                    task = dict(task_row)
                    logger.info(f"触发任务: {task['name']}")
                    exit_code, output = _execute_task(task)

                    # 更新执行结果
                    conn2 = _get_conn()
                    next_run = None
                    if task["schedule"].startswith("once:"):
                        # 单次任务执行后禁用
                        conn2.execute(
                            "UPDATE scheduled_tasks SET enabled=0, last_run=CURRENT_TIMESTAMP, "
                            "last_exit_code=?, last_result=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                            (exit_code, output, task["id"])
                        )
                    else:
                        # 重复任务计算下次执行
                        next_dt = parse_schedule(task["schedule"])
                        next_run = next_dt.isoformat() if next_dt else None
                        conn2.execute(
                            "UPDATE scheduled_tasks SET last_run=CURRENT_TIMESTAMP, "
                            "last_exit_code=?, last_result=?, next_run=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                            (exit_code, output, next_run, task["id"])
                        )
                    conn2.commit()
                    conn2.close()

                    # 通知执行结果
                    icon = "✅" if exit_code == 0 else "❌"
                    _notify(
                        f"{icon} 定时任务: {task['name']}",
                        f"退出码: {exit_code}\n{output[:200]}"
                    )

            except Exception as e:
                logger.warning(f"调度器循环异常: {e}")

            time.sleep(CHECK_INTERVAL)

        logger.info("定时任务调度器已停止")

    # ── action 分发 ──
    if action == "list":
        conn = _get_conn()
        rows = conn.execute(
            "SELECT * FROM scheduled_tasks ORDER BY enabled DESC, next_run ASC"
        ).fetchall()
        conn.close()
        tasks = []
        for r in rows:
            t = dict(r)
            t["_next_label"] = _format_next(t)
            tasks.append(t)
        return {"tasks": tasks, "count": len(tasks), "scheduler_running": _scheduler_running}

    elif action == "add":
        name = kwargs.get("name", "")
        command = kwargs.get("command", "")
        schedule = kwargs.get("schedule", "")
        if not name or not command or not schedule:
            return {"error": "需要 name, command, schedule 参数"}
        next_run = parse_schedule(schedule)
        conn = _get_conn()
        tid = str(__import__('uuid').uuid4())
        conn.execute(
            "INSERT INTO scheduled_tasks (id,name,command,schedule,enabled,next_run) VALUES (?,?,?,?,1,?)",
            (tid, name.strip(), command.strip(), schedule.strip(),
             next_run.isoformat() if next_run else None)
        )
        conn.commit()
        conn.close()
        _notify("⏰ 新增定时任务", f"{name}\n调度: {schedule}")
        return {"status": "added", "task_id": tid, "next_run": next_run.isoformat() if next_run else None}

    elif action == "update":
        tid = kwargs.get("task_id", "")
        if not tid:
            return {"error": "需要 task_id 参数"}
        conn = _get_conn()
        existing = conn.execute("SELECT * FROM scheduled_tasks WHERE id=?", (tid,)).fetchone()
        if not existing:
            conn.close()
            return {"error": f"任务不存在: {tid}"}
        updates = {}
        for field in ["name", "command", "schedule"]:
            if field in kwargs:
                updates[field] = kwargs[field]
        if "enabled" in kwargs:
            updates["enabled"] = 1 if kwargs["enabled"] else 0
        if "schedule" in updates:
            updates["next_run"] = parse_schedule(updates["schedule"])
            updates["next_run"] = updates["next_run"].isoformat() if updates["next_run"] else None
        if updates:
            set_parts = [f"{k}=?" for k in updates]
            vals = list(updates.values()) + [tid]
            conn.execute(
                f"UPDATE scheduled_tasks SET {', '.join(set_parts)}, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                vals
            )
            conn.commit()
        conn.close()
        return {"status": "updated"}

    elif action == "delete":
        tid = kwargs.get("task_id", "")
        if not tid:
            return {"error": "需要 task_id 参数"}
        conn = _get_conn()
        conn.execute("DELETE FROM scheduled_tasks WHERE id=?", (tid,))
        conn.commit()
        conn.close()
        return {"status": "deleted"}

    elif action == "enable":
        tid = kwargs.get("task_id", "")
        conn = _get_conn()
        conn.execute("UPDATE scheduled_tasks SET enabled=1, updated_at=CURRENT_TIMESTAMP WHERE id=?", (tid,))
        conn.commit()
        conn.close()
        return {"status": "enabled"}

    elif action == "disable":
        tid = kwargs.get("task_id", "")
        conn = _get_conn()
        conn.execute("UPDATE scheduled_tasks SET enabled=0, updated_at=CURRENT_TIMESTAMP WHERE id=?", (tid,))
        conn.commit()
        conn.close()
        return {"status": "disabled"}

    elif action == "run":
        tid = kwargs.get("task_id", "")
        if not tid:
            return {"error": "需要 task_id 参数"}
        conn = _get_conn()
        task = conn.execute("SELECT * FROM scheduled_tasks WHERE id=?", (tid,)).fetchone()
        conn.close()
        if not task:
            return {"error": f"任务不存在: {tid}"}
        task = dict(task)
        exit_code, output = _execute_task(task)
        # 更新
        conn2 = _get_conn()
        conn2.execute(
            "UPDATE scheduled_tasks SET last_run=CURRENT_TIMESTAMP, last_exit_code=?, last_result=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (exit_code, output, tid)
        )
        conn2.commit()
        conn2.close()
        _notify(
            f"{'✅' if exit_code == 0 else '❌'} 手动执行: {task['name']}",
            f"退出码: {exit_code}\n{output[:200]}"
        )
        return {"status": "executed", "exit_code": exit_code, "output": output[:500]}

    elif action == "start":
        if _scheduler_running:
            return {"status": "already_running", "pid": _scheduler_pid}
        t = threading.Thread(target=_scheduler_loop, daemon=True)
        t.start()
        time.sleep(0.3)
        return {"status": "started", "pid": _scheduler_pid, "check_interval": CHECK_INTERVAL}

    elif action == "stop":
        _scheduler_running = False
        return {"status": "stopped"}

    elif action == "status":
        return {
            "running": _scheduler_running,
            "pid": _scheduler_pid,
            "check_interval": CHECK_INTERVAL,
            "db_path": DB_PATH,
        }

    elif action == "test_schedule":
        schedule = kwargs.get("schedule", "")
        if not schedule:
            return {"error": "需要 schedule 参数"}
        next_run = parse_schedule(schedule)
        return {
            "schedule": schedule,
            "next_run": next_run.isoformat() if next_run else None,
            "next_label": _format_next({"schedule": schedule, "next_run": next_run.isoformat() if next_run else None}),
        }

    else:
        return {"error": f"未知 action: {action}",
                "supported": ["list","add","update","delete","enable","disable","run","start","stop","status","test_schedule"]}


def _format_next(task: dict) -> str:
    """格式化下次执行时间为人可读"""
    nr = task.get("next_run")
    if not nr:
        if task.get("schedule", "").startswith("once:"):
            return "已过期(单次)"
        return "待计算"
    try:
        from datetime import datetime
        dt = datetime.fromisoformat(str(nr).replace("Z", "+00:00"))
        now = datetime.now()
        diff = dt - now
        if diff.total_seconds() < 0:
            return "已过期"
        days = diff.days
        hours, rem = divmod(diff.seconds, 3600)
        mins = rem // 60
        parts = []
        if days: parts.append(f"{days}天")
        if hours: parts.append(f"{hours}时")
        if mins or not parts: parts.append(f"{mins}分")
        return f"{' '.join(parts)}后 ({dt.strftime('%m-%d %H:%M')})"
    except Exception:
        return str(nr)[:16]


def meta_toolkit_scheduler() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "toolkit_scheduler",
            "description": "定时任务管理器 — 增删改查定时任务、启动停止调度线程、测试调度表达式。\n"
                           "schedule 格式: once:ISO单次 / daily:HH:MM每天 / hourly:MM每小时 / interval:SEC间隔 / weekly:mon:HH:MM每周 / cron:分 时 日 月 周",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["list", "add", "update", "delete", "enable", "disable", "run", "start", "stop", "status", "test_schedule"],
                        "description": "list=列表, add=新增(需name/command/schedule), update=更新(需task_id), delete=删除, enable/disable=启停, run=立即执行, start/stop/status=调度线程, test_schedule=测试表达式"
                    },
                    "task_id": {"type": "string", "description": "[update/delete/enable/disable/run] 任务ID"},
                    "name": {"type": "string", "description": "[add/update] 任务名称"},
                    "command": {"type": "string", "description": "[add/update] 命令行"},
                    "schedule": {"type": "string", "description": "[add/update/test_schedule] 调度表达式"},
                    "enabled": {"type": "boolean", "description": "[update] 是否启用"},
                },
                "required": ["action"],
            },
        },
    }
