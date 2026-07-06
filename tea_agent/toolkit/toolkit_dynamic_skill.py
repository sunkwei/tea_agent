## llm generated tool func, created Mon Jun  1 09:30:31 2026
# version: 1.0.0

"""
动态技能系统

自动记录成功的 agent 组合模式，供未来重用。
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
    """确保技能目录存在。"""
    os.makedirs(SKILLS_DIR, exist_ok=True)


def _load_pattern(name: str) -> dict | None:
    """加载技能模式。"""
    filepath = os.path.join(SKILLS_DIR, f"{name}.json")
    if os.path.exists(filepath):
        try:
            with open(filepath, encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"加载技能模式失败: {e}")
    return None


def _save_pattern(name: str, pattern: dict):
    """保存技能模式。"""
    _ensure_skills_dir()
    filepath = os.path.join(SKILLS_DIR, f"{name}.json")
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(pattern, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"保存技能模式失败: {e}")


def _list_patterns() -> list[dict]:
    """列出所有技能模式。"""
    _ensure_skills_dir()
    patterns = []
    for filepath in Path(SKILLS_DIR).glob("*.json"):
        try:
            with open(filepath, encoding="utf-8") as f:
                pattern = json.load(f)
                pattern["name"] = filepath.stem
                patterns.append(pattern)
        except Exception as e:
            logger.warning(f"读取技能模式失败 {filepath}: {e}")
    return patterns


def _classify_task(task: str) -> str:
    """分类任务类型。"""
    task_lower = task.lower()

    # 关键词映射
    keywords = {
        "refactor": ["重构", "refactor", "优化", "optimize"],
        "debug": ["调试", "debug", "修复", "fix", "bug", "错误"],
        "feature": ["功能", "feature", "添加", "add", "实现", "implement"],
        "test": ["测试", "test", "单元测试", "unittest"],
        "review": ["审查", "review", "检查", "check"],
        "document": ["文档", "document", "注释", "comment"],
        "analyze": ["分析", "analyze", "理解", "understand"],
    }

    for category, kw_list in keywords.items():
        for kw in kw_list:
            if kw in task_lower:
                return category

    return "general"


def _calculate_similarity(task1: str, task2: str) -> float:
    """计算两个任务的相似度（简单实现）。"""
    # 基于关键词重叠
    words1 = set(task1.lower().split())
    words2 = set(task2.lower().split())

    if not words1 or not words2:
        return 0.0

    intersection = words1 & words2
    union = words1 | words2

    return len(intersection) / len(union) if union else 0.0


def toolkit_dynamic_skill(
    action: str,
    task: str = "",
    pattern_name: str = "",
    agents: list[dict] = None,
    query: str = "",
    limit: int = 10
) -> Any:
    """
    动态技能系统。

    Args:
        action: 操作类型
        task: 任务描述
        pattern_name: 技能模式名称
        agents: agent 组合配置
        query: 搜索关键词
        limit: 返回数量限制

    Returns:
        技能信息或推荐结果
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
        return {"ok": False, "error": f"未知操作: {action}"}


def _record_pattern(
    task: str,
    pattern_name: str,
    agents: list[dict]
) -> dict:
    """记录成功的 agent 组合模式。"""
    if not pattern_name:
        # 自动生成名称
        task_type = _classify_task(task)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        pattern_name = f"{task_type}_{timestamp}"

    if not agents:
        return {"ok": False, "error": "缺少 agents 配置"}

    # 构建模式
    pattern = {
        "name": pattern_name,
        "description": task,
        "task_type": _classify_task(task),
        "task_keywords": task.lower().split()[:10],
        "agents": agents,
        "created_at": datetime.now().isoformat(),
        "last_used": None,
        "use_count": 0,
        "success_count": 0,
        "success_rate": 0.0,
    }

    # 保存模式
    _save_pattern(pattern_name, pattern)

    return {
        "ok": True,
        "pattern_name": pattern_name,
        "message": f"技能模式已记录: {pattern_name}"
    }


def _recommend_pattern(task: str, limit: int = 5) -> dict:
    """根据任务推荐 agent 组合。"""
    if not task:
        return {"ok": False, "error": "缺少任务描述"}

    patterns = _list_patterns()
    if not patterns:
        return {
            "ok": True,
            "recommendations": [],
            "message": "暂无技能模式，请先记录成功的 agent 组合"
        }

    # 计算相似度
    scored_patterns = []
    for pattern in patterns:
        # 基于任务类型
        task_type = _classify_task(task)
        type_score = 1.0 if pattern.get("task_type") == task_type else 0.3

        # 基于关键词相似度
        keyword_score = _calculate_similarity(
            task,
            pattern.get("description", "")
        )

        # 综合得分
        total_score = type_score * 0.4 + keyword_score * 0.6

        # 考虑成功率
        success_rate = pattern.get("success_rate", 0.0)
        total_score *= (0.5 + success_rate * 0.5)

        scored_patterns.append((total_score, pattern))

    # 排序并返回
    scored_patterns.sort(key=lambda x: x[0], reverse=True)

    recommendations = []
    for score, pattern in scored_patterns[:limit]:
        recommendations.append({
            "pattern_name": pattern.get("name", ""),
            "description": pattern.get("description", ""),
            "task_type": pattern.get("task_type", ""),
            "agents": pattern.get("agents", []),
            "success_rate": pattern.get("success_rate", 0.0),
            "use_count": pattern.get("use_count", 0),
            "similarity_score": round(score, 3),
        })

    return {
        "ok": True,
        "task": task,
        "recommendations": recommendations,
        "message": f"找到 {len(recommendations)} 个推荐技能模式"
    }


