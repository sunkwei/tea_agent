"""
@2026-05-16 gen by tea_agent, 修复所有 CURRENT_TIMESTAMP → datetime('now','localtime')
"""
import os

STORE_DIR = os.path.dirname(os.path.abspath(__file__))

files_to_fix = [
    "_core.py",
    "_conversations.py",
    "_topics.py",
    "_memories.py",
    "_summaries.py",
    "_vectors.py",
]

def backup(filepath):
    bak = filepath + ".bak"
    if not os.path.exists(bak):
        import shutil
        shutil.copy2(filepath, bak)
        print(f"  OK backup: {bak}")

def fix_file(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    old = "CURRENT_TIMESTAMP"
    new = "datetime('now', 'localtime')"
    count = content.count(old)
    if count == 0:
        print(f"  - {os.path.basename(filepath)}: no change needed")
        return 0
    content = content.replace(old, new)
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f"  OK {os.path.basename(filepath)}: replaced {count} places")
    return count

if __name__ == "__main__":
    print("=" * 60)
    print("Fix: CURRENT_TIMESTAMP -> datetime('now','localtime')")
    print("=" * 60)
    total = 0
    for fname in files_to_fix:
        fpath = os.path.join(STORE_DIR, fname)
        if not os.path.exists(fpath):
            print(f"  MISS: {fname}")
            continue
        backup(fpath)
        n = fix_file(fpath)
        total += n
    print(f"\nTotal replaced: {total}")
    print("Done!")
