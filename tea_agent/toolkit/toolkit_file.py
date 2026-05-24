
import logging

logger = logging.getLogger("toolkit")

def toolkit_file(action: str, filename: str = "", content: str = "", path: str = ".", recursive: bool = False, show_hidden: bool = False, offset: int = 0, limit: int = 0):
    """
    统一文件操作。

    Args:
        action (str): Description.
        filename (str): Description.
        content (str): Description.
        path (str): Description.
        recursive (bool): Description.
        show_hidden (bool): Description.
        offset (int): Description.
        limit (int): Description.
    """
    logger.info(f"toolkit_file called: action={action!r}, filename={filename!r}, content={repr(content)[:80]}, path={path!r}, offset={offset!r}, limit={limit!r}")

    if action == "read":
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                if offset > 0 or limit > 0:
                    lines = f.readlines()
                    start = max(0, offset - 1) if offset > 0 else 0
                    end = min(len(lines), start + limit) if limit > 0 else len(lines)
                    return ''.join(f"{i+1}: {lines[i]}" for i in range(start, end))
                content = f.read()
                if '\r\n' in content or '\r' in content:
                    content = content.replace('\r\n', '\n').replace('\r', '\n')
                return content
        except FileNotFoundError:
            return f"Error: File '{filename}' not found."
        except Exception as e:
            return f"Error: {str(e)}"

    elif action == "write":
        try:
            normalized = content
            if '\r\n' in normalized or '\r' in normalized:
                normalized = normalized.replace('\r\n', '\n').replace('\r', '\n')
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(normalized)
            return 0
        except Exception as e:
            return f"Error: {str(e)}"

    elif action == "list":
        from pathlib import Path
        target = Path(path).resolve()
        if not target.exists():
            return f"❌ Error: The path '{path}' does not exist."

        output_lines = [f"📂 Directory Listing: {target}"]

        def scan_dir(current_dir, indent=""):
            """Scan dir.
            
            Args:
                current_dir: Description.
                indent: Description.
            """
            try:
                items = sorted(current_dir.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
            except PermissionError:
                output_lines.append(f"{indent}🔒 Permission denied")
                return
            except Exception as e:
                output_lines.append(f"{indent}❌ Error: {e}")
                return
            for item in items:
                if not show_hidden and item.name.startswith('.'):
                    continue
                icon = "📁" if item.is_dir() else "📄"
                output_lines.append(f"{indent}{icon} {item.name}")
                if recursive and item.is_dir():
                    scan_dir(item, indent + "    ")

        scan_dir(target)
        return "\n".join(output_lines)

    else:
        return f"❌ 未知 action: '{action}'，可选: read / write / list"

def meta_toolkit_file() -> dict:
    """
    Meta toolkit file

    Returns:
        dict: Description.
    """
    return {
        "type": "function",
        "function": {
            "name": "toolkit_file",
            "description": "统一文件读写与目录列表。action='read' 读取文件；action='write' 写入文件；action='list' 列出目录 (跨平台 dir/ls)。",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["read", "write", "list"],
                        "description": "操作：read=读取, write=写入, list=列出目录",
                    },
                    "filename": {
                        "type": "string",
                        "description": "[read/write] 文件路径",
                    },
                    "content": {
                        "type": "string",
                        "description": "[write] 要写入的内容",
                    },
                    "path": {
                        "type": "string",
                        "description": "[list] 目录路径，默认当前目录",
                    },
                    "recursive": {
                        "type": "boolean",
                        "description": "[list] 是否递归列出子目录",
                    },
                    "show_hidden": {
                        "type": "boolean",
                        "description": "[list] 是否显示隐藏文件",
                    },
                    "offset": {
                        "type": "integer",
                        "description": "[read] 起始行号(1-based)，0=从头开始",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "[read] 返回行数上限，0=不限",
                    },
                },
                "required": ["action"],
            },
        },
    }