def _list_patterns_result(limit: int = 20) -> dict:
    """列出所有技能模式。"""
    patterns = _list_patterns()

    # 按使用次数排序
    patterns.sort(key=lambda p: p.get("use_count", 0), reverse=True)

    result = []
    for pattern in patterns[:limit]:
        result.append({
            "name": pattern.get("name", ""),
            "description": pattern.get("description", ""),
            "task_type": pattern.get("task_type", ""),
            "agents_count": len(pattern.get("agents", [])),
            "success_rate": pattern.get("success_rate", 0.0),
            "use_count": pattern.get("use_count", 0),
            "created_at": pattern.get("created_at", ""),
        })

    return {
        "ok": True,
        "patterns": result,
        "total": len(patterns),
        "message": f"共 {len(patterns)} 个技能模式"
    }


def _search_patterns(query: str, limit: int = 10) -> dict:
    """搜索技能模式。"""
    if not query:
        return _list_patterns_result(limit)

    patterns = _list_patterns()

    # 搜索匹配
    matched = []
    query_lower = query.lower()

    for pattern in patterns:
        # 检查名称
        if query_lower in pattern.get("name", "").lower():
            matched.append((1.0, pattern))
            continue

        # 检查描述
        if query_lower in pattern.get("description", "").lower():
            matched.append((0.8, pattern))
            continue

        # 检查关键词
        keywords = pattern.get("task_keywords", [])
        for kw in keywords:
            if query_lower in kw.lower():
                matched.append((0.6, pattern))
                break

    # 按相关性排序
    matched.sort(key=lambda x: x[0], reverse=True)

    result = []
    for score, pattern in matched[:limit]:
        result.append({
            "name": pattern.get("name", ""),
            "description": pattern.get("description", ""),
            "task_type": pattern.get("task_type", ""),
            "agents": pattern.get("agents", []),
            "relevance_score": round(score, 3),
        })

    return {
        "ok": True,
        "query": query,
        "results": result,
        "message": f"找到 {len(result)} 个匹配的技能模式"
    }


def _delete_pattern(pattern_name: str) -> dict:
    """删除技能模式。"""
    if not pattern_name:
        return {"ok": False, "error": "缺少模式名称"}

    filepath = os.path.join(SKILLS_DIR, f"{pattern_name}.json")
    if not os.path.exists(filepath):
        return {"ok": False, "error": f"技能模式不存在: {pattern_name}"}

    try:
        os.remove(filepath)
        return {
            "ok": True,
            "message": f"已删除技能模式: {pattern_name}"
        }
    except Exception as e:
        return {"ok": False, "error": f"删除失败: {e}"}


def update_pattern_usage(pattern_name: str, success: bool = True):
    """更新技能模式的使用统计。"""
    pattern = _load_pattern(pattern_name)
    if pattern:
        pattern["use_count"] = pattern.get("use_count", 0) + 1
        if success:
            pattern["success_count"] = pattern.get("success_count", 0) + 1
        pattern["success_rate"] = (
            pattern["success_count"] / pattern["use_count"]
            if pattern["use_count"] > 0 else 0.0
        )
        pattern["last_used"] = datetime.now().isoformat()
        _save_pattern(pattern_name, pattern)


# 工具元信息
TOOL_META = {
    "type": "function",
    "function": {
        "name": "toolkit_dynamic_skill",
        "description": "动态技能系统 - 自动记录成功的 agent 组合模式。",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["record", "recommend", "list", "search", "delete"], "description": "操作类型"},
                "task": {"type": "string", "description": "任务描述"},
                "pattern_name": {"type": "string", "description": "技能模式名称"},
                "agents": {"type": "array", "items": {"type": "object"}, "description": "agent 组合配置"},
                "query": {"type": "string", "description": "搜索关键词"},
                "limit": {"type": "integer", "description": "返回数量限制"}
            },
            "required": ["action"]
        }
    }
}


def meta_toolkit_dynamic_skill() -> dict:
    return {"type": "function", "function": {"name": "toolkit_dynamic_skill", "description": "动态技能系统 - 自动记录成功的 agent 组合模式，供未来重用。\n\n功能：\n- record: 记录成功的 agent 组合模式\n- recommend: 根据任务推荐 agent 组合\n- list: 列出所有技能模式\n- search: 搜索相似技能\n\n返回：技能信息或推荐结果", "parameters": {"type": "object", "properties": {"action": {"type": "string", "enum": ["record", "recommend", "list", "search", "delete"], "description": "操作类型"}, "task": {"type": "string", "description": "任务描述（record/recommend 时使用）"}, "pattern_name": {"type": "string", "description": "技能模式名称（record 时使用）"}, "agents": {"type": "array", "items": {"type": "object"}, "description": "agent 组合配置（record 时使用）"}, "query": {"type": "string", "description": "搜索关键词（search 时使用）"}, "limit": {"type": "integer", "description": "返回数量限制，默认 10"}}, "required": ["action"]}}}
