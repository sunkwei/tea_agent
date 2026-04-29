from tea_agent.store import Storage
from tea_agent.memory import MemoryManager, PRIORITY_CRITICAL, PRIORITY_HIGH
from tea_agent.memory import CATEGORY_INSTRUCTION, CATEGORY_REMINDER, CATEGORY_FACT, CATEGORY_PREFERENCE

s = Storage(":memory:")
m = MemoryManager(s, max_inject=5)

# Add test memories
m.add(content="修改代码时标注前缀 {date}: gen by {model}, {subject}", 
      category=CATEGORY_INSTRUCTION, priority=PRIORITY_CRITICAL, importance=5, tags="code,rule")
m.add(content="明天8点提醒检查服务器", 
      category=CATEGORY_REMINDER, priority=PRIORITY_HIGH, importance=4, 
      expires_at="2026-04-30T08:00:00", tags="reminder")
m.add(content="项目使用SQLite存储", 
      category=CATEGORY_FACT, importance=2, tags="tech")
m.add(content="用户偏好简洁回复", 
      category=CATEGORY_PREFERENCE, importance=4, tags="style")
m.add(content="Python 3.10+ 可用 match 语句", 
      category=CATEGORY_FACT, importance=1, tags="python,tech")

print("Stats:", m.get_stats())

# Test selection with relevant context
print("\n--- Context: '修改代码 bug fix' ---")
selected = m.select_memories(context_text="修改代码 bug fix", limit=5)
for mem in selected:
    print(f"  [{mem['priority']}/{mem['category']}] {mem['content'][:50]}")

print("\n--- Formatted ---")
print(m.format_memories(selected))

# Test selection with irrelevant context
print("\n--- Context: '晚饭吃什么' ---")
selected2 = m.select_memories(context_text="晚饭吃什么", limit=5)
for mem in selected2:
    print(f"  [{mem['priority']}/{mem['category']}] {mem['content'][:50]}")

# Test import
print("\n--- Import from extraction ---")
items = [
    {"content": "禁止使用 os.system 调用外部命令", "category": "instruction", 
     "priority": 0, "importance": 5, "tags": ["security", "code"]},
    {"content": "项目使用SQLite存储", "category": "fact", 
     "importance": 3, "tags": ["tech"]},  # 重复，应跳过
]
ids = m.import_from_extraction(items)
print(f"Imported IDs: {ids}")
print(f"Stats after import: {m.get_stats()}")
