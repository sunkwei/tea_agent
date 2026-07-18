# version: 2.0.0 — refactored: clean internal API, unified dict return

"""
动态技能系统
记录成功的 agent 组合模式，供未来重用。
"""

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger("toolkit.dynamic_skill")

# 技能存储目录
SKILLS_DIR = os.path.join(os.path.expanduser("~"), ".tea_agent", "skills")


def _ensure_skills_dir():
    os.makedirs(SKILLS_DIR, exist_ok=True)


def _load_pattern(name: str) -> dict | None:
    filepath = os.path.join(SKILLS_DIR, f"{name}.json")
    if os.path.exists(filepath):
        try:
            with open(filepath, encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.exception(f"load_pattern_failed:{name}")
    return None


def _save_pattern(name: str, pattern: dict):
    _ensure_skills_dir()
    filepath = os.path.join(SKILLS_DIR, f"{name}.json")
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(pattern, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.exception(f"save_pattern_failed:{name}")


def _list_patterns() -> list[dict]:
    _ensure_skills_dir()
    patterns = []
    for filepath in Path(SKILLS_DIR).glob("*.json"):
        try:
            with open(filepath, encoding="utf-8") as f:
                pattern = json.load(f)
                pattern["name"] = filepath.stem
                patterns.append(pattern)
        except Exception as e:
            logger.warning(f"read_pattern_failed:{filepath.stem}")
    return patterns


def toolkit_dynamic_skill(
    action: str,
    task: str = "",
    pattern_name: str = "",
    agents: list[dict] = None,
    query: str = "",
    limit: int = 10
) -> dict:
    """
    动态技能系统 — 记录/推荐/搜索 agent 组合模式。

    - action=record: 记录模式，需 task + agents
    - action=recommend: 根据 task 推荐匹配模式
    - action=list: 列出所有模式
    - action=search: 按 query 搜索模式
    - action=delete: 删除指定 pattern_name
    """
    if action == "record":
        return _record_pattern(task, pattern_name, agents)
    elif action == "recommend":
        return _recommend_pattern(task, limit)
    elif action == "list":
        return _list_patterns_result(limit)
    elif action == "search":
        return _search_patterns(query, limit)
    elif action == "delete":
        return _delete_pattern(pattern_name)
    else:
        return {"ok": False, "error": f"unknown_action:{action}"}


def _record_pattern(task: str, pattern_name: str, agents: list[dict]) -> dict:
    if not pattern_name:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        pattern_name = f"skill_{ts}"
    if not agents:
        return {"ok": False, "error": "missing_agents"}
    pattern = {
        "name": pattern_name,
        "description": task,
        "agents": agents,
        "created_at": datetime.now().isoformat(),
        "use_count": 0,
    }
    _save_pattern(pattern_name, pattern)
    return {"ok": True, "pattern_name": pattern_name}


def _recommend_pattern(task: str, limit: int = 5) -> dict:
    if not task:
        return {"ok": False, "error": "missing_task"}
    patterns = _list_patterns()
    if not patterns:
        return {"ok": True, "recommendations": [], "message": "no_skills"}
    scored = []
    task_lower = task.lower()
    task_words = set(task_lower.split())
    for p in patterns:
        desc = (p.get("description", "") or "").lower()
        desc_words = set(desc.split())
        sim = len(task_words & desc_words) / max(len(task_words | desc_words), 1)
        use_count = p.get("use_count", 0)
        score = sim * 0.7 + min(use_count / 10, 1) * 0.3
        scored.append((score, p))
    scored.sort(key=lambda x: x[0], reverse=True)
    recs = [{"pattern_name": p.get("name", ""), "description": p.get("description", ""), "agents_count": len(p.get("agents", [])), "score": round(s, 3)} for s, p in scored[:limit]]
    return {"ok": True, "task": task, "recommendations": recs}


def _list_patterns_result(limit: int = 20) -> dict:
    patterns = _list_patterns()
    patterns.sort(key=lambda p: p.get("use_count", 0), reverse=True)
    result = [{"name": p.get("name", ""), "description": p.get("description", ""), "agents_count": len(p.get("agents", [])), "use_count": p.get("use_count", 0)} for p in patterns[:limit]]
    return {"ok": True, "patterns": result, "total": len(patterns)}


def _search_patterns(query: str, limit: int = 10) -> dict:
    if not query:
        return _list_patterns_result(limit)
    patterns = _list_patterns()
    q = query.lower()
    matched = []
    for p in patterns:
        if q in p.get("name", "").lower() or q in p.get("description", "").lower():
            matched.append(p)
    matched = matched[:limit]
    return {"ok": True, "query": query, "results": matched}


def _delete_pattern(pattern_name: str) -> dict:
    if not pattern_name:
        return {"ok": False, "error": "missing_pattern_name"}
    filepath = os.path.join(SKILLS_DIR, f"{pattern_name}.json")
    if not os.path.exists(filepath):
        return {"ok": False, "error": f"pattern_not_found:{pattern_name}"}
    try:
        os.remove(filepath)
        return {"ok": True, "message": f"deleted:{pattern_name}"}
    except Exception as e:
        return {"ok": False, "error": f"delete_failed:{e}"}


def update_pattern_usage(pattern_name: str, success: bool = True):
    pattern = _load_pattern(pattern_name)
    if pattern:
        pattern["use_count"] = pattern.get("use_count", 0) + 1
        pattern["last_used"] = datetime.now().isoformat()
        _save_pattern(pattern_name, pattern)


def meta_toolkit_dynamic_skill() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "toolkit_dynamic_skill",
            "description": "动态技能系统 - 记录/推荐/搜索 agent 组合模式。action=record/recommend/list/search/delete",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["record", "recommend", "list", "search", "delete"],
                        "description": "record/recommend/list/search/delete"
                    },
                    "task": {"type": "string", "description": "任务描述（record/recommend 时使用）"},
                    "pattern_name": {"type": "string", "description": "模式名称（record/delete 时使用）"},
                    "agents": {"type": "array", "items": {"type": "object"}, "description": "agent 组合（record 时使用）"},
                    "query": {"type": "string", "description": "搜索关键词（search 时使用）"},
                    "limit": {"type": "integer", "description": "返回数量限制"}
                },
                "required": ["action"]
            }
        }
    }
