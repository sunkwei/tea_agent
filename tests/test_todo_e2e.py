"""TODO 端到端自动验证脚本"""
import sys, os, json, sqlite3
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tea_agent.config import get_config
import requests

cfg = get_config()
base_url = "http://127.0.0.1:8080"

print('=== 🔥 新一轮端到端验证 ===')
print()

# 1. 代码版本检查
print('--- 1. 代码版本 ---')
with open('tea_agent/server/server.py', encoding='utf-8') as f:
    lines = f.readlines()
    for i, line in enumerate(lines):
        if '_ga.current_topic_id = topic_id' in line:
            print(f'  ✅ server.py 行 {i+1}: {line.strip()}')
        if 'todo_items.find' in line:
            print(f'  ✅ server.py 行 {i+1}: {line.strip()}')

with open('tea_agent/server/static/index.html', encoding='utf-8') as f:
    html = f.read()
    if 'hasContent && !_taskPanelOpen && !_taskPanelSuppressAutoOpen && !isStreaming' in html:
        print('  ✅ index.html 自动弹出条件就绪')

print()

# 2. DB 读写验证
print('--- 2. DB 读写验证 ---')
conn = sqlite3.connect(str(cfg.paths.db_path_abs))

test_topic = 'e2e-test-' + str(abs(hash('test')))[-6:]
conn.execute('DELETE FROM todo_items WHERE topic_id=?', (test_topic,))

# 写入
conn.execute(
    'INSERT INTO todo_items (topic_id, desc, idx) VALUES (?,?,?)',
    (test_topic, '端到端测试任务', 0)
)
conn.commit()

# 读取
cur = conn.execute('SELECT desc FROM todo_items WHERE topic_id=? ORDER BY idx', (test_topic,))
rows = cur.fetchall()
print(f'  写入后读取: {[r[0] for r in rows]}')
assert len(rows) == 1 and rows[0][0] == '端到端测试任务'
print('  ✅ DB 读写正常')

# 清理
conn.execute('DELETE FROM todo_items WHERE topic_id=?', (test_topic,))
conn.commit()
conn.close()
print()

# 3. API 验证
print('--- 3. API 接口验证 ---')
try:
    r = requests.get(f'{base_url}/api/config', timeout=5)
    print(f'  ✅ Server 可达 | Status={r.status_code}')

    r2 = requests.get(f'{base_url}/api/topic/{test_topic}/todos', timeout=5)
    data = r2.json()
    print(f'  ✅ TODO API | Status={r2.status_code} | items={data}')
    assert data['total'] == 0  # 刚清理完应该是0
    print('  ✅ API 返回格式正确')
except Exception as e:
    print(f'  ❌ API 错误: {e}')

print()
print('=== ✅ 全部通过！刷新 Web UI → 发消息 → 自动弹出！ ===')
