import re

path = "tea_agent/onlinesession.py"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

# Fix W504: line break after binary operator
# Pattern matches: has_reload = any(tc.function.name ==\n[spaces]"toolkit_reload"...
pattern = r"has_reload = any\(tc\.function\.name ==\n\s+\"toolkit_reload\" for tc in valid_tool_calls\)"
replacement = "has_reload = any(tc.function.name == \"toolkit_reload\" for tc in valid_tool_calls)"

new_content = re.sub(pattern, replacement, content)

if new_content != content:
    with open(path, "w", encoding="utf-8") as f:
        f.write(new_content)
    print("Fixed W504 in onlinesession.py")
else:
    print("Pattern not found, nothing changed")
