## llm generated tool func, created Fri May 22 07:10:44 2026
# version: 1.0.0


import base64
import pathlib
import os

def toolkit_write_b64(path: str, b64_content: str, append: bool = False):
    """
    Write large files via base64-encoded content. Safe for any size with special chars.
    
    Args:
        path: Target file path (absolute or relative to current directory)
        b64_content: Base64-encoded file content (UTF-8)
        append: If True, append to end of file instead of overwriting
    
    Returns:
        dict with status, path, size (bytes), lines
    """
    try:
        data = base64.b64decode(b64_content)
        text = data.decode('utf-8')
        target = pathlib.Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        
        # Backup if file exists and not appending
        if target.exists() and not append:
            bak = target.with_suffix(target.suffix + '.bak')
            bak.write_bytes(target.read_bytes())
        
        if append:
            with open(target, 'a', encoding='utf-8') as f:
                f.write(text)
        else:
            target.write_text(text, encoding='utf-8')
        
        lines = text.count('\n') + (1 if text and not text.endswith('\n') else 0)
        return {
            "status": "ok",
            "path": str(target.resolve()),
            "size": len(data),
            "lines": lines,
            "appended": append
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


def meta_toolkit_write_b64() -> dict:
    return {"type": "function", "function": {"name": "toolkit_write_b64", "description": "Write large files (5KB+) via base64-encoded content. Safe for any content size and any special characters. For files under 5KB, prefer toolkit_file with action='write'. Always use this for files >5KB or containing triple-quotes/curly-braces/backticks/newlines that may break JSON parameter passing.", "parameters": {"type": "object", "properties": {"path": {"type": "string", "description": "Target file path"}, "b64_content": {"type": "string", "description": "Base64-encoded file content (UTF-8). Encode the full source code as base64 before passing."}, "append": {"type": "boolean", "description": "If true, append to file instead of overwriting. Default false."}}, "required": ["path", "b64_content"]}}}
