"""修复 _conversations.py INSERT 语句"""
filepath = "tea_agent/store/_conversations.py"
with open(filepath, 'r', encoding='utf-8') as f:
    lines = f.readlines()

# fix 1: save_msg - INSERT conversations (line 65-68, 0-based: 64-67)
for i, line in enumerate(lines):
    if 'INSERT INTO conversations (id, topic_id, user_msg, ai_msg, is_func_calling)' in line:
        lines[i] = line.replace(
            '(id, topic_id, user_msg, ai_msg, is_func_calling)',
            '(id, topic_id, user_msg, ai_msg, is_func_calling, stamp)')
        # next line should be VALUES
        for j in range(i+1, min(i+3, len(lines))):
            if 'VALUES (?, ?, ?, ?, ?)' in lines[j]:
                lines[j] = lines[j].replace(
                    'VALUES (?, ?, ?, ?, ?)',
                    "VALUES (?, ?, ?, ?, ?, datetime('now', 'localtime'))")
                break
        print(f"✓ line {i+1}: fixed conversations INSERT")
        break

# fix 2: save_agent_round - INSERT agent_rounds
for i, line in enumerate(lines):
    if 'INSERT INTO agent_rounds (conversation_id, round_num, role, content, tool_calls, tool_call_id)' in line:
        lines[i] = line.replace(
            '(conversation_id, round_num, role, content, tool_calls, tool_call_id)',
            '(conversation_id, round_num, role, content, tool_calls, tool_call_id, stamp)')
        for j in range(i+1, min(i+3, len(lines))):
            if 'VALUES (?, ?, ?, ?, ?, ?)' in lines[j]:
                lines[j] = lines[j].replace(
                    'VALUES (?, ?, ?, ?, ?, ?)',
                    "VALUES (?, ?, ?, ?, ?, ?, datetime('now', 'localtime'))")
                break
        print(f"✓ line {i+1}: fixed agent_rounds INSERT")
        break

with open(filepath, 'w', encoding='utf-8') as f:
    f.writelines(lines)
print("Done")
