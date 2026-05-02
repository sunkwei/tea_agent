# NOTE: 2026-05-02 11:59:14, self-evolved by tea_agent --- 合并 toolkit_list_dir 进入 toolkit_file（新增 action='list'），消除文件操作工具重叠
# @2026-04-29 gen by deepseek-v4-pro, 合并load_file+save_file为一个统一入口
# version: 1.1.0
# NOTE: 2026-05-02, self-evolved by tea_agent --- 合并 toolkit_list_dir: 新增 action='list'

def toolkit_file(action: str, filename: str = "", content: str = "", path: str = ".", recursive: bool = False, show_hidden: bool = False):
    """
    统一文件操作。
    - action="read": 读取文件全部内容。需 filename。
    - action="write": 将 content 写入 filename。需 filename + content。
    - action="list": 列出目录内容 (跨平台 dir/ls)。可选 path/recursive/show_hidden。
    """
    if action == "read":
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                return f.read()
        except FileNotFoundError:
            return f"Error: File '{filename}' not found."
        except Exception as e:
            return f"Error: {str(e)}"

    elif action == "write":
        try:
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(content)
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
                },
                "required": ["action"],
            },
        },
    }
