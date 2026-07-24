"""
CheckpointManager — Agent 执行状态持久化与崩溃恢复。

核心设计:
  - 将 Agent 执行状态（status, task, context, result）保存到 SQLite
  - 支持跨会话恢复 — Agent 崩溃后可自动重建
  - 基于时间的过期清理

用法:
    from tea_agent.multi_agent import checkpoint_manager

    # 保存检查点
    cpm = CheckpointManager()
    cpm.save(dict(
        agent_id='analyst-1',
        role='分析专家',
        task='审查 main.py',
        status='running',
        context={'file': 'main.py'},
    ))

    # 恢复
    cp = cpm.load('analyst-1')
    if cp and cp['status'] == 'running':
        print(f'发现中断的任务: {cp["task"]}')
        # 自动恢复执行
"""

import contextlib
import json
import logging
import sqlite3
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger("multi_agent.checkpoint")


class CheckpointManager:
    """
    Agent 检查点管理器 — 持久化 + 恢复。

    Thread-safe, 支持高频写入（去重 + 覆盖）。
    使用独立 SQLite 数据库，不与其他模块冲突。
    """

    _instances: dict[str, 'CheckpointManager'] = {}
    _lock = threading.Lock()

    def __init__(self, db_path: str | None = None, auto_cleanup: bool = True):
        """
        Args:
            db_path: SQLite 数据库路径，None=~/.tea_agent/checkpoints.db
            auto_cleanup: 初始化时自动清理过期检查点
        """
        self.db_path = db_path or str(
            Path.home() / '.tea_agent' / 'checkpoints.db'
        )
        self._local = threading.local()
        self._init_db()
        if auto_cleanup:
            self.cleanup()

    @classmethod
    def get_instance(cls, db_path: str | None = None) -> 'CheckpointManager':
        """获取共享单例（按 db_path 隔离）。"""
        key = db_path or 'default'
        if key not in cls._instances:
            with cls._lock:
                if key not in cls._instances:
                    cls._instances[key] = cls(db_path=db_path)
        return cls._instances[key]

    # ── 数据库连接 ──────────────────────────────────

    def _get_conn(self) -> sqlite3.Connection:
        """获取线程本地连接。"""
        if not hasattr(self._local, 'conn') or self._local.conn is None:
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self.db_path, timeout=10)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            self._local.conn = conn
        return self._local.conn

    def _init_db(self):
        """建表。"""
        conn = self._get_conn()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS checkpoints (
                agent_id    TEXT NOT NULL,
                role        TEXT NOT NULL DEFAULT '',
                goal        TEXT NOT NULL DEFAULT '',
                task        TEXT NOT NULL DEFAULT '',
                context     TEXT NOT NULL DEFAULT '{}',
                status      TEXT NOT NULL DEFAULT 'unknown',
                result      TEXT,
                error       TEXT,
                tool_calls  INTEGER DEFAULT 0,
                parent_id   TEXT DEFAULT '',
                trace_id    TEXT DEFAULT '',
                created_at  TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at  TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (agent_id, created_at)
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_cp_agent
            ON checkpoints(agent_id, updated_at DESC)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_cp_status
            ON checkpoints(status)
        """)
        conn.commit()

    # ── 核心 API ────────────────────────────────────

    def save(self, state: dict[str, Any]) -> str:
        """
        保存检查点。

        Args:
            state: 包含 agent_id, role, goal, task, context, status, result, error
                   tool_calls, parent_id, trace_id

        Returns:
            created_at (ISO 时间戳，作为版本标识)
        """
        agent_id = state.get('agent_id', '')
        if not agent_id:
            raise ValueError("agent_id is required")

        now = datetime.now().isoformat()
        conn = self._get_conn()

        conn.execute("""
            INSERT INTO checkpoints
                (agent_id, role, goal, task, context, status, result, error,
                 tool_calls, parent_id, trace_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            agent_id,
            state.get('role', ''),
            state.get('goal', ''),
            state.get('task', ''),
            json.dumps(state.get('context', {}), ensure_ascii=False),
            state.get('status', 'unknown'),
            state.get('result'),
            state.get('error'),
            state.get('tool_calls', 0),
            state.get('parent_id', ''),
            state.get('trace_id', ''),
            now,
            now,
        ))
        conn.commit()
        return now

    def load(self, agent_id: str) -> dict[str, Any] | None:
        """
        加载最新的检查点。

        Returns:
            最新的检查点 dict，或 None（无记录）
        """
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM checkpoints WHERE agent_id=? ORDER BY updated_at DESC LIMIT 1",
            (agent_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_dict(row)

    def load_by_status(self, status: str, limit: int = 10) -> list[dict[str, Any]]:
        """按状态查询检查点。"""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM checkpoints WHERE status=? ORDER BY updated_at DESC LIMIT ?",
            (status, limit),
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def list_recent(self, limit: int = 20) -> list[dict[str, Any]]:
        """列出最近的检查点。"""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM checkpoints ORDER BY updated_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def list_agents(self) -> list[str]:
        """列出所有有检查点的 Agent ID。"""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT DISTINCT agent_id FROM checkpoints ORDER BY agent_id"
        ).fetchall()
        return [r['agent_id'] for r in rows]

    def get_failed(self, limit: int = 10) -> list[dict[str, Any]]:
        """获取最近失败的检查点（用于自动恢复尝试）。"""
        return self.load_by_status('failed', limit)

    def get_interrupted(self, limit: int = 10) -> list[dict[str, Any]]:
        """
        获取中断的检查点（running 状态但已过时——说明进程崩溃）。
        判断条件: status='running' 且 updated_at > 30秒前
        """
        conn = self._get_conn()
        threshold = (datetime.now() - timedelta(seconds=30)).isoformat()
        rows = conn.execute(
            "SELECT * FROM checkpoints WHERE status=? AND updated_at < ? "
            "ORDER BY updated_at DESC LIMIT ?",
            ('running', threshold, limit),
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def update_status(self, agent_id: str, status: str, **extra):
        """更新最新检查点的状态。"""
        now = datetime.now().isoformat()
        conn = self._get_conn()
        updates = ["status=?", "updated_at=?"]
        params = [status, now]

        for key in ['result', 'error', 'tool_calls']:
            if key in extra:
                updates.append(f"{key}=?")
                params.append(extra[key])

        params.append(agent_id)
        conn.execute(
            f"UPDATE checkpoints SET {', '.join(updates)} "
            "WHERE agent_id=? AND updated_at=("
            "  SELECT MAX(updated_at) FROM checkpoints WHERE agent_id=?"
            ")",
            params + [agent_id],
        )
        conn.commit()

    def delete(self, agent_id: str):
        """删除指定 agent 的所有检查点。"""
        conn = self._get_conn()
        conn.execute("DELETE FROM checkpoints WHERE agent_id=?", (agent_id,))
        conn.commit()

    def cleanup(self, max_age_hours: int = 24):
        """清理超过指定时间的检查点。"""
        threshold = (datetime.now() - timedelta(hours=max_age_hours)).isoformat()
        conn = self._get_conn()
        deleted = conn.execute(
            "DELETE FROM checkpoints WHERE updated_at < ?",
            (threshold,),
        ).rowcount
        if deleted:
            logger.info(f"🧹 清理了 {deleted} 个过期检查点 (> {max_age_hours}h)")
        conn.commit()

    def count(self, status: str | None = None) -> int:
        """统计检查点数量。"""
        conn = self._get_conn()
        if status:
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM checkpoints WHERE status=?", (status,)
            ).fetchone()
        else:
            row = conn.execute("SELECT COUNT(*) as cnt FROM checkpoints").fetchone()
        return row['cnt'] if row else 0

    # ── 工具方法 ────────────────────────────────────

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        d = dict(row)
        # 解析 context JSON
        if isinstance(d.get('context'), str):
            with contextlib.suppress(json.JSONDecodeError, TypeError):
                d['context'] = json.loads(d['context'])
        return d

    def close(self):
        """关闭数据库连接。"""
        if hasattr(self._local, 'conn') and self._local.conn:
            self._local.conn.close()
            self._local.conn = None

    def __repr__(self):
        total = self.count()
        failed = self.count('failed')
        running = self.count('running')
        return f"CheckpointManager(total={total}, failed={failed}, running={running})"


# ── 模块级便利函数 ────────────────────────────

_default_cpm: CheckpointManager | None = None


def get_checkpoint_manager() -> CheckpointManager:
    """获取默认 CheckpointManager 单例。"""
    global _default_cpm
    if _default_cpm is None:
        _default_cpm = CheckpointManager.get_instance()
    return _default_cpm
