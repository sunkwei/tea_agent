# @2026-05-20 gen by tea_agent, 轻量 TODO 清单
import logging
from typing import Optional, List
logger = logging.getLogger("toolkit")
_todos = []

def toolkit_todo(action, items=None, index=None):
    global _todos
    try:
        if action == "create":
            if not items: return {"ok":False,"error":"create needs items"}
            _todos.clear()
            _todos.extend([{"desc":d,"done":False,"idx":i} for i,d in enumerate(items)])
            return {"ok":True,"total":len(_todos),"todo":_fmt()}
        elif action == "check":
            if index is None: return {"ok":False,"error":"check needs index"}
            if 0 <= index < len(_todos):
                _todos[index]["done"] = True
                return {"ok":True,"checked":_todos[index]["desc"],"progress":f"{_done()}/{len(_todos)}","todo":_fmt()}
            return {"ok":False,"error":f"index {index} out of range"}
        elif action == "show":
            if not _todos: return {"ok":True,"todo":"(empty)","progress":"0/0"}
            return {"ok":True,"todo":_fmt(),"progress":f"{_done()}/{len(_todos)}","all_done":_done()==len(_todos)}
        elif action == "clear":
            _todos.clear(); return {"ok":True,"msg":"cleared"}
        else: return {"ok":False,"error":f"unknown action: {action}"}
    except Exception as e:
        logger.exception("toolkit_todo")
        return {"ok":False,"error":str(e)[:300]}

def _done(): return sum(1 for t in _todos if t["done"])

def _fmt():
    lines=[]
    for t in _todos:
        icon = "DONE" if t["done"] else "TODO"
        lines.append(f"[{icon}] [{t['idx']}] {t['desc']}")
    return chr(10).join(lines)

def meta_toolkit_todo():
    return {"type":"function","function":{"name":"toolkit_todo","description":"TODO checklist: create before modifying code, check off step by step","parameters":{"type":"object","properties":{"action":{"type":"string","enum":["create","check","show","clear"]},"items":{"type":"array","items":{"type":"string"}},"index":{"type":"integer"}},"required":["action"]}}}
