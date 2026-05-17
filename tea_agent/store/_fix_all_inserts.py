"""@2026-05-17 gen by tea_agent, 修复所有 INSERT 语句显式传入 datetime('now','localtime')"""
import shutil, os

FIXES = {
    # ── _topics.py ──
    "tea_agent/store/_topics.py": [
        {
            "match": 'INSERT INTO topics (topic_id, title) VALUES (?, ?)',
            "replace": "INSERT INTO topics (topic_id, title, create_stamp, last_update_stamp) "
                       "VALUES (?, ?, datetime('now', 'localtime'), datetime('now', 'localtime'))",
            "desc": "topics: +create_stamp, last_update_stamp",
        },
        {
            "match": 'INSERT INTO topic_token_stats (\n'
                     '                topic_id, total_tokens, total_prompt_tokens, total_completion_tokens,\n'
                     '                total_cheap_tokens, total_cheap_prompt_tokens, total_cheap_completion_tokens,\n'
                     '                total_embedding_tokens, total_embedding_prompt_tokens,\n'
                     '                conversation_count\n'
                     '            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)',
            "replace": 'INSERT INTO topic_token_stats (\n'
                       '                topic_id, total_tokens, total_prompt_tokens, total_completion_tokens,\n'
                       '                total_cheap_tokens, total_cheap_prompt_tokens, total_cheap_completion_tokens,\n'
                       '                total_embedding_tokens, total_embedding_prompt_tokens,\n'
                       '                conversation_count, last_update\n'
                       '            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, datetime(\'now\', \'localtime\'))',
            "desc": "topic_token_stats: +last_update in INSERT",
        },
    ],
    # ── _memories.py ──
    "tea_agent/store/_memories.py": [
        {
            "match": '"INSERT INTO memories (id, content, category, priority, importance, "\n'
                     '            "expires_at, tags, source_topic_id, pinned) '
                     'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"',
            "replace": '"INSERT INTO memories (id, content, category, priority, importance, "\n'
                       '            "expires_at, tags, source_topic_id, pinned, created_at, updated_at) "\n'
                       '            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime(\'now\', \'localtime\'), datetime(\'now\', \'localtime\'))"',
            "desc": "memories: +created_at, updated_at",
        },
    ],
    # ── _prompts.py ──
    "tea_agent/store/_prompts.py": [
        {
            "match": '"INSERT INTO system_prompts (id, version, content, reason, source_reflection_id) "\n'
                     '            "VALUES (?, ?, ?, ?, ?)"',
            "replace": '"INSERT INTO system_prompts (id, version, content, reason, source_reflection_id, created_at) "\n'
                       '            "VALUES (?, ?, ?, ?, ?, datetime(\'now\', \'localtime\'))"',
            "desc": "system_prompts: +created_at",
        },
    ],
    # ── _reflections.py ──
    "tea_agent/store/_reflections.py": [
        {
            "match": '"INSERT INTO reflections (id, topic_id, summary, details, tool_stats, suggestions) "\n'
                     '            "VALUES (?, ?, ?, ?, ?, ?)"',
            "replace": '"INSERT INTO reflections (id, topic_id, summary, details, tool_stats, suggestions, created_at) "\n'
                       '            "VALUES (?, ?, ?, ?, ?, ?, datetime(\'now\', \'localtime\'))"',
            "desc": "reflections: +created_at",
        },
    ],
    # ── _config.py ──
    "tea_agent/store/_config.py": [
        {
            "match": '"INSERT INTO config_history (id, key, old_value, new_value, reason, source_reflection_id) "\n'
                     '            "VALUES (?, ?, ?, ?, ?, ?)"',
            "replace": '"INSERT INTO config_history (id, key, old_value, new_value, reason, source_reflection_id, created_at) "\n'
                       '            "VALUES (?, ?, ?, ?, ?, ?, datetime(\'now\', \'localtime\'))"',
            "desc": "config_history: +created_at",
        },
    ],
}

for filepath, replacements in FIXES.items():
    # backup
    bak = filepath + ".bak2"
    shutil.copy(filepath, bak)

    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    modified = False
    for r in replacements:
        if r["match"] in content:
            content = content.replace(r["match"], r["replace"])
            print(f"✓ {os.path.basename(filepath)}: {r['desc']}")
            modified = True
        else:
            print(f"✗ {os.path.basename(filepath)}: NOT found — {r['desc']}")
            print("   Try fuzzy match...")
            # fuzzy: check if key parts exist
            key = r["match"].split('\n')[0][:60]
            if key in content:
                print(f"   (first line found, but full block mismatch)")

    if modified:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)

print("\nDone. Backups saved as .bak2")
