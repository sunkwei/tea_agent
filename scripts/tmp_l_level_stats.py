"""临时脚点脚归分析：L0/L3/L2/L1 当前占用统计（仅诊取，不修改）"""
import json
import sys
from types import SimpleNamespace

sys.path.insert(0, ".")

try:
    from store._core import StorageCore
    from session.history_builder import estimate_tokens, estimate_messages_tokens
except Exception as e:
    print("import_failed:", e)
    sys.exit(0)

def get_ctx():
    try:
        from server.modules.agent_module import current_session_ctx
        return current_session_ctx()
    except Exception:
        pass
    try:
        from server.app import app
        for attr in ("_session", "session", "_sess", "active_session"):
            s = getattr(app, attr, None)
            if s is not None and hasattr(s, "context"):
                return s.context
    except Exception:
        pass
    return None

class Ctx:
    """最小仓住 stub，仅供 context_fragments / prompt 路径读取"""
    def __init__(self):
        self.max_context_tokens = 0
        self._injected_os_info_text = ""
        self._injected_memories_text = ""
        self._current_mode = ""
        self.interface_type = ""
        self._rounds_collector = []
        self.toolkit = None
        self._last_request_prompt_tokens = 0
        self._last_estimate_tokens = 0
        self._output_cap = 0
        self.budget_warn_ratio = None

print("=" * 70)
print("[1] 当前会话 context 聚归使")
print("=" * 70)
ctx = get_ctx()
if ctx is None:
    print("  (未找到当前活跃 context，仅做离线统计)")
else:
    print(f"  model               : {getattr(ctx, 'model', '?')}")
    print(f"  max_context_tokens  : {getattr(ctx, 'max_context_tokens', 0)}")
    print(f"  _last_request_prompt: {getattr(ctx, '_last_request_prompt_tokens', 0)}")
    print(f"  _last_estimate      : {getattr(ctx, '_last_estimate_tokens', 0)}")
    print(f"  _output_cap         : {getattr(ctx, '_output_cap', 0)}")
    print(f"  _injected_os_info   : {len(getattr(ctx, '_injected_os_info_text', '') or '')} 字符")
    print(f"  _injected_memories  : {len(getattr(ctx, '_injected_memories_text', '') or '')} 字符")
    print(f"  _semantic_summary   : {len(getattr(ctx, '_semantic_summary', '') or '')} 字符")
    print(f"  _tool_chain_summary : {len(getattr(ctx, '_tool_chain_summary', '') or '')} 字符")
    print(f"  _history_summary    : {len(getattr(ctx, '_history_summary', '') or '')} 字符")
    print(f"  _level2 条数        : {len(getattr(ctx, '_level2', []) or [])}")
    print(f"  _level2_selected    : {len(getattr(ctx, '_level2_selected', []) or []) if getattr(ctx, '_level2_selected', None) is not None else 'None'}")
    print(f"  messages 条数        : {len(getattr(ctx, 'messages', []) or [])}")

print()
print("=" * 70)
print("[2] DB 读取：最近 topic 的对话链 / L3 摘要 / L2 储备")
print("=" * 70)
db = StorageCore()
convs = db.get_all_conversations(limit=300)
if not convs:
    print("  (db 无对话)")
topics = {}
for c in convs:
    tid = c.get("topic_id") or "?"
    topics.setdefault(tid, []).append(c)
topic_id = None
for tid in sorted(topics, key=lambda t: max(c.get("created_at", "") for c in topics[t]), reverse=True):
    topic_id = tid
    break

c2 = db.conn.cursor() if hasattr(db, "conn") else None
pairs = []
sem = tc = ""
l2_db = []
if topic_id:
    print(f"  最近 topic_id: {topic_id}")
    for c in topics[topic_id]:
        if c.get("role") == "user":
            pairs.append((c["content"], ""))
        elif c.get("role") == "assistant" and pairs:
            pairs[-1] = (pairs[-1][0], c["content"])
    try:
        sem = db.get_semantic_summary(topic_id) or ""
    except Exception:
        pass
    try:
        tc = db.get_tool_chain_summary(topic_id) or ""
    except Exception:
        pass
    try:
        l2_db = db.get_level2(topic_id) or []
    except Exception:
        pass
print(f"  最近 topic 对话: {len(convs and topics.get(topic_id, []))} 条，user/assistant 对: {len(pairs)}对, L2储备: {len(l2_db)} 条")
print(f"  L3: semantic={len(sem)} 字符, tool_chain={len(tc)} 字符")

print()
print("=" * 70)
print("[3] 会计（与 build_api_messages 相同的估算器）")
print("=" * 70)

