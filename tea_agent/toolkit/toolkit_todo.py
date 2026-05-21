import logging

logger = logging.getLogger("toolkit")

# ── 模块级缓存：快速读写，DB 仅做持久化 ──
_todos = []          # [{"desc":str, "done":bool, "idx":int}, ...]
_restored = False    # 是否已从 DB 恢复
_last_topic = None   # 上次操作的 topic_id, 用于检测主题切换

def _get_db():
    """获取当前 DB 连接（通过 session_ref → agent → db）"""
    try:
        from tea_agent.session_ref import get_agent
        agent = get_agent()
        if agent is not None and hasattr(agent, 'db'):
            return agent.db
    except Exception:
        pass
    return None

def _get_topic_id():
    """获取当前 topic_id"""
    try:
        from tea_agent.session_ref import get_agent
        agent = get_agent()
        if agent is not None:
            return getattr(agent, 'current_topic_id', None)
    except Exception:
        pass
    return None

def _ensure_table(db):
    """确保 todo_items 表存在（兼容旧 DB 未迁移的情况）"""
    try:
        c = db.conn.cursor()
        c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='todo_items'")
        if not c.fetchone():
            c.execute("""CREATE TABLE IF NOT EXISTS todo_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                topic_id TEXT NOT NULL,
                idx INTEGER NOT NULL,
                desc TEXT NOT NULL,
                done INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT (datetime('now', 'localtime')),
                FOREIGN KEY (topic_id) REFERENCES topics(topic_id)
            )""")
            db.conn.commit()
        c.close()
    except Exception as e:
        logger.warning(f"todo ensure_table failed: {e}")

def _sync_to_db():
    """将内存 _todos 全量写入 DB (DELETE + INSERT)"""
    global _last_topic
    topic_id = _get_topic_id()
    if not topic_id:
        return
    db = _get_db()
    if not db:
        return
    _ensure_table(db)
    try:
        c = db.conn.cursor()
        c.execute("DELETE FROM todo_items WHERE topic_id=?", (topic_id,))
        for t in _todos:
            c.execute(
                "INSERT INTO todo_items (topic_id, idx, desc, done) VALUES (?,?,?,?)",
                (topic_id, t["idx"], t["desc"], 1 if t["done"] else 0),
            )
        db.conn.commit()
        c.close()
        _last_topic = topic_id
    except Exception as e:
        logger.warning(f"todo sync to db failed: {e}")

def _sync_item(idx, done):
    """单条更新 DB"""
    topic_id = _get_topic_id()
    if not topic_id:
        return
    db = _get_db()
    if not db:
        return
    _ensure_table(db)
    try:
        c = db.conn.cursor()
        c.execute(
            "UPDATE todo_items SET done=? WHERE topic_id=? AND idx=?",
            (1 if done else 0, topic_id, idx),
        )
        db.conn.commit()
        c.close()
    except Exception as e:
        logger.warning(f"todo sync item failed: {e}")

def _restore_from_db():
    """从 DB 恢复当前 topic 的 TODO"""
    global _todos, _restored, _last_topic
    topic_id = _get_topic_id()
    if not topic_id:
        _restored = True
        return

    db = _get_db()
    if not db:
        _restored = True
        return

    _ensure_table(db)
    try:
        c = db.conn.cursor()
        c.execute(
            "SELECT idx, desc, done FROM todo_items WHERE topic_id=? ORDER BY idx ASC",
            (topic_id,),
        )
        rows = c.fetchall()
        c.close()

        if rows:
            _todos = [{"desc": r[1], "done": bool(r[2]), "idx": r[0]} for r in rows]
            _last_topic = topic_id
            logger.info(f"todo restored {len(_todos)} items for topic {topic_id[:8]}...")
        else:
            _todos = []
    except Exception as e:
        logger.warning(f"todo restore failed: {e}")
        _todos = []
    finally:
        _restored = True

