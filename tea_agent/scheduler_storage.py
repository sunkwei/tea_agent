"""
调度器存储层 — 脚本与任务的统一管理。

设计原则：
1. 脚本内容存储在数据库中（便于备份、迁移、合并）
2. 执行时动态加载到临时目录
3. 支持跨机器同步
"""
import os
import json
import sqlite3
import tempfile
import hashlib
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any


class SchedulerStorage:
    """调度器存储管理"""

    # 任务状态文件（兼容旧版）
    STATE_FILE = Path.home() / ".tea_agent" / "scheduler_state.json"
    
    # 脚本执行目录
    SCRIPTS_DIR = Path(tempfile.gettempdir()) / "tea_agent_scripts"
    
    def __init__(self, db_path: str = None):
        if db_path is None:
            db_path = str(Path.home() / ".tea_agent" / "scheduler.db")
        self.db_path = db_path
        self._ensure_tables()
    
    def _ensure_tables(self):
        """确保必要的表存在"""
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS scheduled_scripts (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                content TEXT NOT NULL,
                description TEXT DEFAULT '',
                is_enabled INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_run TIMESTAMP,
                last_exit_code INTEGER,
                last_output TEXT DEFAULT ''
            )
        """)
        conn.execute("""
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
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                script_id TEXT,
                FOREIGN KEY (script_id) REFERENCES scheduled_scripts(id)
            )
        """)
        conn.commit()
        conn.close()
    
    # ── 脚本管理 ──────────────────────────────────────────────
    
    def save_script(self, script_id: str, name: str, content: str, 
                    description: str = "", is_enabled: bool = True) -> Dict:
        """保存脚本到数据库"""
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("""
                INSERT OR REPLACE INTO scheduled_scripts 
                (id, name, content, description, is_enabled, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (script_id, name, content, description, int(is_enabled), 
                  datetime.now().isoformat()))
            conn.commit()
            return {"status": "saved", "id": script_id}
        finally:
            conn.close()
    
    def get_script(self, script_id: str) -> Optional[Dict]:
        """获取脚本"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                "SELECT * FROM scheduled_scripts WHERE id = ?", (script_id,)
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()
    
    def list_scripts(self) -> List[Dict]:
        """列出所有脚本"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT * FROM scheduled_scripts ORDER BY created_at DESC"
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()
    
    def delete_script(self, script_id: str) -> bool:
        """删除脚本"""
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("DELETE FROM scheduled_scripts WHERE id = ?", (script_id,))
            conn.commit()
            return conn.total_changes > 0
        finally:
            conn.close()
    
    # ── 任务管理 ──────────────────────────────────────────────
    
    def save_task(self, task_id: str, name: str, command: str, 
                  schedule: str, script_id: str = None) -> Dict:
        """保存任务"""
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("""
                INSERT OR REPLACE INTO scheduled_tasks
                (id, name, command, schedule, script_id, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (task_id, name, command, schedule, script_id, 
                  datetime.now().isoformat()))
            conn.commit()
            return {"status": "saved", "id": task_id}
        finally:
            conn.close()
    
    def list_tasks(self) -> List[Dict]:
        """列出所有任务"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT * FROM scheduled_tasks ORDER BY created_at DESC"
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()
    
    # ── 脚本执行 ──────────────────────────────────────────────
    
    def prepare_script_for_execution(self, script_id: str) -> Optional[str]:
        """将脚本从数据库加载到临时目录，返回可执行路径"""
        script = self.get_script(script_id)
        if not script:
            return None
        
        # 确保临时目录存在
        self.SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
        
        # 计算内容哈希，避免重复写入
        content_hash = hashlib.md5(script["content"].encode()).hexdigest()[:8]
        filename = f"{script_id}_{content_hash}.py"
        filepath = self.SCRIPTS_DIR / filename
        
        # 写入脚本
        filepath.write_text(script["content"], encoding="utf-8")
        
        # 更新最后执行时间
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "UPDATE scheduled_scripts SET last_run = ? WHERE id = ?",
            (datetime.now().isoformat(), script_id)
        )
        conn.commit()
        conn.close()
        
        return str(filepath)
    
    def update_script_result(self, script_id: str, exit_code: int, output: str):
        """更新脚本执行结果"""
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            UPDATE scheduled_scripts 
            SET last_exit_code = ?, last_output = ?, last_run = ?
            WHERE id = ?
        """, (exit_code, output[:1000], datetime.now().isoformat(), script_id))
        conn.commit()
        conn.close()
    


# ── 便捷函数 ──────────────────────────────────────────────

def get_scheduler_storage() -> SchedulerStorage:
    """获取调度器存储实例"""
    return SchedulerStorage()


def save_evolve_script():
    """保存自进化守护脚本到数据库"""
    storage = get_scheduler_storage()
    
    script_content = '''#!/usr/bin/env python3
"""
确保自进化进程启动的守护脚本。
从数据库动态加载执行，支持跨机器迁移。
"""
import sys, os, json, subprocess
from pathlib import Path
from datetime import datetime

DATA_DIR = Path.home() / ".tea_agent"
STATE_FILE = DATA_DIR / "self_evolve_state.json"

def _log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

def _read_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except: pass
    return {"running": False, "pid": None}

def _start_thread():
    python = sys.executable
    result = subprocess.run(
        [python, "-c", """
import sys, json, os
sys.path.insert(0, os.getcwd())
from tea_agent.toolkit.toolkit_self_evolve_thread import toolkit_self_evolve_thread
r = toolkit_self_evolve_thread("start")
print(json.dumps(r))
"""],
        capture_output=True, text=True, timeout=15
    )
    return result.returncode == 0

def ensure_running():
    state = _read_state()
    if state.get("running"):
        _log(f"🟢 运行中 (PID: {state.get('pid')})")
        return True
    
    _log("🔴 未启动，正在启动...")
    if _start_thread():
        _log("✅ 启动成功")
        return True
    _log("❌ 启动失败")
    return False

if __name__ == "__main__":
    success = ensure_running()
    sys.exit(0 if success else 1)
'''
    
    storage.save_script(
        script_id="self_evolve_watchdog",
        name="自进化守护",
        content=script_content,
        description="每分钟检查自进化进程，未启动则自动启动"
    )
    
    return {"status": "saved", "id": "self_evolve_watchdog"}


if __name__ == "__main__":
    # 测试
    storage = SchedulerStorage()
    print("Scripts:", len(storage.list_scripts()))
    print("Tasks:", len(storage.list_tasks()))
