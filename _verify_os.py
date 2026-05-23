import sys, tempfile
sys.path.insert(0, '/home/sunkw/work/git/tea_agent')

from tea_agent.tlk import Toolkit
from tea_agent.onlinesession import OnlineToolSession

tk = Toolkit(tempfile.mkdtemp())
sess = OnlineToolSession(
    toolkit=tk,
    api_key='sk-test',
    api_url='https://test.com',
    model='test',
    storage=None,
    max_iterations=1,
    disable_summary=True,
)
msgs = sess._build_api_messages()

found = [m for m in msgs if isinstance(m.get('content'), str) and '当前运行环境' in m['content']]
print('OS_INJECTED:', len(found) > 0)
for m in found:
    print('  ->', m['content'])
print()
print('Total messages:', len(msgs))
for i, m in enumerate(msgs):
    role = m.get('role', '?')
    content = m.get('content', '')
    if isinstance(content, str):
        preview = content[:100].replace('\n', ' ')
    else:
        preview = str(content)[:100]
    print(f'  [{i}] {role}: {preview}')
