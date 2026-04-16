import os
import glob
import re
from datetime import datetime

# Generate the new comment tag
now = datetime.now().strftime("%Y-%m-%d")
new_tag = f"# NOTE: {now}, self-evolved by TeaAgent ---"

# Find all python files in tea_agent/ and subdirectories
files = glob.glob("tea_agent/**/*.py", recursive=True)
count = 0

for f in files:
    try:
        with open(f, 'r', encoding='utf-8') as fp:
            content = fp.read()
        
        # 1. Strip trailing whitespace
        lines = content.splitlines()
        new_lines = [line.rstrip() for line in lines]
        new_content = '\n'.join(new_lines)
        
        # 2. Replace outdated timestamp comments
        # Pattern matches: # NOTE: YYYY-MM-DD, GPT-4 ---
        new_content = re.sub(r'# NOTE: [\d-]+, GPT-4 ---', new_tag, new_content)
        
        if new_content != content:
            with open(f, 'w', encoding='utf-8') as fp:
                fp.write(new_content)
            print(f"Fixed: {f}")
            count += 1
    except Exception as e:
        print(f"Error {f}: {e}")

print(f"Total files fixed: {count}")
