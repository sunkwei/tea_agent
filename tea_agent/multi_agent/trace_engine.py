"""
TraceEngine — Agent 执行轨迹追踪（Span-based Tracing）。

类似 OpenTelemetry 的轻量级追踪系统，记录 Agent 执行的完整调用链。

核心概念:
  Trace — 一次完整的任务执行
  Span  — 一个执行单元（Agent 执行、子任务、工具调用）

架构:
  TraceEngine (API)
      ├── Memory Buffer (实时)
      └── SQLite Persistence (持久化)

用法:
    from tea_agent.multi_agent import TraceEngine

    te = TraceEngine()

    # 1. 创建 trace
    trace_id = te.start_trace('analyst-1', '审查 main.py')

    # 2. 创建 span
    span_id = te.start_span(trace_id, None, '整体审查', 'analyst-1')

    # 3. 创建子 span
    sub_id = te.start_span(trace_id, span_id, '分析语法', 'analyst-1')
    # ... 执行 ...
    te.end_span(sub_id, 'completed', result='无语法问题', tool_calls=3)

    # 4. 结束根 span
    te.end_span(span_id, 'completed', result='审查完成', tool_calls=5)

    # 5. 查看完整 trace
    trace = te.get_trace(trace_id)
    print(json.dumps(trace, indent=2, ensure_ascii=False))
"""

import logging
import sqlite3
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger("multi_agent.trace")


class TraceSpan:
    """单个追踪跨度。"""
    def __init__(
        self,
        span_id: str,
        trace_id: str,
        parent_span_id: str | None,
        name: str,
        agent_id: str,
        agent_role: str = '',
        task: str = '',
    ):
        self.span_id = span_id
        self.trace_id = trace_id
        self.parent_span_id = parent_span_id
        self.name = name
        self.agent_id = agent_id
        self.agent_role = agent_role
        self.task = task
        self.start_time = time.time()
        self.end_time: float | None = None
        self.duration_ms: float | None = None
        self.status = 'started'
        self.result: str | None = None
        self.error: str | None = None
        self.tool_calls = 0
        self.children: list[TraceSpan] = []

    def end(self, status: str = 'completed', result: str | None = None,
            error: str | None = None, tool_calls: int = 0):
        self.end_time = time.time()
        self.duration_ms = round((self.end_time - self.start_time) * 1000, 2)
        self.status = status
        self.result = result
        self.error = error
        self.tool_calls = tool_calls

    def to_dict(self, include_children: bool = True) -> dict:
        d = {
            'span_id': self.span_id,
            'trace_id': self.trace_id,
            'parent_span_id': self.parent_span_id,
            'name': self.name,
            'agent_id': self.agent_id,
            'agent_role': self.agent_role,
            'task': self.task[:200] if self.task else '',
            'start_time': datetime.fromtimestamp(self.start_time).isoformat(),
            'end_time': datetime.fromtimestamp(self.end_time).isoformat() if self.end_time else None,
            'duration_ms': self.duration_ms,
            'status': self.status,
            'result': self.result[:500] if self.result else None,
            'error': self.error[:500] if self.error else None,
            'tool_calls': self.tool_calls,
        }
        if include_children and self.children:
            d['children'] = [c.to_dict() for c in self.children]
        return d

    def __repr__(self):
        return (
            f"TraceSpan({self.name}, agent={self.agent_id}, "
            f"status={self.status}, duration_ms={self.duration_ms})"
        )


