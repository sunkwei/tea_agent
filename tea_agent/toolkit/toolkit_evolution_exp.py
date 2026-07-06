## llm generated tool func, created Thu May 15 13:55:00 2026
# version: 1.0.0

"""
进化经验库管理工具 — toolkit_evolution_exp

记录、查询和管理 Agent 的自主进化经验。
经验库存储在 ~/.tea_agent/evolution_exp.json。

action:
  - record: 记录新的进化经验
  - search: 根据关键词/标签搜索历史经验
  - list: 列出最近的进化经验
"""

import json
import os
from datetime import datetime


def _get_exp_path():
    """Internal: get the exp path."""
    return os.path.join(os.path.expanduser("~"), ".tea_agent", "evolution_exp.json")

def _load_exp_db():
    """Internal: load exp db."""
    path = _get_exp_path()
    if os.path.exists(path):
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    return []

def _save_exp_db(data):
    """Internal: save exp db.

    Args:
        data: Description.
    """
    path = _get_exp_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def toolkit_evolution_exp(action="list", description="", category="", tags="", outcome="success", notes="", query="", limit=10):
    """
    管理进化经验库。

    action:
      - list: 列出最近经验
      - record: 记录经验
      - search: 搜索经验
    """
    db = _load_exp_db()

    if action == "list":
        if not db:
            return "📚 经验库为空，开始记录进化经验吧！"

        lines = [f"📚 最近 {min(limit, len(db))} 条进化经验:"]
        for exp in db[-limit:]:
            tags_str = f" [{', '.join(exp.get('tags', []))}]" if exp.get('tags') else ""
            lines.append(f"- **{exp.get('description', 'N/A')}** ({exp.get('timestamp', '')[:10]}) {tags_str}")
        return "\n".join(lines)

    elif action == "record":
        if not description:
            return "❌ 记录经验需要提供 description 参数"

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
        return f"✅ 已记录经验: {description}"

    elif action == "search":
        if not query:
            return "❌ 搜索经验需要提供 query 参数"

        results = []
        q = query.lower()
        for exp in db:
            text = json.dumps(exp).lower()
            if q in text:
                results.append(exp)

        if not results:
            return f"🔍 未找到与 '{query}' 相关的经验"

        lines = [f"🔍 找到 {len(results)} 条与 '{query}' 相关的经验:"]
        for exp in results[-limit:]:
            tags_str = f" [{', '.join(exp.get('tags', []))}]" if exp.get('tags') else ""
            lines.append(f"- **{exp.get('description', 'N/A')}** ({exp.get('timestamp', '')[:10]}) {tags_str}")
            if exp.get('notes'):
                lines.append(f"  > {exp['notes']}")
        return "\n".join(lines)

    else:
        return f"❌ 未知 action: {action}"

def meta_toolkit_evolution_exp() -> dict:
    """Meta toolkit evolution exp."""
    return {
        "type": "function",
        "function": {
            "name": "toolkit_evolution_exp",
            "description": "进化经验库管理。记录、查询和管理 Agent 的自主进化经验。action=list/record/search。",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["list", "record", "search"], "description": "操作: list=列出, record=记录, search=搜索"},
                    "description": {"type": "string", "description": "[record] 经验描述"},
                    "category": {"type": "string", "description": "[record] 经验分类，如 dependency, architecture, ui"},
                    "tags": {"type": "string", "description": "[record/search] 逗号分隔的标签"},
                    "outcome": {"type": "string", "description": "[record] 结果: success/failure/partial", "default": "success"},
                    "notes": {"type": "string", "description": "[record] 备注或教训"},
                    "query": {"type": "string", "description": "[search] 搜索关键词"},
                    "limit": {"type": "integer", "description": "返回数量上限", "default": 10}
                },
                "required": ["action"]
            }
        }
    }
