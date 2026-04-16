## llm generated tool func, created Wed Apr 15 13:39:29 2026

def toolkit_fix_pyproject(directory: str = ".") -> str:
    """
    Fixes common pyproject.toml issues:
    - Removes UTF-8 BOM
    - Fixes deprecated license table format ({text = "MIT"} -> "MIT")
    - Removes deprecated license classifiers
    - Creates README.md if referenced but missing
    Returns a summary of changes.
    """
    import os
    import re

    filepath = os.path.join(directory, "pyproject.toml")
    if not os.path.exists(filepath):
        return "Error: pyproject.toml not found"

    with open(filepath, "rb") as f:
        raw = f.read()

    changes = []
    
    # Decode handling BOM
    if raw.startswith(b'\xef\xbb\xbf'):
        content = raw.decode('utf-8-sig')
        changes.append("Removed BOM")
    else:
        content = raw.decode('utf-8')

    # 1. Fix License Table
    # Replace {text = "MIT"} with "MIT" or generic regex
    pattern = r'license\s*=\s*\{\s*text\s*=\s*"([^"]+)"\s*\}'
    match = re.search(pattern, content)
    if match:
        content = re.sub(pattern, r'license = "\1"', content)
        changes.append("Fixed deprecated license format")

    # 2. Fix Classifiers
    # Remove lines containing "License :: OSI Approved"
    lines = content.split('\n')
    new_lines = []
    removed_classifier = False
    for line in lines:
        if "License :: OSI Approved" in line:
            removed_classifier = True
            continue
        new_lines.append(line)
    
    if removed_classifier:
        changes.append("Removed deprecated license classifier")
        content = '\n'.join(new_lines)

    # 3. Check Readme
    readme_match = re.search(r'readme\s*=\s*"([^"]+)"', content)
    if readme_match:
        readme_name = readme_match.group(1)
        readme_path = os.path.join(directory, readme_name)
        if not os.path.exists(readme_path):
            with open(readme_path, "w", encoding="utf-8") as f:
                f.write(f"# {os.path.basename(directory)}\n\nProject description.\n")
            changes.append(f"Created missing {readme_name}")

    # Write back
    if changes:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        return "Applied changes: " + ", ".join(changes)
    else:
        return "No changes needed."

def meta_toolkit_fix_pyproject() -> dict:
    return {"type": "function", "function": {"name": "toolkit_fix_pyproject", "description": "Automatically fixes common issues in pyproject.toml to ensure clean builds (BOM, license format, classifiers, missing README).", "parameters": {"type": "object", "properties": {"directory": {"description": "Path to the project directory containing pyproject.toml.", "type": "string"}}, "required": []}}}
