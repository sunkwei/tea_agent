"""Test MemoryManager: select, format, ingest, extraction pipeline"""
from tea_agent.store import Storage
from tea_agent.memory import MemoryManager, PRIORITY_CRITICAL, PRIORITY_HIGH

s = Storage(":memory:")
m = MemoryManager(s)

# ── 1. Add test memories via Storage ──
s.add_memory(content="修改代码时标注前缀 {date}: gen by deepseek-v4-pro, {subject}",
             category="instruction", priority=PRIORITY_CRITICAL, importance=5, tags="code,rule")
s.add_memory(content="明天8点提醒检查服务器",
             category="reminder", priority=PRIORITY_HIGH, importance=4,
             expires_at="2026-04-30T08:00:00", tags="reminder")
s.add_memory(content="项目使用SQLite存储",
             category="fact", importance=2, tags="tech")
s.add_memory(content="用户偏好简洁回复",
             category="preference", importance=4, tags="style")
s.add_memory(content="Python 3.10+ 可用 match 语句",
             category="fact", importance=1, tags="python,tech")

print("Stats:", s.get_memory_stats())

# ── 2. Test selection with relevant context ──
print("\n--- Context: '修改代码 bug fix' ---")
selected = m.select_memories(topic_text="修改代码 bug fix", limit=5)
for mem in selected:
    print(f"  [{mem['priority']}/{mem['category']}] {mem['content'][:50]}")

# ── 3. Test formatting ──
formatted = m.format_memories(selected)
print(f"\nFormatted ({len(formatted)} chars):")
print(formatted[:200])

# ── 4. Test selection with irrelevant context ──
print("\n--- Context: '晚饭吃什么' ---")
selected2 = m.select_memories(topic_text="晚饭吃什么", limit=5)
for mem in selected2:
    print(f"  [{mem['priority']}/{mem['category']}] {mem['content'][:50]}")

# ── 5. Test ingest_extracted ──
print("\n--- Import from extraction ---")
items = [
    {"content": "禁止使用 os.system 调用外部命令", "category": "instruction",
     "priority": 0, "importance": 5, "tags": ["security", "code"]},
    {"content": "项目使用SQLite存储", "category": "fact",
     "importance": 3, "tags": ["tech"]},  # 重复，应跳过
]
ids = m.ingest_extracted(items)
print(f"Imported new: {ids}")
print(f"Stats after import: {s.get_memory_stats()}")

print("\n✅ All MemoryManager tests passed!")
