"""
PatternMarket — Agent 模式市场（可复用模式仓库）。

模式（Pattern）是可复用的 Agent 配置模板，包含角色、目标、背景故事、
工具白名单、标签等。支持 CRUD、搜索、推荐、实例化。

核心概念:
  Pattern — Agent 配置模板（JSON 序列化，存 SQLite）
  Market  — 模式仓库（CRUD + 搜索 + 推荐）
  Instantiate — 从模式创建 RoleAgent 实例

注意: 与 CheckpointManager / TraceEngine 共享同一个 DB。
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import uuid
from datetime import datetime

logger = logging.getLogger(__name__)

# ── 默认内置模式 ─────────────────────────────

BUILTIN_PATTERNS = [
    {
        "name": "代码审查专家",
        "role": "资深代码审查员",
        "goal": "审查代码质量，识别设计问题和代码坏味道",
        "backstory": "你拥有 15 年软件架构经验，精通各种设计模式和重构技术。",
        "tools": ["toolkit_exec", "toolkit_file", "toolkit_search", "toolkit_lsp"],
        "tags": ["code-review", "analysis", "quality"],
    },
    {
        "name": "高级工程师",
        "role": "高级软件工程师",
        "goal": "高效实现功能需求和代码修改",
        "backstory": "你擅长编写高质量、可维护的 Python 代码，熟悉 SOLID 原则。",
        "tools": ["toolkit_exec", "toolkit_file", "toolkit_edit", "toolkit_diff_edit"],
        "tags": ["development", "coding", "refactor"],
    },
    {
        "name": "测试工程师",
        "role": "专业测试工程师",
        "goal": "编写全面的测试用例，确保代码质量",
        "backstory": "你精通 pytest 和各种测试技术，包括单元测试和 Mock。",
        "tools": ["toolkit_exec", "toolkit_file", "toolkit_run_tests"],
        "tags": ["testing", "quality", "pytest"],
    },
    {
        "name": "分析专家",
        "role": "深度分析专家",
        "goal": "深入分析代码库，提供全面的架构审查报告",
        "backstory": "你擅长代码审查和架构分析，能快速理解大型代码库。",
        "tools": ["toolkit_explr", "toolkit_code_review", "toolkit_file", "toolkit_search"],
        "tags": ["analysis", "architecture", "review"],
    },
]

# ── 模块级便利函数 ────────────────────────────

_default_market = None


def get_pattern_market():
    """获取默认 PatternMarket 单例。"""
    global _default_market
    if _default_market is None:
        _default_market = PatternMarket.get_instance()
    return _default_market


# ── 预定义工具集 ──────────────────────────────

COMMON_TOOLS = {
    "code": ["toolkit_exec", "toolkit_file", "toolkit_edit", "toolkit_diff_edit", "toolkit_search"],
    "analysis": ["toolkit_exec", "toolkit_file", "toolkit_search", "toolkit_code_review"],
    "testing": ["toolkit_exec", "toolkit_file", "toolkit_run_tests"],
    "all": None,  # 全部可用
}


class PatternMarket:
    """
    Agent 模式市场 — 可复用模式仓库。

    存储、搜索、推荐、实例化 Agent 配置模板。
    与 CheckpointManager / TraceEngine 共享同一 SQLite 数据库。
    """

    _instances = {}
    _inst_lock = threading.RLock()
    DEFAULT_DB = "checkpoint.db"  # 共享 DB

    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or self.DEFAULT_DB
        self._lock = threading.RLock()
        self._init_db()
        self._seed_builtins()

    @classmethod
    def get_instance(cls, db_path: str | None = None) -> PatternMarket:
        """获取单例实例。"""
        key = db_path or cls.DEFAULT_DB
        with cls._inst_lock:
            if key not in cls._instances:
                cls._instances[key] = cls(db_path)
            return cls._instances[key]

    @classmethod
    def reset_instance(cls):
        """重置单例（测试用）。"""
        with cls._inst_lock:
            cls._instances.clear()

    # ── 数据库 ──────────────────────────────────

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _init_db(self):
        conn = self._get_conn()
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS patterns (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    role TEXT NOT NULL,
                    goal TEXT NOT NULL DEFAULT '',
                    backstory TEXT NOT NULL DEFAULT '',
                    tools TEXT NOT NULL DEFAULT '[]',
                    tags TEXT NOT NULL DEFAULT '[]',
                    description TEXT NOT NULL DEFAULT '',
                    version TEXT NOT NULL DEFAULT '1.0.0',
                    usage_count INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_patterns_name ON patterns(name)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_patterns_tags ON patterns(tags)
            """)
            conn.commit()
        finally:
            conn.close()

    def _seed_builtins(self):
        """插入内置模式（已存在的跳过）。"""
        conn = self._get_conn()
        try:
            now = datetime.now().isoformat()
            for p in BUILTIN_PATTERNS:
                existing = conn.execute(
                    "SELECT id FROM patterns WHERE name = ?", (p["name"],)
                ).fetchone()
                if not existing:
                    pid = f"builtin-{p['name']}"
                    conn.execute(
                        """INSERT INTO patterns
                           (id, name, role, goal, backstory, tools, tags, description, version, usage_count, created_at, updated_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, '1.0.0', 0, ?, ?)""",
                        (
                            pid,
                            p["name"],
                            p["role"],
                            p["goal"],
                            p.get("backstory", ""),
                            json.dumps(p["tools"]),
                            json.dumps(p.get("tags", [])),
                            p.get("description", p["goal"]),
                            now,
                            now,
                        ),
                    )
            conn.commit()
        finally:
            conn.close()

    # ── CRUD ────────────────────────────────────

    def save(self, pattern: dict) -> str:
        """
        保存一个模式（新建或更新）。

        Args:
            pattern: 模式字典，至少需要 'name' 和 'role' 字段。
                     如果包含 'id' 则更新，否则新建。

        Returns:
            模式 ID
        """
        pid = pattern.get("id") or f"pat-{uuid.uuid4().hex[:12]}"
        now = datetime.now().isoformat()

        with self._lock:
            conn = self._get_conn()
            try:
                existing = conn.execute(
                    "SELECT id FROM patterns WHERE id = ?", (pid,)
                ).fetchone()

                if existing:
                    # 更新
                    conn.execute(
                        """UPDATE patterns SET
                           name=?, role=?, goal=?, backstory=?, tools=?,
                           tags=?, description=?, version=?, updated_at=?
                           WHERE id=?""",
                        (
                            pattern.get("name", ""),
                            pattern.get("role", ""),
                            pattern.get("goal", ""),
                            pattern.get("backstory", ""),
                            json.dumps(pattern.get("tools", []), ensure_ascii=False),
                            json.dumps(pattern.get("tags", []), ensure_ascii=False),
                            pattern.get("description", ""),
                            pattern.get("version", "1.0.0"),
                            now,
                            pid,
                        ),
                    )
                else:
                    conn.execute(
                        """INSERT INTO patterns
                           (id, name, role, goal, backstory, tools, tags, description, version, usage_count, created_at, updated_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)""",
                        (
                            pid,
                            pattern.get("name", ""),
                            pattern.get("role", ""),
                            pattern.get("goal", ""),
                            pattern.get("backstory", ""),
                            json.dumps(pattern.get("tools", []), ensure_ascii=False),
                            json.dumps(pattern.get("tags", []), ensure_ascii=False),
                            pattern.get("description", ""),
                            pattern.get("version", "1.0.0"),
                            now,
                            now,
                        ),
                    )
                conn.commit()
            finally:
                conn.close()

        return pid

    def get(self, pattern_id: str) -> dict | None:
        """获取模式详情。"""
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM patterns WHERE id = ?", (pattern_id,)
            ).fetchone()
            if not row:
                return None
            return self._row_to_dict(row)
        finally:
            conn.close()

    def get_by_name(self, name: str) -> dict | None:
        """按名称查找模式。"""
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM patterns WHERE name = ?", (name,)
            ).fetchone()
            if not row:
                return None
            return self._row_to_dict(row)
        finally:
            conn.close()

    def search(self, query: str = "", tags: list[str] | None = None, limit: int = 20) -> list[dict]:
        """
        搜索模式。

        Args:
            query: 关键词（模糊匹配 name/role/goal）
            tags: 标签过滤（OR 匹配）
            limit: 最大返回数

        Returns:
            模式列表
        """
        conn = self._get_conn()
        try:
            sql = "SELECT * FROM patterns WHERE 1=1"
            params = []

            if query:
                sql += " AND (name LIKE ? OR role LIKE ? OR goal LIKE ? OR description LIKE ?)"
                like = f"%{query}%"
                params.extend([like, like, like, like])

            if tags:
                tag_conditions = []
                for tag in tags:
                    tag_conditions.append("tags LIKE ?")
                    params.append(f"%{tag}%")
                sql += " AND (" + " OR ".join(tag_conditions) + ")"

            sql += " ORDER BY usage_count DESC, updated_at DESC LIMIT ?"
            params.append(limit)

            rows = conn.execute(sql, params).fetchall()
            return [self._row_to_dict(r) for r in rows]
        finally:
            conn.close()

    def recommend(self, task: str = "", limit: int = 5) -> list[dict]:
        """
        推荐模式（基于任务描述语义匹配）。

        当前使用关键词匹配，后续可升级为向量搜索。

        Args:
            task: 任务描述
            limit: 推荐数量

        Returns:
            匹配度最高的模式列表
        """
        if not task:
            return self.search(limit=limit)

        # 提取关键词
        keywords = [w.strip() for w in task.replace(",", " ").replace("，", " ").split()
                    if len(w.strip()) > 1]

        conn = self._get_conn()
        try:
            rows = conn.execute("SELECT * FROM patterns ORDER BY usage_count DESC").fetchall()
            patterns = [self._row_to_dict(r) for r in rows]

            # 评分：每个关键词匹配加分
            scored = []
            for p in patterns:
                score = 0
                text = f"{p['name']} {p['role']} {p['goal']} {p['description']} {' '.join(p['tags'])}"
                for kw in keywords:
                    if kw.lower() in text.lower():
                        score += 1
                scored.append((score, p))

            scored.sort(key=lambda x: -x[0])
            return [p for s, p in scored[:limit]]
        finally:
            conn.close()

    def delete(self, pattern_id: str) -> bool:
        """删除模式（内置模式不可删除）。"""
        if pattern_id.startswith("builtin-"):
            logger.warning(f"⚠️ 内置模式不可删除: {pattern_id}")
            return False

        conn = self._get_conn()
        try:
            cur = conn.execute("DELETE FROM patterns WHERE id = ?", (pattern_id,))
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    def increment_usage(self, pattern_id: str):
        """增加模式使用计数。"""
        conn = self._get_conn()
        try:
            conn.execute(
                "UPDATE patterns SET usage_count = usage_count + 1 WHERE id = ?",
                (pattern_id,),
            )
            conn.commit()
        finally:
            conn.close()

    # ── 实例化 ──────────────────────────────────

    def instantiate(self, pattern_id: str, **overrides) -> RoleAgent | None:  # noqa: F821
        """
        从模式创建 RoleAgent 实例。

        Args:
            pattern_id: 模式 ID
            **overrides: 覆盖字段（role, goal, backstory, tools, verbose 等）

        Returns:
            RoleAgent 实例，如果模式不存在则返回 None
        """
        pattern = self.get(pattern_id)
        if not pattern:
            logger.error(f"⚠️ 模式不存在: {pattern_id}")
            return None

        from .role_agent import RoleAgent

        agent = RoleAgent(
            role=overrides.get("role", pattern["role"]),
            goal=overrides.get("goal", pattern["goal"]),
            backstory=overrides.get("backstory", pattern.get("backstory", "")),
            tools=overrides.get("tools", pattern.get("tools", [])),
            verbose=overrides.get("verbose", True),
        )
        self.increment_usage(pattern_id)
        logger.info(f"🎭 从模式实例化: {pattern['name']} -> {agent.agent_id}")
        return agent

    def instantiate_by_name(self, name: str, **overrides) -> RoleAgent | None:  # noqa: F821
        """按名称实例化模式。"""
        pattern = self.get_by_name(name)
        if not pattern:
            return None
        return self.instantiate(pattern["id"], **overrides)

    # ── 统计 ────────────────────────────────────

    def list_all(self, limit: int = 100) -> list[dict]:
        """列出所有模式。"""
        return self.search(limit=limit)

    def count(self) -> int:
        """模式总数。"""
        conn = self._get_conn()
        try:
            row = conn.execute("SELECT COUNT(*) as cnt FROM patterns").fetchone()
            return row["cnt"] if row else 0
        finally:
            conn.close()

    def stats(self) -> dict:
        """统计信息。"""
        conn = self._get_conn()
        try:
            total = conn.execute("SELECT COUNT(*) as cnt FROM patterns").fetchone()["cnt"]
            builtin = conn.execute(
                "SELECT COUNT(*) as cnt FROM patterns WHERE id LIKE 'builtin-%'"
            ).fetchone()["cnt"]
            total_usage = conn.execute(
                "SELECT COALESCE(SUM(usage_count), 0) as u FROM patterns"
            ).fetchone()["u"]
            return {
                "total": total,
                "builtin": builtin,
                "custom": total - builtin,
                "total_usage": total_usage,
            }
        finally:
            conn.close()

    # ── 内置辅助 ────────────────────────────────

    def _row_to_dict(self, row: sqlite3.Row) -> dict:
        d = dict(row)
        d["tools"] = json.loads(d.get("tools", "[]"))
        d["tags"] = json.loads(d.get("tags", "[]"))
        return d

    def __repr__(self):
        s = self.stats()
        return f"PatternMarket(total={s['total']}, builtin={s['builtin']}, custom={s['custom']}, usage={s['total_usage']})"