def _auto_restore():
    """自动恢复（首次调用 + 主题切换时）"""
    global _restored, _last_topic, _todos
    topic_id = _get_topic_id()
    if not _restored or (topic_id and topic_id != _last_topic):
        _restore_from_db()

def toolkit_todo(action: str, items: list = None, index: int = None) -> dict:
    """TODO checklist: create before modifying code, check off step by step.
    支持 DB 持久化（per-topic），跨进程重启不丢失。"""
    global _todos

    _auto_restore()

    try:
        if action == "create":
            if not items:
                return {"ok": False, "error": "create needs items"}
            _todos.clear()
            _todos.extend([{"desc": d, "done": False, "idx": i} for i, d in enumerate(items)])
            _sync_to_db()
            return {
                "ok": True,
                "total": len(_todos),
                "todo": _fmt(),
                "persisted": _get_topic_id() is not None,
            }

        elif action == "check":
            if index is None:
                return {"ok": False, "error": "check needs index"}
            if 0 <= index < len(_todos):
                _todos[index]["done"] = True
                _sync_item(index, True)
                return {
                    "ok": True,
                    "checked": _todos[index]["desc"],
                    "progress": f"{_done()}/{len(_todos)}",
                    "todo": _fmt(),
                }
            return {"ok": False, "error": f"index {index} out of range (0..{len(_todos)-1})"}

        elif action == "show":
            if not _todos:
                topic_id = _get_topic_id()
                return {
                    "ok": True,
                    "todo": "(empty)",
                    "progress": "0/0",
                    "topic_id": topic_id[:8] + "..." if topic_id else None,
                }
            all_done = _done() == len(_todos)
            topic_id = _get_topic_id()
            return {
                "ok": True,
                "todo": _fmt(),
                "progress": f"{_done()}/{len(_todos)}",
                "all_done": all_done,
                "topic_id": topic_id[:8] + "..." if topic_id else None,
            }

        elif action == "clear":
            n = len(_todos)
            _todos.clear()
            # 清除 DB 中当前 topic 的记录
            topic_id = _get_topic_id()
            if topic_id:
                db = _get_db()
                if db:
                    _ensure_table(db)
                    try:
                        c = db.conn.cursor()
                        c.execute("DELETE FROM todo_items WHERE topic_id=?", (topic_id,))
                        db.conn.commit()
                        c.close()
                    except Exception as e:
                        logger.warning(f"todo clear db failed: {e}")
            return {"ok": True, "msg": f"cleared {n} items"}

        elif action == "restore":
            _restore_from_db()
            return {"ok": True, "todo": _fmt(), "progress": f"{_done()}/{len(_todos)}"}

        else:
            return {"ok": False, "error": f"unknown action: {action}"}

    except Exception as e:
        logger.exception("toolkit_todo")
        return {"ok": False, "error": str(e)[:300]}

def _done():
    return sum(1 for t in _todos if t["done"])

def _fmt():
    lines = []
    for t in _todos:
        icon = "DONE" if t["done"] else "TODO"
        lines.append(f"[{icon}] [{t['idx']}] {t['desc']}")
    return "\n".join(lines)

def meta_toolkit_todo():
    return {
        "type": "function",
        "function": {
            "name": "toolkit_todo",
            "description": (
                "TODO checklist: create before modifying code, check off step by step. "
                "Persisted to DB per-topic — survives restart. "
                "Use create(items=[...]) to start, check(index=N) to mark done, "
                "show to view, clear when all done, restore to reload from DB."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["create", "check", "show", "clear", "restore"],
                        "description": "create=开始清单, check=勾选完成, show=显示, clear=清除, restore=从DB恢复",
                    },
                    "items": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "[create] 任务列表",
                    },
                    "index": {
                        "type": "integer",
                        "description": "[check] 要勾选的任务序号",
                    },
                },
                "required": ["action"],
            },
        },
    }
