# version: 1.0.1


import os
import sqlite3

DB_PATH = os.path.expanduser("~/.tea_agent/chat_history.db")

def toolkit_query_chat_history(action="schema", conversation_id=None, keyword=None, limit=5, topic_id=None):
    """查询 chat_history.db 中的 conversations 表"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    if action == "schema":
        cur.execute("SELECT sql FROM sqlite_master WHERE type='table' ORDER BY name")
        tables = cur.fetchall()
        result = "=== Tables ===\n"
        for t in tables:
            result += f"\n{t['sql']}\n"
        conn.close()
        return result

    elif action == "query":
        if not conversation_id:
            conn.close()
            return "Error: conversation_id required"
        cur.execute("SELECT * FROM conversations WHERE id = ?", (conversation_id,))
        row = cur.fetchone()
        if not row:
            conn.close()
            return f"Not found: {conversation_id}"
        cols = row.keys()
        result = f"=== Record: {conversation_id} ===\n"
        for c in cols:
            val = str(row[c]) if row[c] is not None else "NULL"
            if len(val) > 4000:
                val = val[:4000] + f"...[TRUNCATED {len(val)} chars]"
            result += f"\n--- {c} ---\n{val}\n"
        conn.close()
        return result

    elif action == "topic":
        if not topic_id:
            conn.close()
            return "Error: topic_id required"
        cur.execute("SELECT id, user_msg, ai_msg, is_func_calling, is_summarized, stamp FROM conversations WHERE topic_id = ? ORDER BY stamp", (str(topic_id),))
        rows = cur.fetchall()
        if not rows:
            conn.close()
            return f"No conversations for topic_id={topic_id}"
        result = f"=== Topic {topic_id}: {len(rows)} conversation(s) ===\n"
        for i, row in enumerate(rows):
            d = dict(row)
            result += f"\n--- [{i+1}] {d['id']} ---\n"
            result += f"  stamp: {d['stamp']}\n"
            result += f"  is_func_calling: {d['is_func_calling']}  is_summarized: {d['is_summarized']}\n"
            user = d['user_msg'][:200] + ('...' if len(d['user_msg'])>200 else '')
            ai = d['ai_msg'][:300] + ('...' if len(d['ai_msg'])>300 else '')
            result += f"  user_msg: {user}\n"
            result += f"  ai_msg: {ai}\n"
            # 检查是否包含错误
            if 'error' in (d['ai_msg'] or '').lower():
                result += "  ⚠️ CONTAINS ERROR in ai_msg\n"
        conn.close()
        return result

    elif action == "search":
        if not keyword:
            conn.close()
            return "Error: keyword required"
        cur.execute("SELECT * FROM conversations")
        cols = None
        matches = []
        for row in cur.fetchall():
            if cols is None:
                cols = row.keys()
            row_str = " ".join(str(v) for v in row if v)
            if keyword.lower() in row_str.lower():
                matches.append(dict(row))
                if len(matches) >= limit:
                    break
        if not matches:
            conn.close()
            return f"No matches for: {keyword}"
        result = f"=== {len(matches)} match(es) for '{keyword}' ===\n"
        for m in matches:
            result += f"\nID: {m.get('id', '?')}\n"
            for k, v in m.items():
                if k == 'id':
                    continue
                vs = str(v)[:500] if v else "NULL"
                result += f"  {k}: {vs}\n"
        conn.close()
        return result

    conn.close()
    return f"Unknown action: {action}"


def meta_toolkit_query_chat_history() -> dict:
    return {"type": "function", "function": {"name": "toolkit_query_chat_history", "description": "查询 chat_history.db 中的 conversations 表。action=schema查看表结构, query按UUID查记录, topic按topic_id列所有对话, search按关键词搜。", "parameters": {"type": "object", "properties": {"action": {"type": "string", "enum": ["schema", "query", "topic", "search"], "description": "schema=表结构, query=按ID查, topic=按topic_id列出, search=搜索"}, "conversation_id": {"type": "string", "description": "conversation UUID"}, "keyword": {"type": "string", "description": "关键词"}, "topic_id": {"type": "string", "description": "topic_id"}, "limit": {"type": "integer", "description": "返回上限,默认5", "default": 5}}, "required": ["action"]}}}
