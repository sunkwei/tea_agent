"""
# @2026-06-07 gen by deepseek-v4-pro, SymbolIndex — 持久化符号索引系统
基于 ts_analyzer 的 AST 解析 + SQLite 持久化 + 关键词搜索。

注：原「嵌入向量搜索」已移除 —— 向量能力整体下线，语义查询改由
符号名/关键词匹配承担（见 ``search_natural``）。
"""

import contextlib
import hashlib
import json
import logging
import os
import re
import sqlite3
from pathlib import Path

logger = logging.getLogger("SymbolIndex")


class SymbolIndex:
    """持久化符号索引 — 全量扫描、增量更新、关键词搜索。"""

    def __init__(self, project_root: str, db_path: str | None = None):
        self.project_root = Path(project_root).resolve()
        self.db_path = db_path or str(self.project_root / ".tea_agent_run" / "symbol_index.db")
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._init_tables()

    def _init_tables(self):
        c = self._conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS symbols (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_path TEXT NOT NULL,
                name TEXT NOT NULL,
                kind TEXT NOT NULL,
                line INTEGER NOT NULL,
                col INTEGER DEFAULT 0,
                end_line INTEGER DEFAULT 0,
                parent TEXT DEFAULT '',
                params TEXT DEFAULT '[]',
                docstring TEXT DEFAULT '',
                module TEXT DEFAULT '',
                UNIQUE(file_path, name, kind, line)
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS calls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                caller_file TEXT NOT NULL,
                caller_name TEXT NOT NULL,
                caller_line INTEGER NOT NULL,
                callee_name TEXT NOT NULL,
                call_type TEXT DEFAULT 'direct'
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS imports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_path TEXT NOT NULL,
                module TEXT NOT NULL,
                names TEXT DEFAULT '[]',
                line INTEGER NOT NULL
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS file_tracking (
                file_path TEXT PRIMARY KEY,
                mtime REAL NOT NULL,
                hash TEXT NOT NULL,
                last_indexed TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self._conn.commit()
        c.close()

    # ── 索引构建 ──

    def build_index(self, force: bool = False) -> dict:
        from tea_agent.lsp.ts_analyzer import parse_file
        py_files = list(self.project_root.rglob("*.py"))
        scanned = indexed = skipped = errors = 0
        for pf in py_files:
            pf_str = str(pf)
            if any(s in pf_str for s in (".tea_agent_run", "__pycache__", ".git", "build", "dist", "node_modules")):
                continue
            rel = os.path.relpath(pf_str, str(self.project_root)).replace("\\", "/")
            scanned += 1
            if not force and not self._is_file_changed(pf_str):
                skipped += 1
                continue
            parsed = parse_file(pf_str)
            if not parsed:
                errors += 1
                continue
            self._clear_file_data(pf_str)
            module = rel.replace("/", ".").replace(".py", "")
            for func in parsed.get("functions", []):
                self._insert_symbol(rel, func["name"], "function", func["line"],
                                    params=json.dumps(func.get("params", [])),
                                    docstring=func.get("docstring", ""), module=module,
                                    calls=func.get("calls", []))
                indexed += 1
            for cls in parsed.get("classes", []):
                self._insert_symbol(rel, cls["name"], "class", cls["line"],
                                    docstring=cls.get("docstring", ""), module=module)
                indexed += 1
                for m in cls.get("methods", []):
                    self._insert_symbol(rel, m["name"], "method", m["line"],
                                        parent=cls["name"],
                                        params=json.dumps(m.get("params", [])),
                                        docstring=m.get("docstring", ""), module=module,
                                        calls=m.get("calls", []))
                    indexed += 1
            for imp in parsed.get("imports", []):
                c = self._conn.cursor()
                c.execute("INSERT INTO imports (file_path, module, names, line) VALUES (?, ?, ?, ?)",
                          (rel, imp.get("module", ""), json.dumps(imp.get("names", [])), imp.get("line", 0)))
                self._conn.commit()
                c.close()
            self._record_file(pf_str)
        return {"scanned": scanned, "indexed": indexed, "skipped": skipped,
                "errors": errors, "total_symbols": self.get_symbol_count()}

    def _is_file_changed(self, file_path: str) -> bool:
        c = self._conn.cursor()
        c.execute("SELECT mtime, hash FROM file_tracking WHERE file_path = ?", (file_path,))
        row = c.fetchone()
        c.close()
        if not row:
            return True
        try:
            cm = os.path.getmtime(file_path)
            if abs(cm - row["mtime"]) > 0.01:
                return True
            ch = hashlib.md5(open(file_path, "rb").read()).hexdigest()[:16]
            if ch != row["hash"]:
                return True
        except Exception:
            return True
        return False

    def _record_file(self, file_path: str):
        c = self._conn.cursor()
        mtime = os.path.getmtime(file_path)
        fhash = hashlib.md5(open(file_path, "rb").read()).hexdigest()[:16]
        c.execute("INSERT OR REPLACE INTO file_tracking (file_path, mtime, hash, last_indexed) VALUES (?, ?, ?, datetime('now'))",
                  (file_path, mtime, fhash))
        self._conn.commit()
        c.close()

    def _clear_file_data(self, file_path: str):
        c = self._conn.cursor()
        rel = os.path.relpath(file_path, str(self.project_root)).replace("\\", "/")
        # 兼容绝对路径和相对路径存储
        c.execute("DELETE FROM symbols WHERE file_path IN (?, ?)", (rel, file_path))
        c.execute("DELETE FROM calls WHERE caller_file IN (?, ?)", (rel, file_path))
        c.execute("DELETE FROM imports WHERE file_path IN (?, ?)", (rel, file_path))
        self._conn.commit()
        c.close()

    def _insert_symbol(self, file_path: str, name: str, kind: str, line: int,
                        parent: str = "", params: str = "[]", docstring: str = "",
                        module: str = "", calls: list = None):
        c = self._conn.cursor()
        try:
            c.execute("INSERT OR IGNORE INTO symbols (file_path, name, kind, line, parent, params, docstring, module) "
                      "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                      (file_path, name, kind, line, parent, params, docstring, module))
            if calls:
                for callee in calls:
                    c.execute("INSERT INTO calls (caller_file, caller_name, caller_line, callee_name) VALUES (?, ?, ?, ?)",
                              (file_path, name, line, callee))
            self._conn.commit()
        except sqlite3.Error as e:
            logger.error(f"Insert symbol failed {file_path}:{name}: {e}")
        except Exception as e:
            logger.error(f"Unexpected error inserting symbol {file_path}:{name}: {e}")
        finally:
            c.close()

    # ── 查询 ──

    def search_by_name(self, query: str, limit: int = 20) -> list[dict]:
        c = self._conn.cursor()
        escaped = query.replace("%", r"\%").replace("_", r"\_")
        c.execute("SELECT * FROM symbols WHERE name LIKE ? ESCAPE '\\' ORDER BY kind, name LIMIT ?",
                  (f"%{escaped}%", limit))
        rows = [dict(r) for r in c.fetchall()]
        c.close()
        return rows

    def search_by_file(self, file_path: str) -> list[dict]:
        c = self._conn.cursor()
        rel = file_path.replace("\\", "/")
        c.execute("SELECT * FROM symbols WHERE file_path = ? ORDER BY line", (rel,))
        rows = [dict(r) for r in c.fetchall()]
        c.close()
        return rows

    def get_callers(self, symbol_name: str, limit: int = 50) -> list[dict]:
        c = self._conn.cursor()
        c.execute("SELECT * FROM calls WHERE callee_name = ? ORDER BY caller_file, caller_line LIMIT ?",
                  (symbol_name, limit))
        rows = [dict(r) for r in c.fetchall()]
        c.close()
        return rows

    def get_callees(self, name: str, file_path: str = "") -> list[dict]:
        c = self._conn.cursor()
        if file_path:
            c.execute("SELECT * FROM calls WHERE caller_name = ? AND caller_file = ? ORDER BY callee_name",
                      (name, file_path))
        else:
            c.execute("SELECT * FROM calls WHERE caller_name = ? ORDER BY callee_name", (name,))
        rows = [dict(r) for r in c.fetchall()]
        c.close()
        return rows

    def search_natural(self, query: str, top_k: int = 10) -> list[dict]:
        """按查询串搜索符号（关键词匹配；替代原向量语义搜索）。

        打分（纯确定性，无网络、无向量、无额外依赖）：
        - 符号名与 query 完全相同 +1000；符号名整体包含 query +500
        - query 的每个 token（按非标识符字符切分）在 name 命中 +60
        - token 在 parent 命中 +25、在 docstring 命中 +20

        ``similarity`` 字段为归一化分值（score/1000，上限 1.0），保持与旧调用方
        的字段契约；排序优先分值、同分取更短的符号名（越短越可能是本体）。

        Args:
            query: 查询串（符号名或其片段）
            top_k: 返回条数上限

        Returns:
            [{id,name,kind,file_path,line,docstring,parent,similarity}, ...]
        """
        if not query or not query.strip():
            return []
        raw = query.strip()
        tokens = [t for t in re.split(r"[^0-9A-Za-z_\u4e00-\u9fff]+", raw) if t] or [raw]
        low = raw.lower()

        c = self._conn.cursor()
        c.execute("SELECT id, name, kind, file_path, line, docstring, parent FROM symbols")
        rows = c.fetchall()
        c.close()

        scored: list[dict] = []
        for row in rows:
            d = dict(row)
            lname = (d.get("name") or "").lower()
            doc = (d.get("docstring") or "").lower()
            parent = (d.get("parent") or "").lower()
            score = 0.0
            if lname == low:
                score += 1000.0
            elif low in lname:
                score += 500.0
            for t in tokens:
                lt = t.lower()
                if lt in lname:
                    score += 60.0
                if lt in parent:
                    score += 25.0
                if lt in doc:
                    score += 20.0
            if score <= 0:
                continue
            scored.append({**d, "similarity": round(min(1.0, score / 1000.0), 4)})

        scored.sort(key=lambda x: (-x["similarity"], len(x.get("name") or "")))
        return scored[:top_k]

    def get_symbol_count(self) -> int:
        c = self._conn.cursor()
        c.execute("SELECT COUNT(*) as cnt FROM symbols")
        count = c.fetchone()["cnt"]
        c.close()
        return count

    def get_stats(self) -> dict:
        c = self._conn.cursor()
        c.execute("SELECT kind, COUNT(*) as cnt FROM symbols GROUP BY kind")
        by_kind = {r["kind"]: r["cnt"] for r in c.fetchall()}
        c.execute("SELECT COUNT(*) as cnt FROM calls")
        calls = c.fetchone()["cnt"]
        c.execute("SELECT COUNT(*) as cnt FROM file_tracking")
        files = c.fetchone()["cnt"]
        c.close()
        return {"symbols": dict(by_kind), "total_symbols": sum(by_kind.values()),
                "call_edges": calls, "tracked_files": files}

    def close(self):
        with contextlib.suppress(Exception):
            self._conn.close()