class TraceEngine:
    """
    轨迹追踪引擎 — Span-based, 内存缓冲区 + SQLite 持久化。

    Thread-safe。
    """

    _instances: dict[str, 'TraceEngine'] = {}
    _lock = threading.Lock()

    def __init__(self, db_path: str | None = None, auto_cleanup: bool = True):
        self.db_path = db_path or str(
            Path.home() / '.tea_agent' / 'checkpoints.db'
        )
        self._local = threading.local()
        # 内存缓冲区: {trace_id: {span_id: TraceSpan}}
        self._buffer: dict[str, dict[str, TraceSpan]] = {}
        self._buffer_lock = threading.Lock()
        self._init_db()
        if auto_cleanup:
            self.cleanup()

    @classmethod
    def get_instance(cls, db_path: str | None = None) -> 'TraceEngine':
        """获取共享单例。"""
        key = db_path or 'default'
        if key not in cls._instances:
            with cls._lock:
                if key not in cls._instances:
                    cls._instances[key] = cls(db_path=db_path)
        return cls._instances[key]

    # ── 数据库 ──────────────────────────────────────

    def _get_conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, 'conn') or self._local.conn is None:
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self.db_path, timeout=10)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            self._local.conn = conn
        return self._local.conn

    def _init_db(self):
        conn = self._get_conn()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS traces (
                trace_id    TEXT PRIMARY KEY,
                root_span   TEXT NOT NULL,
                agent_id    TEXT NOT NULL DEFAULT '',
                agent_role  TEXT NOT NULL DEFAULT '',
                task        TEXT NOT NULL DEFAULT '',
                status      TEXT NOT NULL DEFAULT 'started',
                total_duration_ms REAL DEFAULT 0,
                total_tool_calls INTEGER DEFAULT 0,
                span_count  INTEGER DEFAULT 0,
                created_at  TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS spans (
                span_id     TEXT NOT NULL,
                trace_id    TEXT NOT NULL,
                parent_span_id TEXT,
                name        TEXT NOT NULL,
                agent_id    TEXT NOT NULL DEFAULT '',
                agent_role  TEXT NOT NULL DEFAULT '',
                task        TEXT NOT NULL DEFAULT '',
                start_time  TEXT NOT NULL,
                end_time    TEXT,
                duration_ms REAL,
                status      TEXT NOT NULL DEFAULT 'started',
                result      TEXT,
                error       TEXT,
                tool_calls  INTEGER DEFAULT 0,
                PRIMARY KEY (trace_id, span_id)
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_spans_agent
            ON spans(agent_id, start_time DESC)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_spans_trace
            ON spans(trace_id, parent_span_id)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_traces_agent
            ON traces(agent_id, updated_at DESC)
        """)
        conn.commit()

    # ── 核心 API ────────────────────────────────────

    def start_trace(
        self,
        agent_id: str,
        task: str,
        agent_role: str = '',
        trace_id: str | None = None,
    ) -> str:
        """创建新的 Trace（根 Span）。"""
        tid = trace_id or uuid.uuid4().hex[:12]
        root = TraceSpan(
            span_id=f"root-{tid}",
            trace_id=tid,
            parent_span_id=None,
            name='root',
            agent_id=agent_id,
            agent_role=agent_role,
            task=task,
        )

        with self._buffer_lock:
            self._buffer[tid] = {root.span_id: root}

        # 写入 DB
        conn = self._get_conn()
        now = datetime.now().isoformat()
        conn.execute(
            "INSERT OR REPLACE INTO traces "
            "(trace_id, root_span, agent_id, agent_role, task, status, "
            " total_duration_ms, total_tool_calls, span_count, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (tid, root.span_id, agent_id, agent_role, task[:500],
             'started', 0, 0, 1, now, now),
        )
        self._save_span(root)
        conn.commit()

        return tid

    def start_span(
        self,
        trace_id: str,
        parent_span_id: str | None,
        name: str,
        agent_id: str,
        agent_role: str = '',
        task: str = '',
        span_id: str | None = None,
    ) -> str:
        """创建子 Span。"""
        sid = span_id or uuid.uuid4().hex[:12]
        span = TraceSpan(
            span_id=sid,
            trace_id=trace_id,
            parent_span_id=parent_span_id,
            name=name,
            agent_id=agent_id,
            agent_role=agent_role,
            task=task,
        )

        with self._buffer_lock:
            if trace_id not in self._buffer:
                self._buffer[trace_id] = {}
            self._buffer[trace_id][sid] = span

            # 挂到父 span
            if parent_span_id and parent_span_id in self._buffer[trace_id]:
                self._buffer[trace_id][parent_span_id].children.append(span)

        self._save_span(span)

        # 更新 trace 统计
        conn = self._get_conn()
        conn.execute(
            "UPDATE traces SET span_count=span_count+1, updated_at=? WHERE trace_id=?",
            (datetime.now().isoformat(), trace_id),
        )
        conn.commit()

        return sid

    def end_span(
        self,
        span_id: str,
        status: str = 'completed',
        result: str | None = None,
        error: str | None = None,
        tool_calls: int = 0,
    ):
        """结束 Span。"""
        span = self._find_span(span_id)
        if not span:
            logger.warning(f"⚠️ Span {span_id} 未找到")
            return

        span.end(status=status, result=result, error=error, tool_calls=tool_calls)

        # 更新 DB
        conn = self._get_conn()
        now = datetime.now().isoformat()
        conn.execute(
            "UPDATE spans SET end_time=?, duration_ms=?, status=?, result=?, "
            "error=?, tool_calls=? WHERE trace_id=? AND span_id=?",
            (now, span.duration_ms, status, result, error, tool_calls,
             span.trace_id, span_id),
        )

        # 如果是根 span，更新 trace 状态
        if span.parent_span_id is None or span_id.startswith('root-'):
            conn.execute(
                "UPDATE traces SET status=?, total_duration_ms=?, "
                "total_tool_calls=?, updated_at=? WHERE trace_id=?",
                (status, span.duration_ms or 0, tool_calls, now, span.trace_id),
            )

        conn.commit()

    def get_trace(self, trace_id: str) -> dict[str, Any] | None:
        """获取完整 Trace 树。"""
        conn = self._get_conn()
        trace_row = conn.execute(
            "SELECT * FROM traces WHERE trace_id=?", (trace_id,)
        ).fetchone()
        if not trace_row:
            return None

        trace = dict(trace_row)

        # 加载所有 spans
        span_rows = conn.execute(
            "SELECT * FROM spans WHERE trace_id=? ORDER BY start_time",
            (trace_id,),
        ).fetchall()

        spans = [dict(r) for r in span_rows]

        # 构建树
        span_map = {s['span_id']: s for s in spans}
        root = None
        for s in spans:
            s['children'] = []
            if s['parent_span_id'] is None or s['parent_span_id'] == '':
                root = s
            elif s['parent_span_id'] in span_map:
                span_map[s['parent_span_id']]['children'].append(s)

        trace['spans'] = root
        return trace

    def get_agent_traces(
        self, agent_id: str, limit: int = 20
    ) -> list[dict[str, Any]]:
        """获取指定 Agent 的所有 Trace。"""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM traces WHERE agent_id=? ORDER BY updated_at DESC LIMIT ?",
            (agent_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def list_traces(
        self, status: str | None = None, limit: int = 20
    ) -> list[dict[str, Any]]:
        """列出所有 Traces。"""
        conn = self._get_conn()
        if status:
            rows = conn.execute(
                "SELECT * FROM traces WHERE status=? ORDER BY updated_at DESC LIMIT ?",
                (status, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM traces ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_stats(self) -> dict[str, Any]:
        """获取聚合统计。"""
        conn = self._get_conn()
        stats = {'total_traces': 0, 'total_spans': 0, 'by_status': {}}

        row = conn.execute("SELECT COUNT(*) as c FROM traces").fetchone()
        stats['total_traces'] = row['c'] if row else 0

        row = conn.execute("SELECT COUNT(*) as c FROM spans").fetchone()
        stats['total_spans'] = row['c'] if row else 0

        for s in ['started', 'completed', 'failed']:
            row = conn.execute(
                "SELECT COUNT(*) as c FROM traces WHERE status=?", (s,)
            ).fetchone()
            stats['by_status'][s] = row['c'] if row else 0

        # 平均耗时
        row = conn.execute(
            "SELECT AVG(total_duration_ms) as avg FROM traces "
            "WHERE status IN ('completed', 'failed')"
        ).fetchone()
        stats['avg_duration_ms'] = round(row['avg'], 2) if row and row['avg'] else 0

        return stats

    def export(self, limit: int = 50) -> dict:
        """导出最近 traces 为 JSON。"""
        traces = self.list_traces(limit=limit)
        result = []
        for t in traces:
            full = self.get_trace(t['trace_id'])
            if full:
                result.append(full)
        return {
            'exported_at': datetime.now().isoformat(),
            'count': len(result),
            'traces': result,
        }

    def cleanup(self, max_age_hours: int = 72):
        """清理旧 traces。"""
        threshold = (datetime.now()).timestamp() - max_age_hours * 3600
        threshold_iso = datetime.fromtimestamp(threshold).isoformat()
        conn = self._get_conn()

        # 删除旧 spans
        deleted_spans = conn.execute(
            "DELETE FROM spans WHERE trace_id IN "
            "(SELECT trace_id FROM traces WHERE updated_at < ?)",
            (threshold_iso,),
        ).rowcount

        # 删除旧 traces
        deleted_traces = conn.execute(
            "DELETE FROM traces WHERE updated_at < ?",
            (threshold_iso,),
        ).rowcount

        if deleted_traces:
            logger.info(
                f"🧹 清理了 {deleted_traces} traces / {deleted_spans} spans"
                f" (> {max_age_hours}h)"
            )
        conn.commit()

    # ── 内部方法 ────────────────────────────────────

    def _save_span(self, span: TraceSpan):
        """持久化 span 到 DB。"""
        conn = self._get_conn()
        conn.execute(
            "INSERT OR REPLACE INTO spans "
            "(span_id, trace_id, parent_span_id, name, agent_id, agent_role, "
            " task, start_time, end_time, duration_ms, status, result, error, "
            " tool_calls) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                span.span_id,
                span.trace_id,
                span.parent_span_id,
                span.name,
                span.agent_id,
                span.agent_role,
                span.task[:500],
                datetime.fromtimestamp(span.start_time).isoformat(),
                datetime.fromtimestamp(span.end_time).isoformat() if span.end_time else None,
                span.duration_ms,
                span.status,
                span.result,
                span.error,
                span.tool_calls,
            ),
        )
        conn.commit()

    def _find_span(self, span_id: str) -> TraceSpan | None:
        """在所有缓冲区内查找 span。"""
        with self._buffer_lock:
            for _tid, spans in self._buffer.items():
                if span_id in spans:
                    return spans[span_id]
        return None

    # ── 生命周期 ────────────────────────────────────

    def close(self):
        if hasattr(self._local, 'conn') and self._local.conn:
            self._local.conn.close()
            self._local.conn = None

    def clear_buffer(self):
        """清空内存缓冲区（不影响 DB）。"""
        with self._buffer_lock:
            self._buffer.clear()


# ── 模块级便利函数 ────────────────────────────

_default_te: TraceEngine | None = None


def get_trace_engine() -> TraceEngine:
    """获取默认 TraceEngine 单例。"""
    global _default_te
    if _default_te is None:
        _default_te = TraceEngine.get_instance()
    return _default_te
