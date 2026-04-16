## llm generated tool func, created Thu Apr 16 16:23:48 2026

def toolkit_list_dir(path=".", recursive=False, show_hidden=False):
    """
    Lists files and directories in the specified path using Python's pathlib.
    This is a cross-platform replacement for 'dir' (Windows) or 'ls' (Linux/Mac).
    """
    import os
    from pathlib import Path

    if not path:
        path = "."

    try:
        target_path = Path(path).resolve()
    except Exception as e:
        return f"❌ Invalid path: {e}"

    if not target_path.exists():
        return f"❌ Error: The path '{path}' does not exist."
    
    # Start building output
    output_lines = [f"📂 Directory Listing: {target_path}"]
    
    # Recursive scan function
    def scan_dir(current_dir, indent=""):
        try:
            # List all items, sorting dirs first or alphabetically
            items = list(current_dir.iterdir())
            items.sort(key=lambda x: (not x.is_dir(), x.name.lower()))
        except PermissionError:
            output_lines.append(f"{indent}🔒 Permission denied")
            return
        except Exception as e:
            output_lines.append(f"{indent}❌ Error reading directory: {e}")
            return

        for item in items:
            # Filter hidden files
            if not show_hidden and item.name.startswith('.'):
                continue
            
            # Icon selection
            icon = "📁" if item.is_dir() else "📄"
            output_lines.append(f"{indent}{icon} {item.name}")
            
            # Recursion
            if recursive and item.is_dir():
                # Optional: add a limit or depth control in the future
                scan_dir(item, indent + "    ")

    scan_dir(target_path)
    
    return "\n".join(output_lines)

def meta_toolkit_list_dir() -> dict:
    return {"type": "function", "function": {"name": "toolkit_list_dir", "description": "Lists files and directories using Python's pathlib. A cross-platform replacement for dir/ls commands.", "parameters": {"type": "object", "properties": {"path": {"type": "string", "description": "The directory path to list. Defaults to current directory."}, "recursive": {"type": "boolean", "description": "If true, lists files in subdirectories recursively."}, "show_hidden": {"type": "boolean", "description": "If true, shows hidden files (starting with dot)."}}, "required": []}}}
