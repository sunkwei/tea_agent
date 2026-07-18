# version: 2.0.0 — refactored: unified dict return, removed emoji from API

"""
进化经验库管理
记录、查询 Agent 的自主进化经验。存储于 ~/.tea_agent/evolution_exp.json。
"""

import json
import logging
import os
from datetime import datetime

logger = logging.getLogger("toolkit.evolution_exp")


def _get_exp_path() -> str:
    return os.path.join(os.path.expanduser("~"), ".tea_agent", "evolution_exp.json")


def _load_exp_db() -> list[dict]:
    path = _get_exp_path()
    if os.path.exists(path):
        try:
            with open(path, encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.exception(f"load_exp_failed:{e}")
    return []


def _save_exp_db(data: list[dict]):
    path = _get_exp_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def toolkit_evolution_exp(
    action: str = "list",
    description: str = "",
    category: str = "",
    tags: str = "",
    outcome: str = "success",
    notes: str = "",
    query: str = "",
    limit: int = 10
) -> dict:
    """
    进化经验库管理。

    - action=list: 列出最近经验
    - action=record: 记录新经验
    - action=search: 搜索经验
    """
    db = _load_exp_db()

    if action == "list":
        if not db:
            return {"ok": True, "experiences": [], "total": 0}
        result = []
        for exp in db[-limit:]:
            result.append({
                "description": exp.get("description", ""),
                "category": exp.get("category", ""),
                "outcome": exp.get("outcome", ""),
                "date": exp.get("timestamp", "")[:10]
            })
        return {"ok": True, "experiences": result, "total": len(db)}

    elif action == "record":
        if not description:
            return {"ok": False, "error": "missing_description"}
        exp = {
            "timestamp": datetime.now().isoformat(),
            "description": description,
            "category": category or "general",
            "tags": [t.strip() for t in tags.split(",") if t.strip()] if tags else [],
            "outcome": outcome,
            "notes": notes
        }
        db.append(exp)
        _save_exp_db(db)
        return {"ok": True, "message": f"recorded:{description[:60]}"}

    elif action == "search":
        if not query:
            return {"ok": False, "error": "missing_query"}
        q = query.lower()
        results = [exp for exp in db if q in json.dumps(exp, ensure_ascii=False).lower()]
        return {"ok": True, "query": query, "results": results[-limit:], "total": len(results)}

    else:
        return {"ok": False, "error": f"unknown_action:{action}"}


def meta_toolkit_evolution_exp() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "toolkit_evolution_exp",
            "description": "进化经验库管理。记录/查询 Agent 的自主进化经验。action=list/record/search",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["list", "record", "search"], "description": "list/record/search"},
                    "description": {"type": "string", "description": "经验描述（record 时必需）"},
                    "category": {"type": "string", "description": "分类"},
                    "tags": {"type": "string", "description": "逗号分隔标签"},
                    "outcome": {"type": "string", "description": "success/failure/partial"},
                    "notes": {"type": "string", "description": "备注"},
                    "query": {"type": "string", "description": "搜索关键词"},
                    "limit": {"type": "integer", "description": "返回上限"}
                },
                "required": ["action"]
            }
        }
    }
